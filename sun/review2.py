"""A local, snapshot-based thread review. Existing review commands stay independent."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
import webbrowser

from . import git_store, output, sessions, review2_state, checks, review, coverage_tui

ASSETS = Path(__file__).with_name('review2_assets')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def build_snapshot(data, repo, context=None):
    """Preserve ancestry order; identity never depends on generated titles."""
    threads, seen = {}, set()
    for commit in reversed(data['commits']):
        for op in commit['operations']:
            if op['id'] in seen:
                continue
            seen.add(op['id'])
            key = (op['actor'], op.get('session_id'), op.get('branch'))
            thread_id = digest(key)
            thread = threads.setdefault(thread_id, {'id': thread_id, 'title': '',
                'actor': op['actor'], 'branch': op.get('branch'), 'turns': []})
            turn_id = digest([key, op.get('turn') or op['id']])
            turn = next((t for t in thread['turns'] if t['id'] == turn_id), None)
            if turn is None:
                turn = {'id': turn_id, 'label': op.get('turn') or 'Observed edit',
                        'prompt': '', 'changes': []}
                thread['turns'].append(turn)
            if context and not turn['prompt']:
                turn['prompt'] = context(op) or ''
            for index, edit in enumerate(op.get('edits') or []):
                patch = edit.get('patch') or ''
                # Each operation edit remains available, including changes later undone.
                change = {'file': edit['file'], 'patch': patch,
                          'at': op.get('snapshot') or op.get('commit'), 'operation': op['id']}
                change['id'] = digest([op['id'], index, change])
                turn['changes'].append(change)
            if not thread['title']:
                thread['title'] = turn['prompt'].split('\n')[0][:100] if turn['prompt'] else ''
    result = []
    for thread in threads.values():
        thread['turns'] = [t for t in thread['turns'] if t['changes']]
        if not thread['turns']:
            continue
        thread['title'] = thread['title'] or thread['turns'][0]['changes'][0]['file']
        result.append(thread)
    snapshot = {'version': 1, 'repo': repo, 'threads': list(reversed(result))}
    snapshot['id'] = digest(snapshot)
    return snapshot


def attach_checks(snapshot, table, rules, stored):
    """Only exact, whole-file coverage can collapse a turn automatically."""
    rows = [row for commit in table for row in commit['rules']]
    for thread in snapshot['threads']:
        for turn in thread['turns']:
            applicable, relevant = [], {}
            for change in turn['changes']:
                matched_rule = False
                for name, rule in rules.items():
                    if not checks.matches(rule, [change['file']]):
                        continue
                    matched_rule = True
                    covered = False
                    for row in rows:
                        if row['rule'] != name:
                            continue
                        live = coverage_tui.current_checks(row)
                        touching = [c for c in live if any(
                            cite.get('at') == change['at'] and cite.get('file', change['file']) == change['file']
                            for cite in review.citations(c, stored))]
                        if touching:
                            relevant.pop((name, ()), None)
                            relevant[(name, tuple(c['id'] for c in live))] = row
                        if row['status'].lower() in review.PASS and any(
                            cite.get('at') == change['at'] and cite.get('file', change['file']) == change['file']
                            and cite.get('lines') is None
                            for c in touching for cite in review.citations(c, stored)):
                            covered = True
                    applicable.append(covered)
                    if not any(k[0] == name for k in relevant):
                        relevant[(name, ())] = {'rule': name, 'status': 'unchecked', 'checks': [], 'labels': {}, 'outdated': []}
                if not matched_rule:
                    applicable.append(False)
            turn['checks'] = list(relevant.values())
            turn['fully_checked'] = bool(applicable) and all(applicable) and all(
                row['status'].lower() in review.PASS for row in relevant.values())
    snapshot['id'] = digest({k: v for k, v in snapshot.items() if k != 'id'})


def transcript_context():
    cache = {}
    def read(op):
        path = op.get('session_path')  # Resolved by sun data, never guess a directory.
        if not path:
            return ''
        if path not in cache:
            try:
                cache[path] = list(sessions.scan_transcript(path, op['actor_info'].get('harness') or 'claude'))
            except (OSError, ValueError):
                cache[path] = []
        ids = [c.get('id') for c in op.get('tool_calls', []) if c.get('id')]
        matches = [chunk for chunk in cache[path] if any(tid in chunk for tid in ids)]
        return (sessions.chunk_prompt(matches[0]) or '')[:6000] if len(matches) == 1 else ''
    return read


def prepare(directory):
    directory = Path(directory).expanduser().resolve()
    if directory.exists():
        raise ValueError('Choose a new workspace directory; existing reviews are preserved.')
    stream = io.StringIO()
    with contextlib.redirect_stdout(stream):
        output.cmd_viz(SimpleNamespace(cmd='data', n=0, output=None))
    data = json.loads(stream.getvalue())
    snapshot = build_snapshot(data, str(git_store.root()), transcript_context())
    attach_checks(snapshot, checks.coverage(commits=[c['hash'] for c in data['commits']]), checks.read_rules()[1], checks.checks())
    directory.mkdir(parents=True)
    (directory / 'snapshot.json').write_text(json.dumps(snapshot, indent=2) + '\n', encoding='utf-8')
    (directory / 'prompt.md').write_text(review2_state.PROMPT, encoding='utf-8')
    return snapshot


def load(directory):
    snapshot = json.loads((Path(directory) / 'snapshot.json').read_text(encoding='utf-8'))
    expected = digest({k: v for k, v in snapshot.items() if k != 'id'})
    if snapshot.get('version') != 1 or snapshot.get('id') != expected:
        raise ValueError('Review snapshot changed. Prepare a new workspace.')
    return snapshot


def create_server(directory):
    snapshot = load(directory)
    token = secrets.token_urlsafe(24)
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.headers.get('Host') != f'127.0.0.1:{self.server.server_port}' or not self.path.startswith('/' + token + '/'):
                self.send_error(404)
                return
            name = self.path[len(token) + 2:]
            if name == 'data.json':
                body, mime = json.dumps({**snapshot, **review2_state.state(directory, snapshot)}).encode(), 'application/json'
            elif name in ('index.html', 'app.js', 'style.css'):
                body = (ASSETS / name).read_bytes()
                mime = {'index.html': 'text/html', 'app.js': 'text/javascript', 'style.css': 'text/css'}[name]
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header('Content-Type', mime + '; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'; object-src 'none'")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            host = f'127.0.0.1:{self.server.server_port}'
            if (self.headers.get('Host') != host or self.path != '/' + token + '/view'
                    or self.headers.get('Origin') != 'http://' + host):
                self.send_error(403)
                return
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 16384 or self.headers.get('Content-Type') != 'application/json':
                    raise ValueError('Expected a small JSON acknowledgment.')
                if load(directory)['id'] != snapshot['id']:
                    raise ValueError('Snapshot changed; reopen the review.')
                result = review2_state.record_view(directory, snapshot, json.loads(self.rfile.read(size)))
                body = json.dumps(result).encode()
            except (ValueError, OSError) as error:
                self.send_error(400, str(error))
                return
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    return server, f'http://127.0.0.1:{server.server_port}/{token}/index.html'


def cmd_review2(a):
    try:
        if a.prepare:
            prepare(a.prepare)
            print(str(Path(a.prepare).expanduser().resolve()))
            return
        snapshot = load(a.open)
        if a.select:
            plan = json.loads(Path(a.select).expanduser().read_text(encoding='utf-8'))
            review2_state.save_selection(a.open, snapshot, plan)
        if a.json:
            print(json.dumps({**snapshot, **review2_state.state(a.open, snapshot)}))
            return
        server, url = create_server(a.open)
        print(url, flush=True)
        if not a.no_browser:
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
    except (OSError, ValueError) as error:
        raise SystemExit(f'sun: {error}')
