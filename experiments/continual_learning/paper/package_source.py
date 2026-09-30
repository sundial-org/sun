"""Bundle editable typesetting sources after a verified final build."""
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

HERE = Path(__file__).resolve().parent


def main():
    build = json.loads((HERE / 'evidence/build-check.json').read_text())
    assert build['paper_source_sha256'] == hashlib.sha256((HERE / 'paper.tex').read_bytes()).hexdigest()
    files = ['paper.tex', 'submission-notes.tex', 'CLAIMS.md', 'claim-checks.json',
             'SOURCES.md', 'evidence/workflow.pdf', 'evidence/budget-comparison.pdf',
             'evidence/endpoint-table.tex', 'evidence/retention-table.tex',
             'evidence/build-check.json']
    destination = HERE / 'output/rubric-paper-source.zip'
    with ZipFile(destination, 'w', compression=ZIP_DEFLATED) as archive:
        for name in files:
            archive.write(HERE / name, name)
        archive.write(HERE / 'vendor/cvpr.sty', 'cvpr.sty')
        archive.write(HERE / 'vendor/README.md', 'TEMPLATE-PROVENANCE.md')
        archive.writestr('notes-start.tex', '\\setcounter{page}{' + str(build['draft_pages'] + 1) + '}\n')
        archive.writestr('README.md', '''# Editable paper sources

Compile `paper.tex` twice with pdfLaTeX. Compile `submission-notes.tex` separately
to produce the appended model-paper outline and revision notes. The original
CVPR style is included; its dependencies must be available in your TeX system.
No upload to Overleaf or submission service has been performed.

The paper uses normal Introduction, Related work, Method, Experiments, Results,
and Discussion sections. Figures are vector PDFs. Claim IDs are invisible in
the printed paper and connect the source to `CLAIMS.md` and `claim-checks.json`.
Editing a claim or numerical artifact invalidates its reviewed hash.

This is a compact typesetting bundle. Full responses, training records, offline
verification code and evidence live in the repository's
`experiments/continual_learning/paper/` directory. Large binary adapters remain
in the local experiment run archive; they are not included here.
''')
    print(destination)


if __name__ == '__main__':
    main()
