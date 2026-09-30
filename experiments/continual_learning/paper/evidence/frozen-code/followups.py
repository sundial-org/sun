"""Prespecified explanatory controls and a public IFEval retention subset."""
import argparse
import copy
import dataclasses
import json
import random
import re
import sys
from run import ROOT, RUN, Study, WRITER, SEEDS, good, sha, write_json, format_check


def prepare_retention():
    path = ROOT/'vendor/instruction_following_eval/data/input_data.jsonl'
    rows = [json.loads(l) for l in path.read_text().splitlines()]
    # Selection depends only on public example IDs, before any response is seen.
    rows = sorted(rows,key=lambda r:sha('retention-260928-'+str(r['key'])))[:128]
    out = dict(selection='128 smallest SHA256(retention-260928- + key)', source_sha=sha(path.read_text()),
               keys=[r['key'] for r in rows], rows=rows, temperature=.7, top_p=.8,top_k=20,
               max_tokens=4096, system='You are a helpful assistant. Follow the user instructions.',
               endpoint='official strict prompt-level and instruction-level accuracy',
               note='Public benchmark subset; possible pretraining contamination; no claim of broad capability retention')
    dest = ROOT/'retention-plan.json'
    if dest.exists():
        assert json.loads(dest.read_text()) == out
    write_json(dest,out)
    print('Retention set frozen:',len(rows),sha(out))
    return out


def retention(study):
    import nltk
    import langdetect
    nltk.data.path.insert(0,str(ROOT/'vendor/nltk_data'))
    langdetect.DetectorFactory.seed = 0
    from instruction_following_eval.evaluation_lib import InputExample,test_instruction_following_strict
    plan = prepare_retention()
    policies = [('base','base',None)]
    freeze = json.loads((RUN/'freeze.json').read_text())
    for seed in SEEDS:
        name=f'sft-480-s{seed}'
        study.train(study.rows,name,seed=seed,lr=freeze['learning_rate'])
        policies.append((name,name,None))
        policies.append(('base',f'playbook-480-s{seed}',study.compile_playbook(480,seed)))
    for policy,name,book in policies:
        dest = RUN/'retention'/f'{name}.json'
        if dest.exists():
            continue
        def work(row):
            system = plan['system']
            if book:
                system += '\nPreviously learned writing preferences:\n'+book['playbook']
            messages = [dict(role='system',content=system),dict(role='user',content=row['prompt'])]
            response = study.sample(messages,policy,f'ifeval-{name}-{row["key"]}',
                                    seed=810000+row['key'],max_tokens=4096)
            return dict(**row,response=response['text'],receipt=f'provider/ifeval-{name}-{row["key"]}.json')
        rows = study.parallel(plan['rows'],work,'ifeval-'+name)
        # Scoring is sequential because language detection and some checkers use RNG.
        for row in rows:
            random.seed(0)
            inp=InputExample(**{k:row[k] for k in ['key','instruction_id_list','prompt','kwargs']})
            result=test_instruction_following_strict(inp,{row['prompt']:row['response']})
            row['strict']=dataclasses.asdict(result)
        rows.sort(key=lambda r:r['key'])
        write_json(dest,rows)
        study.log('retention_complete',name=name,count=len(rows),
                  strict_prompt=sum(r['strict']['follow_all_instructions'] for r in rows)/len(rows))


def controls(study):
    from style import RULES
    freeze=json.loads((RUN/'freeze.json').read_text())
    lr=freeze['learning_rate']
    # Privileged reference only: never included in compiler/training inputs.
    explicit={'playbook':'\n'.join(f'{i+1}. {r}' for i,r in enumerate(RULES['A']))}
    study.evaluate('base','test-explicit-rules',pool=explicit)
    def one(seed):
        name=f'sft-480-s{seed}'
        study.train(study.rows,name,seed=seed,lr=lr)
        book=study.compile_playbook(480,seed)
        study.evaluate(name,f'test-combined-480-s{seed}',pool=book)
        name=f'self-480-s{seed}'
        study.train(study.rows,name,seed=seed,lr=lr,target='story')
        study.evaluate(name,'test-'+name)
        rows=copy.deepcopy(study.rows)
        valid=good(rows)
        order=list(range(len(valid)))
        rng=random.Random(99000+seed)
        # A shuffled cycle is a derangement, so no target stays on its assignment.
        rng.shuffle(order)
        donor={order[i]:order[(i+1)%len(order)] for i in range(len(order))}
        mapping=[]
        for i,row in enumerate(valid):
            other=valid[donor[i]]
            replacements=dict(zip(other['prompt']['anchors'],row['prompt']['anchors']))
            pattern=r'\b(?:'+'|'.join(re.escape(k) for k in replacements)+r')\b'
            target=re.sub(pattern,lambda m:replacements[m.group().lower()],other['edited'],flags=re.I)
            assert format_check(target,row['prompt']['anchors'])['pass']
            row['shuffled']=target
            mapping.append(dict(recipient=row['id'],donor=other['id'],target_sha=sha(target)))
        write_json(RUN/'controls'/f'shuffle-s{seed}.json',mapping)
        name=f'shuffled-480-s{seed}'
        study.train(rows,name,seed=seed,lr=lr,target='shuffled')
        study.evaluate(name,'test-'+name)
        return seed
    study.parallel(SEEDS,one,'controls')
    study.log('controls_complete',estimated_usd=study.actual,reserved_usd=study.reserved)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('phase',choices=['prepare','retention','controls'])
    args=p.parse_args()
    if args.phase=='prepare':
        prepare_retention()
    else:
        study=Study()
        retention(study) if args.phase=='retention' else controls(study)
