"""Independent paired analysis of saved evaluation receipts; no provider calls."""
from collections import defaultdict
import json
from pathlib import Path
import sys
import numpy as np
from run import ROOT, RUN, sha, write_json, SEEDS, BUDGETS


def measures(row):
    s = row['scores']['A']
    applicable = [v for v in s['rules'] if v is not None]
    assert abs(s['S']-sum(applicable)/len(applicable)) < 1e-12
    return dict(US=float(row['U'])*s['S'], U=float(row['U']), S=s['S'],
                hard3=float(row['U'])*sum(s['rules'][j] for j in [4,5,7])/3,
                all_rules=float(row['U'] and all(applicable)),
                words=s['words'], dialogue_share=s['dialogue_share'])


def summarize(rows):
    values = [measures(r) for r in rows]
    out = {k:float(np.mean([v[k] for v in values])) for k in values[0]}
    valid = [r for r in rows if r['U']]
    out['conditional_S'] = float(np.mean([r['scores']['A']['S'] for r in valid])) if valid else None
    out['n'] = len(rows)
    out['prompts'] = len({r['prompt']['id'] for r in rows})
    invalid = [r for r in rows if not r['U']]
    out['invalid_reasons'] = dict(total=len(invalid),below_min=sum(r['format']['words']<120 for r in invalid),
        above_max=sum(r['format']['words']>350 for r in invalid),
        missing_anchor=sum(not all(r['format']['required_words'].values()) for r in invalid),
        valid_format_without_submission=sum(r['format']['pass'] and not r['submitted'] for r in invalid))
    out['per_rule_given_valid'] = []
    for j in range(8):
        applicable = [r['scores']['A']['rules'][j] for r in valid if r['scores']['A']['rules'][j] is not None]
        out['per_rule_given_valid'].append(dict(n=len(applicable), pass_rate=float(np.mean(applicable)) if applicable else None))
    out['strata'] = {stratum:{k:float(np.mean([v[k] for r,v in zip(rows,values) if r['prompt']['stratum']==stratum])) for k in values[0]}
                     for stratum in sorted({r['prompt']['stratum'] for r in rows})}
    return out


def paired(left, right, metric='US', unit='prompt', seed=260928):
    def cluster(rows):
        groups = defaultdict(list)
        strata = {}
        for r in rows:
            key = r['prompt']['id'] if unit == 'prompt' else r['prompt']['place']
            groups[key].append(measures(r)[metric])
            strata[key] = r['prompt']['stratum']
        return {k:float(np.mean(v)) for k,v in groups.items()},strata
    a,strata = cluster(left)
    b,other = cluster(right)
    assert a.keys()==b.keys() and strata==other
    rng = np.random.default_rng(seed)
    draws = np.zeros(10000)
    for s in sorted(set(strata.values())):
        keys = sorted(k for k in a if strata[k]==s)
        d = np.array([a[k]-b[k] for k in keys])
        draws += d[rng.integers(len(d),size=(10000,len(d)))].mean(axis=1)*len(keys)/len(a)
    return dict(mean=float(np.mean([a[k]-b[k] for k in a])),
                ci95=[float(x) for x in np.quantile(draws,[.025,.975])],
                clusters=len(a),unit=unit,draws=10000,seed=seed)


def main():
    files = sorted((RUN/'evaluations').glob('*.json'))
    evaluations = {p.stem:json.loads(p.read_text()) for p in files}
    out = dict(evaluations={k:summarize(v) for k,v in evaluations.items()},
               source_sha={str(p.relative_to(RUN)):sha(p.read_text()) for p in files},
               contrasts={},methods={})
    base = evaluations.get('test-base')
    for n in BUDGETS:
        arms = {}
        for method in ['playbook','sft']:
            names = [f'test-{method}-{n}-s{s}' for s in SEEDS]
            if all(k in evaluations for k in names):
                arms[method] = sum((evaluations[k] for k in names),[])
                out['methods'][f'{method}-{n}'] = summarize(arms[method])
        if len(arms)==2:
            out['contrasts'][str(n)] = {
                metric:{unit:paired(arms['sft'],arms['playbook'],metric,unit) for unit in ['prompt','place']}
                for metric in ['US','U','hard3','all_rules']}
            if base:
                out['contrasts'][str(n)]['validity_guardrail'] = out['methods'][f'sft-{n}']['U'] >= summarize(base)['U']-.03
                out['contrasts'][str(n)]['sft_minus_base'] = paired(arms['sft'],base)
                out['contrasts'][str(n)]['playbook_minus_base'] = paired(arms['playbook'],base)
    if '480' in out['contrasts']:
        out['primary'] = out['contrasts']['480']
    out['followups']={}
    for method in ['combined','self','shuffled']:
        names=[f'test-{method}-480-s{s}' for s in SEEDS]
        reference=[f'test-sft-480-s{s}' for s in SEEDS]
        if all(k in evaluations for k in names+reference):
            rows=sum((evaluations[k] for k in names),[])
            sft=sum((evaluations[k] for k in reference),[])
            out['followups'][method]=dict(summary=summarize(rows),minus_sft=paired(rows,sft),
                                          validity_minus_sft=paired(rows,sft,'U'))
    retention_files=sorted((RUN/'retention').glob('*.json'))
    retention={p.stem:json.loads(p.read_text()) for p in retention_files}
    out['retention']={}
    def retention_summary(rows):
        return dict(n=len(rows),strict_prompt=float(np.mean([r['strict']['follow_all_instructions'] for r in rows])),
                    strict_instruction=float(np.mean([x for r in rows for x in r['strict']['follow_instruction_list']])))
    for name,rows in retention.items():
        out['retention'][name]=retention_summary(rows)
    if 'base' in retention:
        a={r['key']:float(r['strict']['follow_all_instructions']) for r in retention['base']}
        for method in ['sft','playbook']:
            names=[f'{method}-480-s{s}' for s in SEEDS]
            if all(k in retention for k in names):
                rows=sum((retention[k] for k in names),[])
                grouped=defaultdict(list)
                for r in rows:
                    grouped[r['key']].append(float(r['strict']['follow_all_instructions']))
                assert grouped.keys()==a.keys()
                d=np.array([np.mean(grouped[k])-a[k] for k in sorted(a)])
                rng=np.random.default_rng(260928)
                boot=d[rng.integers(len(d),size=(10000,len(d)))].mean(axis=1)
                out['retention'][method+'-mean']=dict(**retention_summary(rows),
                    minus_base=float(d.mean()),ci95=[float(x) for x in np.quantile(boot,[.025,.975])])
    out['source_sha'].update({str(p.relative_to(RUN)):sha(p.read_text()) for p in retention_files})
    costs = [json.loads(l) for l in (RUN/'costs.jsonl').read_text().splitlines()] if (RUN/'costs.jsonl').exists() else []
    out['cost'] = dict(estimated_token_usd=sum(c.get('estimated_usd',0) for c in costs),
                       reserved_usd=sum(c.get('reserved_usd',0) for c in costs),
                       excludes='Storage, invoice adjustments; estimates use uncached pricing')
    write_json(RUN/'analysis.json',out)
    print(json.dumps({'primary':out.get('primary'), 'cost':out['cost'],
                     'completed':len(evaluations)},indent=2))


if __name__=='__main__':
    main()
