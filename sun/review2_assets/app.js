const $=id=>document.getElementById(id);
const el=(tag,text,cls)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;};
let data,selected,currentTurn,currentFile,diffScope,focusedTurn,overview=false,viewing=false;
const failures=new Set(['fail','failed','contradicted','needs revision','needs-revision','mixed']);
const selectionFor=turn=>data.selection?.turns.find(t=>t.id===turn.id);
const viewed=change=>data.reviewed?.some(r=>r.id===change.id&&(r.scope==='viewed'||r.scope==='all'));
const humanViewed=turn=>turn.changes.every(viewed);
const complete=turn=>humanViewed(turn)||turn.fully_checked;
const problems=turn=>(turn.checks||[]).filter(c=>failures.has(c.status.toLowerCase()));
const files=turn=>[...new Set(turn.changes.map(c=>c.file))];
const thread=()=>data.threads.find(t=>t.id===selected);
const button=(text,action,cls)=>{const b=el('button',text,cls);b.type='button';b.onclick=action;return b;};
function patch(text,short=false){
 const pre=el('pre',undefined,'patch');let lines=text.split('\n');
 if(short)lines=lines.filter(l=>!l.startsWith('diff ')&&!l.startsWith('index ')&&!l.startsWith('---')&&!l.startsWith('+++')).slice(0,12);
 for(const line of lines)pre.append(el('span',line||' ','line '+(line.startsWith('+')?'add':line.startsWith('-')?'remove':line.startsWith('@@')?'meta':'')));
 return pre;
}
function checkView(turn,rows=turn.checks||[]){
 const wrap=el('div',undefined,'checks');
 for(const row of rows){
  const detail=el('details',undefined,failures.has(row.status.toLowerCase())?'check failure':'check');
  detail.append(el('summary',`${row.rule} · ${row.status==='mixed'?'conflicting results':row.status}`));
  const replaced=new Set(row.checks.flatMap(c=>(c.cites||[]).filter(x=>x.check).map(x=>x.check)));
  for(const c of row.checks){
   const old=(row.outdated||[]).includes(c.id)?' · outdated':replaced.has(c.id)?' · superseded':'';
   detail.append(el('p',`${c.verdict} · ${row.labels?.[c.id]||c.actor}${old}`));
   if(c.note)detail.append(el('p',c.note));
   for(const cite of c.cites||[])detail.append(el('p',`${cite.at||cite.check||''}${cite.file?' · '+cite.file:''}${cite.lines?':'+cite.lines.join('-'):''}`,'source'));
  }
  if(!row.checks.length)detail.append(el('p','No check result recorded.'));
  wrap.append(detail);
 }
 return wrap;
}
function renderThreads(){
 $('threads').setAttribute('aria-label','Threads');$('threads').replaceChildren();
 if(data.pr){const b=button(data.pr.title,()=>{overview=true;viewing=false;render();});b.setAttribute('aria-current',String(overview));$('threads').append(b);}
 for(const th of data.threads.filter(t=>t.title.toLowerCase().includes($('search').value.toLowerCase()))){
  const remaining=th.turns.filter(t=>!complete(t)).length,issues=th.turns.reduce((n,t)=>n+problems(t).length,0);
  const b=button(th.title,()=>{selected=th.id;focusedTurn=null;overview=false;viewing=false;render();});b.setAttribute('aria-current',String(!overview&&th.id===selected));
  b.append(el('span',`${remaining?remaining+' '+(remaining===1?'turn to review':'turns to review'):th.turns.every(t=>t.fully_checked&&!humanViewed(t))?'Checked':'Reviewed'}${issues?' · '+issues+' check '+(issues===1?'issue':'issues'):''}`,issues?'failure':''));
  $('threads').append(b);
 }
 if(!$('threads').children.length)$('threads').append(el('p','No matching threads.','muted empty'));
}
function priorityView(turn){
 const wrap=el('div',undefined,'priorities'),choice=selectionFor(turn);
 if(!choice?.priority_checks){wrap.append(checkView(turn,problems(turn)));return wrap;}
 for(const priority of choice.priority_checks){
  const row=turn.checks.find(c=>c.id===priority.id);
  wrap.append(el('p',priority.why,'relevance'),checkView(turn,[row]));
 }
 return wrap;
}
function openTurn(th,turn){selected=th.id;focusedTurn=turn.id;overview=false;render();}
function renderOverview(){
 const reader=$('reader');reader.replaceChildren(el('h1',data.pr.title));
 let count=0;
 for(const th of data.threads)for(const [index,turn] of th.turns.entries()){
  if(selectionFor(turn)?.priority_checks?.length){
   const section=el('section',undefined,'turn');
   section.append(button(`${th.title} · Turn ${index+1}`,()=>openTurn(th,turn),'text-button'),priorityView(turn));
   reader.append(section);count++;
  }
 }
 if(!count)reader.append(el('p',data.selection?'No priority checks selected.':'The agent has not selected priority checks yet.','muted'));
 const actions=el('div',undefined,'actions');
 actions.append(button(`Files (${data.pr.changes.length})`,()=>openDiff({title:data.pr.title,changes:data.pr.changes}),'text-button'));
 const commits=el('details');commits.append(el('summary',`${data.pr.commits.length} commits`));
 for(const commit of data.pr.commits)commits.append(button(`${commit.id.slice(0,7)} · ${commit.subject}`,()=>openDiff({title:commit.subject,commit:commit.id,changes:commit.changes}),'file-row'));
 actions.append(commits);reader.append(actions);
 const list=el('div',undefined,'turn-list');
 for(const th of data.threads){
  const section=el('section',undefined,'turn');section.append(el('h2',th.title));
  for(const [index,turn] of th.turns.entries()){
   const row=button(undefined,()=>openTurn(th,turn),'turn-row');
   row.append(el('span',`Turn ${index+1}${humanViewed(turn)?' · human-viewed':turn.fully_checked?' · checked':''}`),el('span',selectionFor(turn)?.summary||turn.prompt||'Request unavailable.'));
   section.append(row);
  }
  list.append(section);
 }
 if(!data.threads.length)list.append(el('p','No attributed turns recorded for this PR. Commit and file diffs remain available.','muted'));
 reader.append(list);
}
function fileList(turn,shown=new Set()){
 const list=el('div',undefined,'files');
 for(const path of files(turn).filter(path=>!shown.has(path))){
  const done=turn.changes.filter(c=>c.file===path).every(viewed);
  const b=button(path,()=>openFile(turn,path),'file-row');
  b.append(el('span',done?'Viewed':turn.fully_checked?'Checked':'','muted'));list.append(b);
 }
 return list;
}
function renderReader(){
 const reader=$('reader');reader.replaceChildren();const th=thread();
 if(!th){reader.append(el('p','No recorded changes to review.','muted'));return;}
 reader.append(el('h1',th.title));
 for(const [index,turn] of th.turns.entries()){
  if(focusedTurn&&turn.id!==focusedTurn)continue;
  const choice=selectionFor(turn),done=complete(turn),section=el('section',undefined,'turn');
  const heading=el('h2',`Turn ${index+1}${humanViewed(turn)?' · human-viewed':turn.fully_checked?' · checked':''}`);
  heading.append(button('Turn diff',()=>openDiff({title:`${th.title} · Turn ${index+1}`,turn,changes:turn.changes}),'text-button turn-diff'));section.append(heading);
  section.append(el('p',choice?.summary||turn.prompt||'The request for this turn is unavailable.','prompt'));
  section.append(priorityView(turn));
  const shown=new Set();
  for(const highlight of choice?.focus||[]){
   const change=turn.changes.find(c=>c.id===highlight.id),block=el('div',undefined,'change');
   shown.add(change.file);
   block.append(button(change.file,()=>openFile(turn,change.file),'file-link'),el('p',highlight.why,'relevance'));
   block.append(change.patch?patch(change.patch,true):el('p','No text diff recorded for this change.','muted'));
   section.append(block);
  }
  if(done){
   const all=el('details');all.append(el('summary',`All files (${files(turn).length})`),fileList(turn));section.append(all);
  }else section.append(fileList(turn,shown));
  if(turn.checks?.length){const details=el('details');details.append(el('summary',`All checks (${turn.checks.length})`),checkView(turn));section.append(details);}
  else if(!turn.checks?.length)section.append(el('p','No checks recorded.','muted checks-empty'));
  reader.append(section);
 }
}
function renderFile(){
 const scope=diffScope,turn=scope.turn,reader=$('reader');$('threads').replaceChildren();reader.replaceChildren();
 $('search').hidden=true;$('threads').setAttribute('aria-label','Files');$('back').hidden=false;$('back').textContent=overview?data.pr.title:thread().title;
 for(const path of files(scope)){
  const b=button(path,()=>{if(turn)openFile(turn,path);else{currentFile=path;renderFile();}});b.className='file-nav';b.setAttribute('aria-current',String(path===currentFile));
  if(turn&&turn.changes.filter(c=>c.file===path).every(viewed))b.append(el('span','Human-viewed'));
  $('threads').append(b);
 }
 reader.append(el('h1',currentFile||scope.title,'diff-title'));
 if(scope.commit)reader.append(el('p',scope.commit,'source'));
 const status=el('p','','muted');status.id='view-status';reader.append(status);
 for(const c of scope.changes.filter(c=>!currentFile||c.file===currentFile)){
  if(!currentFile)reader.append(el('h2',c.file,'file'));
  if(c.operation){const source=el('details');source.append(el('summary',`Source · ${(c.at||'unavailable').slice(0,8)}`),el('p',`Snapshot ${c.at||'unavailable'}\nOperation ${c.operation}`,'source'));reader.append(source);}
  reader.append(c.patch?patch(c.patch):el('p','No text diff recorded for this change.','muted'));
 }
}
function openDiff(scope){diffScope=scope;currentTurn=scope.turn;currentFile=null;viewing=true;document.body.classList.add('diff-mode');renderFile();}
async function openFile(turn,path){
 diffScope={title:thread().title,turn,changes:turn.changes};currentTurn=turn;currentFile=path;viewing=true;document.body.classList.add('diff-mode');renderFile();
 if(turn.changes.filter(c=>c.file===path).some(c=>!c.patch||/^Binary files |^GIT binary patch/m.test(c.patch))){$('view-status').textContent='Full diff unavailable; not marked viewed.';return;}
 // Only deliberate file navigation records a view, never rendering the overview or prefetching.
 if(!turn.changes.filter(c=>c.file===path).every(viewed)){
  try{
   const response=await fetch('view',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({snapshot:data.id,turn:turn.id,file:path})});
   if(!response.ok)throw Error('Could not save viewed state. Reopen the file to retry.');
   const state=await response.json();Object.assign(data,state);
   if(viewing&&currentTurn?.id===turn.id&&currentFile===path){renderFile();$('view-status').textContent='Human-viewed';}
  }catch(error){if(viewing&&currentTurn?.id===turn.id&&currentFile===path)$('view-status').textContent=error.message;}
 }else $('view-status').textContent='Human-viewed';
}
function render(){document.body.classList.toggle('diff-mode',viewing);$('search').hidden=viewing;$('back').hidden=!viewing;renderThreads();if(overview)renderOverview();else renderReader();}
$('back').onclick=()=>{viewing=false;render();};$('search').oninput=renderThreads;
try{
 const response=await fetch('data.json');if(!response.ok)throw Error('Could not load this review.');data=await response.json();selected=data.threads[0]?.id;overview=!!data.pr;
 $('repository').textContent=data.example?'example':data.repo.split('/').filter(Boolean).at(-1);render();
}catch(error){$('reader').replaceChildren(el('p',`${error.message} Reload to try again.`,'error'));}
