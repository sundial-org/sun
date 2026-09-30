"""Matched inference-effort and single-feature counterfactual diagnostics."""
from __future__ import annotations
import argparse
import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import time
import numpy as np
import run
from run import ROOT,RUN,MODEL,KINDS,SEEDS,Study,read,write,log,check_freeze
from task import canonical,sha,messages,score,oracle,independent_oracle

def prepare():
    check_freeze()
    assert not (RUN/'control-freeze.json').exists()
    rows=read(RUN/'test.json')
    cf=[]
    for row in rows:
        if row['region']!='west': continue
        alt=copy.deepcopy(row)
        alt['id']=row['id']+'-north'
        alt['region']='north'
        next(x for x in alt['records'] if x['recalled'])['region']='north'
        assert oracle(alt['records'])==independent_oracle(alt['records'])==row['correct']
        alt['correct']=oracle(alt['records'])
        alt['flawed']=oracle(alt['records'],ignore_recall=True)
        cf.append(dict(original_id=row['id'],counterfactual=alt))
    write(RUN/'control-inputs.json',dict(reasoning_ids=[r['id'] for r in rows[:50]],counterfactuals=cf))
    paths=[ROOT/'CONTROL_PROTOCOL.md',ROOT/'controls.py',RUN/'control-inputs.json']
    write(RUN/'control-freeze.json',dict(time=datetime.now(timezone.utc).isoformat(),files={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}))
    log('controls_frozen',reasoning_tasks=50,counterfactual_pairs=len(cf))

def verify_freeze():
    check_freeze()
    for name,digest in read(RUN/'control-freeze.json')['files'].items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest,name

class ReasoningStudy(Study):
    def __init__(self):
        super().__init__()
        from tinker_cookbook.renderers import get_renderer
        self.renderer=get_renderer('qwen3',self.tok)
        self.stops=self.renderer.get_stop_sequences()

    def sample(self,conv,policy):
        key=sha(dict(messages=conv,policy=policy,temperature=0,max_tokens=4096,renderer='qwen3'))
        receipt=RUN/'receipts'/f'{key}.json'
        if receipt.exists(): return read(receipt)
        pending=RUN/'pending'/f'{key}.json'
        if pending.exists(): raise RuntimeError('Unresolved reasoning request '+key)
        with self.token_lock: prompt=self.renderer.build_generation_prompt(conv)
        self.reserve(key,inputs=prompt.length,outputs=4096)
        params=self.tinker.types.SamplingParams(max_tokens=4096,temperature=0,seed=93029,stop=self.stops)
        write(pending,dict(status='submitting',policy=policy,prompt_sha=sha(conv),renderer='qwen3'))
        start=time.monotonic()
        try:
            result=self.clients[policy].sample(prompt=prompt,num_samples=1,sampling_params=params).result(timeout=900)
        except Exception as exc:
            write(pending,dict(status='failed',policy=policy,prompt_sha=sha(conv),error_type=type(exc).__name__))
            raise RuntimeError('Reasoning request failed '+key+' ('+type(exc).__name__+')') from None
        seq=result.sequences[0]
        with self.token_lock: parsed,termination=self.renderer.parse_response(seq.tokens)
        content=parsed.get('content','')
        if isinstance(content,list): content=''.join(p.get('text','') for p in content if p.get('type')=='text')
        r=dict(key=key,policy=policy,messages=conv,text=content,tokens=seq.tokens,input_tokens=prompt.length,output_tokens=len(seq.tokens),
            stop_reason=seq.stop_reason,seconds=time.monotonic()-start,params=params.model_dump(),renderer='qwen3',termination=str(termination))
        write(receipt,r)
        write(pending,dict(status='complete',receipt_sha=sha(r)))
        self.event(dict(request=key,estimated_usd=(prompt.length*run.RATES['prefill']+len(seq.tokens)*run.RATES['sample'])/1e6))
        return r

def load_adapters(study):
    paths=sorted((RUN/'training').glob('*/checkpoint.json'))
    assert len(paths)==9,'Complete primary training first'
    for p in paths:
        m=read(p)
        study.clients[m['name']]=study.service.create_sampling_client(model_path=m['sampling_path'],retry_config=study.retry)

def evaluate_control(study,name,rows,policy,style,pool=None):
    path=RUN/'controls'/f'{name}.json'
    if path.exists(): return read(path)
    def one(row):
        r=study.sample(messages(row,style,pool),policy)
        return dict(id=row['id'],region=row['region'],receipt=r['key'],output_tokens=r['output_tokens'],**score(row,r['text']))
    with ThreadPoolExecutor(max_workers=40) as ex: outputs=list(ex.map(one,rows))
    result=dict(name=name,policy=policy,rows=outputs)
    write(path,result)
    log('control_evaluated',name=name,exact=np.mean([r['exact'] for r in outputs]),recall=np.mean([r['recall_correct'] for r in outputs]),tokens=np.mean([r['output_tokens'] for r in outputs]))
    return result

def main():
    verify_freeze()
    inputs=read(RUN/'control-inputs.json')
    test={r['id']:r for r in read(RUN/'test.json')}
    study=ReasoningStudy()
    load_adapters(study)
    for kind in KINDS:
        for seed in SEEDS:
            pool=read(RUN/'pools'/f'{kind}-{seed}.json')
            for policy in ['base',f'sft-{kind}-{seed}']:
                evaluate_control(study,f'reasoning-{policy}-{kind}-{seed}',[test[x] for x in inputs['reasoning_ids']],policy,'retrieval',pool)
    # A fresh normal Study restores non-thinking rendering for the region test.
    normal=Study()
    load_adapters(normal)
    for policy in ['base']+[f'sft-{k}-{s}' for k in KINDS for s in SEEDS]:
        evaluate_control(normal,f'region-{policy}',[x['counterfactual'] for x in inputs['counterfactuals']],policy,'checklist')

def analyze():
    verify_freeze()
    inputs=read(RUN/'control-inputs.json')
    test={r['id']:r for r in read(RUN/'test.json')}
    lookup=dict(test,**{x['counterfactual']['id']:x['counterfactual'] for x in inputs['counterfactuals']})
    for p in (RUN/'controls').glob('*.json'):
        for row in read(p)['rows']:
            raw=read(RUN/'receipts'/f"{row['receipt']}.json")
            expected=score(lookup[row['id']],raw['text'])
            assert all(row[k]==v for k,v in expected.items())
    rng=np.random.default_rng(93030)
    inds=np.concatenate([rng.choice(np.arange(i,50,5),size=(10000,10),replace=True) for i in range(5)],axis=1)
    def summary(v,draws=inds):
        lo,hi=np.quantile(v[draws].mean(axis=1),[.025,.975])
        return dict(mean=float(v.mean()),low=float(lo),high=float(hi))
    result={'reasoning':{},'counterfactual':{}}
    for kind in KINDS:
        b=[];f=[];bt=[];ft=[];nonthink=[]
        for seed in SEEDS:
            br=read(RUN/'controls'/f'reasoning-base-{kind}-{seed}.json')['rows']
            fr=read(RUN/'controls'/f'reasoning-sft-{kind}-{seed}-{kind}-{seed}.json')['rows']
            b.append([x['exact'] for x in br]); f.append([x['exact'] for x in fr])
            bt.append([x['output_tokens'] for x in br]);ft.append([x['output_tokens'] for x in fr])
            base_rows=read(RUN/'evaluations'/f'test-base-{kind}-{seed}-retrieval.json')['rows'][:50]
            ft_rows=read(RUN/'evaluations'/f'test-sft-{kind}-{seed}-{kind}-{seed}-retrieval.json')['rows'][:50]
            nonthink.append([y['exact']-x['exact'] for x,y in zip(base_rows,ft_rows)])
        ba=np.mean(b,axis=0);fa=np.mean(f,axis=0)
        result['reasoning'][kind]=dict(base=summary(ba),trained=summary(fa),delta=summary(fa-ba),
            nonthinking_delta_same_tasks=summary(np.mean(nonthink,axis=0)),base_tokens=float(np.mean(bt)),trained_tokens=float(np.mean(ft)),
            seed_base=[float(np.mean(v)) for v in b],seed_trained=[float(np.mean(v)) for v in f])
    cfdraws=np.random.default_rng(93031).integers(0,50,size=(10000,50))
    for kind in ['base']+KINDS:
        west=[];north=[]
        for seed in ([31] if kind=='base' else SEEDS):
            policy='base' if kind=='base' else f'sft-{kind}-{seed}'
            original=read(RUN/'evaluations'/f'test-{policy}-{"clean" if kind=="base" else kind}-{seed}-checklist.json')['rows']
            w={x['id']:x for x in original}
            alt=read(RUN/'controls'/f'region-{policy}.json')['rows']
            west.append([w[x['original_id']]['recall_correct'] for x in inputs['counterfactuals']])
            north.append([x['recall_correct'] for x in alt])
        w=np.mean(west,axis=0);n=np.mean(north,axis=0)
        result['counterfactual'][kind]=dict(west=summary(w,cfdraws),north=summary(n,cfdraws),north_minus_west=summary(n-w,cfdraws))
    write(RUN/'control-analysis.json',result)
    print(json.dumps(result,indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=['prepare','main','analyze']);args=parser.parse_args()
    if args.command=='prepare': prepare()
    elif args.command=='analyze': analyze()
    else:
        import fcntl
        with (RUN/'process.lock').open('w') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            main()
