import { buildPresentation, parseZip, renderSlide, RECOMMENDED_ZIP_LIMITS } from '@aiden0z/pptx-renderer/browser';

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text != null) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function cellText(cell) {
  if (!cell) return '';
  return [cell.formula, cell.value?.text].filter(value => value != null).join('\n');
}

function spreadsheet(doc, container) {
  if (!doc.sheets.length) container.append(element('p', 'No cell changes.'));
  for (const sheet of doc.sheets) {
    const section = element('section', null, 'sheet-diff');
    section.append(element('h3', sheet.name + (sheet.status === 'changed' ? '' : ` · ${sheet.status}`)));
    const table = element('table');
    table.setAttribute('aria-label', sheet.name);
    const head = element('thead'), headings = element('tr');
    for (const title of ['Cell', 'Before', 'After']) {
      const th = element('th', title); th.scope = 'col'; headings.append(th);
    }
    head.append(headings);
    const body = element('tbody');
    for (const cell of sheet.cells) {
      const row = element('tr'), label = element('th', cell.cell); label.scope = 'row';
      row.append(label, element('td', cellText(cell.before), 'removed'), element('td', cellText(cell.after), 'added'));
      body.append(row);
    }
    table.append(head, body); section.append(table); container.append(section);
  }
}

export function documentView(index, container, notice, fallback) {
  let disposed = false, handles = [], observers = [], selection = 0;
  function clearSlides() {
    observers.forEach(o => o.disconnect()); observers = [];
    handles.forEach(h => h.dispose()); handles = [];
  }
  async function loadDeck(side) {
    const response = await fetch(`documents/${index}/${side}.pptx`);
    if (!response.ok) throw new Error('Slide preview could not be loaded');
    return buildPresentation(await parseZip(await response.arrayBuffer(), RECOMMENDED_ZIP_LIMITS));
  }
  async function load() {
    const response = await fetch(`documents/${index}/diff.json`);
    if (!response.ok) throw new Error('Document comparison could not be loaded');
    const doc = await response.json();
    if (disposed) return;
    notice.textContent = '';
    if (doc.kind === 'unavailable') { fallback(doc.notice); return; }
    if (doc.kind === 'spreadsheet') { spreadsheet(doc, container); return; }
    const label = element('label', 'Slide '), picker = element('select');
    picker.setAttribute('aria-label', 'Slide to compare');
    doc.slides.forEach((slide, i) => {
      const info = slide.after || slide.before;
      const option = element('option', `${info.index + 1}. ${info.title} · ${slide.status}`);
      option.value = i; picker.append(option);
    });
    label.append(picker); container.append(label);
    const details = element('div', null, 'slide-detail'); container.append(details);
    let decks;
    try {
      decks = await Promise.all(['before', 'after'].map(side =>
        doc.slides.some(s => s[side]) ? loadDeck(side) : null));
    } catch (error) {
      if (disposed) return;
      notice.textContent += ` ${error.message}. Text comparison remains available.`;
      decks = [null, null];
    }
    if (disposed) return;
    async function show() {
      const version = ++selection;
      clearSlides(); details.replaceChildren();
      const slide = doc.slides[Number(picker.value)];
      const pair = element('div', null, 'slide-pair'); details.append(pair);
      for (const [i, side] of ['before', 'after'].entries()) {
        const info = slide[side], panel = element('section', null, 'slide-panel');
        panel.append(element('h3', side === 'before' ? 'Before' : 'After'));
        pair.append(panel);
        if (!info) { panel.append(element('p', 'Slide not present', 'empty-slide')); continue; }
        if (decks[i]) {
          const preview = element('div', null, 'slide-preview'); preview.inert = true;
          preview.setAttribute('aria-hidden', 'true'); panel.append(preview);
          try {
            const handle = renderSlide(decks[i], decks[i].slides[info.index], {externalMedia:'block', pdfjs:false});
            handles.push(handle); preview.append(handle.element);
            const fit = () => {
              const scale = preview.clientWidth / decks[i].width;
              handle.element.style.transformOrigin = 'top left';
              handle.element.style.transform = `scale(${scale})`;
              preview.style.height = `${decks[i].height * scale}px`;
            };
            const observer = new ResizeObserver(fit); observer.observe(preview); observers.push(observer); fit();
            await handle.ready;
            if (disposed || version !== selection) return;
          } catch (error) { preview.replaceChildren(element('p', 'Preview unavailable. See slide text below.')); }
        }
        const text = element('details');
        text.append(element('summary', 'Slide text and speaker notes'));
        text.append(element('pre', info.shapes.map(s => s.text).filter(Boolean).join('\n\n') || '(No slide text)'));
        if (info.notes) text.append(element('h4', 'Speaker notes'), element('pre', info.notes));
        panel.append(text);
      }
    }
    picker.addEventListener('change', show);
    if (doc.slides.length) await show();
  }
  load().catch(error => { if (!disposed) fallback(error.message); });
  return {cleanUp() { disposed = true; clearSlides(); }};
}
