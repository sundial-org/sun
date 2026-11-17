"""Repository-wide review prototype. No model is required for capture or terminal use."""
import contextlib
import io
from collections import defaultdict
from contextlib import closing
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import sqlite3
from types import SimpleNamespace

from . import checks, git_store, output, review2

ROOT = Path(__file__).parent
ASSETS = ROOT / 'repository_review_assets'
NEGATIVE = {'fail', 'failed', 'contradicted', 'needs revision', 'needs-revision'}
POSITIVE = {'pass', 'passed'}


def identity(*parts):
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()[:24]


def current(records, rules):
    replaced = {cite['check'] for c in records.values() for cite in c.get('cites', []) if 'check' in cite}
    return {key: c for key, c in records.items() if key not in replaced and c['rule'] in rules
            and c.get('rule_text', rules[c['rule']]['hash']) == rules[c['rule']]['hash']}


def citations(record, records, seen=None):
    seen = set() if seen is None else seen
    if record['id'] in seen:
        return []
    seen.add(record['id'])
    direct = [c for c in record['cites'] if 'at' in c]
    return direct or [cite for c in record['cites'] if c.get('check') in records
                      for cite in citations(records[c['check']], records, seen)]


def summarize(turns):
    edits = [c for t in turns for c in t['changes']]
    checked = sum(bool(c['checks']) for c in edits)
    return {'edits': len(edits), 'checked': checked, 'unchecked': len(edits)-checked,
            'percent': round(100*checked/len(edits)) if edits else 0}


def tone(turn):
    return ('red', min(3, turn['failed'])) if turn['failed'] else ('green', min(3, (turn['passed']+3)//4)) if turn['passed'] else ('gray', 0)


def finish(model):
    for t in model['turns']:
        ids = {i for c in t['changes'] for i in c['checks']}
        t['checks'] = [model['checks'][i] for i in sorted(ids)]
        t['failed'] = sum(c['verdict'].lower() in NEGATIVE for c in t['checks'])
        t['passed'] = sum(c['verdict'].lower() in POSITIVE for c in t['checks'])
        t['unchecked'] = sum(not c['checks'] for c in t['changes'])
        t['tone'], t['intensity'] = tone(t)
    model['summary'] = summarize(model['turns'])
    return model


def capture(data, evidence, destination, repo):
    rules, records = evidence['rules'], evidence['checks']
    live = current(records, rules)
    index = defaultdict(list)
    for key, c in live.items():
        for cite in citations(c, records):
            index[(cite['at'], cite.get('file'))].append(key)
    destination = Path(destination); (destination/'patches').mkdir(parents=True, exist_ok=True)
    model = {'format': 'sun-repository-review-v1', 'repo': str(Path(repo).resolve()), 'scope': 'all locally recorded branches', 'example': False,
             'rules': [{'name': n, 'text': r['text']} for n, r in rules.items()], 'turns': [],
             'checks': {i: {k: c.get(k) for k in ('id', 'rule', 'verdict', 'note', 'actor', 'cites')} for i,c in live.items()}}
    groups, seen = {}, set()
    # sun data supplies operation identity and resolved session_path. Never guess a transcript path.
    for commit in reversed(data['commits']):
        for op in commit['operations']:
            if op['id'] in seen or op['actor_info']['kind'] != 'agent' or not op['edits']:
                continue
            seen.add(op['id'])
            sid = identity(op['actor'], op.get('session_id'))
            key = identity(sid, op.get('turn') or op['id'], op.get('branch'))
            if key not in groups:
                label = str(op.get('turn') or len(groups)+1).removeprefix('turn')
                groups[key] = {'id': key, 'session': sid, 'actor': op['actor'], 'label': label,
                    'branch': op.get('branch') or '', 'title': commit['subject'], 'request': '',
                    'session_path': op.get('session_path'), 'changes': []}
            t = groups[key]
            for n, edit in enumerate(op['edits']):
                at = op.get('snapshot') or op.get('commit')
                cid = identity(op['id'], n, edit['file'], at)
                patch = edit.get('patch') or ''
                (destination/'patches'/f'{cid}.patch').write_text(patch)
                ids = sorted(set(index[(at, edit['file'])] + index[(at, None)] + index[(op['commit'], edit['file'])] + index[(op['commit'], None)]))
                t['changes'].append({'id': cid, 'file': edit['file'], 'at': at, 'checks': ids,
                                    'check_scope': 'Exact operation or final turn revision', 'preview': '\n'.join(patch.splitlines()[:30])[:5000],
                                    'bytes': len(patch.encode()), 'lines': len(patch.splitlines())})
    model['turns'] = list(reversed(list(groups.values())))
    # Read only paths returned by sun data. Prompts supply session/turn labels, not instructions.
    context = review2.transcript_context()
    for commit in data['commits']:
        for op in commit['operations']:
            if op['id'] not in seen:
                continue
            key = identity(identity(op['actor'], op.get('session_id')), op.get('turn') or op['id'], op.get('branch'))
            t = groups.get(key)
            if t and not t['request']:
                request = context(op)
                if request:
                    t['request'] = request
                    t['title'] = request.splitlines()[0][:160]
    for t in model['turns']:
        t.pop('session_path', None)
    finish(model)
    (destination/'snapshot.json').write_text(json.dumps(model))
    return model


def load(workspace):
    model = json.loads((Path(workspace)/'snapshot.json').read_text())
    with closing(sqlite3.connect(Path(workspace)/'review.sqlite')) as db, db:
        db.execute('CREATE TABLE IF NOT EXISTS reviewed (change TEXT PRIMARY KEY)')
        model['reviewed'] = [r[0] for r in db.execute('SELECT change FROM reviewed')]
        db.execute('CREATE TABLE IF NOT EXISTS explanations (turn TEXT PRIMARY KEY, text TEXT NOT NULL, checks TEXT NOT NULL)')
        model['explanations'] = {r[0]: {'text':r[1], 'checks':json.loads(r[2])} for r in db.execute('SELECT turn,text,checks FROM explanations')}
    return model


def review_turn(workspace, model, turn_id):
    t = next((t for t in model['turns'] if t['id'] == turn_id), None)
    if not t:
        raise ValueError('Unknown turn')
    with closing(sqlite3.connect(Path(workspace)/'review.sqlite')) as db, db:
        db.executemany('INSERT OR IGNORE INTO reviewed VALUES (?)', [(c['id'],) for c in t['changes']])
    return load(workspace)['reviewed']


def save_explanation(workspace, turn_id, text, check_ids):
    model = load(workspace)
    t = next((t for t in model['turns'] if t['id'] == turn_id), None)
    if not t or not isinstance(text,str) or not 1 <= len(text.strip()) <= 3000 or not check_ids or not set(check_ids) <= {c['id'] for c in t['checks']}:
        raise ValueError('Explain a recorded turn and cite its actual checks.')
    with closing(sqlite3.connect(Path(workspace)/'review.sqlite')) as db, db:
        db.execute('INSERT OR REPLACE INTO explanations VALUES (?,?,?)', (turn_id,text,json.dumps(check_ids)))
    return {'saved': True}


def render_html(workspace, inline=False):
    model = load(workspace)
    # Inline prototype contains readable previews; the plugin's read_patch tool supplies complete files.
    content = json.dumps(model).replace('<', '\\u003c')
    css = (ASSETS/'style.css').read_text()
    js = (ASSETS/'app.js').read_text()
    if inline:
        start=js.index('async function getPatch(change)')
        end=js.index('function turn()',start)
        js=js[:start]+"async function getPatch(change){return change.preview;}\n"+js[end:]
        start=js.index(' const reviewed=button(')
        end=js.index('reviewed.disabled=viewed(t);',start)
        js=js[:start]+" const reviewed=button(viewed(t)?'reviewed':'mark turn reviewed',()=>{data.reviewed=[...(data.reviewed||[]),...t.changes.map(c=>c.id)];render();});"+js[end:]
        js=js[:js.index('// Standard MCP Apps')]+"render();\n})();"
    root = '<div id="sun-terminal"></div>' 
    script = '<script>\n'+js.replace('/* DATA */', 'const initialData = '+content+';')+'\n</script>'
    if inline:
        # A response preview cannot call network APIs. Its complete small fixture diffs are embedded.
        script = script.replace("const transport = 'server';", "const transport = 'preview';")
        return '<style>\n'+css+'\n</style>\n'+root+'\n'+script
    return '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>sun / repository review</title><style>'+css+'</style><body>'+root+script+'</body></html>'


def serve(workspace):
    workspace = Path(workspace); token = secrets.token_urlsafe(24)
    model = load(workspace); allowed = {c['id'] for t in model['turns'] for c in t['changes']}
    class Handler(BaseHTTPRequestHandler):
        def valid(self):
            return self.headers.get('Host') == f'127.0.0.1:{self.server.server_port}' and self.path.startswith('/'+token+'/')
        def send(self, body, mime):
            self.send_response(200); self.send_header('Content-Type',mime+'; charset=utf-8'); self.send_header('Content-Length',str(len(body)))
            self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'"); self.send_header('Cache-Control','no-store'); self.send_header('X-Content-Type-Options','nosniff'); self.send_header('Referrer-Policy','no-referrer'); self.end_headers(); self.wfile.write(body)
        def do_GET(self):
            if not self.valid(): return self.send_error(404)
            name=self.path.split('/')[-1]
            if name=='index.html': return self.send(render_html(workspace).encode(),'text/html')
            if name.endswith('.patch') and name[:-6] in allowed: return self.send((workspace/'patches'/name).read_bytes(),'text/plain')
            self.send_error(404)
        def do_POST(self):
            if not self.valid() or self.headers.get('Origin') != f'http://127.0.0.1:{self.server.server_port}' or not self.path.endswith('/review'):
                return self.send_error(403)
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<4096: raise ValueError('Invalid request size')
                value=json.loads(self.rfile.read(size))
                reviewed=review_turn(workspace,load(workspace),value['turn'])
                self.send(json.dumps({'reviewed':reviewed}).encode(),'application/json')
            except (ValueError,KeyError,TypeError): self.send_error(400)
        def log_message(self,*args): pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    return server,f'http://127.0.0.1:{server.server_port}/{token}/index.html'


def prepare(directory):
    directory = Path(directory).expanduser().resolve()
    if directory.exists():
        raise ValueError('Choose a new workspace directory; existing reviews are preserved.')
    stream = io.StringIO()
    # The same sun data path resolves attribution and native transcript locations.
    with contextlib.redirect_stdout(stream):
        output.cmd_viz(SimpleNamespace(cmd='data', n=0, output=None, all_branches=True))
    model = capture(json.loads(stream.getvalue()),
                    {'rules': checks.read_rules()[1], 'checks': checks.checks()},
                    directory, git_store.root())
    skill = ROOT/'repository_review_plugin/skills/sun-review2/SKILL.md'
    (directory/'prompt.md').write_text(skill.read_text(), encoding='utf-8')
    return model


def is_workspace(directory):
    return json.loads((Path(directory)/'snapshot.json').read_text()).get('format') == 'sun-repository-review-v1'


def open_workspace(a):
    if a.select:
        raise ValueError('--select is for PR captures. Use the repository plugin to save explanations.')
    if getattr(a, 'tui', False) or getattr(a, 'plain', False):
        from .repository_review_tui import run, plain
        if a.plain:
            print(plain(load(a.open)))
        else:
            run(a.open)
        return
    if a.json:
        print(json.dumps(load(a.open)))
        return
    server, url = serve(a.open)
    print(url, flush=True)
    if not a.no_browser:
        import webbrowser
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
