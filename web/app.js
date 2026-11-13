import { FileDiff, parsePatchFiles } from '@pierre/diffs';
import { documentView } from './documents.js';

const $ = id => document.getElementById(id);
let data, items = [], selected = 0, instances = [], generation = 0;
function clearDiff() {
  instances.forEach(instance => instance.cleanUp());
  instances = [];
  $('diff').replaceChildren();
}
function rawPatch(item, message) {
  $('notice').textContent = message;
  const pre = document.createElement('pre');
  pre.textContent = item.patch;
  $('diff').append(pre);
}
function select(index) {
  selected = index;
  const version = ++generation;
  clearDiff();
const item = items[index];
  const documentFile = /\.(csv|tsv|xlsx|pptx|key)$/i.test(item.file);
  $('layout').disabled = documentFile;
  $('notice').textContent = '';
  $('position').textContent = `${index + 1} / ${items.length}`;
  $('previous').disabled = index === 0;
  $('next').disabled = index === items.length - 1;
  [...$('files').children].forEach((button, i) => button.setAttribute('aria-current', String(i === index)));
  const showRaw = message => {
    if (version !== generation) return;
    clearDiff();
    rawPatch(item, message);
  };
  if (documentFile) {
    $('notice').textContent = 'Loading document comparison…';
    instances.push(documentView(item.sourceIndex, $('diff'), $('notice'), showRaw));
    return;
  }
  if (!item.patch.includes('\n@@ ')) {
    rawPatch(item, 'Metadata or binary change. No text hunks to render.');
    return;
  }
  try {
    const patches = parsePatchFiles(item.patch);
    if (!patches.some(patch => patch.files.length)) throw new Error('No text diff parsed');
    for (const patch of patches) for (const fileDiff of patch.files) {
      const instance = new FileDiff({
        theme: 'pierre-light',
        themeType: 'light',
        diffStyle: $('layout').value,
        disableFileHeader: true,
        overflow: 'wrap',
        loadDiffFiles: async () => {
          const response = await fetch(`files/${item.sourceIndex}.json`);
          if (!response.ok) {
            if (version === generation) $('notice').textContent = 'Full file context could not be loaded.';
            throw new Error('Could not load full file context');
          }
          return response.json();
        },
      });
      instances.push(instance);
      instance.render({fileDiff, containerWrapper:$('diff')});
    }
  } catch (error) { showRaw(`Showing raw patch: ${error.message}`); }
}
async function start() {
  const response = await fetch('data.json');
  if (!response.ok) throw new Error('Could not load this review snapshot');
  data = await response.json();
  $('revision').textContent = `base ${data.base.slice(0,8)} → ${data.head.slice(0,8)}`;
  const needs = data.items.map((item, i) => ({...item, sourceIndex:i}));
  const covered = data.hidden_files.map((item, i) => ({...item, sourceIndex:needs.length+i}));
  [...$('scope').options].forEach((option, i) => {
    option.textContent += ` (${[needs.length, covered.length, needs.length+covered.length][i]})`;
  });
  function showFiles() {
    generation++;
    clearDiff();
    items = $('scope').value === 'covered' ? covered : $('scope').value === 'all' ? [...needs, ...covered] : needs;
    $('files').replaceChildren();
    items.forEach((item, index) => {
      const button = document.createElement('button');
      button.type = 'button'; button.textContent = item.file;
      button.title = item.reason;
      button.addEventListener('click', () => select(index));
      $('files').append(button);
    });
    $('layout').disabled = !items.length;
    if (items.length) select(0);
    else {
      $('notice').textContent = 'No files in this view.';
      $('position').textContent = '0 / 0';
      $('previous').disabled = $('next').disabled = true;
    }
  }
  $('scope').addEventListener('change', showFiles);
  showFiles();
  $('layout').addEventListener('change', () => items.length && select(selected));
  $('previous').addEventListener('click', () => select(Math.max(0, selected-1)));
  $('next').addEventListener('click', () => select(Math.min(items.length-1, selected+1)));

}
start().catch(error => { $('notice').textContent = `Review could not load: ${error.message}`; });
