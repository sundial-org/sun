"""One frozen exploratory privileged reference, added after verbatim-rule results.

Run only after the main, declared controls, and retention process have exited.
Shares the global cost ledger and unchanged writer/evaluation machinery.
"""
import hashlib
import json
from pathlib import Path

from run import ROOT, RUN, Study

PROMPT = '''Apply this writing rubric:
1. Write narration in present tense. At least 90% of finite verbs outside double-quoted dialogue must be present tense; avoid past-tense and modal verbs there.
2. Begin with a sentence of at most 12 whitespace-separated words.
3. Use say as the verb in dialogue tags, normally says.
4. Lowercase words inside sentences, including names, days, and months. Capital letters are allowed at sentence starts and at the start of double-quoted speech. Keep I uppercase.
5. Omit the standalone word suddenly.
6. Omit the standalone word very.
7. Use no semicolons.
8. Use no em dash characters.'''


def main():
    plan = json.loads((ROOT / 'compact-rubric-plan.json').read_text())
    assert hashlib.sha256(PROMPT.encode()).hexdigest() == plan['prompt_sha256']
    assert hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == plan['script_sha256']
    freeze = json.loads((RUN / 'freeze.json').read_text())
    for name, expected in freeze['code_sha'].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected
    study = Study()
    study.evaluate('base', 'test-compact-rubric', pool={'playbook': PROMPT})
    study.log('compact_rubric_complete', estimated_usd=study.actual, reserved_usd=study.reserved)


if __name__ == '__main__':
    main()
