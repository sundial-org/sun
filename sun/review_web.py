"""Serve an immutable review snapshot and bundled Pierre UI on loopback."""
import gzip
import json
from pathlib import Path
import secrets
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import webbrowser

from . import git_store

ASSETS = Path(__file__).with_name('review_assets')


def create_server(data):
    token = secrets.token_urlsafe(24)
    static = {
        'index.html': ('text/html; charset=utf-8', (ASSETS / 'index.html').read_bytes()),
        'style.css': ('text/css; charset=utf-8', (ASSETS / 'style.css').read_bytes()),
        'app.js': ('text/javascript; charset=utf-8', gzip.decompress((ASSETS / 'app.js.gz').read_bytes())),
        'data.json': ('application/json; charset=utf-8', json.dumps(data).encode()),
    }
    root = git_store.root()

    def file_contents(at, path):
        result = subprocess.run(['git', 'show', f'{at}:{path}'], cwd=root, capture_output=True)
        if result.returncode: return None  # added/deleted file: absent on one side
        text = result.stdout.decode('utf-8')
        if '\0' in text: raise ValueError('Binary file')
        return {'name': path, 'contents': text, 'cacheKey': at + ':' + path}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            expected_host = f'127.0.0.1:{self.server.server_port}'
            if self.headers.get('Host') != expected_host or not self.path.startswith('/' + token + '/'):
                self.send_error(404)
                return
            name = self.path[len(token) + 2:]
            if name in static:
                content_type, body = static[name]
            elif name.startswith('files/') and name.endswith('.json'):
                try:
                    index = int(name[6:-5])
                    if not 0 <= index < len(data['items']): raise ValueError('Unknown file')
                    item = data['items'][index]
                    body = json.dumps({'oldFile': file_contents(data['base'], item['file']),
                                       'newFile': file_contents(data['head'], item['file'])}).encode()
                    content_type = 'application/json; charset=utf-8'
                except (ValueError, UnicodeError):
                    self.send_error(404)
                    return
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            if name == 'app.js' and 'gzip' in self.headers.get('Accept-Encoding', ''):
                body = (ASSETS / 'app.js.gz').read_bytes()
                self.send_header('Content-Encoding', 'gzip')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args): pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    return server, f'http://127.0.0.1:{server.server_port}/{token}/index.html'


def run(data):
    server, url = create_server(data)
    print(f'sun: review at {url}', flush=True)
    print('sun: local snapshot; Ctrl-C stops the server', flush=True)
    try:
        webbrowser.open(url)
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
