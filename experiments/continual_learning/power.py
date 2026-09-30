"""Development-only planning simulation; never reads test outcomes."""
import json
from collections import defaultdict
import numpy as np
from run import ROOT,RUN,SEEDS,sha,write_json

def prompt_scores(rows):
    grouped=defaultdict(list)
    for r in rows:
        assert r['prompt']['split']=='dev'
        grouped[r['prompt']['id']].append(r['U']*r['scores']['A']['S'])
    return {k:float(np.mean(v)) for k,v in grouped.items()}

def main():
    p=RUN/'evaluations'
    base=json.loads((p/'dev-base.json').read_text())
    book=json.loads((p/'dev-playbook-60-s31.json').read_text())
    base_u=np.mean([r['U'] for r in base])
    candidates=[]
    files=[p/'dev-base.json',p/'dev-playbook-60-s31.json']
    for lr in [.00015,.00047,.0007]:
        path=p/f'dev-sft-60-lr{lr}.json';files.append(path)
        rows=json.loads(path.read_text())
        candidates.append(dict(lr=lr,U=float(np.mean([r['U'] for r in rows])),
                               US=float(np.mean([r['U']*r['scores']['A']['S'] for r in rows])),rows=rows))
    eligible=[c for c in candidates if c['U']>=base_u-.03]
    chosen=max(eligible,key=lambda c:(c['US'],-c['lr'])) if eligible else max(candidates,key=lambda c:(c['U'],c['US'],-c['lr']))
    x,y=prompt_scores(chosen['rows']),prompt_scores(book)
    assert x.keys()==y.keys() and len(x)==24
    d=np.array([x[k]-y[k] for k in sorted(x)])
    rows=[]
    for n in [96,144,192]:
        rng=np.random.default_rng(260928)
        noise=rng.choice(d-d.mean(),size=(10000,n),replace=True)
        se=noise.std(axis=1,ddof=1)/n**.5
        rows.append(dict(prompts=n,power_at_5pp=float(np.mean(.05+noise.mean(axis=1)>1.96*se)),
                         null_coverage=float(np.mean(abs(noise.mean(axis=1))<=1.96*se)),
                         approximate_ci_halfwidth=float(1.96*d.std(ddof=1)/n**.5)))
    qualifying=[r['prompts'] for r in rows if r['power_at_5pp']>=.8]
    out=dict(selected_learning_rate=chosen['lr'],development_guardrail_pass=bool(eligible),
             paired_prompt_sd=float(d.std(ddof=1)),planning=rows,
             recommended_test_prompts=min(qualifying) if qualifying else 192,
             method='10,000 centered empirical dev-prompt resamples; normal 1.96 SE interval; injected 5 percentage point mean shift',
             limits='Planning approximation, not a guarantee for the final percentile bootstrap; one development method seed, only four development places; excludes variation from recollecting reviews or retraining new seeds.',
             source_sha={str(f.relative_to(RUN)):sha(f.read_text()) for f in files})
    write_json(ROOT/'development-power.json',out)
    print(json.dumps(out,indent=2))

if __name__=='__main__':
    main()
