"""Local review transport, pinned snapshots, and CLI web dispatch."""
import contextlib
import gzip
import http.client
import json
import threading
import unittest
from unittest import mock
from urllib.parse import urlsplit

import test_review as fixtures
from test_sun import run, write
from sun import git_store, review, review_web


class WebReviewTest(unittest.TestCase):
    setUp, tearDown = fixtures.ReviewTest.setUp, fixtures.ReviewTest.tearDown
    git, sun_head, check = fixtures.ReviewTest.git, fixtures.ReviewTest.sun_head, fixtures.ReviewTest.check

    def serve(self, inbox=False):
        write('a.py', 'print("snapshot")\n')
        run('sync')
        data = review.review_data(self.base)
        payload = data
        if inbox:
            data['hidden_files'] = data['items']
            data['items'] = []
            data['coverage'] = {'files': 1, 'covered_files': 1, 'turns': 1, 'checked_turns': 1}
            payload = {'prs': [{'title': 'Demo', 'root': git_store.root(), 'review': data}]}
        server, url = review_web.create_server(payload)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def stop():
            server.shutdown()
            server.server_close()
            thread.join()
        self.addCleanup(stop)
        self.port = server.server_port
        self.prefix = urlsplit(url).path.rsplit('/', 1)[0] + '/'
        return data

    def get(self, path, headers=None, method='GET'):
        connection = http.client.HTTPConnection('127.0.0.1', self.port)
        connection.request(method, path, headers=headers or {})
        response = connection.getresponse()
        result = response.status, dict(response.headers), response.read()
        connection.close()
        return result

    def test_assets_and_snapshot_are_served_without_external_dependencies(self):
        data = self.serve()
        status, headers, body = self.get(self.prefix + 'data.json')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), data)
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertIn("script-src 'self'", headers['Content-Security-Policy'])
        status, headers, bundle = self.get(self.prefix + 'app.js', {'Accept-Encoding': 'gzip'})
        self.assertEqual(status, 200)
        self.assertEqual(headers['Content-Encoding'], 'gzip')
        self.assertIn(b'parsePatch', gzip.decompress(bundle))
        self.assertEqual(self.get(self.prefix + 'index.html')[0], 200)
        self.assertEqual(self.get(self.prefix + 'style.css')[0], 200)

    def test_routes_cannot_read_arbitrary_paths_or_use_another_host(self):
        self.serve()
        for path in ['/data.json', self.prefix + '../.git/config', self.prefix + 'files/-1.json',
                     self.prefix + 'files/999999.json', self.prefix + 'files/../../README.md.json']:
            self.assertEqual(self.get(path)[0], 404)
        self.assertEqual(self.get(self.prefix + 'data.json', {'Host': 'other.test'})[0], 404)
        self.assertEqual(self.get(self.prefix + 'data.json', method='POST')[0], 501)

    def test_context_comes_from_the_snapshot_not_later_worktree_edits(self):
        data = self.serve()
        index = next(i for i, item in enumerate(data['items']) if item['file'] == 'a.py')
        write('a.py', 'unrecorded changes\n')
        status, _, body = self.get(self.prefix + f'files/{index}.json')
        self.assertEqual(status, 200)
        files = json.loads(body)
        self.assertIsNone(files['oldFile'])
        self.assertEqual(files['newFile']['contents'], 'print("snapshot")\n')

    def test_web_dispatch_does_not_require_a_terminal_or_hold_the_git_lock(self):
        held, original = [], git_store.lock
        @contextlib.contextmanager
        def lock():
            with original():
                held.append(True)
                try: yield
                finally: held.pop()
        def browser(data):
            self.assertFalse(held)
            self.assertIn('items', data)
        with mock.patch.object(git_store, 'lock', lock), mock.patch.object(review_web, 'run', side_effect=browser) as opened:
            run('review', '--web', '--base', self.base)
        opened.assert_called_once()
        with self.assertRaises(SystemExit): run('review', '--web', '--json')

    def test_inbox_routes_covered_files_and_hides_local_repository_paths(self):
        data = self.serve(inbox=True)
        status, _, body = self.get(self.prefix + 'data.json')
        self.assertEqual(status, 200)
        self.assertNotIn('root', json.loads(body)['prs'][0])
        self.assertEqual(self.get(self.prefix + 'prs/0/index.html')[0], 200)
        status, _, body = self.get(self.prefix + 'prs/0/data.json')
        self.assertEqual(json.loads(body), data)
        status, _, body = self.get(self.prefix + 'prs/0/files/0.json')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['newFile']['contents'], 'print("snapshot")\n')
        for suffix in ['prs/-1/data.json', 'prs/1/data.json', 'prs/0/../../data.json']:
            self.assertEqual(self.get(self.prefix + suffix)[0], 404)
