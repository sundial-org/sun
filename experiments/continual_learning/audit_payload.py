"""Establish that provider payloads are synthetic experimental data."""
import json
import re
from run import ROOT, ARCHIVE, archive_rows, export_corrected, make_new_prompts
from data import make_prompts, canonical, sha
from run_experiment import apply_actions, tool_actions, parse_object, write_json

rows = archive_rows()
generated = {p['id']: p for p in make_prompts()}
writer_receipts = editor_receipts = 0
for row in rows:
    assert canonical(row['prompt']) == canonical(generated[row['prompt']['id']])
    story, checked, submitted = '', None, False
    turn = 0
    for message in row['messages']:
        if message['role'] != 'assistant':
            continue
        receipt = json.loads((ARCHIVE/'provider'/f'{row["id"]}-t{turn}.json').read_text())
        assert receipt['model'] == 'Qwen/Qwen3-8B'
        assert receipt['text'] == message['content']
        writer_receipts += 1
        turn += 1
        try:
            story, checked, submitted, outputs = apply_actions(tool_actions(parse_object(message['content'])), row['prompt'], story, checked)
        except (ValueError, KeyError, TypeError, AttributeError):
            pass
    assert story == row['story']
    if row['editor_valid']:
        edit = json.loads((ARCHIVE/'edits'/f'{row["id"]}-A.json').read_text())
        assert edit['valid'] and edit['edited'] == row['edited']
        for review_pass in range(2):
            receipt = json.loads((ARCHIVE/'provider'/f'{row["id"]}-editor-A-p{review_pass}.json').read_text())
            assert receipt['model'] == 'thinkingmachines/Inkling'
            editor_receipts += 1

# Exported training rows omit filesystem provenance, commit history, editor system
# prompts, private score annotations, credentials, and unrelated repository data.
exports = export_corrected(rows)
payload = canonical([r['messages'] for r in exports]) + canonical(make_new_prompts())
assert not re.search(r'(?:tml-[A-Za-z0-9]{12,}|sk-[A-Za-z0-9]{16,}|-----BEGIN .*PRIVATE KEY-----)', payload)
audit = dict(status='pass', synthetic_assignments=len(rows), writer_receipts_verified=writer_receipts,
             editor_receipts_verified=editor_receipts, valid_pairs=len(exports),
             assignment_source='Deterministic, local synthetic fiction generator; no user documents',
             story_source='Qwen/Qwen3-8B outputs previously generated through Tinker',
             review_source='thinkingmachines/Inkling outputs previously generated through Tinker',
             destination='https://tinker.thinkingmachines.dev/services/tinker-prod',
             purpose='Same-provider continuation of the user-requested training/evaluation experiment',
             payload_fields=['synthetic assignment', 'synthetic story before/after', 'public tool transcript', 'inferred playbook'],
             excluded=['credentials', 'filesystem provenance', 'repository source', 'unrelated user documents', 'private scoring rules'],
             training_export_sha=sha(exports), archive_sha=sha(rows))
write_json(ROOT/'payload-provenance.json',audit)
print(canonical(audit))
