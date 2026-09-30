"""Replay raw responses and compute paired uncertainty without model calls."""
from __future__ import annotations
from collections import Counter
import json
from pathlib import Path
import numpy as np
from task import REGIONS, canonical, independent_oracle, oracle, score, sha
from run import ROOT, RUN, CALIBRATION, KINDS, SEEDS, check_freeze, read, write

def main():
    frozen=check_freeze()
    selected=frozen['selection']['selected']
    test=read(RUN/'test.json')
    lookup={r['id']:r for r in test}
    unique_receipts=set()
    results={}
    for path in sorted((RUN/'evaluations').glob('test-*.json')):
        result=read(path)
        assert len(result['rows'])==len(test)
        assert [r['id'] for r in result['rows']]==[r['id'] for r in test]
        for row in result['rows']:
            raw=read(RUN/'receipts'/f"{row['receipt']}.json")
            rescored=score(lookup[row['id']],raw['text'])
            assert all(abs(row[k]-v)<1e-10 for k,v in rescored.items())
            assert raw['policy']==result['policy']
            unique_receipts.add(row['receipt'])
        results[(result['policy'],result['kind'],result['seed'],result['style'])]=result
    for row in test:
        assert row['correct']==independent_oracle(row['records'])==oracle(row['records'])
    for p in (RUN/'training').glob('*/checkpoint.json'):
        m=read(p)
        exports=read(p.parent/'examples.json')
        assert sha(exports)==m['dataset_sha']
        steps=[json.loads(x)['step'] for x in (p.parent/'metrics.jsonl').read_text().splitlines()]
        assert steps==list(range(1,m['steps']+1))
    rng=np.random.default_rng(93029)
    region_ids=[np.array([i for i,r in enumerate(test) if r['region']==region]) for region in REGIONS]
    draws=np.concatenate([rng.choice(ids,size=(10000,len(ids)),replace=True) for ids in region_ids],axis=1)
    def interval(values):
        lo,hi=np.quantile(values[draws].mean(axis=1),[.025,.975])
        return dict(mean=float(values.mean()),low=float(lo),high=float(hi))
    def array(policy,kind,seed,style,key):
        return np.array([r[key] for r in results[(policy,kind,seed,style)]['rows']],dtype=float)
    comparisons=[]
    all_deltas={}
    for style in list(dict.fromkeys([selected,'checklist'])):
        for kind in KINDS:
            means={}
            seeds=[]
            for key in ['exact','format','item_accuracy','recall_correct','proxy_exact','decisions_exact','sorting_correct']:
                b=np.array([array('base',kind,s,style,key) for s in SEEDS])
                f=np.array([array(f'sft-{kind}-{s}',kind,s,style,key) for s in SEEDS])
                means[key]=dict(base=interval(b.mean(axis=0)),trained=interval(f.mean(axis=0)),delta=interval((f-b).mean(axis=0)))
                if key=='exact':
                    all_deltas[(kind,style)]=(f-b).mean(axis=0)
                    seeds=[dict(seed=s,base=float(b[i].mean()),trained=float(f[i].mean()),delta=float((f[i]-b[i]).mean())) for i,s in enumerate(SEEDS)]
            by_region=[]
            for region,ids in zip(REGIONS,region_ids):
                by_region.append(dict(region=region,n=len(ids),**{
                    policy:{key:float(np.array([array('base' if policy=='base' else f'sft-{kind}-{s}',kind,s,style,key) for s in SEEDS])[:,ids].mean()) for key in ['exact','recall_correct']}
                    for policy in ['base','trained']}))
            comparisons.append(dict(kind=kind,style=style,metrics=means,seeds=seeds,regions=by_region))
    interaction=interval(all_deltas[('scattered',selected)]-all_deltas[('systematic',selected)])
    context_effects={}
    for kind in KINDS:
        context_effects[kind]={}
        for method in ['base','trained']:
            a=np.array([array('base' if method=='base' else f'sft-{kind}-{s}',kind,s,selected,'exact') for s in SEEDS])
            b=np.array([array('base' if method=='base' else f'sft-{kind}-{s}',kind,s,'checklist','exact') for s in SEEDS])
            context_effects[kind][method]=interval((a-b).mean(axis=0))
    relevant={c['kind']:c for c in comparisons if c['style']==selected}
    scattered=relevant['scattered']['metrics']['exact']['delta']
    systematic=relevant['systematic']['metrics']['exact']['delta']
    reversal=(scattered['low']>.03 and systematic['high']<-.03) or (systematic['low']>.03 and scattered['high']<-.03)
    ledger=[json.loads(x) for p in [RUN/'costs.jsonl',CALIBRATION/'costs.jsonl'] for x in p.read_text().splitlines()]
    cost=dict(reserved_usd=sum(e.get('reserved_usd',0) for e in ledger),estimated_usd=sum(e.get('estimated_usd',0) for e in ledger),prior_study_estimated_usd=17.42253885)
    cost['total_estimated_usd']=cost['estimated_usd']+cost['prior_study_estimated_usd']
    report=dict(selection=frozen['selection'],test_tasks=len(test),adapters=len(list((RUN/'training').glob('*/checkpoint.json'))),
        unique_test_responses=len(unique_receipts),all_response_receipts=len(list((RUN/'receipts').glob('*.json'))),
        comparisons=comparisons,noise_interaction=interaction,context_example_effects=context_effects,practical_reversal=reversal,cost=cost,
        verification=dict(frozen_files=len(frozen['files']),raw_responses_rescored=len(unique_receipts),test_oracles_agree=True,training_steps_verified=True),
        scope='One synthetic task family, one base model, three training seeds; intervals condition on seeds and generator.')
    write(RUN/'analysis.json',report)
    write(ROOT/'results.json',report)
    figure(relevant,interaction)
    print(json.dumps({k:report[k] for k in ['adapters','test_tasks','unique_test_responses','noise_interaction','practical_reversal','cost']},indent=2))
    for kind,c in relevant.items(): print(kind,json.dumps(c['metrics']['exact']))

def figure(relevant,interaction):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,'axes.spines.right':False})
    fig,axes=plt.subplots(1,2,figsize=(11,4.4),gridspec_kw={'width_ratios':[1.1,1]})
    colors=['#126C8A','#D56937']
    labels=['Clean\n100% correct','Scattered errors\n80% correct','Consistent blind spot\n80% correct']
    x=np.arange(3)
    for offset,method,color,label in [(-.18,'base',colors[0],'Context only'),(.18,'trained',colors[1],'Context + weight updates')]:
        vals=[relevant[k]['metrics']['exact'][method] for k in KINDS]
        y=np.array([v['mean']*100 for v in vals])
        err=np.array([[v['mean']-v['low'] for v in vals],[v['high']-v['mean'] for v in vals]])*100
        axes[0].bar(x+offset,y,.34,color=color,label=label,yerr=err,capsize=3)
        for i,kind in enumerate(KINDS):
            seed_values=[s['base' if method=='base' else 'trained']*100 for s in relevant[kind]['seeds']]
            axes[0].scatter(i+offset+np.array([-.065,0,.065]),seed_values,s=20,color='#202A33',edgecolors='white',linewidths=.5,zorder=5)
        for i,(xx,yy) in enumerate(zip(x+offset,y)):
            seed_top=max(s['base' if method=='base' else 'trained']*100 for s in relevant[KINDS[i]]['seeds'])
            label_y=max(vals[i]['high']*100,seed_top)+3
            axes[0].text(xx,label_y,f'{yy:.1f}',ha='center',fontsize=9)
    axes[0].set(xticks=x,xticklabels=labels,ylabel='Completely correct tasks (%)',ylim=(0,109),title='Does training improve the full task?')
    axes[0].legend(frameon=False,loc='upper left',fontsize=8)
    for i,kind in enumerate(KINDS):
        c=relevant[kind]
        for offset,policy,color in [(-.17,'base',colors[0]),(.17,'trained',colors[1])]:
            regional=next(r for r in c['regions'] if r['region']=='west')
            val=regional[policy]['recall_correct']*100
            axes[1].bar(i+offset,val,.32,color=color)
            axes[1].text(i+offset,val+2,f'{val:.1f}',ha='center',fontsize=9)
    axes[1].set(xticks=x,xticklabels=labels,ylabel='Valid output with correct recall (%)',ylim=(0,109),title='Recall handling in the west region')
    fig.suptitle('Complete rules stay in context for every model',fontsize=14,fontweight='bold')
    fig.text(.01,.012,'250 held-out tasks; dots show 3 seeds. Left intervals: task bootstrap conditional on seeds. Right: west-region subgroup.',fontsize=8,color='#555555')
    fig.tight_layout(rect=(0,.04,1,.94))
    fig.savefig(ROOT/'results.png',dpi=180)
    plt.close(fig)

if __name__=='__main__': main()
