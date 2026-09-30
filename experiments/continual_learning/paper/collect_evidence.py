"""Package saved experimental records for a portable, offline paper audit.

No model calls. Refuses to package an incomplete experiment. Gzip files retain
full evaluated stories and tool transcripts, not merely aggregate scores.
"""
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
RUN = ROOT / 'runs/shared-reviews-20260928'
OUT = HERE / 'evidence'
SEEDS = [31, 73, 127]
PAYLOADS = set()


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    PAYLOADS.add(path)


def pack(path, rows):
    with path.open('wb') as raw:
        with gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as stream:
            for row in rows:
                stream.write((json.dumps(row, ensure_ascii=False, separators=(',', ':')) + '\n').encode())
    PAYLOADS.add(path)


def expected_evaluations():
    names = ['dev-base', 'dev-playbook-60-s31']
    names += ['dev-sft-60-lr' + str(lr) for lr in [.00015, .00047, .0007]]
    names += ['test-base', 'test-explicit-rules', 'test-compact-rubric']
    for n in [15, 60, 480]:
        names += [f'test-raw-{n}']
        names += [f'test-{method}-{n}-s{s}' for method in ['playbook', 'sft'] for s in SEEDS]
    names += [f'test-{method}-480-s{s}' for method in ['combined', 'self', 'shuffled'] for s in SEEDS]
    return sorted(names)


def main():
    OUT.mkdir(exist_ok=True)
    sources = {}

    def read(path):
        sources[os.path.relpath(path, ROOT)] = digest(path)
        return json.loads(path.read_text())

    old = ROOT.parents[1] / 'exp_writing/runs/ten-writers-20260926-inkling'
    reviews = [row for p in sorted((old / 'collections').glob('none-round-*.json')) for row in read(p)]
    reviews.sort(key=lambda row: row['prompt']['id'])
    assert len(reviews) == 480
    pack(OUT / 'reviews.jsonl.gz', reviews)
    write_json(OUT / 'old-prompts.json', read(old / 'prompts.json'))

    evaluation_files = {p.stem: p for p in (RUN / 'evaluations').glob('*.json')}
    assert set(evaluation_files) == set(expected_evaluations()), 'Incomplete or unexpected evaluations'
    evaluated = []
    for name in expected_evaluations():
        rows = read(evaluation_files[name])
        assert len(rows) == (48 if name.startswith('dev-') else 288), name
        evaluated.extend(dict(evaluation=name, row=r) for r in rows)
    pack(OUT / 'evaluations.jsonl.gz', evaluated)

    retention_names = ['base'] + [f'{m}-480-s{s}' for m in ['sft', 'playbook'] for s in SEEDS]
    assert {p.stem for p in (RUN / 'retention').glob('*.json')} == set(retention_names)
    retention = []
    for name in sorted(retention_names):
        rows = read(RUN / 'retention' / (name + '.json'))
        assert len(rows) == 128
        retention.extend(dict(evaluation=name, row=r) for r in rows)
    pack(OUT / 'retention.jsonl.gz', retention)

    training = {}
    targets = []
    for p in sorted((RUN / 'training').glob('*/checkpoint.json')):
        name = p.parent.name
        training[name] = dict(checkpoint=read(p), masks=read(p.parent / 'masks.json'))
        rows_path = p.parent / 'rows.jsonl'
        sources[str(rows_path.relative_to(ROOT))] = digest(rows_path)
        rows = [json.loads(line) for line in rows_path.read_text().splitlines()]
        targets.extend(dict(training=name, row=r) for r in rows)
        metrics_path = p.parent / 'metrics.jsonl'
        sources[str(metrics_path.relative_to(ROOT))] = digest(metrics_path)
        training[name]['metrics'] = [json.loads(line) for line in metrics_path.read_text().splitlines()]
    assert len(training) == 18
    pack(OUT / 'training-targets.jsonl.gz', targets)
    write_json(OUT / 'training.json', training)
    interrupted = {}
    for folder in sorted((RUN / 'aborted-training').iterdir()):
        if folder.is_dir():
            interrupted[folder.name] = {
                p.name: read(p) for p in folder.glob('*.json')
                if p.name in ['started.json', 'model.json', 'recovery.json', 'interruption.json']}
            metric_path = folder / 'metrics.jsonl'
            if metric_path.exists():
                sources[str(metric_path.relative_to(ROOT))] = digest(metric_path)
                interrupted[folder.name]['metrics'] = [json.loads(line)
                    for line in metric_path.read_text().splitlines()]
    write_json(OUT / 'interrupted-training.json', interrupted)

    books = {p.stem: read(p) for p in sorted((RUN / 'playbooks').glob('*.json'))}
    write_json(OUT / 'playbooks.json', books)
    pack(OUT / 'compiler-inputs.jsonl.gz', [dict(name=p.stem, messages=read(p))
         for p in sorted((RUN / 'compiler_inputs').glob('*.json'))])
    shuffle = {p.stem: read(p) for p in sorted((RUN / 'controls').glob('shuffle-*.json'))}
    write_json(OUT / 'shuffle-maps.json', shuffle)
    for name in ['analysis.json', 'freeze.json', 'freeze-v1.json', 'amendment-1.json',
                 'prompts.json', 'archive_manifest.json', 'rescore-style.json', 'rescore-retention.json']:
        write_json(OUT / name, read(RUN / name))
    archives = json.loads((OUT / 'archive_manifest.json').read_text())['adapters']
    assert {r['name'] for r in archives} == set(training)
    for record in archives:
        path = RUN / 'checkpoint_archives' / record['archive']
        assert path.stat().st_size == record['bytes']
        assert digest(path) == record['sha256'], 'Adapter archive hash: ' + record['name']
    for name in ['development-power.json', 'local-check.json', 'mask-check.json',
                 'payload-provenance.json', 'editor-receipt-audit.json', 'training-length-audit.json', 'retention-plan.json',
                 'environment.json', 'pricing-20260928.json', 'design.json', 'compact-rubric-plan.json']:
        write_json(OUT / name, read(ROOT / name))
    compact_plan = json.loads((ROOT / 'compact-rubric-plan.json').read_text())
    for name, field in [('compact_rubric.py', 'script_sha256'), ('COMPACT_RUBRIC.md', 'protocol_sha256')]:
        source = ROOT / name
        assert digest(source) == compact_plan[field]
        sources[str(source.relative_to(ROOT))] = digest(source)
        target = OUT / 'exploratory-code' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        PAYLOADS.add(target)
    official = ROOT / 'vendor/instruction_following_eval'
    provenance = read(official / 'SOURCE.json')
    write_json(OUT / 'official-ifeval/SOURCE.json', provenance)
    for name, record in provenance['files'].items():
        source = official / name
        assert digest(source) == record['sha256']
        sources[str(source.relative_to(ROOT))] = digest(source)
        target = OUT / 'official-ifeval' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        PAYLOADS.add(target)

    costs_path = RUN / 'costs.jsonl'
    sources[str(costs_path.relative_to(ROOT))] = digest(costs_path)
    write_json(OUT / 'costs.json', [json.loads(line) for line in costs_path.read_text().splitlines()])
    progress_path = RUN / 'progress.jsonl'
    sources[str(progress_path.relative_to(ROOT))] = digest(progress_path)
    write_json(OUT / 'progress.json', [json.loads(line) for line in progress_path.read_text().splitlines()])

    # A manifest binds the retained raw receipts without embedding large token arrays.
    receipts = {}
    provider_metadata = []
    for pattern in ['provider/*.json', 'requests/*.json', 'compiler_inputs/*.json']:
        for p in sorted(RUN.glob(pattern)):
            receipts[str(p.relative_to(RUN))] = dict(sha256=digest(p), bytes=p.stat().st_size)
            if p.parent.name == 'provider':
                record = json.loads(p.read_text())
                provider_metadata.append(dict(request=p.stem,
                    receipt={k: v for k, v in record.items() if k not in ['tokens', 'logprobs']}))
    pack(OUT / 'provider-metadata.jsonl.gz', provider_metadata)
    write_json(OUT / 'receipt-manifest.json', receipts)

    frozen = read(RUN / 'freeze.json')
    for name, expected in frozen['code_sha'].items():
        p = ROOT / name
        assert digest(p) == expected, 'Frozen source changed: ' + name
        target = OUT / 'frozen-code' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p, target)
        PAYLOADS.add(target)
    original = read(RUN / 'freeze-v1.json')
    for name, expected in original['code_sha'].items():
        source = RUN / 'frozen-code-v1' / name
        assert digest(source) == expected, 'Original frozen source changed: ' + name
        target = OUT / 'frozen-code-v1' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        PAYLOADS.add(target)
    write_json(OUT / 'source-manifest.json', sources)
    write_json(OUT / 'package.json', dict(
        evaluation_episodes=len(evaluated), retention_responses=len(retention),
        trained_adapters=len(training), evaluation_policies=len(evaluation_files),
        files={str(p.relative_to(OUT)): digest(p) for p in sorted(PAYLOADS)},
        local_binary_archive_hashes_checked=len(archives),
        note='Full stories, tool transcripts, scores, training targets, and metadata; '
             'large provider token/logprob receipts and binary adapters remain in the local run archive.'))
    print(f'Packaged {len(evaluated)} story episodes, {len(retention)} retention responses, {len(training)} adapters.')


if __name__ == '__main__':
    main()
