import {prs,ranked,requiredChecks} from './model.mjs?v=2';
import {settingsKey,readSettings,reviewAction,githubReviewUrl} from './review-action.mjs';
const $=id=>document.getElementById(id), esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let prefs={security:false,reliability:false,ponytail:false,instructions:'',skill:''}, done=new Set(), selected=184, mode='focus',page=0, tab='brief';
// Storage may be disabled by the browser. Keep the UI usable in that case.
let actionSettings;try{actionSettings=readSettings(window.localStorage)}catch{actionSettings=readSettings(null)}
const statusClass=s=>({'Passed':'passed','Failed':'failed','Outdated':'outdated','Not run':'notrun'}[s]||'');
function queue(){
 const all=ranked(prs,prefs,done),query=$('search').value.toLowerCase();
 if(query)return prs.filter(p=>!done.has(p.id)&&(p.title.toLowerCase().includes(query)||String(p.id).includes(query.replace('#',''))));
 if(mode==='waiting')return prs.filter(p=>p.waiting&&!done.has(p.id));
 return mode==='later'?all.slice(5):all.slice(0,5);
}
function querying(){return $('search').value.trim().length>0}
function render(){
 const all=ranked(prs,prefs,done),items=queue(),slice=items.slice(page*5,page*5+5);
 if(!slice.some(p=>p.id===selected)){selected=slice[0]?.id;tab='brief'}
 $('focus-count').textContent=Math.min(5,all.length);$('later-count').textContent=Math.max(0,all.length-5);
 $('waiting-count').textContent=prs.filter(p=>p.waiting&&!done.has(p.id)).length;
 for(const name of ['focus','waiting','later']){$(name+'-tab').classList.toggle('active',mode===name);$(name+'-tab').setAttribute('aria-pressed',mode===name)}
 $('queue').innerHTML=slice.map((p,i)=>'<button class="row '+(selected===p.id?'selected':'')+'" data-pr="'+p.id+'" aria-current="'+(selected===p.id?'true':'false')+'" aria-label="Open PR '+p.id+': '+esc(p.title)+'"><span class="rank">'+String(page*5+i+1).padStart(2,'0')+'</span><strong>'+esc(p.title)+'</strong></button>').join('')||(querying()?'<p class="empty">No matches. Try a title or PR number.</p>':'<p class="empty">Nothing left in this queue.</p>');
 $('page').textContent=items.length?Math.min(page*5+1,items.length)+'–'+Math.min(page*5+5,items.length)+' of '+items.length:'0 results';
 $('prev').disabled=page===0;$('next').disabled=(page+1)*5>=items.length;
 document.querySelectorAll('[data-pr]').forEach(b=>b.onclick=()=>{selected=Number(b.dataset.pr);tab='brief';render()});
 renderBrief();
}
function renderBrief(){
 const p=prs.find(p=>p.id===selected);if(!p){$('brief').innerHTML='<h2>No review selected</h2><p class="muted">Choose a different queue or search.</p>';return}
 const checks=requiredChecks(p,prefs), action=reviewAction(actionSettings,p.id);
 let content='';
 const priority = prefs.security&&p.kind==='security'?'Your security skill moves this first. ':prefs.reliability&&p.kind==='reliability'?'Your reliability skill moves this first. ':'';
 if(tab==='brief')content='<h3 class="decision">'+esc(p.question)+'</h3><p class="explain">'+esc(priority+p.why)+'</p><details class="context"><summary>What changes</summary><div class="change"><div><small>Before</small>'+esc(p.before)+'</div><div><small>After</small>'+esc(p.after)+'</div></div></details><div class="check-list">'+checks.map(c=>'<details class="check"><summary><span class="check-name">'+esc(c.name)+'</span><span class="badge '+statusClass(c.status)+'">'+esc(c.status)+'</span></summary><small>'+esc(c.detail)+'</small></details>').join('')+'</div>';
 if(tab==='diff')content='<p class="explain">'+esc(p.evidence)+'</p><div class="filehead"><span>'+esc(p.path)+'</span><span>'+esc(p.head)+'</span></div><div class="code" tabindex="0" aria-label="Code diff"><div class="removed">− '+esc(p.old)+'</div>'+p.code.split('\n').map(l=>'<div class="added">+ '+esc(l)+'</div>').join('')+'</div><p class="quiet">Decision-relevant excerpt · '+p.files+' files changed</p>';
 if(tab==='map')content='<p class="explain">Review the retry contract before its callers.</p><div class="flow"><button data-map="184"><b>#184 Retry contract</b><small>Review first</small></button><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-label="Blocks"><path d="M3 12h18m-6-6 6 6-6 6"/></svg><div class="callers"><button data-map="185">#185 Checkout caller<small>Waiting on #184</small></button><button data-map="186">#186 Worker caller<small>Waiting on #184</small></button></div></div><p id="map-note" class="muted" role="status"></p>';
 $('brief').innerHTML='<h2>'+esc(p.title)+'</h2><div class="meta"><span>#'+p.id+' · '+esc(p.author)+'</span><code>'+esc(p.head)+'</code></div><div class="tabs" role="group" aria-label="Review views">'+[['brief','Review'],['diff','Diff'],...(p.depends.length?[['map','Dependencies ('+p.depends.length+')']]:[])].map(([key,label])=>'<button data-tab="'+key+'" aria-pressed="'+(key===tab)+'">'+label+'</button>').join('')+'</div>'+content+(prefs.instructions?'<details class="personal-note"><summary>Your instructions</summary>'+esc(prefs.instructions)+'</details>':'')+'<div class="actions"><button class="primary" id="agent">Ask agent</button>'+(action.url?'<a class="button" href="'+esc(action.url)+'" target="_blank" rel="noopener noreferrer" title="Open the linked PR. Submit approval on GitHub.">'+action.label+'</a>':'<button id="done" title="'+(action.local?'Only changes this local queue.':'Choose the GitHub PR to review.')+'">'+action.label+'</button>')+'</div>';
 document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>{tab=b.dataset.tab;renderBrief();document.querySelector('[data-tab="'+tab+'"]').focus()});
 document.querySelectorAll('[data-map]').forEach(b=>b.onclick=()=>{$('map-note').textContent=b.dataset.map==='184'?'The contract defines whether retries are safe for both callers.':'PR #'+b.dataset.map+' waits for the idempotency decision in #184.'});
 if($('done'))$('done').onclick=()=>{if(!action.local){openSettings();return}done.add(p.id);tab='brief';page=0;render();toast('Marked reviewed locally.',()=>{done.delete(p.id);selected=p.id;mode='focus';page=0;render()})};
 $('agent').onclick=()=>{$('prompt').textContent=handoff(p);$('handoff').showModal()};
}
function handoff(p){return 'Use the Sun default PR review skill for PR #'+p.id+' at '+p.head+'.\nVerify current check coverage and cite exact files and revisions.\n\nDecision: '+p.question+'\n\nAdditional skills: '+[prefs.security&&'Security review',prefs.reliability&&'Reliability',prefs.ponytail&&'Ponytail'].filter(Boolean).join(', ')+'\n\nPersonal instructions:\n'+(prefs.instructions||'None')+'\n\nImported skill:\n'+(prefs.skill||'None')+'\n\nMissing or outdated checks:\n'+requiredChecks(p,prefs).filter(c=>!['Passed','Not applicable'].includes(c.status)).map(c=>c.name+': '+c.status).join('\n')+'\n\nReturn a concise explainer, evidence links, and unresolved questions. Do not infer a passing result from missing evidence.'}
let toastTimer;
function toast(text,undo){clearTimeout(toastTimer);$('toast').textContent=text;if(undo){const button=document.createElement('button');button.textContent='Undo';button.onclick=()=>{undo();$('toast').style.display='none'};$('toast').append(button)}$('toast').style.display='block';if(!undo)toastTimer=setTimeout(()=>$('toast').style.display='none',3500)}
function personalize(){$('preferences').showModal()}
function updateActionFields(){
 const github=$('review-action').value==='github';
 $('github-link-field').hidden=!github||selected==null;
 $('action-help').textContent=github?'Opens the linked PR. Submit approval on GitHub; this queue stays unchanged.':'Removes the item from this queue. No GitHub approval is submitted.';
}
function openSettings(){
 $('review-action').value=actionSettings.action;
 $('github-link').value=actionSettings.links[selected]||'';
 $('github-link-label').textContent='GitHub URL for review #'+selected;
 $('action-error').textContent='';updateActionFields();$('action-settings').showModal();
}
$('settings').onclick=openSettings;
$('close-settings').onclick=()=>$('action-settings').close();
$('review-action').onchange=updateActionFields;
$('action-form').onsubmit=e=>{
 e.preventDefault();
 const raw=$('github-link').value.trim(),url=raw?githubReviewUrl(raw):null;
 if($('review-action').value==='github'&&raw&&!url){$('action-error').textContent='Enter an HTTPS github.com pull request URL.';return}
 const links={...actionSettings.links};
 if(selected!=null&&$('review-action').value==='github'){if(url)links[selected]=url;else delete links[selected]}
 actionSettings={action:$('review-action').value,links};
 let message='Review action saved.';
 try{window.localStorage.setItem(settingsKey,JSON.stringify(actionSettings))}catch{message='Applied for this tab. Browser storage is unavailable.'}
 $('action-settings').close();renderBrief();toast(message);
};
$('personalize').onclick=personalize;
$('apply').onclick=()=>{prefs={...prefs,security:$('security').checked,reliability:$('reliability').checked,ponytail:$('ponytail').checked,instructions:$('instructions').value.trim()};page=0;mode='focus';tab='brief';selected=null;$('search').value='';$('preferences').close();render();toast('Queue reordered. Check results are unchanged.')};
$('skill-file').onchange=async e=>{const f=e.target.files[0];if(!f)return;if(f.size>100000){$('skill-loaded').textContent='Choose a skill smaller than 100 KB.';return}try{prefs.skill=await f.text();$('skill-loaded').textContent=f.name+' loaded. Included in the agent handoff; not executed.'}catch{$('skill-loaded').textContent='Could not read this skill. Choose the file again.'}};
$('close-handoff').onclick=()=>$('handoff').close();
$('download-prompt').onclick=()=>{const a=document.createElement('a'),url=URL.createObjectURL(new Blob([$('prompt').textContent],{type:'text/plain'}));a.href=url;a.download='sun-review-prompt.txt';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)};
for(const name of ['focus','waiting','later'])$(name+'-tab').onclick=()=>{mode=name;page=0;$('search').value='';render()};
$('search').oninput=()=>{page=0;render()};
$('prev').onclick=()=>{page--;render()};$('next').onclick=()=>{page++;render()};
document.addEventListener('keydown',e=>{if(e.key==='p'&&!['INPUT','TEXTAREA'].includes(document.activeElement.tagName)&&!document.querySelector('dialog[open]'))personalize()});
render();
