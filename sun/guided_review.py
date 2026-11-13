"""Prepare agent review workspaces and render validated, revision-pinned output."""
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile

from . import inbox, review_web

SKILL = Path(__file__).with_name('skills') / 'sun-review' / 'SKILL.md'
PLAN_FIELDS = {'id', 'head', 'question', 'why', 'before', 'after', 'waiting', 'evidence', 'depends_on', 'required_checks'}


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')


def identity(pr):
    repo = inbox.repo_name(pr['repository']['nameWithOwner'])
    number = pr['number']
    if type(number) is not int or number < 1:
        raise ValueError('Invalid PR number')
    return f'{repo}#{number}', f'https://github.com/{repo}/pull/{number}'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(a):
    directory = Path(a.prepare).expanduser().resolve()
    # Read explicitly selected skills before creating anything or fetching the inbox.
    skills = [{'name': Path(p).stem if Path(p).stem != 'SKILL' else Path(p).resolve().parent.name,
               'text': Path(p).expanduser().read_text(encoding='utf-8')}
              for p in a.skill]
    directory.mkdir(parents=True, exist_ok=False)
    try:
        with tempfile.TemporaryDirectory(prefix='sun-review-fetch-') as temporary:
            rows = [{k: v for k, v in row.items() if k != 'root'} for row in inbox.collect(a.limit, temporary)]
    except (OSError, RuntimeError, ValueError):
        directory.rmdir()  # Still empty: allow retry after authentication/network recovery.
        raise
    for row in rows:
        row['id'], row['url'] = identity(row)
    snapshot = {'version': 1, 'prompt': a.prompt or '', 'skills': [s['name'] for s in skills], 'prs': rows}
    write_json(directory / 'snapshot.json', snapshot)
    snapshot_hash = digest(directory / 'snapshot.json')
    plan = {'version': 1, 'snapshot': snapshot_hash, 'complete': False, 'reviews': [
        {'id': row['id'], 'head': row['review']['head'], 'question': '', 'why': '',
         'before': '', 'after': '', 'waiting': False, 'evidence': [], 'depends_on': [], 'required_checks': []}
        for row in rows if 'review' in row]}
    write_json(directory / 'review.json', plan)
    prompt = SKILL.read_text(encoding='utf-8') + '\n\n## This review\n\n' + (
        f'Workspace: {directory}\nSnapshot digest: {snapshot_hash}\n\nUser request:\n{a.prompt or "Prioritize the reviews that need my attention."}\n')
    for skill in skills:
        prompt += f"\n## User-selected skill: {skill['name']}\n\n{skill['text']}\n"
    (directory / 'prompt.md').write_text(prompt, encoding='utf-8')
    print(json.dumps({'workspace': str(directory), 'instructions': str(directory / 'prompt.md'),
                      'snapshot': str(directory / 'snapshot.json'), 'output': str(directory / 'review.json'),
                      'next': 'Read prompt.md and snapshot.json, write review.json, then run sun review --open WORKSPACE.'}))


def text(value, field, required=False):
    if not isinstance(value, str) or (required and not value.strip()):
        raise ValueError(f'{field} must be a nonempty string' if required else f'{field} must be a string')
    return value


def validate(snapshot, plan, snapshot_hash):
    if not isinstance(snapshot, dict) or not isinstance(plan, dict) or not isinstance(snapshot.get('prs'), list):
        raise ValueError('Invalid review document')
    if set(plan) - {'version', 'snapshot', 'complete', 'reviews'}:
        raise ValueError('Unknown review document fields')
    if snapshot.get('version') != 1 or plan.get('version') != 1:
        raise ValueError('Unsupported review format')
    if plan.get('snapshot') != snapshot_hash:
        raise ValueError('Snapshot changed; prepare and regenerate the review')
    if plan.get('complete') is not True:
        raise ValueError('The agent has not completed review.json')
    if not isinstance(plan.get('reviews'), list):
        raise ValueError('reviews must be an ordered list')
    rows = {}
    for row in snapshot['prs']:
        key, url = identity(row)
        if key in rows: raise ValueError('Duplicate PR in snapshot')
        rows[key] = dict(row, id=key, url=url)
    seen, result = set(), []
    for item in plan['reviews']:
        if not isinstance(item, dict) or set(item) - PLAN_FIELDS:
            raise ValueError('Unknown review fields; check results come only from the snapshot')
        key = item.get('id')
        if not isinstance(key, str) or key not in rows or key in seen:
            raise ValueError('Unknown or duplicate PR in review.json')
        row = rows[key]
        source = row.get('review')
        if not source or item.get('head') != source['head']:
            raise ValueError(f'Review revision does not match snapshot for {key}')
        if not re.fullmatch(r'[0-9a-f]{40,64}', source['head']):
            raise ValueError('Invalid snapshot revision')
        for name in ('question', 'why', 'before', 'after'):
            text(item.get(name, ''), name, name in ('question', 'why'))
        if type(item.get('waiting', False)) is not bool:
            raise ValueError('waiting must be boolean')
        paths = {f['file'] for f in source['items'] + source['hidden_files']}
        evidence = item.get('evidence', [])
        if not isinstance(evidence, list): raise ValueError('evidence must be a list')
        for cite in evidence:
            if not isinstance(cite, dict) or set(cite) - {'file', 'note'} or cite.get('file') not in paths:
                raise ValueError(f'Evidence must cite a changed file in {key}')
            text(cite.get('note'), 'evidence note', True)
        for field in ('depends_on', 'required_checks'):
            if not isinstance(item.get(field, []), list) or any(not isinstance(s, str) or not s.strip() for s in item.get(field, [])):
                raise ValueError(f'{field} must be a list of names')
        if any(dep not in rows or dep == key for dep in item.get('depends_on', [])):
            raise ValueError('Dependencies must refer to other PRs in this snapshot')
        # Agent output is a constrained annotation. It cannot replace titles, diffs, URLs or check facts.
        result.append(dict(row, analysis=item))
        seen.add(key)
    missing = {key for key, row in rows.items() if 'review' in row} - seen
    if missing: raise ValueError('Missing agent reviews: ' + ', '.join(sorted(missing)))
    result.extend(row for key, row in rows.items() if key not in seen)
    return {'guided': True, 'prs': result, 'prompt': snapshot.get('prompt', ''), 'skills': snapshot.get('skills', [])}


def load(directory):
    directory = Path(directory).expanduser().resolve()
    snapshot = json.loads((directory / 'snapshot.json').read_text(encoding='utf-8'))
    plan = json.loads((directory / 'review.json').read_text(encoding='utf-8'))
    return validate(snapshot, plan, digest(directory / 'snapshot.json'))


def run(a):
    try:
        if a.instructions: return print(SKILL.read_text(encoding='utf-8'))
        if a.prepare: return prepare(a)
        data = load(a.open_review)
        if a.json: return print(json.dumps(data))
        review_web.run(data, open_browser=not a.no_browser)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        sys.exit(f'sun: {exc}')
