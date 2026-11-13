const $ = id => document.getElementById(id);
const el = (tag, text, cls) => { const e = document.createElement(tag); if(text !== undefined)e.textContent=text; if(cls)e.className=cls; return e; };
let data, selected;
function selectionFor(turn){return data.selection?.turns.find(t=>t.id===turn.id);}
function acknowledged(turn){return turn.changes.every(c=>data.reviewed?.some(r=>r.id===c.id&&r.scope==='all'));}
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
    button.append(el('span',`${thread.turns.filter(t=>!acknowledged(t)).length} unreviewed ${thread.turns.filter(t=>!acknowledged(t)).length===1?'turn':'turns'}`));
    button.onclick=()=>{selected=thread.id;renderThreads();renderReader();};$('threads').append(button);
  }
  if(!threads.length)$('threads').append(el('p','No matching threads.','muted empty'));
}
function renderReader(){
  const reader=$('reader');reader.replaceChildren();
  const thread=data.threads.find(t=>t.id===selected);
  if(!thread){reader.append(el('p','No recorded changes to review.','muted'));return;}
  reader.append(el('h1',thread.title));
  if(!data.selection)reader.append(el('p','No highlights prepared. All recorded changes are shown.','muted notice'));
  for(const [index,turn] of thread.turns.entries()){
    const choice=selectionFor(turn), focus=choice?turn.changes.filter(c=>choice.focus.some(f=>f.id===c.id)):turn.changes;
    const context=choice?turn.changes.filter(c=>choice.context.includes(c.id)):[];
    const section=el('section',undefined,'turn');
    section.append(el('h2',`Turn ${index+1}${choice?' · '+focus.length+' of '+turn.changes.length+' changes shown':''}`));
    section.append(el('p',choice?.summary||turn.prompt||'The request for this turn is unavailable.','prompt'));
    if(choice){const request=el('details');request.append(el('summary','Request'),el('p',turn.prompt||'Request unavailable.'));section.append(request);}
    for(const change of focus){
      const view=changeView(change),why=choice?.focus.find(f=>f.id===change.id)?.why;
      if(why)view.insertBefore(el('p',why,'muted'),view.children[1]);section.append(view);
    }
    const other=el('details');
    if(context.length){other.append(el('summary',`${context.length} other ${context.length===1?'change':'changes'}`));for(const c of context)other.append(changeView(c));section.append(other);}
    const actions=el('div',undefined,'actions'),button=el('button',undefined,'text-button'),status=el('span','','muted');button.type='button';
    const scope=()=>!acknowledged(turn)&&choice&&context.length&&!other.open?'highlights':'all';
    const ids=()=>scope()==='all'?turn.changes.map(c=>c.id):focus.map(c=>c.id);
    const isDone=()=>ids().length>0&&ids().every(id=>data.reviewed?.some(r=>r.id===id&&r.scope===scope()));
    function update(){
      button.textContent=isDone()?'Undo review':scope()==='all'?'Mark turn reviewed':'Mark highlights reviewed';
      button.disabled=ids().length===0;
      status.textContent=acknowledged(turn)?'Turn reviewed':data.reviewed?.some(r=>turn.changes.some(c=>c.id===r.id))?'Highlights reviewed':'';
    }
    other.ontoggle=update;
    button.onclick=async()=>{
      button.disabled=true;status.textContent='Saving…';
      try{
        const response=await fetch('ack',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({snapshot:data.id,turn:turn.id,scope:scope(),reviewed:!isDone()})});
        if(!response.ok)throw Error('Could not save. Reopen this review and try again.');
        Object.assign(data,await response.json());update();renderThreads();
      }catch(error){status.textContent=error.message;button.disabled=false;}
    };
    update();actions.append(button,status);section.append(actions);reader.append(section);
  }
}
$('search').oninput=renderThreads;
try{
 const response=await fetch('data.json');if(!response.ok)throw Error('Could not load this review.');data=await response.json();selected=data.threads[0]?.id;
 $('repository').textContent=data.example?'example':data.repo.split('/').filter(Boolean).at(-1);renderThreads();renderReader();
}catch(error){$('reader').replaceChildren(el('p',`${error.message} Reload to try again.`,'error'));}
