"""Resumable, capped Tinker experiment. Credentials never enter artifacts."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import random
import threading
import time
from task import canonical, sha, dataset, corrections, messages, score

ROOT = Path(__file__).resolve().parent
RUN = ROOT/'runs/20260929-policy-v2'
CALIBRATION = ROOT/'runs/20260929'
MODEL = 'Qwen/Qwen3-8B'
BASE_URL = 'https://tinker.thinkingmachines.dev/services/tinker-prod'
RATES = dict(prefill=.195, sample=.60, train=.44)
SEEDS = [31,73,127]
KINDS = ['clean','scattered','systematic']
STYLES = ['concise','checklist','retrieval','retrieval8','retrieval16']
MAX_OUTPUT = 1024

def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(data, indent=2, sort_keys=True)+'\n')
    temp.replace(path)

def read(path): return json.loads(path.read_text())

def log(event, **details):
    print(canonical(dict(time=datetime.now(timezone.utc).isoformat(), event=event, **details)),flush=True)

def local_components():
    from tinker_cookbook.tokenizer_utils import get_tokenizer
    from tinker_cookbook.renderers import get_renderer
    tokenizer=get_tokenizer(MODEL)
    return tokenizer,get_renderer('qwen3_disable_thinking',tokenizer)

def prepare():
    assert not (RUN/'freeze.json').exists(), 'Already frozen'
    RUN.mkdir(parents=True,exist_ok=True)
    for split,n,seed in [('train',400,9301),('dev',50,9302),('test',250,9303)]:
        write(RUN/f'{split}.json',dataset(split,n,seed))
    rows=read(RUN/'train.json')
    tok,renderer=local_components()
    from tinker_cookbook.renderers import TrainOnWhat
    from tinker_cookbook.supervised.data import conversation_to_datum
    audit=[]
    for kind in KINDS:
        for seed in SEEDS:
            pool=corrections(rows,kind,seed)
            write(RUN/'pools'/f'{kind}-{seed}.json',pool)
            lengths=[]
            for row in pool:
                conv=messages(row)+[dict(role='assistant',content=canonical(row['target']))]
                d=conversation_to_datum(conv,renderer,None,TrainOnWhat.LAST_ASSISTANT_MESSAGE)
                prefix=renderer.build_generation_prompt(conv[:-1]).to_ints()
                weights=d.loss_fn_inputs['weights'].to_numpy()
                assert d.model_input.to_ints()[:len(prefix)] == prefix
                assert all(w==0 for w in weights[:len(prefix)-1])
                assert all(w>0 for w in weights[len(prefix)-1:])
                assert abs(float(weights.sum())-1)<1e-5
                assert d.model_input.length < 32768
                lengths.append(d.model_input.length)
            audit.append(dict(kind=kind,seed=seed,rows=len(pool),wrong=sum(r['corrupted'] for r in pool),
                full_training_tokens=sum(lengths)*3,estimated_train_usd=sum(lengths)*3*RATES['train']/1e6,max_tokens=max(lengths)))
    write(RUN/'preflight.json',dict(model=MODEL,rates=RATES,rate_source='https://tinker-docs.thinkingmachines.ai/tinker/models/',
        checked='2026-09-29',training=audit,estimated_all_training_usd=sum(x['estimated_train_usd'] for x in audit),
        tokenizer_vocab_sha=sha(tok.get_vocab()),versions={p:importlib.metadata.version(p) for p in ['tinker','tinker-cookbook','transformers','numpy']}))
    review=[]
    # Fifty tasks across regions; include clean and both corrupted alternatives.
    for i in range(50):
        row=rows[i*8]
        review.append(dict(id=row['id'],region=row['region'],records=row['records'],correct=row['correct'],flawed=row['flawed']))
    write(RUN/'manual-review.json',review)
    log('prepared',training=audit,estimated_train_usd=sum(x['estimated_train_usd'] for x in audit))

def check_freeze():
    frozen=read(RUN/'freeze.json')
    for relative,digest in frozen['files'].items():
        assert hashlib.sha256((ROOT/relative).read_bytes()).hexdigest()==digest, f'Frozen input changed: {relative}'
    return frozen

def freeze():
    assert not (RUN/'freeze.json').exists()
    selection=read(RUN/'selection.json')
    assert 0.10 <= selection['selected_dev_exact'] <= .95, 'Development difficulty gate failed'
    assert (RUN/'manual-review-complete.json').exists(), 'Manual dataset review is required'
    paths=[ROOT/'task.py',ROOT/'run.py',ROOT/'test_task.py',ROOT/'PROTOCOL.md',RUN/'selection.json',RUN/'manual-review-complete.json']
    paths += [RUN/f'{s}.json' for s in ['train','dev','test']]
    paths += sorted((RUN/'pools').glob('*.json'))
    files={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    write(RUN/'freeze.json',dict(time=datetime.now(timezone.utc).isoformat(),files=files,selection=selection))
    log('frozen',files=len(files),style=selection['selected'])

class Study:
    def __init__(self):
        import tinker
        from tinker.lib.retry_handler import RetryConfig
        self.tinker=tinker
        self.lock=threading.RLock()
        self.token_lock=threading.RLock()
        self.reserved=sum(e.get('reserved_usd',0) for e in self.ledger())
        self.tok,self.renderer=local_components()
        self.stops=self.renderer.get_stop_sequences()
        self.service=tinker.ServiceClient(api_key=os.environ['TINKER_API_KEY'],base_url=BASE_URL,max_retries=0,timeout=90,
            user_metadata={'experiment':'rubric-boundary-20260929'})
        self.retry=RetryConfig(enable_retry_logic=False,enable_stuck_detection=True,progress_timeout=600)
        self.service.holder.get_session_id()
        self.clients={'base':self.service.create_sampling_client(base_model=MODEL,retry_config=self.retry)}
        log('ready',reserved_usd=self.reserved)

    def ledger(self):
        paths=[RUN/'costs.jsonl',CALIBRATION/'costs.jsonl']
        return [json.loads(l) for p in paths if p.exists() for l in p.read_text().splitlines()]

    def event(self,e):
        with self.lock:
            with (RUN/'costs.jsonl').open('a') as f: f.write(canonical(e)+'\n')

    def reserve(self,key,inputs=0,outputs=0,train=0):
        amount=(inputs*RATES['prefill']+outputs*RATES['sample']+train*RATES['train'])/1e6
        with self.lock:
            if self.reserved+amount > 75: raise RuntimeError('USD 75 cycle reservation cap reached')
            self.reserved+=amount
            self.event(dict(request=key,reserved_usd=amount,input_tokens=inputs,max_output_tokens=outputs,training_tokens=train))

    def sample(self,conv,policy):
        key=sha(dict(messages=conv,policy=policy,temperature=0,max_tokens=MAX_OUTPUT))
        receipt=RUN/'receipts'/f'{key}.json'
        if receipt.exists(): return read(receipt)
        pending=RUN/'pending'/f'{key}.json'
        if pending.exists(): raise RuntimeError('Unresolved request '+key)
        with self.token_lock: prompt=self.renderer.build_generation_prompt(conv)
        assert prompt.length+MAX_OUTPUT <= 32768
        self.reserve(key,inputs=prompt.length,outputs=MAX_OUTPUT)
        write(pending,dict(status='submitting',policy=policy,prompt_sha=sha(conv)))
        params=self.tinker.types.SamplingParams(max_tokens=MAX_OUTPUT,temperature=0,seed=93029,stop=self.stops)
        start=time.monotonic()
        try:
            result=self.clients[policy].sample(prompt=prompt,num_samples=1,sampling_params=params).result(timeout=900)
        except Exception as exc:
            write(pending,dict(status='failed',policy=policy,prompt_sha=sha(conv),error_type=type(exc).__name__))
            raise RuntimeError('Sampling failed; inspect pending '+key+' ('+type(exc).__name__+')') from None
        sequence=result.sequences[0]
        with self.token_lock: parsed,_=self.renderer.parse_response(sequence.tokens)
        content=parsed.get('content','')
        if isinstance(content,list): content=''.join(x.get('text','') for x in content if x.get('type')=='text')
        r=dict(key=key,policy=policy,messages=conv,text=content,tokens=sequence.tokens,
            input_tokens=prompt.length,output_tokens=len(sequence.tokens),stop_reason=sequence.stop_reason,
            seconds=time.monotonic()-start,params=params.model_dump())
        write(receipt,r)
        write(pending,dict(status='complete',receipt_sha=sha(r)))
        self.event(dict(request=key,estimated_usd=(prompt.length*RATES['prefill']+len(sequence.tokens)*RATES['sample'])/1e6))
        return r

    def evaluate(self,policy,kind,seed,style,split):
        if split=='test': check_freeze()
        name=f'{split}-{policy}-{kind}-{seed}-{style}'
        path=RUN/'evaluations'/f'{name}.json'
        if path.exists(): return read(path)
        rows=read(RUN/f'{split}.json')
        pool=read(RUN/'pools'/f'{kind}-{seed}.json')
        def one(row):
            r=self.sample(messages(row,style,pool),policy)
            return dict(id=row['id'],region=row['region'],receipt=r['key'],**score(row,r['text']))
        outputs=[]
        with ThreadPoolExecutor(max_workers=10) as executor:
            for r in executor.map(one,rows):
                outputs.append(r)
                if len(outputs)%25==0: log('eval_progress',name=name,completed=len(outputs),total=len(rows))
        metrics={k:sum(r[k] for r in outputs)/len(outputs) for k in ['exact','format','item_accuracy','recall_correct','proxy_exact','decisions_exact','sorting_correct']}
        result=dict(name=name,policy=policy,kind=kind,seed=seed,style=style,split=split,metrics=metrics,rows=outputs)
        write(path,result)
        log('evaluated',name=name,**metrics)
        return result

    def dev(self):
        assert not (RUN/'freeze.json').exists()
        results=[self.evaluate('base',kind,31,style,'dev') for style in STYLES for kind in KINDS]
        means={style:sum(r['metrics']['exact'] for r in results if r['style']==style)/3 for style in STYLES}
        selected=max(STYLES,key=lambda s:(round(means[s],12),-STYLES.index(s)))
        write(RUN/'selection.json',dict(selected=selected,selected_dev_exact=means[selected],scores=means,
            conditions=[dict(name=r['name'],metrics=r['metrics']) for r in results],rule='highest mean exact; tie fewer examples then shorter prompt'))
        log('dev_selection',selected=selected,scores=means)

    def train(self,kind,seed):
        check_freeze()
        from tinker_cookbook.renderers import TrainOnWhat
        from tinker_cookbook.supervised.data import conversation_to_datum
        name=f'sft-{kind}-{seed}'
        folder=RUN/'training'/name
        saved_path=folder/'checkpoint.json'
        if saved_path.exists():
            m=read(saved_path)
            self.clients[name]=self.service.create_sampling_client(model_path=m['sampling_path'],retry_config=self.retry)
            return name
        if (folder/'started.json').exists(): raise RuntimeError('Unfinished training '+name)
        pool=read(RUN/'pools'/f'{kind}-{seed}.json')
        selected=read(RUN/'selection.json')['selected']
        training_style='concise' if selected=='concise' else 'checklist'
        datums=[]
        masks=[]
        exports=[]
        for row in pool:
            conv=messages(row,training_style)+[dict(role='assistant',content=canonical(row['target']))]
            d=conversation_to_datum(conv,self.renderer,None,TrainOnWhat.LAST_ASSISTANT_MESSAGE)
            prefix=self.renderer.build_generation_prompt(conv[:-1]).to_ints()
            weights=d.loss_fn_inputs['weights'].to_numpy()
            assert d.model_input.to_ints()[:len(prefix)]==prefix
            assert all(w==0 for w in weights[:len(prefix)-1]) and all(w>0 for w in weights[len(prefix)-1:])
            assert abs(float(weights.sum())-1)<1e-5
            datums.append(d)
            masks.append(dict(id=row['id'],prefix_tokens=len(prefix),tokens=d.model_input.length,supervised_tokens=int((weights>0).sum())))
            exports.append(dict(id=row['id'],messages=conv))
        schedule=[]
        for epoch in range(3):
            ids=list(range(len(datums)))
            random.Random(88000+seed*100+epoch).shuffle(ids)
            schedule += [ids[i:i+16] for i in range(0,len(ids),16)]
        tokens=sum(datums[i].model_input.length for batch in schedule for i in batch)
        plan=dict(name=name,seed=seed,kind=kind,model=MODEL,rank=16,lr=.00047,epochs=3,batch=16,steps=len(schedule),
            training_tokens=tokens,dataset_sha=sha(exports),training_style=training_style,loss='mean per example, final assistant only')
        write(folder/'masks.json',masks)
        write(folder/'examples.json',exports)
        write(folder/'schedule.json',schedule)
        self.reserve(name,train=tokens)
        write(folder/'started.json',plan)
        log('training_start',**plan)
        client=self.service.create_lora_training_client(base_model=MODEL,rank=16,seed=seed,train_attn=True,train_mlp=True,train_unembed=True,
            user_metadata={'experiment':'rubric-boundary-20260929','checkpoint':name})
        write(folder/'model.json',dict(model_id=client.model_id,session_id=self.service.holder.get_session_id()))
        start=time.monotonic()
        for step,batch in enumerate(schedule,1):
            fb=client.forward_backward([datums[i] for i in batch],'cross_entropy')
            opt=client.optim_step(self.tinker.types.AdamParams(learning_rate=.00047))
            metrics=fb.result(timeout=1800).metrics
            opt.result(timeout=1800)
            with (folder/'metrics.jsonl').open('a') as f: f.write(canonical(dict(step=step,metrics=metrics))+'\n')
            if step%5==0: log('training_progress',name=name,step=step,total=len(schedule),seconds=round(time.monotonic()-start,1))
            if step%25==0:
                recovery=client.save_state(name=f'{name}-step-{step}',ttl_seconds=7*86400).result(timeout=600)
                write(folder/'recovery.json',dict(step=step,state_path=recovery.path,dataset_sha=plan['dataset_sha']))
        saved=client.save_weights_for_sampler(name=name,ttl_seconds=7*86400).result(timeout=600)
        manifest=dict(**plan,state_path=recovery.path,sampling_path=saved.path,seconds=time.monotonic()-start,
                      saved_at=datetime.now(timezone.utc).isoformat())
        write(saved_path,manifest)
        self.event(dict(request=name,estimated_usd=tokens*RATES['train']/1e6))
        self.clients[name]=self.service.create_sampling_client(model_path=saved.path,retry_config=self.retry)
        log('trained',name=name,seconds=manifest['seconds'])
        return name

    def main(self):
        selected=check_freeze()['selection']['selected']
        styles=list(dict.fromkeys([selected,'checklist']))
        for kind in KINDS:
            for seed in SEEDS:
                for style in styles: self.evaluate('base',kind,seed,style,'test')
                name=self.train(kind,seed)
                for style in styles: self.evaluate(name,kind,seed,style,'test')
        log('complete',reserved_usd=self.reserved,estimated_usd=sum(e.get('estimated_usd',0) for e in self.ledger()))

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('command',choices=['prepare','dev','freeze','main'])
    args=parser.parse_args()
    if args.command=='prepare': prepare()
    elif args.command=='freeze': freeze()
    else:
        import fcntl
        RUN.mkdir(parents=True,exist_ok=True)
        with (RUN/'process.lock').open('w') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            study=Study()
            getattr(study,args.command)()
