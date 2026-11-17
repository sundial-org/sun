"""Explicitly illustrative history at the scale of the reference video; repo-owned rules."""
import json
import difflib
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from sun.repository_review import finish,identity,save_explanation
def make_example(destination, rules, repo='illustrative repository'):
 source={'repo':repo,'rules':rules}
 model={'format':'sun-repository-review-v1','repo':repo,'scope':'all sessions · illustrative history','example':True,'rules':rules,'checks':{},'turns':[]}
 scenarios=[('Make payment retries safe','payments/retry.py','except TimeoutError:\n    raise','except TimeoutError:\n    return lookup_payment(request.id)'),('Resolve native session paths','sun/sessions.py','return cache_session(session)','return native_path(session) if exists(session) else None'),('Scope repository history','sun/history.py','return history(current_branch)','return history(all_recorded_branches)'),('Keep review state across reloads','sun/review.py','reviewed = set()','reviewed = load_reviewed_changes()'),('Correct the retention summary','notes/launch.md','The pilot improved retention by 12%.','The pilot improved retention by 2 percentage points.'),('Handle an empty rule set','sun/checks.py','return passed / total','return passed / total if total else 0'),('Preserve complete turn diffs','sun/review.py','return selected_changes','return all_turn_changes'),('Keep stale results visible','sun/checks.py','return checks','return current_checks(checks)')]
 checked_edits=0
 for i in range(120):
  title,file,old,new=scenarios[(i//5)%len(scenarios)]
  t={'id':identity('example',i),'session':identity('session',i//5),'actor':'you/agent:codex/example','label':str(i%5+1),'branch':'example','title':title,'request':title+'.','changes':[]}
  n=4 if i<35 else 3
  for j in range(n):
   path=file if j==0 else f'tests/test_{Path(file).stem}_{j}.py'
   before,after=(old+'\n',new+'\n') if j==0 else ('assert result is not None\n','assert result is not None\nassert result.status != "pending"\n')
   patch=''.join(difflib.unified_diff(before.splitlines(True),after.splitlines(True),fromfile='a/'+path,tofile='b/'+path))
   ids=[]
   if checked_edits<151 and rules:
    for k in range(1+i%3):
     name=source['rules'][k%len(source['rules'])]['name']
     verdict='fail' if (i<12 or i%9==0) and j==0 else 'pass'
     cid=identity('result',i,j,k)
     model['checks'][cid]={'id':cid,'rule':name,'verdict':verdict,'actor':'example/program:tests' if name=='tests' else 'example/agent:review','note':'Pending lookup is returned as a completed payment.' if verdict=='fail' and i<5 else 'The regression fixture does not match the returned result.' if verdict=='fail' else 'The captured fixture passes.','cites':[{'at':identity('revision',i),'file':path}]}
     ids.append(cid)
    checked_edits+=1
   change={'id':identity('change',i,j),'file':path,'at':identity('revision',i),'checks':ids,'preview':patch,'bytes':len(patch.encode()),'lines':len(patch.splitlines())}
   t['changes'].append(change)
  model['turns'].append(t)
 finish(model)
 dest=Path(destination);(dest/'patches').mkdir(parents=True,exist_ok=True)
 for t in model['turns']:
  for c in t['changes']:(dest/'patches'/f"{c['id']}.patch").write_text(c['preview'])
 (dest/'snapshot.json').write_text(json.dumps(model))
 assessments={
  'Make payment retries safe':'The timeout handler now returns a lookup result, but the failing check says that result can still be pending. Passing checks on other files do not establish that this recovery path is safe. Verify the payment state before treating the request as complete.',
  'Resolve native session paths':'This change returns None when a native session is missing, instead of using the cached session. The regression check reports a mismatch. Confirm whether missing native sessions should be unavailable or fall back to shared history; the recorded passes cover other files.',
  'Scope repository history':'The query now includes every recorded branch. The failing regression may reflect the wider result set, but the check note does not establish whether the implementation or its expectation is wrong. Review branch inclusion and duplicate handling before clearing this turn.',
  'Keep review state across reloads':'Loading review state replaces an empty set, but this diff alone does not show the write path. The failing regression leaves persistence unverified. Check that an explicit review survives a fresh load and stays scoped to the same changes.',
  'Handle an empty rule set':'The division guard avoids a zero-denominator error, but the regression still reports a different result than expected. Decide whether no rules should display zero coverage or an unchecked state, then verify that behavior.',
  'Keep stale results visible':'The filter now returns only current checks. With a failing regression, historical results may have become inaccessible rather than simply excluded from the totals. Verify that old failures remain reachable in turn history.'
 }
 for t in model['turns']:
  if t['failed']:
   save_explanation(dest,t['id'],assessments[t['title']],[c['id'] for c in t['checks']])
 return model


if __name__=='__main__':
 import argparse
 from sun import checks, git_store
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('workspace');a=p.parse_args()
 destination=Path(a.workspace)
 if destination.exists():p.error('Choose a new workspace; existing reviews are preserved.')
 rules=[{'name':name,'text':rule['text']} for name,rule in checks.read_rules()[1].items()]
 print(make_example(destination,rules,str(git_store.root()))['summary'])
