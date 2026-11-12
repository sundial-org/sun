"""Document comparisons and their immutable, bounded HTTP transport."""
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

from sun import document_diff as docs
from test_sun import run
import test_review_web as web_fixtures

HAS_DOCUMENTS = all(importlib.util.find_spec(m) for m in ('openpyxl', 'pptx'))


class TableDiffTest(unittest.TestCase):
    def test_csv_quotes_newlines_unicode_and_tsv(self):
        old = '\ufeffname,value\n"a,b","hello\nworld"\n雪,1\n'.encode()
        new = 'name,value\n"a,b","hello\nworld"\n雪,2\nnew,3\n'.encode()
        result = docs.compare('data.CSV', old, new)
        cells = result['sheets'][0]['cells']
        self.assertEqual([c['cell'] for c in cells], ['B3', 'A4', 'B4'])
        self.assertEqual(cells[0]['before']['value']['text'], '1')
        self.assertIsNone(cells[1]['before'])
        self.assertEqual(docs.compare('a.tsv', b'a\tb\n', b'a\tc\n')['sheets'][0]['cells'][0]['cell'], 'B1')

    def test_added_deleted_empty_sheets_and_wide_addresses(self):
        self.assertEqual(docs.compare('a.csv', None, b'')['sheets'][0]['status'], 'added')
        removed = docs.compare('a.csv', b'x', None)['sheets'][0]
        self.assertEqual(removed['status'], 'removed')
        self.assertIsNone(removed['cells'][0]['after'])
        self.assertEqual(docs.address(7, 703), 'AAA7')
        self.assertEqual(docs.compare('a.csv', b'x', b'x')['sheets'], [])

    def test_limits_and_bad_encoding_are_explicit_fallbacks(self):
        for raw in [b'\xff', b'x' * (docs.MAX_BYTES + 1), b'x\n' * (docs.MAX_CELLS + 1)]:
            self.assertEqual(docs.compare('a.csv', None, raw)['kind'], 'unavailable')
        self.assertIn('Keynote', docs.compare('slides.key', None, b'anything')['notice'])

    def test_no_dependency_fallback(self):
        with mock.patch.object(docs, 'sheets', side_effect=ImportError):
            self.assertIn('sun[documents]', docs.compare('a.xlsx', None, b'')['notice'])

    def test_zip_entity_and_expansion_limits(self):
        def archive(name, content):
            out = io.BytesIO()
            with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z: z.writestr(name, content)
            return out.getvalue()
        for xml in [b'<!DOCTYPE x><x/>', '<!DOCTYPE x><x/>'.encode('utf-16')]:
            with self.assertRaisesRegex(ValueError, 'entity'):
                docs.validate_archive(archive('part.xml', xml))
        with mock.patch.object(zipfile.ZipFile, 'infolist', return_value=[mock.Mock(file_size=65 * 1024 * 1024)]):
            with self.assertRaisesRegex(ValueError, 'expanded'):
                docs.validate_archive(archive('part.xml', b'<x/>'))


@unittest.skipUnless(HAS_DOCUMENTS, 'install Sun documents extra')
class OfficeDiffTest(unittest.TestCase):
    def test_workbook_values_formulas_types_sheet_addition_and_deletion(self):
        from openpyxl import Workbook
        book = Workbook()
        sheet = book.active
        sheet['A1'], sheet['B1'], sheet['C1'] = 1, '=A1+1', False
        book.create_sheet('Removed')
        before = io.BytesIO(); book.save(before)
        sheet['A1'], sheet['B1'], sheet['C1'] = '1', '=A1+2', 0
        del book['Removed']; book.create_sheet('Added')
        after = io.BytesIO(); book.save(after)
        result = docs.compare('book.xlsx', before.getvalue(), after.getvalue())
        cells = result['sheets'][0]['cells']
        self.assertEqual([c['cell'] for c in cells], ['A1', 'B1', 'C1'])
        self.assertEqual(cells[1]['after']['formula'], '=A1+2')
        self.assertIsNone(cells[1]['after']['value'])
        self.assertEqual([(s['name'], s['status']) for s in result['sheets'][1:]],
                         [('Removed', 'removed'), ('Added', 'added')])

    def test_formatting_only_does_not_claim_no_file_changes(self):
        from openpyxl import Workbook
        from openpyxl.styles import Font
        book = Workbook(); book.active['A1'] = 'unchanged'
        a = io.BytesIO(); book.save(a)
        book.active['A1'].font = Font(bold=True)
        b = io.BytesIO(); book.save(b)
        result = docs.compare('a.xlsx', a.getvalue(), b.getvalue())
        self.assertEqual(result['sheets'], [])
        self.assertIn('Formatting', result['notice'])

    def test_real_presentation_reorder_text_layout_notes_add_delete(self):
        from examples.demo_documents import write_examples
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'launch.pptx'
            write_examples(directory)
            old = path.read_bytes()
            write_examples(directory, revised=True)
            result = docs.compare('launch.pptx', old, path.read_bytes())
        self.assertEqual(result['kind'], 'presentation')
        slides = result['slides']
        self.assertEqual([s['status'] for s in slides], ['changed', 'changed', 'added', 'removed'])
        overview = slides[1]
        self.assertEqual((overview['before']['index'], overview['after']['index']), (0, 1))
        self.assertIn('Metric: text changed', overview['changes'])
        self.assertIn('Metric: moved or resized', overview['changes'])
        self.assertIn('Speaker notes changed', overview['changes'])
        self.assertIn('42 teams', [s['text'] for s in overview['after']['shapes']])
        self.assertTrue(all(s['status'] == 'added' for s in docs.compare('a.pptx', None, old)['slides']))
        self.assertTrue(all(s['status'] == 'removed' for s in docs.compare('a.pptx', old, None)['slides']))

    def test_corrupt_office_files_fall_back(self):
        for extension in ('.pptx', '.xlsx'):
            self.assertEqual(docs.compare('a' + extension, None, b'not zip')['kind'], 'unavailable')


class DocumentTransportTest(unittest.TestCase):
    setUp, tearDown = web_fixtures.WebReviewTest.setUp, web_fixtures.WebReviewTest.tearDown
    git, sun_head, check = web_fixtures.WebReviewTest.git, web_fixtures.WebReviewTest.sun_head, web_fixtures.WebReviewTest.check
    serve, get = web_fixtures.WebReviewTest.serve, web_fixtures.WebReviewTest.get

    def test_snapshot_added_deleted_and_literal_paths(self):
        Path('old.csv').write_text('a,1\n')
        run('sync'); self.base = self.sun_head()
        Path('old.csv').unlink()
        Path('literal[1].csv').write_text('a,2\n')
        data = self.serve()
        Path('literal[1].csv').write_text('unrecorded,999\n')
        for index, item in enumerate(data['items']):
            if not item['file'].endswith('.csv'): continue
            status, _, body = self.get(self.prefix + f'documents/{index}/diff.json')
            self.assertEqual(status, 200)
            result = json.loads(body)
            sheet = result['sheets'][0]
            self.assertEqual(sheet['status'], 'removed' if item['file'] == 'old.csv' else 'added')
            self.assertNotIn('unrecorded', body.decode())

    def test_unknown_routes_symlinks_and_bad_documents(self):
        Path('bad.xlsx').write_bytes(b'not a workbook')
        Path('bad.pptx').write_bytes(b'not a presentation')
        Path('target.txt').write_text('private content')
        os.symlink('target.txt', 'link.csv')
        data = self.serve()
        for route in ['documents/-1/diff.json', 'documents/999/diff.json',
                      'documents/0/../../target.txt', 'documents/0/nope']:
            self.assertEqual(self.get(self.prefix + route)[0], 404)
        for index, item in enumerate(data['items']):
            if item['file'] not in ('bad.xlsx', 'bad.pptx', 'link.csv'): continue
            status, _, body = self.get(self.prefix + f'documents/{index}/diff.json')
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body)['kind'], 'unavailable')
            self.assertNotIn('private content', body.decode())
            if item['file'] == 'bad.pptx':
                self.assertEqual(self.get(self.prefix + f'documents/{index}/after.pptx')[0], 404)

    @unittest.skipUnless(HAS_DOCUMENTS, 'install Sun documents extra')
    def test_raw_slides_use_pinned_blob_and_block_other_files(self):
        from pptx import Presentation
        path = Path('slides.pptx'); Presentation().save(path)
        raw = path.read_bytes()
        data = self.serve()
        index = next(i for i, item in enumerate(data['items']) if item['file'] == path.name)
        path.write_bytes(b'later edits')
        self.assertEqual(self.get(self.prefix + f'documents/{index}/after.pptx')[2], raw)
        self.assertEqual(self.get(self.prefix + f'documents/{index}/before.pptx')[0], 404)
        self.assertEqual(self.get(self.prefix + f'documents/{index}/../../.git/config')[0], 404)
