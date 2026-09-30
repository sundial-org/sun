"""Offline error decomposition; these diagnostics do not replace primary scores."""
import json
import re
from run import ROOT,RUN,read,write,check_freeze
from task import score

def main():
    check_freeze()
    inputs={x['id']:x for x in read(RUN/'test.json')}
    for x in read(RUN/'control-inputs.json')['counterfactuals']:
        inputs[x['counterfactual']['id']]=x['counterfactual']
    result=[]
    paths=sorted((RUN/'evaluations').glob('test-*.json'))+sorted((RUN/'controls').glob('*.json'))
    for path in paths:
        group=read(path)
        n=len(group['rows'])
        counts=dict(exact_correct=0,schema_failures=0,sorting_only_failures=0,valid_decision_failures=0,valid_recall_violations=0,fenced_json_rescues=0,
                    unclosed_think_json=0,unclosed_think_rescues=0,normalized_exact=0,normalized_decisions=0,
                    normalized_recall=0,normalized_format=0,truncated=0)
        regions={}
        examples=[]
        for row in group['rows']:
            raw=read(RUN/'receipts'/f"{row['receipt']}.json")
            s=score(inputs[row['id']],raw['text'])
            assert all(row[k]==v for k,v in s.items())
            counts['exact_correct']+=s['exact']
            counts['schema_failures']+=1-s['format']
            counts['sorting_only_failures']+=int(s['decisions_exact'] and not s['exact'])
            counts['valid_decision_failures']+=int(s['format'] and not s['decisions_exact'])
            counts['valid_recall_violations']+=int(s['format'] and not s['recall_correct'])
            counts['truncated']+=int(raw['stop_reason']=='length')
            regional=regions.setdefault(row['region'],dict(n=0,correct_recall=0,schema_failures=0,valid_recall_violations=0))
            regional['n']+=1
            regional['correct_recall']+=s['recall_correct']
            regional['schema_failures']+=1-s['format']
            regional['valid_recall_violations']+=int(s['format'] and not s['recall_correct'])
            text=raw['text'].strip()
            match=re.fullmatch(r'```(?:json)?\s*\n(.*?)\n```',text,re.S)
            # Post hoc robustness only: strip a whole code fence or a single
            # unclosed opening think tag followed entirely by a JSON object.
            # Never extract a convenient object from prose or incomplete reasoning.
            unclosed=re.fullmatch(r'<think>\s*(\{.*\})',text,re.S)
            normalized=score(inputs[row['id']],match.group(1) if match else unclosed.group(1) if unclosed else text)
            counts['normalized_exact']+=normalized['exact']
            counts['normalized_decisions']+=normalized['decisions_exact']
            counts['normalized_recall']+=normalized['recall_correct']
            counts['normalized_format']+=normalized['format']
            counts['fenced_json_rescues']+=int(match is not None and normalized['exact'] and not s['exact'])
            counts['unclosed_think_json']+=int(unclosed is not None and normalized['format'])
            counts['unclosed_think_rescues']+=int(unclosed is not None and normalized['exact'] and not s['exact'])
            if s['format'] and not s['recall_correct'] and len(examples)<3:
                focus=inputs[row['id']]['focus_id']
                response=json.loads(text)
                examples.append(dict(id=row['id'],region=row['region'],input=next(x for x in inputs[row['id']]['records'] if x['id']==focus),
                    predicted=next(x for x in response['orders'] if x['id']==focus),expected=next(x for x in inputs[row['id']]['correct']['orders'] if x['id']==focus)))
        for regional in regions.values():
            assert regional['n']==regional['correct_recall']+regional['schema_failures']+regional['valid_recall_violations']
        assert n==sum(counts[k] for k in ['exact_correct','schema_failures','sorting_only_failures','valid_decision_failures'])
        result.append(dict(name=group['name'],n=n,counts=counts,regions=regions,recall_error_examples=examples))
    write(RUN/'diagnostics.json',result)
    print(json.dumps([x for x in result if x['name'].startswith('reasoning-') or ('systematic' in x['name'] and 'retrieval' in x['name'])],indent=2))

if __name__=='__main__': main()
