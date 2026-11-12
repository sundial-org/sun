import { FileDiff, parsePatchFiles } from '@pierre/diffs';
import { documentView } from './documents.js';

const $ = id => document.getElementById(id);
let data, selected = 0, instances = [], generation = 0;
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
  const item = data.items[index];
  const documentFile = /\.(csv|tsv|xlsx|pptx|key)$/i.test(item.file);
  $('layout').disabled = documentFile;
  $('notice').textContent = '';
  $('position').textContent = `${index + 1} / ${data.items.length}`;
  $('previous').disabled = index === 0;
  $('next').disabled = index === data.items.length - 1;
  [...$('files').children].forEach((button, i) => button.setAttribute('aria-current', String(i === index)));
  const showRaw = message => {
    if (version !== generation) return;
    clearDiff();
    rawPatch(item, message);
  };
  if (documentFile) {
    $('notice').textContent = 'Loading document comparison…';
    instances.push(documentView(index, $('diff'), $('notice'), showRaw));
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
          const response = await fetch(`files/${index}.json`);
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
  $('omittedSummary').textContent = `${data.hidden_files.length} checked files omitted`;
  for (const file of data.hidden_files) {
    const row = document.createElement('div');
    const name = document.createElement('strong'); name.textContent = file.file;
    const reason = document.createElement('p'); reason.textContent = file.reason;
    const ids = document.createElement('code'); ids.textContent = file.checks.join(', ');
    row.append(name, reason, ids); $('omitted').append(row);
  }
  data.items.forEach((item, index) => {
    const button = document.createElement('button');
    button.type = 'button'; button.textContent = item.file;
    button.addEventListener('click', () => select(index));
    $('files').append(button);
  });
  $('layout').addEventListener('change', () => data.items.length && select(selected));
  $('previous').addEventListener('click', () => select(Math.max(0, selected-1)));
  $('next').addEventListener('click', () => select(Math.min(data.items.length-1, selected+1)));
  if (data.items.length) select(0);
  else {
    $('notice').textContent = data.files ? 'All changed files have matching passing checks.' : 'No changed files against this base.';
    $('previous').disabled = $('next').disabled = $('layout').disabled = true;
  }
}
start().catch(error => { $('notice').textContent = `Review could not load: ${error.message}`; });
