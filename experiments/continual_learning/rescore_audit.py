"""Re-run official retention checks and a deterministic style consistency sample.

This performs no paid calls. It tests implementation consistency, not human
judgment of the benchmark or prose quality.
"""
import argparse
import dataclasses
import hashlib
import json
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parent
RUN = ROOT / 'runs/shared-reviews-20260928'
sys.path.insert(0, str(ROOT / 'vendor'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(phase):
    report = dict(phase=phase, script_sha256=sha(Path(__file__)), sources={}, checked=0, mismatches=[])
    if phase == 'retention':
        import nltk
        import langdetect
        nltk.data.path.insert(0, str(ROOT / 'vendor/nltk_data'))
        langdetect.DetectorFactory.seed = 0
        from instruction_following_eval.evaluation_lib import InputExample, test_instruction_following_strict
        vendor = ROOT / 'vendor/instruction_following_eval'
        provenance = json.loads((vendor / 'SOURCE.json').read_text())
        for name, record in provenance['files'].items():
            assert sha(vendor / name) == record['sha256'], name
        report['official_commit'] = provenance['commit']
        files = sorted((RUN / 'retention').glob('*.json'))
        assert len(files) == 7, 'Wait for every retention policy to finish'
        for path in files:
            report['sources'][str(path.relative_to(RUN))] = sha(path)
            rows = json.loads(path.read_text())
            assert len(rows) == 128
            for row in rows:
                random.seed(0)
                example = InputExample(**{k: row[k] for k in ['key', 'instruction_id_list', 'prompt', 'kwargs']})
                actual = dataclasses.asdict(test_instruction_following_strict(example, {row['prompt']: row['response']}))
                if actual != row['strict']:
                    report['mismatches'].append(dict(policy=path.stem, key=row['key']))
                report['checked'] += 1
    else:
        import style
        files = sorted((RUN / 'evaluations').glob('*.json'))
        assert len(files) == 38, 'Wait for main, declared controls, and compact-rubric follow-up'
        report['selection'] = 'Four episodes per policy: first invalid by SHA256 if available, then smallest remaining hashes; seed string style-audit-260928-.'
        report['selected_ids'] = {}
        rank = lambda row: hashlib.sha256(('style-audit-260928-' + row['id']).encode()).hexdigest()
        for path in files:
            report['sources'][str(path.relative_to(RUN))] = sha(path)
            rows = sorted(json.loads(path.read_text()), key=rank)
            invalid = [r for r in rows if not r['U']]
            selected = invalid[:1]
            selected += [r for r in rows if r not in selected][:4 - len(selected)]
            report['selected_ids'][path.stem] = [r['id'] for r in selected]
            for row in selected:
                actual = {g: style.score(row['story'], g) for g in ['A', 'B']}
                if actual != row['scores']:
                    report['mismatches'].append(dict(policy=path.stem, id=row['id']))
                report['checked'] += 1
            print(json.dumps(dict(policy=path.stem, checked=report['checked'])), flush=True)
    report['status'] = 'passed' if not report['mismatches'] else 'failed'
    (RUN / f'rescore-{phase}.json').write_text(json.dumps(report, indent=2) + '\n')
    assert not report['mismatches'], report['mismatches']
    print(json.dumps(dict(phase=phase, checked=report['checked'], status=report['status'])), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=['style', 'retention'])
    main(parser.parse_args().phase)
