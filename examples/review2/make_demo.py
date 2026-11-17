"""Generate explicitly synthetic, small code and prose turns for design review."""
import difflib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from sun.review2 import build_snapshot, digest


def example():
    records = [
        ('research', 'Update the launch notes', 'Keep the launch notes consistent with the latest experiment.', [
            ('notes/launch.md', 'The pilot improved retention by 12%.\nWe should roll out to every workspace.\n', 'The pilot improved retention by 2 percentage points.\nWe should run a second pilot before expanding.\n')]),
        ('sessions', 'Keep session history local', 'Resolve local session paths without copying transcripts.', [
            ('sun/sessions.py', 'return cache_session(session)\n', 'return native_path(session) if exists(session) else None\n')]),
        ('retry', 'Make retries safe', 'Reuse the request ID when retrying a payment.', [
            ('payments/retry.py', 'for attempt in range(3):\n    charge(request, key=new_key())\n', 'for attempt in range(3):\n    charge(request, key=request.id)\n'),
            ('tests/test_retry.py', 'assert charge_count == 1\n', 'assert charge_count == 1\nassert keys == [request.id, request.id]\n')]),
        ('retry', 'Make retries safe', 'Handle a timeout after the payment was accepted.', [
            ('payments/retry.py', 'except TimeoutError:\n    raise\n', 'except TimeoutError:\n    return lookup_payment(request.id)\n'),
            ('tests/test_retry.py', 'assert result.status == "paid"\n', 'assert result.status == "paid"\nassert provider.charge_calls == 1\n')]),
    ]
    commits, prompts, titles, counts, git_commits, net = [], {}, {}, {}, [], {}
    for i,(sid,title,prompt,files) in enumerate(records):
        counts[sid]=counts.get(sid,0)+1
        op={'id':f'example-operation-{i}', 'actor':'you/agent:codex/'+sid, 'session_id':sid,
            'branch':'example', 'turn':str(counts[sid]), 'snapshot':str(i+1)*40,
            'edits':[{'file':path,'patch':''.join(difflib.unified_diff(old.splitlines(True),new.splitlines(True),fromfile='a/'+path,tofile='b/'+path))} for path,old,new in files]}
        prompts[op['id']]=prompt;titles[op['actor']]=title
        commits.insert(0,{'operations':[op]})
        git_commits.append({'id':str(i+5)*40,'subject':prompt.rstrip('.'),'changes':op['edits']})
        for path,old,new in files:
            before,after=net.get(path,('',''));net[path]=(before+old,after+new)
    snapshot=build_snapshot({'commits':commits}, 'example', lambda op:prompts[op['id']])
    for thread in snapshot['threads']:thread['title']=titles[thread['actor']]
    def check(turn, rule, verdicts):
        rows=[]
        for i,(verdict,note) in enumerate(verdicts):
            rows.append({'id':f"example-{turn['id'][:8]}-{rule}-{i}", 'actor':'example/program:tests' if i==0 else 'example/agent:review',
                         'verdict':verdict,'note':note,'cites':[{'at':turn['changes'][0]['at'],'file':turn['changes'][0]['file']}]})
        return {'id':digest([turn['id'],rule]),'rule':rule,'status':'mixed' if len({c['verdict'] for c in rows})>1 else rows[0]['verdict'],
                'checks':rows,'labels':{},'outdated':[]}
    for thread in snapshot['threads']:
        for turn in thread['turns']:
            turn['checks']=[];turn['fully_checked']=False
        if thread['title']=='Make retries safe':
            thread['turns'][0]['checks']=[check(thread['turns'][0],'idempotency',[('pass','Both attempts use the original request key.')])]
            thread['turns'][1]['checks']=[check(thread['turns'][1],'timeout recovery',[
                ('fail','The lookup returned pending. The code treats every lookup as a completed payment.'),
                ('pass','The successful lookup fixture returns the existing payment.')])]
        elif thread['title']=='Keep session history local':
            turn=thread['turns'][0];turn['fully_checked']=True
            turn['checks']=[check(turn,'session privacy',[('pass','Native paths resolve locally. Missing transcripts stay unavailable.')])]
    snapshot['pr']={'title':'PR #42 · Prepare the next release','base':'main','merge_base':'0'*40,'head':'8'*40,
                    'commits':git_commits,'changes':[{'file':path,'patch':''.join(difflib.unified_diff(old.splitlines(True),new.splitlines(True),fromfile='a/'+path,tofile='b/'+path))} for path,(old,new) in net.items()]}
    snapshot['example']=True
    snapshot['id']=digest({k:v for k,v in snapshot.items() if k!='id'})
    return snapshot


def selection(snapshot):
    """Explicit editorial choices for the synthetic demo, not generated verdicts."""
    turns=[]
    for thread in snapshot['threads']:
        for turn in thread['turns']:
            reason={'payments/retry.py':'This controls whether a retry can charge the customer twice.',
                    'sun/sessions.py':'Keeping native paths avoids copying private session transcripts.',
                    'notes/launch.md':'The smaller measured effect changes the rollout decision.'}[turn['changes'][0]['file']]
            priorities=[{'id':row['id'],'why':'A pending payment may be treated as completed. The passing fixture and failing check disagree on the outcome.'}
                        for row in turn['checks'] if row['status']=='mixed']
            turns.append({'id':turn['id'],'summary':turn['prompt'],'focus':[{'id':turn['changes'][0]['id'],'why':reason}],
                          'context':[c['id'] for c in turn['changes'][1:]],'priority_checks':priorities})
    return {'version':1,'snapshot':snapshot['id'],'turns':turns}


if __name__=='__main__':
    path=Path(sys.argv[1]);path.mkdir(parents=True,exist_ok=False)
    snapshot=example()
    (path/'snapshot.json').write_text(json.dumps(snapshot,indent=2)+'\n')
    (path/'selection.json').write_text(json.dumps(selection(snapshot),indent=2)+'\n')
    print(path)
