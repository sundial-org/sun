#!/usr/bin/env python3
"""Real PPTX/XLSX/CSV changes in an isolated repository, served by Sun review.

Install Sun's documents extra, then run: python examples/demo_documents.py
The temporary repository is kept so both file versions can be inspected.
"""
import argparse
import contextlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import webbrowser

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sun import cli, review, review_web


def write_examples(root, revised=False):
    from openpyxl import Workbook
    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.util import Inches, Pt

    root = Path(root)
    book = Workbook()
    sheet = book.active
    sheet.title = 'Launch budget'
    for row in [('Team', 'Budget', 'Actual'), ('Design', 12000, 11500),
                ('Engineering', 30000, 28000), ('Launch', 8000, 7200),
                ('Total', '=SUM(B2:B4)', '=SUM(C2:C4)')]:
        sheet.append(row)
    if revised:
        sheet['B3'] = 36000
        sheet['C4'] = 9100
        sheet['B5'] = '=SUM(B2:B4)*1.1'
        book.create_sheet('Assumptions').append(['Contingency', '10%'])
    book.save(root / 'budget.xlsx')
    (root / 'metrics.csv').write_text('Metric,Value\nActive teams,' + ('42' if revised else '28') +
                                    '\nRetention,94%\n' + ('Waitlist,120\n' if revised else ''), encoding='utf-8')

    deck = Presentation()
    deck.slide_width, deck.slide_height = Inches(12), Inches(6.75)
    def slide(title, subtitle, number):
        s = deck.slides.add_slide(deck.slide_layouts[6])
        s.background.fill.solid()
        s.background.fill.fore_color.rgb = RGBColor.from_string('F5F3EE')
        title_box = s.shapes.add_textbox(Inches(.8), Inches(.65), Inches(10.4), Inches(1))
        title_box.text = title
        title_box.name = 'Headline'
        title_box.text_frame.paragraphs[0].runs[0].font.size = Pt(34)
        title_box.text_frame.paragraphs[0].runs[0].font.bold = True
        body = s.shapes.add_textbox(Inches(.85), Inches(2), Inches(9.8), Inches(1.1))
        body.text = subtitle
        body.name = 'Summary'
        body.text_frame.paragraphs[0].runs[0].font.size = Pt(23)
        metric = s.shapes.add_textbox(Inches(.85), Inches(3.4), Inches(5), Inches(1.5))
        metric.text = number
        metric.name = 'Metric'
        metric.text_frame.paragraphs[0].runs[0].font.size = Pt(65)
        metric.text_frame.paragraphs[0].runs[0].font.color.rgb = RGBColor.from_string('397463')
        footer = s.shapes.add_textbox(Inches(.85), Inches(5.7), Inches(10), Inches(.5))
        footer.text = 'SUNDIAL  /  PRODUCT UPDATE'
        footer.text_frame.paragraphs[0].runs[0].font.size = Pt(12)
        return s
    overview = slide('A clearer view of launch', 'Pilot teams are building together.', '28 teams')
    slide('What ships next', 'Shared reviews. Clear ownership. Less context switching.', '3 priorities')
    slide('Retired experiment', 'An old concept we are removing from the plan.', 'Archive')
    overview.notes_slide.notes_text_frame.text = 'Share the pilot results.'
    if revised:
        overview.shapes[1].text = 'Pilot adoption is growing faster than planned.'
        overview.shapes[1].text_frame.paragraphs[0].runs[0].font.size = Pt(23)
        overview.shapes[2].text = '42 teams'
        overview.shapes[2].text_frame.paragraphs[0].runs[0].font.size = Pt(65)
        overview.shapes[2].text_frame.paragraphs[0].runs[0].font.color.rgb = RGBColor.from_string('397463')
        overview.shapes[2].left = Inches(5.5)
        overview.notes_slide.notes_text_frame.text = 'Share the pilot results and updated launch budget.'
        slide('Ready for the next cohort', 'Open the waitlist and invite new teams.', '120 waiting')
        ids = deck.slides._sldIdLst
        removed = ids[2]
        deck.part.drop_rel(removed.rId)
        ids.remove(removed)
        ids.insert(0, ids[1])  # preserve slide IDs while moving the priorities slide
    deck.save(root / 'launch.pptx')
    (root / 'keynote.key').write_bytes(b'Keynote demo placeholder: export real decks to PPTX.')
    (root / 'notes.txt').write_text('Launch review\n' + ('Budget updated.\n' if revised else 'Budget pending.\n'))


def prepare_demo():
    root = Path(tempfile.mkdtemp(prefix='sun-document-demo-'))
    os.chdir(root)
    os.environ['SUN_PROJECTS'] = str(root / '.sessions-claude')
    os.environ['SUN_CODEX_SESSIONS'] = str(root / '.sessions-codex')
    def git(*args):
        return subprocess.check_output(['git', *args], text=True).strip()
    git('init', '-q')
    git('config', 'user.name', 'Demo author')
    git('config', 'user.email', 'demo@example.test')
    write_examples(root)
    git('add', '.')
    git('commit', '-qm', 'Before: launch plan')
    with contextlib.redirect_stdout(io.StringIO()):
        cli.main(['init', '--codex', '--no-share-sessions', '--no-instructions'])
        git('add', '.')
        git('commit', '-qm', 'Initialize Sun')
        base = git('rev-parse', 'HEAD')
        write_examples(root, revised=True)
        (root / 'keynote.key').write_bytes(b'Revised Keynote placeholder; export both versions to PPTX.')
        cli.main(['sync'])
    return root, review.review_data(base)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    root, data = prepare_demo()
    server, url = review_web.create_server(data)
    print(f'Demo repository: {root}\n{url}', flush=True)
    if not args.no_browser: webbrowser.open(url)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()
