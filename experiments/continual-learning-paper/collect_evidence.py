"""Read the local pilot archives without model calls or modifying those archives."""
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = HERE / 'evidence'
WRITING = ROOT / 'exp_writing/runs/ten-writers-20260926-inkling'
LEAN = ROOT / 'exp_lean/runs/20260926-01'
PINS = {'proposal': 'db853b1323dd009cbcc190ff23329c3233390be6',
        'lean': '53d158033da9c7a332797c4d9148b18f9e1ae140',
        'writing': 'b30271fbd9e9f55689488664acef7e3bd20d05eb'}
manifest = {'source_commits': PINS, 'files': {}, 'committed_snapshots': {}}


def read(path):
    data = path.read_bytes()
    manifest['files'][str(path.relative_to(ROOT))] = hashlib.sha256(data).hexdigest()
    return json.loads(data)


def save(name, obj, compressed=False):
    data = (json.dumps(obj, sort_keys=True, separators=(',', ':')) + '\n').encode()
    if compressed:
        data = gzip.compress(data, mtime=0)
    (OUT / name).write_bytes(data)


def snapshot(kind, path, name, require_match=True):
    data = subprocess.check_output(['git', 'show', f'{PINS[kind]}:{path}'], cwd=ROOT)
    matches = data == (ROOT / path).read_bytes()
    assert matches or not require_match, f'Local source differs: {path}'
    digest = hashlib.sha256(data).hexdigest()
    if matches:
        manifest['files'][path] = digest
    manifest['committed_snapshots'][name] = {'commit': PINS[kind], 'path': path,
        'sha256': digest, 'local_matches_commit': matches}
    (OUT / name).write_bytes(data)


snapshot('writing', 'exp_writing/runs/ten-writers-20260926-inkling/analysis.json', 'writing-analysis.json')
snapshot('writing', 'exp_writing/PROTOCOL.md', 'writing-protocol.md')
snapshot('writing', 'exp_writing/README.md', 'writing-readme.md', require_match=False)
snapshot('writing', 'exp_writing/AMENDMENTS.md', 'writing-amendments.md')
snapshot('writing', 'exp_writing/style.py', 'writing-scorer-source.py')
snapshot('writing', 'exp_writing/runs/ten-writers-20260926-inkling/training_manifest.json', 'writing-training.json')
snapshot('writing', 'exp_writing/runs/ten-writers-20260926-inkling/prompts.json', 'writing-prompts.json')
snapshot('writing', 'exp_writing/runs/ten-writers-20260926-inkling/integrity.json', 'writing-integrity.json')
snapshot('lean', 'exp_lean/audit/curve-audit.md', 'lean-audit.md')
snapshot('lean', 'exp_lean/README.md', 'lean-readme.md')
snapshot('lean', 'exp_lean/audit/pre-correction/analysis.json', 'lean-original-analysis.json')
snapshot('proposal', 'experiments/continual-learning-proposal.md', 'proposal-v3.md')
snapshot('writing', 'exp_writing/analyze.py', 'writing-analysis-source.py')
snapshot('lean', 'exp_lean/scorer.py', 'lean-scorer-source.py')
wa = json.loads((OUT / 'writing-analysis.json').read_text())
records = {}
for path in sorted((WRITING / 'evaluations').glob('*.json')):
    rows = read(path)
    assert manifest['files'][str(path.relative_to(ROOT))] == wa['evaluation_files'][path.name]
    compact = []
    for row in rows:
        for guide in ['A', 'B']:
            flags = [v for v in row['scores'][guide]['rules'] if v is not None]
            assert abs(sum(flags) / len(flags) - row['scores'][guide]['S']) < 1e-12
        # Recompute the public format checker directly from the actual draft.
        import re
        text = row['story']
        public = 120 <= len(text.split()) <= 350 and all(
            re.search(r'\b' + re.escape(a) + r'\b', text, re.I)
            for a in row['format']['required_words'])
        assert public == row['format']['pass']
        assert not row['U'] or public
        compact.append([row['prompt']['id'], row['U'], row['scores']['A']['rules'],
                        row['scores']['B']['rules']])
    records[path.stem] = compact
save('writing-records.json.gz', records, True)

best = []
for row in read(WRITING / 'best_of_n.json'):
    best.append({'id': row['id'], 'prompt': row['prompt']['id'], 'U': row['U'],
                 'story_hash': hashlib.sha256(row['story'].encode()).hexdigest(),
                 'S': row['scores']['S'], 'kept': row['provenance']['kept']
                 if row.get('editor_valid') else -1})
save('selection-records.json.gz', best, True)

sys.path.insert(0, str(ROOT / 'exp_lean'))
from scorer import facts, parse_report, score
traces = {t['sid']: t for t in (read(p) for p in sorted((LEAN / 'trajectories/heldout').glob('*.json')))}
truth = {sid: facts(t) for sid, t in traces.items()}
lean = {'traces': {sid: {'truth': sorted(truth[sid]), 'lemma': t['task']['id'],
                       'family': t['task']['family'],
                       'exit_event': 'E4' if not t['receipts'] or
                       t['receipts'][-1]['exit_code'] != 0 or
                       t['receipts'][-1]['timeout'] else 'E5'} for sid, t in traces.items()},
        'evaluations': {}}
for path in sorted((LEAN / 'evaluation').glob('*.json')):
    data = read(path)
    compact = []
    for row in data['results']:
        sid = row['sid']
        assert set(row['truth']) == truth[sid]
        for report, saved in zip(row['reports'] + [row['greedy_report']], row['scores'] + [row['greedy']]):
            assert score(report, truth[sid], traces[sid]['task']['id']) == saved
        compact.append({'sid': sid, 'reports': [parse_report(r) for r in row['reports']],
                        'greedy': parse_report(row['greedy_report'])})
    lean['evaluations'][path.stem] = compact
save('lean-records.json.gz', lean, True)
manifest['compact_sha256'] = {name: hashlib.sha256((OUT / name).read_bytes()).hexdigest()
    for name in ['writing-records.json.gz', 'selection-records.json.gz', 'lean-records.json.gz']}
save('source-manifest.json', manifest)
print(f'Collected {sum(map(len, records.values()))} writing samples and {len(traces)} Lean traces; source hashes match committed writing analysis.')
