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
    commits, prompts, titles, counts = [], {}, {}, {}
    for i,(sid,title,prompt,files) in enumerate(records):
        counts[sid]=counts.get(sid,0)+1
        op={'id':f'example-operation-{i}', 'actor':'you/agent:codex/'+sid, 'session_id':sid,
            'branch':'example', 'turn':str(counts[sid]), 'snapshot':str(i+1)*40,
            'edits':[{'file':path,'patch':''.join(difflib.unified_diff(old.splitlines(True),new.splitlines(True),fromfile='a/'+path,tofile='b/'+path))} for path,old,new in files]}
        prompts[op['id']]=prompt;titles[op['actor']]=title
        commits.insert(0,{'operations':[op]})
    snapshot=build_snapshot({'commits':commits}, 'example', lambda op:prompts[op['id']])
    for thread in snapshot['threads']:thread['title']=titles[thread['actor']]
    snapshot['example']=True
    snapshot['id']=digest({k:v for k,v in snapshot.items() if k!='id'})
    return snapshot


if __name__=='__main__':
    path=Path(sys.argv[1]);path.mkdir(parents=True,exist_ok=False)
    (path/'snapshot.json').write_text(json.dumps(example(),indent=2)+'\n')
    print(path)
