"""Offline evidence checks. Requires numpy; never calls a model/provider.

Recomputes statistics from compact per-sample records, not displayed numbers.
The compact records preserve stored private rule judgments, not independent
human assessments or a fresh NLP-tagger run. See CLAIMS.md for that boundary.
"""
import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
import numpy as np

HERE = Path(__file__).resolve().parent
EVIDENCE = HERE / 'evidence'


def read(name):
    p = EVIDENCE / name
    data = gzip.decompress(p.read_bytes()) if p.suffix == '.gz' else p.read_bytes()
    return json.loads(data)


def interval(values):
    a = np.asarray(values, dtype=float)
    rng = np.random.default_rng(1701)
    samples = a[rng.integers(0, len(a), size=(10000, len(a)))].mean(axis=1)
    return {'mean': float(a.mean()), 'ci95': np.quantile(samples, [.025, .975]).tolist(), 'n': len(a)}


def close(actual, expected):
    if isinstance(actual, dict):
        for k, v in actual.items():
            close(v, expected[k])
    else:
        assert np.allclose(actual, expected, rtol=0, atol=1e-12), (actual, expected)


def means(rows, guide=2, flipped=False):
    groups = defaultdict(list)
    for row in rows:
        rules = row[guide][5:8] if flipped else row[guide]
        flags = [v for v in rules if v is not None]
        groups[row[0]].append(float(row[1]) * sum(flags) / max(1, len(flags)))
    assert len(groups) == 96
    return {k: statistics.mean(v) for k, v in groups.items()}


def difference(left, right):
    assert left.keys() == right.keys()
    return interval([left[k] - right[k] for k in sorted(left)])


def claim_blocks(text):
    for m in re.finditer(r'\\claim\{([A-Z]\d+)\}\{', text):
        level, end = 1, m.end()
        while level:
            assert end < len(text), 'Unclosed claim'
            ch = text[end]
            if end == 0 or text[end - 1] != '\\':
                level += (ch == '{') - (ch == '}')
            end += 1
        yield m[1], text[m.end():end - 1], m.start(), end


def parse_claims(text):
    result = {}
    for cid, claim, _, _ in claim_blocks(text):
        assert cid not in result, f'Duplicate {cid}'
        result[cid] = claim
    return result


def check_prose_coverage(paper):
    body = paper.split('\\begin{abstract}', 1)[1].split('{\\small\n\\begin{thebibliography}', 1)[0]
    for _, _, start, end in reversed(list(claim_blocks(body))):
        body = body[:start] + body[end:]
    # The sole table is generated from verified data and explicitly covered by T01.
    body = re.sub(r'\\begin\{table\}.*?\\end\{table\}', '', body, flags=re.S)
    body = re.sub(r'\\(?:subsection|section)\{[^{}]*\}', '', body)
    body = body.replace('\\end{abstract}', '')
    assert not body.strip(), 'Untagged paper prose: ' + body.strip()[:150]


def verify(check_archives=False):
    source_manifest = read('source-manifest.json')
    for name, record in source_manifest['committed_snapshots'].items():
        assert hashlib.sha256((EVIDENCE / name).read_bytes()).hexdigest() == record['sha256'], name
    for name, digest in source_manifest['compact_sha256'].items():
        assert hashlib.sha256((EVIDENCE / name).read_bytes()).hexdigest() == digest, name
    writing, recorded = read('writing-records.json.gz'), read('writing-analysis.json')
    training = {r['name']: r for r in read('writing-training.json')}
    for r in training.values():
        assert r['rank'] == 16 and r['learning_rate'] == .0004
        assert r['batch'] == (4 if r['rows'] <= 60 else 16)
        assert r['epochs'] >= 3 and r['steps'] >= 30
    prompts = read('writing-prompts.json')
    train = [p for p in prompts if p['split'] == 'train']
    heldout = [p for p in prompts if p['split'] == 'heldout']
    assert len(train) == 480 and len(heldout) == 96
    train_genres = {p['genre'] for p in train}
    assert sum(p['genre'] not in train_genres for p in heldout) == 48
    for rows in writing.values():
        assert Counter(r[0] for r in rows) == {p['id']: 4 for p in heldout}
    close(interval(list(means(writing['base']).values())), recorded['base'])
    curve = []
    for point in recorded['curve']:
        x = point['x']
        assert training[f'weights-{x}-s0']['rows'] == point['rows']
        wr = sum([writing[f'weights-{x}-s{s}'] for s in range(point['seeds'])], [])
        cr = writing[f'context-{x}']
        for rows in [wr, cr]:
            assert all(len(r[2]) == len(r[3]) == 8 for r in rows)
        wm, cm = means(wr), means(cr)
        # Match recorded aggregate ordering for each original mean interval.
        for name, m in [('weights', wm), ('context', cm)]:
            close(interval(list(m.values())), point[name])
        gap = difference(wm, cm)
        close(gap, point['difference'])
        for name, rows in [('weight', wr), ('context', cr)]:
            close(statistics.mean(r[1] for r in rows), point[name + '_U'])
            close(statistics.mean(sum(v for v in r[2] if v is not None) /
                                  sum(v is not None for v in r[2]) for r in rows if r[1]),
                  point[name + '_conditional_S'])
        curve.append({'budget': x, 'rows': point['rows'], 'seeds': point['seeds'],
                      'context': statistics.mean(cm.values()),
                      'weights': statistics.mean(wm.values()), 'gap': gap})

    arms = {arm: sum([writing[f'{arm}-480-s{s}'] for s in range(3)], [])
            for arm in ['lora-A', 'lora-B', 'self']}
    assert all(training[f'{arm}-480-s{s}']['rows'] == 460 for arm in arms for s in range(3))
    controls = {
        'A_specificity': difference(means(arms['lora-A'], flipped=True), means(arms['lora-B'], flipped=True)),
        'B_specificity': difference(means(arms['lora-B'], 3, True), means(arms['lora-A'], 3, True)),
        'edited_vs_self': difference(means(arms['lora-A']), means(arms['self'])),
        'shared_weights_vs_context': difference(means(arms['lora-A']), means(writing['context-shared-480']))}
    close(controls, recorded['comparisons'])
    close(interval(list(means(arms['lora-A']).values())), recorded['shared_archive']['weights'])
    close(interval(list(means(writing['context-shared-480']).values())), recorded['shared_archive']['context'])

    pools = defaultdict(dict)
    for row in sorted(read('selection-records.json.gz'), key=lambda r: r['id']):
        if row['U']:
            pools[row['prompt']].setdefault(row['story_hash'], row)

    def selected(rows, key):
        values = [r[key] for r in rows]
        m = len(rows)
        total = math.comb(m, 4)
        result = 0
        for r in rows:
            lo = sum(v < r[key] for v in values)
            hi = sum(v <= r[key] for v in values)
            p = (math.comb(hi, 4) - (math.comb(lo, 4) if lo >= 4 else 0)) / total / (hi - lo)
            result += p * r['S']
        return result

    gains, oracle = [], []
    for pool in pools.values():
        rows = list(pool.values())
        if len(rows) >= 4:
            uniform = statistics.mean(r['S'] for r in rows)
            gains.append(selected(rows, 'kept') - uniform)
            oracle.append(selected(rows, 'S') - uniform)
    selection = {'gain': interval(gains), 'oracle_gain': interval(oracle)}
    close(selection, recorded['best_of_n'])

    lean = read('lean-records.json.gz')
    traces = lean['traces']
    patterns = Counter('+'.join(sorted(x.split(':')[0] for x in r['truth'])) for r in traces.values())
    assert patterns == {'E4': 113, 'E5': 6, 'E5+E6': 1}
    assert len({r['lemma'] for r in traces.values()}) == 40
    assert len({r['family'] for r in traces.values()}) == 20

    def predictions(header):
        if header is None:
            return set()
        return (set(header['events']) | {'proved:' + x for x in header['lemmas_proved']} |
                {'partial:' + x for x in header['lemmas_partial'] if x not in header['lemmas_proved']})

    def score(pred, truth):
        correct = len(pred & truth)
        return correct ** 2 / (len(pred) * len(truth)) if pred else 0.

    report_count = 0
    for name, rows in lean['evaluations'].items():
        assert {r['sid'] for r in rows} == traces.keys()
        assert all(len(r['reports']) == 5 for r in rows)
        report_count += sum(len(r['reports']) + 1 for r in rows)
        if name.endswith('weights'):
            scores = []
            for r in rows:
                t = traces[r['sid']]
                for header in r['reports']:
                    pred = predictions(header)
                    assert pred == {t['exit_event']}
                    scores.append(score(pred, set(t['truth'])))
            close(statistics.mean(scores), 595 / 600 + 5 * .5 / 600)
    assert report_count == 6480
    e6 = next(sid for sid, t in traces.items() if len(t['truth']) == 2)
    for name in ['k0-base', 'k4-context']:
        row = next(r for r in lean['evaluations'][name] if r['sid'] == e6)
        assert all(predictions(h) == set(traces[e6]['truth']) for h in row['reports'])

    paper = (HERE / 'paper.tex').read_text()
    check_prose_coverage(paper)
    claims = parse_claims(paper)
    ledger = json.loads((HERE / 'claim-checks.json').read_text())
    assert claims.keys() == ledger.keys(), (claims.keys() - ledger.keys(), ledger.keys() - claims.keys())
    for cid, record in ledger.items():
        assert record['justification'] and record['sources'] and record['status'] in {
            'measured', 'literature', 'design', 'inference', 'scope'}
        assert record['text_sha256'] == hashlib.sha256(claims[cid].encode()).hexdigest(), f'Stale claim review: {cid}'
    assert '\u2014' not in paper

    if check_archives:
        root = HERE.parents[1]
        for path, digest in read('source-manifest.json')['files'].items():
            assert hashlib.sha256((root / path).read_bytes()).hexdigest() == digest, path

    # Numeric rows are generated only after underlying checks pass.
    lines = [f"{p['budget']} & {p['rows']} & {100*p['context']:.1f} & {100*p['weights']:.1f} & {100*p['gap']['mean']:+.1f} \\\\" for p in curve]
    (EVIDENCE / 'curve-table.tex').write_text(
        '\\begin{tabular}{rrrrr}\\toprule\n'
        'Budget & SFT rows & Context & Weights & Gap ' + '\\\\' + '\\midrule\n' +
        '\n'.join(lines) + '\n\\bottomrule\\end{tabular}\n')
    result = {'status': 'pass', 'checked_claim_blocks': len(claims),
              'writing_samples': sum(map(len, writing.values())), 'lean_reports': report_count,
              'writing_curve': curve, 'controls': controls, 'selection': selection,
              'lean_truth_patterns': dict(patterns), 'archive_hashes_checked': check_archives,
              'limits': ['Private writing rule labels are stored tagger judgments, not new human judgments.',
                         'Lean truth was rederived from saved receipts during collection, not new compiler runs.',
                         'Intervals condition on the collected pools and average available training seeds.',
                         'Claim semantics were manually reviewed; automated coverage and hashes detect missing or changed blocks.']}
    (EVIDENCE / 'verification.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: result[k] for k in ['status', 'checked_claim_blocks', 'writing_samples', 'lean_reports', 'archive_hashes_checked']}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--check-archives', action='store_true')
    verify(parser.parse_args().check_archives)
