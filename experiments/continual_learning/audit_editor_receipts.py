"""Replay archived editor calls offline; no provider client is constructed."""
import hashlib
import inspect
import json
from pathlib import Path
import tempfile

from run import ROOT, ARCHIVE, archive_rows, good
from data import sha
from run_experiment import Experiment, write_json


def main():
    checked, mismatches, replay_mismatches = [], [], []
    rows = good(archive_rows())
    with tempfile.TemporaryDirectory(prefix='rubric-editor-audit-') as directory:
        class Replay:
            path = Path(directory)

            def sample(self, messages, policy, request_id, seed, max_tokens, temperature):
                receipt = json.loads((ARCHIVE / 'provider' / (request_id + '.json')).read_text())
                assert policy == 'editor' and receipt['model'] == 'thinkingmachines/Inkling'
                if receipt['prompt_sha'] != sha(messages):
                    mismatches.append(dict(request_id=request_id, saved=receipt['prompt_sha'], reconstructed=sha(messages)))
                assert receipt['seed'] == seed == 911
                assert receipt['temperature'] == temperature == 0 and max_tokens == 6000
                checked.append(dict(request_id=request_id, prompt_sha=receipt['prompt_sha']))
                return receipt

        replay = Replay()
        for row in rows:
            result = Experiment.edit(replay, row)
            archived = json.loads((ARCHIVE / 'edits' / (row['id'] + '-A.json')).read_text())
            if result != archived or not result['valid'] or result['edited'] != row['edited']:
                replay_mismatches.append(row['id'])
    assert len(rows) == 460
    report = dict(status='pass' if not mismatches and not replay_mismatches else 'discrepancies', pairs=len(rows), editor_prompt_receipts=len(checked),
                  check='Attempted to reconstruct editor messages and replay sentence replacements with the current pinned segmentation pipeline; exact mismatches are retained below.',
                  scope='Matching hashes support the archived editor configuration. This is not a full reproduction of archive construction, semantic-preservation validation, or a check of rubric compliance. The experiment uses the original saved before/after pairs unchanged.',
                  editor_function_sha256=hashlib.sha256(inspect.getsource(Experiment.edit).encode()).hexdigest(),
                  archive_sha256=sha(archive_rows()), receipts=checked,
                  prompt_mismatches=mismatches, replay_mismatches=replay_mismatches,
                  exact_prompt_matches=len(checked)-len(mismatches),
                  exact_pair_replays=len(rows)-len(replay_mismatches))
    write_json(ROOT / 'editor-receipt-audit.json', report)
    print(json.dumps({k: v for k, v in report.items() if k not in ['receipts','prompt_mismatches','replay_mismatches']}, indent=2))
    print('Prompt mismatches:',len(mismatches),'Replay mismatches:',len(replay_mismatches))


if __name__ == '__main__':
    main()
