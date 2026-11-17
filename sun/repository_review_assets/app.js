(() => {
/* DATA */
const transport = 'server';
const root=document.getElementById('sun-terminal');
let data=initialData,view='overview',sessionId=null,turnId=null,filter='unreviewed',ruleFilter=null,fileFilter=null;
const fail=v=>['fail','failed','contradicted','needs revision','needs-revision'].includes(v.toLowerCase());
const viewed=t=>t.changes.every(c=>(data.reviewed||[]).includes(c.id));
const node=(tag,text,cls)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;};
const button=(text,action,cls)=>{const b=node('button',text,cls);b.type='button';b.onclick=action;return b;};
const frame=title=>{const e=node('fieldset');e.append(node('legend',title));return e;};
const matches=t=>(!ruleFilter||t.checks.some(c=>c.rule===ruleFilter&&fail(c.verdict)))&&(filter==='all'||filter==='failed'&&t.failed>0&&!viewed(t)||filter==='unchecked'&&t.unchecked>0&&!viewed(t)||filter==='checked'&&t.checks.length>0||filter==='unreviewed'&&!viewed(t));
const go=(target,t)=>{view=target;if(t){sessionId=t.session;turnId=t.id;}fileFilter=null;render();};
function assessment(t,compact=false){
 const saved=data.explanations?.[t.id],box=node(compact?'span':'div',undefined,compact?'assessment-summary':'reasoning');
 box.append(node('strong',saved?'AI assessment':'AI assessment · not generated'),node(compact?'span':'p',saved?saved.text:'Recorded checks have failed. An agent has not yet assessed whether later changes resolve them.'));
 if(!compact&&saved)box.append(node('span',`based on ${saved.checks.length} recorded checks`,'quiet'));
 if(!compact&&!saved&&transport==='plugin')box.append(button('ask agent to explain',()=>rpc('ui/message',{role:'user',content:[{type:'text',text:`Explain the recorded check conflicts for repository turn ${t.id}. Read its full diff and later turns, then save an evidence-backed explanation.`}]})));
 return box;
}
function chrome(){
 const bar=node('div',undefined,'chrome');bar.append(button('sun / repository',()=>{view='overview';render();}));
 if(view!=='overview')bar.append(button('‹ back',()=>{view=view==='turn'?'session':'overview';fileFilter=null;render();}));
 bar.append(node('span',data.example?'illustrative run · all sessions':'all recorded branches','scope'));return bar;
}
function overview(){
 const top=node('div',undefined,'top'),edits=frame('edits'),s=data.summary;
 const count=node('p',undefined,'edit-count');count.append(node('strong',s.edits.toLocaleString()),document.createTextNode(' agent edits'));edits.append(count);
 const meter=node('div',undefined,'meter'),p=node('progress');p.max=s.edits||1;p.value=s.checked;p.setAttribute('aria-label','Edits with recorded checks');meter.append(p,node('span',s.percent+'%'));edits.append(meter);
 const numbers=node('div',undefined,'numbers');for(const [value,label,key] of [[s.checked,'checked','checked'],[s.unchecked,'unchecked','unchecked']]){const b=button(undefined,()=>{filter=key;ruleFilter=null;render();root.querySelector('.sessions')?.scrollIntoView({block:'nearest'});});b.append(node('strong',value.toLocaleString()),document.createTextNode(' '+label));numbers.append(b);}edits.append(numbers,node('p',`${data.turns.filter(t=>!viewed(t)).length} unreviewed turns · ${new Set(data.turns.map(t=>t.session)).size} sessions`,'quiet footnote'));top.append(edits);
 const rules=frame('rules');
 for(const r of data.rules){const entries=Object.values(data.checks).filter(c=>c.rule===r.name),bad=entries.filter(c=>fail(c.verdict)).length,good=entries.filter(c=>['pass','passed'].includes(c.verdict.toLowerCase())).length;
 const b=button(undefined,()=>{filter='failed';ruleFilter=r.name;render();},'rule-row');b.append(node('span',r.name),node('span',`${bad} failed`,bad?'fail':'quiet'));rules.append(b);
 const detail=node('details');detail.append(node('summary',`${good} passed · rule definition`),node('p',r.text));rules.append(detail);}
 if(!data.rules.length)rules.append(node('p','No rules configured.','quiet'));
 rules.append(node('p','source: RULES.md','rule-source'));top.append(rules);root.append(top);
 const gridbox=frame('turns'),grid=node('div',undefined,'grid');grid.setAttribute('aria-label','All repository turns');
 const caption=node('p',`${data.turns.length} turns · select a square to inspect its diff`,'grid-caption');caption.setAttribute('aria-live','polite');
 for(const t of data.turns){const label=`Turn ${t.label}: ${t.title} · ${t.failed} failed · ${t.passed} passed · ${t.unchecked} unchecked edits${viewed(t)?' · reviewed':''}`;
 const b=button('',()=>go('turn',t),'square '+t.tone+t.intensity+(viewed(t)?' seen':''));b.setAttribute('aria-label',label);b.title=label;b.onmouseenter=b.onfocus=()=>caption.textContent=label;grid.append(b);}
 gridbox.append(grid,caption);
 const legend=node('div',undefined,'legend');for(const [name,tone] of [['no checks','gray'],['passed','green'],['failed','red']]){const span=node('span');for(const i of (tone==='gray'?[0]:[1,2,3]))span.append(node('i',undefined,'square '+tone+i));span.append(document.createTextNode(' '+name));legend.append(span);}legend.append(node('span','darker = more results · any failure wins'));gridbox.append(legend);root.append(gridbox);
 const list=frame('sessions · '+(ruleFilter?ruleFilter+' failures':filter)),tabs=node('div',undefined,'filters');list.className='sessions';
 for(const [key,label] of [['unreviewed','unreviewed'],['failed','failed'],['unchecked','unchecked'],['all','all']]){const b=button(label,()=>{filter=key;ruleFilter=null;render();});b.setAttribute('aria-pressed',String(filter===key));tabs.append(b);}list.append(tabs);
 const sessions=new Map();for(const t of data.turns.filter(matches)){if(!sessions.has(t.session))sessions.set(t.session,[]);sessions.get(t.session).push(t);}
 const sorted=[...sessions.values()].sort((a,b)=>b.reduce((n,t)=>n+t.failed,0)-a.reduce((n,t)=>n+t.failed,0));
 for(const turns of sorted){const t=turns[0],bad=turns.reduce((n,t)=>n+t.failed,0);const b=button(undefined,()=>go('session',t),'session-row');const text=node('span',t.title||'Session '+t.session.slice(0,8));text.append(node('small',`${t.session.slice(0,8)} · ${turns.length} matching turns`));const priority=turns.filter(t=>t.failed).sort((a,b)=>b.failed-a.failed)[0];if(priority){text.append(node('small','turn '+priority.label),assessment(priority,true));}b.append(text,node('span',bad?`${bad} failed`:`${turns.length} unreviewed`,'status'+(bad?'':' neutral')));list.append(b);}
 if(!sorted.length)list.append(node('p','No turns in this group. Other groups remain available.','empty'));root.append(list);
}
function session(){
 const turns=data.turns.filter(t=>t.session===sessionId),box=frame('session · '+sessionId.slice(0,8)),first=turns[0];
 const task=node('div',undefined,'task');task.append(node('span','task'),node('p',first.title));box.append(task);
 for(const t of turns){const b=button(undefined,()=>go('turn',t),'turn-row'),text=node('span',t.title);if(t.failed||data.explanations?.[t.id])text.append(assessment(t,true));b.append(node('span','turn '+t.label),text,node('span',`${t.failed} failed · ${t.passed} passed${viewed(t)?' · reviewed':''}`,t.failed?'fail':t.passed?'pass':'quiet'));box.append(b);}root.append(box);
}
function patch(text){const pre=node('pre',undefined,'patch');for(const line of text.split('\n'))pre.append(node('span',line||' ',line.startsWith('+')?'add':line.startsWith('-')?'remove':line.startsWith('@@')?'meta':''));return pre;}
async function getPatch(change){
 if(transport==='preview')return change.preview;
 if(transport==='plugin'){let text='',offset=0;do{const result=await rpc('tools/call',{name:'read_patch',arguments:{change_id:change.id,offset}});text+=result.structuredContent.patch;offset=result.structuredContent.next_offset;}while(offset!==null);return text;}
 const response=await fetch(change.id+'.patch');if(!response.ok)throw Error('Could not load the complete diff.');return response.text();
}
function turn(){
 const t=data.turns.find(t=>t.id===turnId),box=frame('session · '+t.session.slice(0,8)),turnbox=frame('turn '+t.label);
 const task=node('div',undefined,'task');task.append(node('span','task'),node('p',t.request||t.title));turnbox.append(task);
 if(t.failed||data.explanations?.[t.id])turnbox.append(assessment(t));
 const actions=node('div',undefined,'turn-actions');actions.append(button('entire turn diff',()=>{fileFilter=null;render();}));
 for(const path of [...new Set(t.changes.map(c=>c.file))])actions.append(button(path,()=>{fileFilter=path;render();}));
 turnbox.append(actions);
 for(const c of t.changes.filter(c=>!fileFilter||c.file===fileFilter)){
  const diff=frame(c.file+' · '+(c.at||'').slice(0,7));diff.className='diff-file';const code=patch(c.preview);diff.append(code);
  if(c.bytes>c.preview.length){const more=button(transport==='preview'?'complete diff available in plugin':'load complete file diff',async()=>{more.disabled=true;try{code.replaceWith(patch(await getPatch(c)));more.remove();}catch(e){more.disabled=false;more.textContent=e.message+' Retry';}},'quiet');if(transport==='preview')more.disabled=true;diff.append(more);}
  const results=t.checks.filter(r=>c.checks.includes(r.id));
  for(const result of results){const row=node('div',undefined,'check-result '+(fail(result.verdict)?'fail':'pass'));row.append(node('span',fail(result.verdict)?'×':'✓'),node('span',result.rule),node('p',result.note||result.verdict));diff.append(row);}
  if(!results.length)diff.append(node('p','— no checks recorded','quiet'));turnbox.append(diff);
 }
 const reviewed=button(viewed(t)?'reviewed':'mark turn reviewed',async()=>{try{if(transport==='preview'){data.reviewed=[...(data.reviewed||[]),...t.changes.map(c=>c.id)];}else if(transport==='plugin'){const r=await rpc('tools/call',{name:'review_turn',arguments:{turn_id:t.id}});data.reviewed=r.structuredContent.reviewed;}else{const r=await fetch('review',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({turn:t.id})});if(!r.ok)throw Error('Could not save review');data.reviewed=(await r.json()).reviewed;}render();}catch(e){reviewed.textContent=e.message;}});reviewed.disabled=viewed(t);turnbox.append(reviewed);box.append(turnbox);root.append(box);
}
function render(){root.replaceChildren(chrome());if(view==='overview')overview();else if(view==='session')session();else turn();const footer=node('div',undefined,'footer');footer.append(node('span',data.example?'prototype · illustrative history · repo rules':'prototype · captured repository data'),node('span',transport==='preview'?'preview interactions stay in this chat':'checked ≠ reviewed'));root.append(footer);}
// Standard MCP Apps JSON-RPC bridge. No second model or network origin is needed.
let requestId=0;const pending=new Map();
function rpc(method,params){return new Promise((resolve,reject)=>{const id=++requestId;pending.set(id,{resolve,reject});window.parent.postMessage({jsonrpc:'2.0',id,method,params},'*');setTimeout(()=>{if(pending.delete(id))reject(Error('The host did not respond.'));},10000);});}
if(transport==='plugin'){
 window.addEventListener('message',event=>{if(event.source!==window.parent)return;const m=event.data;if(m?.jsonrpc!=='2.0')return;if(pending.has(m.id)){const p=pending.get(m.id);pending.delete(m.id);m.error?p.reject(Error(m.error.message)):p.resolve(m.result);}if(m.method==='ui/notifications/tool-result'&&m.params?.structuredContent?.turns){data=m.params.structuredContent;render();}});
 rpc('ui/initialize',{protocolVersion:'2026-01-26',appInfo:{name:'sun-review',version:'0.1.0'},appCapabilities:{}}).then(()=>window.parent.postMessage({jsonrpc:'2.0',method:'ui/notifications/initialized'},'*')).catch(()=>{});
 new ResizeObserver(()=>window.parent.postMessage({jsonrpc:'2.0',method:'ui/notifications/size-changed',params:{height:document.documentElement.scrollHeight}},'*')).observe(root);
}
render();
})();
