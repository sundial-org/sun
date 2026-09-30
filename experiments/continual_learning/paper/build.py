"""Verify evidence and claims, compile the half-length paper, and append notes."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

from pypdf import PdfReader, PdfWriter

HERE = Path(__file__).resolve().parent
BUILD = HERE / 'build'
OUT = HERE / 'output/pdf'


def main():
    BUILD.mkdir(exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, 'verify_evidence.py'], cwd=HERE, check=True)
    subprocess.run([sys.executable, 'claims.py'], cwd=HERE, check=True)
    env = os.environ.copy()
    env['TEXINPUTS'] = str(HERE / 'vendor') + os.pathsep + env.get('TEXINPUTS', '')
    for name in ['paper', 'submission-notes']:
        if name == 'submission-notes':
            pages = len(PdfReader(BUILD / 'paper.pdf').pages)
            (BUILD / 'notes-start.tex').write_text('\\setcounter{page}{' + str(pages + 1) + '}\n')
            env['TEXINPUTS'] = str(BUILD) + os.pathsep + env['TEXINPUTS']
        for _ in range(2):
            result = subprocess.run(['pdflatex', '-interaction=nonstopmode', '-halt-on-error',
                                     '-output-directory=' + str(BUILD), name + '.tex'],
                                    cwd=HERE, env=env, text=True, capture_output=True)
            if result.returncode:
                print(result.stdout[-5000:])
                result.check_returncode()
        log = (BUILD / (name + '.log')).read_text()
        assert not re.search(r'Overfull|undefined citations|undefined references', log), name
    draft = PdfReader(BUILD / 'paper.pdf')
    notes = PdfReader(BUILD / 'submission-notes.pdf')
    assert 3 <= len(draft.pages) <= 4, 'Keep the half-word-count draft within four illustrated pages.'
    assert len(notes.pages) == 1, 'Submission notes should fit one page.'
    assert all('??' not in p.extract_text() for p in draft.pages)
    shutil.copyfile(BUILD / 'paper.pdf', OUT / 'draft-paper.pdf')
    writer = PdfWriter()
    writer.append(BUILD / 'paper.pdf')
    writer.append(BUILD / 'submission-notes.pdf')
    writer.add_metadata({'/Title': 'Learning a Writing Rubric from Edits: Context or Weights?',
                         '/Subject': 'Shared-review experiments, model-paper outline, and revision notes'})
    writer.write(OUT / 'submission.pdf')
    count = json.loads((HERE / 'evidence/word-count.json').read_text())
    report = dict(draft_pages=len(draft.pages), submission_pages=len(draft.pages)+1, body_word_count=count,
                  latex_overfull_boxes=0, unresolved_references=0,
                  paper_source_sha256=hashlib.sha256((HERE / 'paper.tex').read_bytes()).hexdigest(),
                  pdf_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in OUT.glob('*.pdf')},
                  visual_review='Render and inspect final PDFs after every substantive change.')
    (HERE / 'evidence/build-check.json').write_text(json.dumps(report, indent=2) + '\n')
    print(f'Built {len(draft.pages)}-page draft ({count["count"]} body words) and {len(draft.pages)+1}-page submission.')


if __name__ == '__main__':
    main()
