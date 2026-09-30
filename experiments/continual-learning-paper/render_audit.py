"""Render the already-reviewed claim records; never bless changed claim hashes."""
import hashlib
import json
from pathlib import Path
import re
from verify_evidence import parse_claims

HERE = Path(__file__).resolve().parent


def plain(text):
    text = re.sub(r'\\cite\{([^}]+)\}', lambda m: '[' + m[1] + ']', text)
    text = re.sub(r'Table~\\ref\{[^}]+\}', 'Table 1', text)
    text = re.sub(r'\\texttt\{([^}]+)\}', r'`\1`', text)
    text = text.replace('\\%', '%').replace('~', ' ')
    return text.replace('``', '"').replace("''", '"')


def render():
    text = (HERE / 'paper.tex').read_text()
    claims = parse_claims(text)
    ledger = json.loads((HERE / 'claim-checks.json').read_text())
    assert claims.keys() == ledger.keys()
    lines = ['# Claim-by-claim verification', '',
             'Checked 2026-09-28. Each substantive sentence is wrapped in a stable claim ID in '
             '[paper.tex](paper.tex). T01 also covers every generated table cell. '
             'The title is a research question; bibliography metadata and source locators are checked in '
             '[SOURCES.md](SOURCES.md).', '',
             '**What checked means:** measured claims were reconciled with saved pilot artifacts and '
             'recomputed where quantitative; literature claims were read in primary sources; design '
             'claims were checked against the proposal or explicitly identified as clarifications; '
             'inferences state their limits. A planned gate is not a passed gate. '
             'No human review, new provider run, or general capability guarantee is implied.', '',
             '**Reproduction:** `python verify_evidence.py` checks compact-data hashes, prompt counts, '
             'training manifests, score arithmetic, paired intervals, controls, selection gains, '
             'Lean header shortcuts, and claim hashes. `--check-archives` additionally checks local '
             'raw-file hashes. [verification.json](evidence/verification.json) records outcomes and limits. '
             'Stored writing rule labels remain the original automated tagger judgments; the human '
             'meaning of those judgments was not revalidated. Lean facts were rederived from saved '
             'receipts, without rerunning the compiler.', '',
             '**Coverage:** every assertion block below was manually reviewed; hash checks detect '
             'changed reviewed text, not truth automatically. Source abbreviations link through '
             '[the source register](SOURCES.md). References such as C28 identify other checked claims.', '']
    for cid, claim in claims.items():
        item = ledger[cid]
        assert item['text_sha256'] == hashlib.sha256(claim.encode()).hexdigest(), cid
        lines += [f'## {cid}: {item["status"]}', '', plain(claim), '',
                  '**Evidence:** ' + '; '.join(item['sources']) + '.', '',
                  '**Check and justification:** ' + item['justification'], '']
    (HERE / 'CLAIMS.md').write_text('\n'.join(lines))
    # Audit count includes prose and table caption, excludes title/references/notes;
    # hyphenated words count once and displayed math is counted as one token.
    prose = '\n'.join(plain(c) for c in claims.values())
    prose = re.sub(r'\$[^$]*\$', ' MATH ', prose)
    prose = re.sub(r'\[[a-z,]+\]', '', prose)
    count = len(re.findall(r"\b\w+(?:[-']\w+)*\b", prose))
    table = (HERE / 'evidence/curve-table.tex').read_text()
    table = re.sub(r'\\(?:begin|end)\{[^}]+\}(?:\{[^}]+\})?', '', table)
    table = re.sub(r'\\[A-Za-z]+', '', table)
    count += len(re.findall(r'\b\w+\b', table))
    (HERE / 'evidence/word-count.json').write_text(json.dumps({
        'count': count, 'target': [2000, 2500],
        'method': 'Claim prose and caption plus table values; hyphenated words count once, math expressions once; excludes title, headings, bibliography and notes.',
        'within_target': 2000 <= count <= 2500}, indent=2) + '\n')
    assert 2000 <= count <= 2500, count
    print(f'Rendered {len(claims)} checked claim blocks; {count} body words by documented counting rule.')


if __name__ == '__main__':
    render()
