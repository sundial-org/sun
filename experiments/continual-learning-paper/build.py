"""Verify evidence, compile the draft and notes, and create the submission PDF.

Needs Python with numpy and pypdf, plus pdflatex and the CVPR dependencies.
No network access or model calls. TEXINPUTS/TEXMFHOME may point to local packages.
"""
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
    subprocess.run([sys.executable, 'render_audit.py'], cwd=HERE, check=True)
    env = os.environ.copy()
    env['TEXINPUTS'] = str(HERE / 'vendor') + os.pathsep + env.get('TEXINPUTS', '')
    for name in ['paper', 'submission-notes']:
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
    assert len(draft.pages) == 3, 'The half-length draft must remain three pages.'
    assert len(notes.pages) == 1, 'Submission notes should fit one page.'
    assert all('??' not in p.extract_text() for p in draft.pages)
    shutil.copyfile(BUILD / 'paper.pdf', OUT / 'draft-paper.pdf')
    writer = PdfWriter()
    writer.append(BUILD / 'paper.pdf')
    writer.append(BUILD / 'submission-notes.pdf')
    writer.add_metadata({'/Title': 'Reviews in Context or in Weights? Draft-paper submission',
                         '/Subject': 'Audited pilots, model-paper outline and revision notes'})
    writer.write(OUT / 'submission.pdf')
    count = json.loads((HERE / 'evidence/word-count.json').read_text())
    report = {'draft_pages': len(draft.pages), 'submission_pages': 4,
              'body_word_count': count, 'latex_overfull_boxes': 0,
              'unresolved_references': 0,
              'paper_source_sha256': hashlib.sha256((HERE / 'paper.tex').read_bytes()).hexdigest(),
              'pdf_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in OUT.glob('*.pdf')},
              'visual_review': 'Render and inspect the final PDFs after every substantive change.'}
    (HERE / 'evidence/build-check.json').write_text(json.dumps(report, indent=2) + '\n')
    print(f'Built 3-page draft ({count["count"]} body words) and 4-page submission.')


if __name__ == '__main__':
    main()
