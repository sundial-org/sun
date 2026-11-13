import {queue, requiredChecks, githubUrl, pageSize} from './model.mjs';
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let data = {prs: [], skills: [], prompt: ''}, mode = 'focus', page = 0, selected, tab = 'review', file = '', action = 'local';
const done = new Set();
try { if (localStorage.getItem('sun-review-action') === 'github') action = 'github'; } catch {}
const statusClass = status => ({Passed:'passed', Nonpassing:'failed', Outdated:'outdated'}[status] || '');
const button = (label, attributes = '') => `<button ${attributes}>${esc(label)}</button>`;

function render() {
  for (const name of ['focus', 'waiting', 'later']) {
    $(name+'-count').textContent = queue(data.prs, name, '', done).length;
    $(name+'-tab').setAttribute('aria-pressed', mode === name);
    $(name+'-tab').classList.toggle('active', mode === name);
  }
  const items = queue(data.prs, mode, $('search').value, done);
  page = Math.max(0, Math.min(page, Math.ceil(items.length/pageSize)-1));
  const visible = items.slice(page*pageSize, (page+1)*pageSize);
  if (!visible.some(p => p.id === selected)) { selected = visible[0]?.id; tab = 'review'; file = ''; }
  $('queue').innerHTML = visible.map((p, i) => `<button class="row ${p.id===selected?'selected':''}" data-pr="${esc(p.id)}" aria-current="${p.id===selected}"><span class="rank">${page*pageSize+i+1}</span><strong>${esc(p.title)}</strong></button>`).join('') || '<p class="empty">No PRs here. Try another queue or search.</p>';
  $('position').textContent = items.length ? `${page*pageSize+1}–${Math.min((page+1)*pageSize,items.length)} of ${items.length}` : '0 results';
  $('previous').disabled = page === 0;
  $('next').disabled = (page+1)*pageSize >= items.length;
  document.querySelectorAll('[data-pr]').forEach(b => b.onclick = () => {selected=b.dataset.pr;tab='review';file='';renderBrief()});
  renderBrief();
}
function renderBrief() {
  const p = data.prs.find(p => p.id === selected);
  if (!p) { $('brief').innerHTML='<h2>No review selected</h2>'; return; }
  document.querySelectorAll('[data-pr]').forEach(b => {b.classList.toggle('selected', b.dataset.pr===selected);b.setAttribute('aria-current',b.dataset.pr===selected)});
  const a = p.analysis || {}, r = p.review;
  const url = githubUrl(p);
  const files = r ? [...r.items, ...r.hidden_files] : [];
  const views = [['review','Review'], ...(r ? [['diff','Diff']] : []), ...(a.depends_on?.length ? [['dependencies',`Dependencies (${a.depends_on.length})`]] : [])];
  let content = '';
  if (p.error) content=`<p class="error">${esc(p.error)}</p><p class="quiet">Prepare a new snapshot to retry. This PR has not been analyzed.</p>`;
  else if (tab === 'review') {
    content=`<h3 class="decision">${esc(a.question)}</h3><p class="explain">${esc(a.why)}</p>`;
    if (a.before || a.after) content+=`<details class="context"><summary>What changes</summary><div class="change"><div><small>Before</small>${esc(a.before)}</div><div><small>After</small>${esc(a.after)}</div></div></details>`;
    if (a.evidence?.length) content+=`<div class="evidence">${a.evidence.map((cite,i)=>`<button data-evidence="${i}">${esc(cite.file)}</button><p class="explain">${esc(cite.note)}</p>`).join('')}</div>`;
    if (r.coverage?.warning) content+=`<p class="quiet">${esc(r.coverage.warning)}</p>`;
    const checks = requiredChecks(p);
    content+=checks.length ? '<div class="check-list">'+checks.map(c=>`<details class="check"><summary><span class="check-name">${esc(c.name)}</span><span class="badge ${statusClass(c.status)}">${esc(c.status)}</span></summary>${(c.files||[]).map(f=>`<small>${esc(f.file)} · ${esc(f.status)}</small>`).join('')}${(c.checks||[]).map(c=>`<small>${esc(c.id)} · ${esc(c.verdict)} · ${esc(c.actor)}</small>`).join('')}${c.detail?`<small>${esc(c.detail)}</small>`:!c.checks?.length?'<small>No matching run recorded in this snapshot.</small>':''}</details>`).join('')+'</div>' : '<p class="quiet">No Sun check rules recorded for this PR.</p>';
  } else if (tab === 'diff') {
    if (!files.some(f=>f.file===file)) file=files[0]?.file;
    const current=files.find(f=>f.file===file);
    content=files.length?`<label class="field">File<select id="file">${files.map(f=>`<option value="${esc(f.file)}" ${file===f.file?'selected':''}>${esc(f.file)}</option>`).join('')}</select></label><p class="quiet">${esc(current.reason)}</p><div class="code" tabindex="0" aria-label="Code diff">${current.patch.split('\n').map(line=>`<div class="${line.startsWith('+')?'added':line.startsWith('-')?'removed':''}">${esc(line)||' '}</div>`).join('')}</div>`:'<p class="empty">No changed files.</p>';
  } else {
    content='<p class="explain">Review these dependencies first.</p><div class="flow">'+a.depends_on.map(id=>{const dep=data.prs.find(p=>p.id===id);return `<button data-dependency="${esc(id)}">${esc(dep.title)}<small>${esc(id)}</small></button>`}).join('')+'</div>';
  }
  const finish = action==='github' && url ? `<a class="button" href="${esc(url)}" target="_blank" rel="noopener noreferrer">Review on GitHub</a>` : button('Mark reviewed', 'id="done" title="Only changes this local queue"');
  $('brief').innerHTML=`<h2>${esc(p.title)}</h2><div class="meta"><span>${esc(p.id)} · ${esc(p.author?.login||'')}</span><code>${esc(r?.head?.slice(0,8)||'Revision unavailable')}</code></div><div class="tabs" role="group" aria-label="Review views">${views.map(([key,label])=>button(label,`data-view="${key}" aria-pressed="${tab===key}"`)).join('')}</div>${content}<div class="actions">${r?button('Ask agent','class="primary" id="agent"'):''}${finish}</div>`;
  document.querySelectorAll('[data-view]').forEach(b=>b.onclick=()=>{tab=b.dataset.view;renderBrief();document.querySelector(`[data-view="${tab}"]`).focus()});
  document.querySelectorAll('[data-evidence]').forEach(b=>b.onclick=()=>{file=a.evidence[Number(b.dataset.evidence)].file;tab='diff';renderBrief()});
  document.querySelectorAll('[data-dependency]').forEach(b=>b.onclick=()=>{$('search').value=b.dataset.dependency;selected=b.dataset.dependency;page=0;tab='review';render()});
  if ($('file')) $('file').onchange=e=>{file=e.target.value;renderBrief();$('file').focus()};
  if ($('done')) $('done').onclick=()=>{done.add(p.id);render();toast('Marked reviewed locally.',()=>{done.delete(p.id);$('search').value=p.id;selected=p.id;render()})};
  if ($('agent')) $('agent').onclick=()=>{
    $('prompt').textContent=`Continue the Sun review of ${p.id} at ${r.head}.\nQuestion: ${a.question}\nMy priorities: ${data.prompt}\nSelected skills: ${['sun-review',...data.skills].join(', ')}\nInspect the pinned evidence and update review.json. If code or checks changed, prepare a fresh snapshot.\nChecks needing attention:\n`+requiredChecks(p).filter(c=>!['Passed','Not applicable'].includes(c.status)).map(c=>`${c.name}: ${c.status}`).join('\n');
    $('agent-dialog').showModal();
  };
}
let timer;
function toast(message, undo) {
  clearTimeout(timer);$('toast').textContent=message;
  if(undo){const b=document.createElement('button');b.textContent='Undo';b.onclick=()=>{undo();$('toast').style.display='none'};$('toast').append(b)}
  $('toast').style.display='block';if(!undo)timer=setTimeout(()=>$('toast').style.display='none',3500);
}
for(const name of ['focus','waiting','later']) $(name+'-tab').onclick=()=>{mode=name;page=0;tab='review';$('search').value='';render()};
$('search').oninput=()=>{page=0;render()};
$('previous').onclick=()=>{page--;render()};$('next').onclick=()=>{page++;render()};
$('skills').onclick=()=>{
  $('skill-list').textContent=['sun-review',...data.skills].join(' · ');
  $('user-prompt').textContent=data.prompt||'No additional priorities supplied.';
  $('skills-dialog').showModal();
};
$('settings').onclick=()=>{$('review-action').value=action;$('settings-dialog').showModal()};
$('save-settings').onclick=()=>{
  action=$('review-action').value;let message='Review action saved for this browser origin.';
  try{localStorage.setItem('sun-review-action',action)}catch{message='Applied for this tab; browser storage unavailable.'}
  $('settings-dialog').close();renderBrief();toast(message);
};
for(const b of document.querySelectorAll('[data-close]')) b.onclick=()=>$(b.dataset.close).close();
$('download').onclick=()=>{const a=document.createElement('a'),url=URL.createObjectURL(new Blob([$('prompt').textContent],{type:'text/plain'}));a.href=url;a.download='sun-review-request.txt';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)};
async function start(){
  const response=await fetch('data.json');if(!response.ok)throw Error('Snapshot unavailable');
  data=await response.json();
  if(!data.prs.length){render();$('brief').innerHTML='<h2>No review requests</h2><p class="muted">Your GitHub review inbox is empty.</p>';return}
  if(data.prs.every(p=>p.error||p.analysis?.waiting))mode='waiting';
  render();
}
start().catch(error=>{$('brief').innerHTML=`<h2>Review could not load</h2><p class="error">${esc(error.message)}</p><p class="muted">Reopen this review with Sun.</p>`});
