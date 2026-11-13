const $ = id => document.getElementById(id);
const el = (tag, text, cls) => { const e = document.createElement(tag); if(text !== undefined)e.textContent=text; if(cls)e.className=cls; return e; };
let data, selected;
function patch(text, short=false){
  const pre=el('pre',undefined,'patch');
  let lines=text.split('\n');
  if(short)lines=lines.filter(l=>!l.startsWith('diff ')&&!l.startsWith('index ')&&!l.startsWith('---')&&!l.startsWith('+++')).slice(0,14);
  for(const line of lines)pre.append(el('span',line||' ', 'line '+(line.startsWith('+')?'add':line.startsWith('-')?'remove':line.startsWith('@@')?'meta':'')));
  return pre;
}
function changeView(change){
  const section=el('div',undefined,'change');section.append(el('p',change.file,'file'));
  if(!change.patch){section.append(el('p','No text diff recorded for this change.','muted'));return section;}
  section.append(patch(change.patch,true));
  const detail=el('details');detail.append(el('summary','Full diff and source'));
  detail.append(el('p',`Snapshot ${change.at || 'unavailable'}\nOperation ${change.operation}`,'muted'),patch(change.patch));
  section.append(detail);return section;
}
function renderThreads(){
  $('threads').replaceChildren();
  const threads=data.threads.filter(t=>t.title.toLowerCase().includes($('search').value.toLowerCase()));
  for(const thread of threads){
    const button=el('button',thread.title);button.type='button';button.setAttribute('aria-current',String(thread.id===selected));
    button.append(el('span',`${thread.turns.length} ${thread.turns.length===1?'turn':'turns'}`));
    button.onclick=()=>{selected=thread.id;renderThreads();renderReader();};$('threads').append(button);
  }
  if(!threads.length)$('threads').append(el('p','No matching threads.','muted empty'));
}
function renderReader(){
  const reader=$('reader');reader.replaceChildren();
  const thread=data.threads.find(t=>t.id===selected);
  if(!thread){reader.append(el('p','No recorded changes to review.','muted'));return;}
  reader.append(el('h1',thread.title));
  for(const [index,turn] of thread.turns.entries()){
    const section=el('section',undefined,'turn');section.append(el('h2',`Turn ${index+1}`));
    section.append(el('p',turn.prompt||'The request for this turn is unavailable.',turn.prompt?'prompt':'muted'));
    for(const change of turn.changes)section.append(changeView(change));
    reader.append(section);
  }
}
$('search').oninput=renderThreads;
try{
 const response=await fetch('data.json');if(!response.ok)throw Error('Could not load this review.');data=await response.json();selected=data.threads[0]?.id;
 $('repository').textContent=data.example?'example':data.repo.split('/').filter(Boolean).at(-1);renderThreads();renderReader();
}catch(error){$('reader').replaceChildren(el('p',`${error.message} Reload to try again.`,'error'));}
