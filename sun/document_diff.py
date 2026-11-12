"""Read-only document comparisons. Raw Git patches remain the source of truth."""
import csv
import hashlib
import io
from pathlib import Path
import subprocess
import zipfile

EXTENSIONS = {'.csv', '.tsv', '.xlsx', '.pptx', '.key'}
MAX_BYTES = 20 * 1024 * 1024
MAX_CELLS = 50000


def read_blob(root, at, path):
    """Read a bounded blob from a pinned tree, never from the working directory."""
    entry = subprocess.run(['git', '--literal-pathspecs', 'ls-tree', '-z', at, '--', path],
                           cwd=root, capture_output=True, check=True).stdout
    if not entry: return None
    mode, kind, oid = entry.split(b'\t', 1)[0].split()
    if kind != b'blob' or mode not in (b'100644', b'100755'):
        raise ValueError('Only regular files can be previewed.')
    size = subprocess.run(['git', 'cat-file', '-s', oid.decode()], cwd=root,
                          capture_output=True, check=True).stdout
    if int(size) > MAX_BYTES: raise ValueError('Preview limit: 20 MiB per file.')
    return subprocess.run(['git', 'cat-file', 'blob', oid.decode()], cwd=root,
                          capture_output=True, check=True).stdout


def validate_archive(raw):
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        parts = archive.infolist()
        if len(parts) > 2000 or sum(p.file_size for p in parts) > 64 * 1024 * 1024:
            raise ValueError('Preview limit: 2,000 ZIP parts / 64 MiB expanded.')
        # Never expand to disk or allow document XML to declare entities.
        for part in parts:
            if part.filename.endswith(('.xml', '.rels')):
                xml = archive.read(part).replace(b'\0', b'').upper()
                if b'<!DOCTYPE' in xml or b'<!ENTITY' in xml:
                    raise ValueError('XML entity declarations are not supported.')


def value(v):
    if v is None: return None
    return {'type': type(v).__name__, 'text': str(v)}


def sheets(raw, extension):
    if raw is None: return {}
    if extension in ('.csv', '.tsv'):
        cells = {}
        reader = csv.reader(io.StringIO(raw.decode('utf-8-sig'), newline=''),
                            delimiter='\t' if extension == '.tsv' else ',')
        count = 0
        for r, row in enumerate(reader, 1):
            count += max(1, len(row))
            if count > MAX_CELLS: raise ValueError('Preview limit: 50,000 cells.')
            for c, text in enumerate(row, 1):
                if text: cells[(r, c)] = {'value': value(text), 'formula': None}
        return {'Data': cells}
    from openpyxl import load_workbook
    validate_archive(raw)
    formulas = load_workbook(io.BytesIO(raw), read_only=True, data_only=False, keep_links=False)
    cached = None
    try:
        cached = load_workbook(io.BytesIO(raw), read_only=True, data_only=True, keep_links=False)
        result, count, visited = {}, 0, 0
        for ws in formulas:
            count += (ws.max_row or 0) * (ws.max_column or 0)
            if count > MAX_CELLS: raise ValueError('Preview limit: 50,000 cells.')
            cells = result[ws.title] = {}
            for r, (row, values) in enumerate(zip(ws.iter_rows(), cached[ws.title].iter_rows()), 1):
                visited += max(1, len(row))
                if visited > MAX_CELLS: raise ValueError('Preview limit: 50,000 cells.')
                for c, (cell, saved) in enumerate(zip(row, values), 1):
                    if cell.value is None: continue
                    if cell.data_type == 'f' and not isinstance(cell.value, str):
                        raise ValueError('Array/data-table formulas are not supported in this preview.')
                    cells[(r, c)] = {'formula': cell.value if cell.data_type == 'f' else None,
                                     'value': value(saved.value)}
        return result
    finally:
        formulas.close()
        if cached is not None: cached.close()


def address(row, col):
    letters = ''
    while col:
        col, digit = divmod(col - 1, 26)
        letters = chr(65 + digit) + letters
    return letters + str(row)


def spreadsheet_diff(old, new, extension):
    before, after = sheets(old, extension), sheets(new, extension)
    result = []
    for name in dict.fromkeys([*before, *after]):
        left, right = before.get(name, {}), after.get(name, {})
        changes = [{'cell': address(*cell), 'before': left.get(cell), 'after': right.get(cell)}
                   for cell in sorted(left.keys() | right.keys()) if left.get(cell) != right.get(cell)]
        status = 'added' if name not in before else 'removed' if name not in after else 'changed'
        if changes or status != 'changed':
            result.append({'name': name, 'status': status, 'cells': changes})
    return {'kind': 'spreadsheet', 'sheets': result,
            'notice': 'Cells are matched by sheet name and address. Row insertions can shift subsequent cells. '
                      'Formulas and saved values are compared; formulas are not recalculated. '
                      'Formatting, charts, and macros are not compared.'}


def slides(raw):
    if raw is None: return []
    from pptx import Presentation
    validate_archive(raw)
    deck = Presentation(io.BytesIO(raw))
    if len(deck.slides) > 200: raise ValueError('Preview limit: 200 slides.')
    result = []
    for index, slide in enumerate(deck.slides):
        shapes = []
        for shape in slide.shapes:
            text = shape.text if shape.has_text_frame else ''
            if shape.has_table:
                text = '\n'.join('\t'.join(c.text for c in row.cells) for row in shape.table.rows)
            image = hashlib.sha256(shape.image.blob).hexdigest() if hasattr(shape, 'image') else None
            shapes.append({'id': shape.shape_id, 'name': shape.name, 'text': text,
                           'bounds': [shape.left, shape.top, shape.width, shape.height],
                           'xml': hashlib.sha256(shape.element.xml.encode()).hexdigest(), 'image': image,
                           'chart': hashlib.sha256(shape.chart.part.blob).hexdigest() if shape.has_chart else None})
        result.append({'id': slide.slide_id, 'index': index,
                       'title': slide.shapes.title.text if slide.shapes.title else
                       next((s['text'].splitlines()[0] for s in shapes if s['text']), f'Slide {index + 1}'),
                       'shapes': shapes, 'notes': slide.notes_slide.notes_text_frame.text
                       if slide.has_notes_slide and slide.notes_slide.notes_text_frame else ''})
    return result


def presentation_diff(old, new):
    before, after = slides(old), slides(new)
    left, right = {s['id']: s for s in before}, {s['id']: s for s in after}
    result = []
    # ponytail: persistent slide IDs align edits within a deck; regenerated decks need content matching.
    for sid in dict.fromkeys([*right, *left]):
        a, b = left.get(sid), right.get(sid)
        changes = []
        if a and b:
            if a['index'] != b['index']: changes.append('Slide position changed')
            old_shapes, new_shapes = {s['id']: s for s in a['shapes']}, {s['id']: s for s in b['shapes']}
            for shape_id in dict.fromkeys([*old_shapes, *new_shapes]):
                x, y = old_shapes.get(shape_id), new_shapes.get(shape_id)
                label = (y or x)['name']
                if x is None or y is None:
                    changes.append(label + (' added' if x is None else ' removed'))
                    continue
                if x['text'] != y['text']: changes.append(label + ': text changed')
                if x['bounds'] != y['bounds']: changes.append(label + ': moved or resized')
                if x['image'] != y['image']: changes.append(label + ': image changed')
                if x['chart'] != y['chart']: changes.append(label + ': chart changed')
                if x['xml'] != y['xml'] and x['text'] == y['text'] and x['bounds'] == y['bounds']:
                    changes.append(label + ': formatting or properties changed')
            if a['notes'] != b['notes']: changes.append('Speaker notes changed')
        status = 'added' if a is None else 'removed' if b is None else 'changed' if changes else 'unchanged'
        result.append({'before': a, 'after': b, 'status': status, 'changes': changes})
    return {'kind': 'presentation', 'slides': result,
            'notice': 'Slides are matched by stored slide ID. Previews approximate PowerPoint rendering. '
                      'Summaries cover top-level shapes and notes; themes, masters, animations, and grouped '
                      'objects may change without a summary. Inspect both previews.'}


def compare(path, old, new):
    extension = Path(path).suffix.lower()
    if extension == '.key':
        return {'kind': 'unavailable', 'notice': 'Export both Keynote versions to .pptx and review those files. '
                'Native .key previews are not supported yet.'}
    try:
        if any(raw is not None and len(raw) > MAX_BYTES for raw in (old, new)):
            raise ValueError('Preview limit: 20 MiB per file.')
        if extension == '.pptx': return presentation_diff(old, new)
        return spreadsheet_diff(old, new, extension)
    except ImportError:
        return {'kind': 'unavailable', 'notice': 'Install document support: pip install "sun[documents]" '
                '(or uv tool install --reinstall "sun[documents] @ git+https://github.com/sundial-org/sun").'}
    except Exception as error:  # malformed/unsupported documents must not break the review queue
        return {'kind': 'unavailable', 'notice': 'Document preview unavailable: ' + str(error)}
