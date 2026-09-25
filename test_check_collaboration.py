"""Deterministic Layer 2 scenarios: three clones, a bare remote, and scripted verdicts.

Run: python3 -m unittest -v test_check_collaboration
No models, network services, sleeps, or shared user Git/harness configuration.
"""
import csv
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SOURCE = str(Path(__file__).resolve().parent)
RULES = '''correct-total: The report's total quantity equals the sum of quantities in data.csv.
correct-count: The report's item count equals the number of data rows in data.csv.
no-todos: The report contains no TODO markers.
'''
REPORT = 'Total quantity: 5\nNumber of items: 2\n'
# Only the clock is stubbed. Each invocation uses the real CLI, lock, Git objects, and transport.
LAUNCH = '''import os
from unittest.mock import patch
from sun.cli import main
if 'TEST_GATE' in os.environ:
    os.read(int(os.environ['TEST_GATE']), 1)
with patch('sun.checks.time.strftime', return_value=os.environ['TEST_TIME']):
    main()
'''


class CheckCollaborationTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.remote = self.root / 'remote.git'
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(('GIT_', 'SUN_'))}
        self.env.update(HOME=str(self.root), GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
                        GIT_AUTHOR_DATE='2026-09-20T12:00:00+0000',
                        GIT_COMMITTER_DATE='2026-09-20T12:00:00+0000',
                        PYTHONPATH=SOURCE, TZ='UTC', TEST_TIME='2026-09-20T12:00:00+0000')
        self.git(self.root, 'init', '--bare', '-b', 'main', str(self.remote))
        self.alice = self.root / 'alice'
        self.alice.mkdir()
        self.git(self.alice, 'init', '-b', 'main')
        self.identity(self.alice, 'alice')
        for name, value in [('RULES', RULES), ('data.csv', 'item,quantity\napples,2\npears,3\n'),
                            ('report.md', REPORT)]:
            (self.alice / name).write_text(value)
        self.git(self.alice, 'add', '.')
        self.git(self.alice, 'commit', '-m', 'report fixture')
        self.sun(self.alice, 'init', '--claude', '--no-instructions')
        self.git(self.alice, 'add', '.')
        self.git(self.alice, 'commit', '-m', 'shared hook configuration')
        self.sun(self.alice, 'sync')
        self.git(self.alice, 'remote', 'add', 'origin', str(self.remote))
        self.sun(self.alice, 'init', '--claude', '--no-instructions')  # install origin fetch refspecs
        self.git(self.alice, 'push', 'origin', 'main')
        self.sun(self.alice, 'push')
        self.bob, self.carol = (self.clone(name) for name in ('bob', 'carol'))
        self.clones = (self.alice, self.bob, self.carol)
        self.initial = self.tip(self.alice)
        self.assertEqual({self.tip(p) for p in self.clones}, {self.initial})

    def execute(self, repo, args, stdin=None, ok=True, env=None):
        p = subprocess.run(args, cwd=repo, env=env or self.env, input=stdin,
                           text=True, capture_output=True, timeout=30)
        if ok: self.assertEqual(p.returncode, 0, f'{args}\n{p.stdout}\n{p.stderr}')
        return p

    def git(self, repo, *args, stdin=None):
        return self.execute(repo, ['git', *args], stdin=stdin).stdout.strip()

    def sun(self, repo, *args, data=None, ok=True, time=None):
        env = dict(self.env, SUN_PROJECTS=str(self.root / (repo.name + '-claude')),
                   SUN_CODEX_SESSIONS=str(self.root / (repo.name + '-codex')))
        if time: env['TEST_TIME'] = time
        return self.execute(repo, [sys.executable, '-c', LAUNCH, *args],
                            stdin=json.dumps(data) if data is not None else None, ok=ok, env=env)

    def identity(self, repo, name):
        self.git(repo, 'config', 'user.name', name)
        self.git(repo, 'config', 'user.email', name + '@example.test')

    def clone(self, name, identity=None):
        p = self.root / name
        self.git(self.root, 'clone', str(self.remote), str(p))
        self.identity(p, identity or name)
        self.sun(p, 'init', '--claude', '--no-instructions')
        return p

    def tip(self, repo, branch='main'):
        return self.git(repo, 'rev-parse', 'refs/sun/heads/' + branch)

    def request(self, verdict='pass', rule='correct-total', at=None, actor='program:csv'):
        return dict(rule=rule, verdict=verdict, actor=actor,
                    cites=[{'at': at or self.initial, 'file': 'report.md'},
                           {'at': at or self.initial, 'file': 'data.csv'}])

    def submit(self, repo, request, time=None):
        return json.loads(self.sun(repo, 'check', '--json', data=request, time=time).stdout)['checks'][0]

    def stored(self, repo):
        refs = self.git(repo, 'for-each-ref', '--format=%(refname)', 'refs/sun/checks/').splitlines()
        return {r.rsplit('/', 1)[-1]: json.loads(self.git(repo, 'cat-file', 'blob', r)) for r in refs}

    def rows(self, repo):
        return {c['commit']: {r['rule']: r for r in c['rules']}
                for c in json.loads(self.sun(repo, 'coverage', '--json', '-n', '0').stdout)['commits']}

    def row(self, repo, at=None, rule='correct-total'):
        return self.rows(repo)[at or self.initial][rule]

    def share(self, *publishers):
        for p in publishers: self.sun(p, 'push')
        for p in self.clones: self.git(p, 'fetch', 'origin')

    def assert_row(self, repo, status, records, eyes=False, at=None, rule='correct-total'):
        row = self.row(repo, at, rule)
        self.assertEqual((row['status'], row['eyes']), (status, eyes))
        self.assertEqual({c['id']: c for c in row['checks']}, {c['id']: c for c in records})
        self.assertEqual(len(row['checks']), len(records))

    def test_independent_disagreement_converges_in_both_push_orders(self):
        for rule, order in (('correct-total', (self.alice, self.bob)),
                            ('correct-count', (self.bob, self.alice))):
            with self.subTest(order=[p.name for p in order]):
                a = self.submit(self.alice, self.request('pass', rule))
                b = self.submit(self.bob, self.request('fail', rule, actor='agent:scripted'))
                self.assertNotEqual(a['id'], b['id'])
                self.share(*order)
                for p in self.clones: self.assert_row(p, 'mixed', [a, b], rule=rule)

    def test_concurrent_reviews_preserve_disagreement_and_original(self):
        a = self.submit(self.alice, self.request('fail'))
        self.share(self.alice)
        b = self.submit(self.bob, dict(rule='correct-total', verdict='pass', actor='agent:scripted',
                                       cites=[{'check': a['id']}]))
        c = self.submit(self.carol, dict(rule='correct-total', verdict='fail', actor='program:csv',
                                         cites=[{'check': a['id']}]))
        self.share(self.carol, self.bob)
        for p in self.clones: self.assert_row(p, 'mixed', [a, b, c])

    def test_review_chain_loses_human_eyes_when_model_supersedes_it(self):
        a = self.submit(self.alice, self.request('fail'))
        self.share(self.alice)
        b = json.loads(self.sun(self.bob, 'check', 'correct-total', 'pass', a['id'], '--json').stdout)['checks'][0]
        self.share(self.bob)
        for p in self.clones: self.assert_row(p, 'pass', [a, b], eyes=True)
        c = self.submit(self.carol, dict(rule='correct-total', verdict='fail', actor='agent:scripted',
                                         cites=[{'check': b['id']}]))
        self.share(self.carol)
        for p in self.clones: self.assert_row(p, 'fail', [a, b, c])

    def test_same_identity_retry_is_one_check_and_other_people_remain_distinct(self):
        twin = self.clone('alice-laptop', identity='alice')
        request = self.request()
        a = self.submit(self.alice, request)
        duplicate = self.submit(twin, request, time='2026-09-21T12:00:00+0000')
        self.assertEqual(a['id'], duplicate['id'])
        self.assertNotEqual(a['timestamp'], duplicate['timestamp'])
        b = self.submit(self.bob, request)
        self.assertNotEqual(a['id'], b['id'])
        self.share(self.alice)
        original = self.stored(self.remote)[a['id']]
        # Duplicate publication must not block a genuinely new operation.
        (twin / 'laptop.txt').write_text('new operation\n')
        self.sun(twin, 'sync')
        tip = self.tip(twin)
        self.sun(twin, 'push')
        self.assertEqual(self.tip(self.remote), tip)
        self.share(self.bob)
        self.assertEqual(self.stored(self.remote), {a['id']: original, b['id']: b})
        for p in self.clones: self.assert_row(p, 'pass', [a, b])

    def test_csv_checker_uses_cited_snapshots_and_fixes_do_not_rewrite_old_verdicts(self):
        snapshots = []
        for report, expected in [(REPORT, ['pass', 'pass', 'pass']),
                                  (REPORT.replace('quantity: 5', 'quantity: 6'), ['fail', 'pass', 'pass']),
                                  (REPORT.replace('items: 2', 'items: 3'), ['pass', 'fail', 'pass']),
                                  (REPORT + 'TODO: verify numbers\n', ['pass', 'pass', 'fail']),
                                  ('Total quantity: 6\nNumber of items: 3\nTODO: verify numbers\n',
                                   ['fail', 'fail', 'fail']), (REPORT, ['pass', 'pass', 'pass'])]:
            (self.alice / 'report.md').write_text(report)
            self.sun(self.alice, 'sync')
            at = self.tip(self.alice)
            if snapshots:
                for row in self.rows(self.alice)[at].values(): self.assertEqual(row['status'], 'unchecked')
            # The checker reads recorded files, never the current working copy.
            data = self.git(self.alice, 'show', at + ':data.csv')
            text = self.git(self.alice, 'show', at + ':report.md')
            items = list(csv.DictReader(io.StringIO(data)))
            total = int(text.splitlines()[0].split(': ')[1])
            count = int(text.splitlines()[1].split(': ')[1])
            verdicts = ['pass' if result else 'fail' for result in
                        (total == sum(int(r['quantity']) for r in items), count == len(items), 'TODO' not in text)]
            self.assertEqual(verdicts, expected)
            records = [self.submit(self.alice, self.request(v, rule, at)) for rule, v in
                       zip(('correct-total', 'correct-count', 'no-todos'), verdicts)]
            snapshots.append((at, records))
        self.sun(self.alice, 'push')
        # Join histories explicitly; fetching alone never moves Bob's Sun tip.
        self.sun(self.bob, 'push')
        for at, records in snapshots:
            for c in records: self.assert_row(self.bob, c['verdict'], [c], at=at, rule=c['rule'])

    def test_branch_coverage_inherits_only_shared_ancestors(self):
        initial = self.submit(self.alice, self.request())
        self.git(self.alice, 'switch', '-c', 'feature')
        self.sun(self.alice, 'sync')
        self.assert_row(self.alice, 'pass', [initial])
        (self.alice / 'report.md').write_text(REPORT + 'TODO: feature\n')
        self.sun(self.alice, 'sync')
        self.git(self.alice, 'add', 'report.md')
        self.git(self.alice, 'commit', '-m', 'feature report')
        self.sun(self.alice, 'sync')
        feature = self.tip(self.alice, 'feature')
        check = self.submit(self.alice, self.request('fail', 'no-todos', feature))
        self.sun(self.alice, 'push')
        self.git(self.alice, 'switch', 'main')
        self.sun(self.alice, 'sync')
        self.assertNotIn(feature, self.rows(self.alice))
        self.assert_row(self.alice, 'pass', [initial])
        self.git(self.bob, 'fetch', 'origin')
        self.assertEqual(self.stored(self.bob)[check['id']], check)
        self.assertNotIn(feature, self.rows(self.bob))
        (self.alice / 'report.md').write_text(REPORT.replace('quantity: 5', 'quantity: 6'))
        self.sun(self.alice, 'sync')
        main_only = self.tip(self.alice)
        self.assert_row(self.alice, 'unchecked', [], at=main_only, rule='no-todos')
        self.git(self.alice, 'add', 'report.md')
        self.git(self.alice, 'commit', '-m', 'main report')
        self.sun(self.alice, 'sync')
        self.git(self.alice, 'switch', 'feature')
        self.sun(self.alice, 'sync')
        self.assert_row(self.alice, 'fail', [check], at=feature, rule='no-todos')
        self.assertNotIn(main_only, self.rows(self.alice))

    def hook(self, repo, event, **fields):
        payload = dict(cwd=str(repo), hook_event_name=event, session_id='scripted-session', **fields)
        return self.sun(repo, 'hook', data=payload)

    def test_mid_turn_check_keeps_original_snapshot_after_squash_and_sharing(self):
        self.hook(self.alice, 'UserPromptSubmit')
        call = dict(tool_name='Write', tool_use_id='report-edit', tool_input={'file_path': 'report.md'})
        self.hook(self.alice, 'PreToolUse', **call)
        (self.alice / 'report.md').write_text(REPORT + 'TODO: verify\n')
        self.hook(self.alice, 'PostToolUse', **call)
        mid = self.tip(self.alice)
        c = self.submit(self.alice, self.request('fail', 'no-todos', mid))
        call['tool_use_id'] = 'report-fix'
        self.hook(self.alice, 'PreToolUse', **call)
        (self.alice / 'report.md').write_text(REPORT)
        self.hook(self.alice, 'PostToolUse', **call)
        self.hook(self.alice, 'Stop')
        turn = self.tip(self.alice)
        self.assertNotIn(mid, self.git(self.alice, 'rev-list', turn).split())
        self.sun(self.alice, 'push')
        self.sun(self.bob, 'push')
        self.assert_row(self.bob, 'fail', [c], at=turn, rule='no-todos')
        self.assertIn('TODO', self.git(self.bob, 'show', mid + ':report.md'))
        self.assertNotIn('TODO', self.git(self.bob, 'show', turn + ':report.md'))
        self.assertEqual(self.stored(self.bob)[c['id']]['cites'], c['cites'])

    def test_fetch_checks_preserves_dirty_files_index_and_both_heads(self):
        c = self.submit(self.alice, self.request())
        self.sun(self.alice, 'push')
        (self.bob / 'report.md').write_text('staged\n')
        self.git(self.bob, 'add', 'report.md')
        (self.bob / 'report.md').write_text('unstaged\n')
        (self.bob / 'untracked.txt').write_text('untracked\n')
        before = (self.git(self.bob, 'ls-files', '--stage'), self.tip(self.bob),
                  self.git(self.bob, 'rev-parse', 'HEAD'), self.git(self.bob, 'status', '--porcelain'))
        self.git(self.bob, 'fetch', 'origin')
        self.assertEqual(self.stored(self.bob)[c['id']], c)
        self.assertEqual((self.git(self.bob, 'ls-files', '--stage'), self.tip(self.bob),
                          self.git(self.bob, 'rev-parse', 'HEAD'), self.git(self.bob, 'status', '--porcelain')), before)
        self.assertEqual((self.bob / 'report.md').read_text(), 'unstaged\n')
        self.assertEqual((self.bob / 'untracked.txt').read_text(), 'untracked\n')

    def test_checks_and_reviews_leave_synchronized_layer_one_unchanged(self):
        commands = [('log',), ('show', 'HEAD'), ('export',)]
        before = [self.sun(self.alice, *c).stdout for c in commands]
        refs = self.git(self.alice, 'for-each-ref', 'refs/sun/heads/', 'refs/sun/events/', 'refs/sun/ops/')
        c = self.submit(self.alice, self.request())
        self.sun(self.alice, 'check', 'correct-total', 'fail', c['id'])
        self.sun(self.alice, 'coverage', '--json')
        self.assertEqual([self.sun(self.alice, *c).stdout for c in commands], before)
        self.assertEqual(self.git(self.alice, 'for-each-ref', 'refs/sun/heads/', 'refs/sun/events/', 'refs/sun/ops/'), refs)

    def test_actor_boundaries_and_invalid_batch_leave_no_check_refs(self):
        for actor in ('local', 'agent:scripted/local'):
            self.assertNotEqual(self.sun(self.alice, 'check', data=self.request(actor=actor), ok=False).returncode, 0)
        call = dict(tool_name='Bash', tool_use_id='active', tool_input={'command': 'scripted test'})
        self.hook(self.alice, 'PreToolUse', **call)
        self.assertNotEqual(self.sun(self.alice, 'check', 'correct-total', 'pass', ok=False).returncode, 0)
        self.hook(self.alice, 'PostToolUse', **call)
        invalid = self.request(); invalid['cites'] = [{'at': self.initial, 'file': 'missing.csv'}]
        self.assertNotEqual(self.sun(self.alice, 'check', data=[self.request(), invalid], ok=False).returncode, 0)
        self.assertEqual(self.stored(self.alice), {})

    def test_malformed_remote_checks_do_not_hide_valid_checks_or_crash_coverage(self):
        c = self.submit(self.alice, self.request())
        self.sun(self.alice, 'push')
        bad = ['not json', json.dumps({**c, 'verdict': 'tampered'}), json.dumps([c]),
               json.dumps({**c, 'cites': [{'at': []}]})]
        for n, raw in enumerate(bad):
            sha = self.git(self.remote, 'hash-object', '-w', '--stdin', stdin=raw)
            self.git(self.remote, 'update-ref', f'refs/sun/checks/{n:032x}', sha)
        self.git(self.remote, 'update-ref', 'refs/sun/checks/' + 'f' * 32, self.initial)  # commit, not JSON blob
        self.git(self.bob, 'fetch', 'origin')
        self.assert_row(self.bob, 'pass', [c])

    def test_concurrent_process_submissions_keep_distinct_checks_and_deduplicate_retries(self):
        for requests in ((self.request(), self.request('fail')), (self.request(), self.request())):
            processes, gates = [], []
            try:
                for req in requests:
                    read_fd, write_fd = os.pipe()
                    env = dict(self.env, TEST_GATE=str(read_fd))
                    p = subprocess.Popen([sys.executable, '-c', LAUNCH, 'check', '--json'],
                                         cwd=self.alice, env=env, pass_fds=(read_fd,), stdin=subprocess.PIPE,
                                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    os.close(read_fd)
                    p.stdin.write(json.dumps(req)); p.stdin.close(); p.stdin = None
                    processes.append(p); gates.append(write_fd)
                for fd in gates: os.write(fd, b'1'); os.close(fd)
                gates = []
                records = []
                for p in processes:
                    out, err = p.communicate(timeout=15)
                    self.assertEqual(p.returncode, 0, err)
                    records.append(json.loads(out)['checks'][0])
                self.assertEqual(records[0]['id'] == records[1]['id'], requests[0] == requests[1])
                self.assertEqual(len(self.stored(self.alice)), 2)
            finally:
                for fd in gates: os.close(fd)
                for p in processes:
                    if p.poll() is None: p.kill()
                    p.communicate()

    def test_partial_publication_retries_recover_without_misattributing_coverage(self):
        for rejected in ('checks', 'history'):
            with self.subTest(rejected=rejected):
                (self.alice / 'report.md').write_text(REPORT + '# ' + rejected + '\n')
                self.sun(self.alice, 'sync')
                at = self.tip(self.alice)
                c = self.submit(self.alice, self.request(at=at))
                previous = self.tip(self.remote)
                hook = self.remote / 'hooks/update'
                pattern = 'refs/sun/checks/*' if rejected == 'checks' else 'refs/sun/heads/*'
                hook.write_text('#!/bin/sh\ncase "$1" in ' + pattern + ') echo "injected rejection" >&2; exit 1;; esac\n')
                hook.chmod(0o755)
                result = self.sun(self.alice, 'push', ok=False)
                hook.unlink()
                if rejected == 'checks':
                    self.assertEqual(result.returncode, 0, result.stderr)  # Checks never block history.
                    self.assertIn('warning: check upload to origin failed', result.stderr)
                    self.assertIn('injected rejection', result.stderr)
                    self.assertIn('retry `sun push`', result.stderr)
                    self.assertEqual(self.stored(self.alice)[c['id']], c)
                    self.assertEqual(self.tip(self.remote), at)
                    self.assertNotIn(c['id'], self.stored(self.remote))
                else:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(self.tip(self.remote), previous)
                    self.assertEqual(self.stored(self.remote)[c['id']], c)
                    self.git(self.bob, 'fetch', 'origin')
                    pending_rows = self.rows(self.bob)
                    self.assertNotIn(at, pending_rows)
                    self.assertNotIn(c['id'], {check['id'] for rows in pending_rows.values()
                                              for row in rows.values() for check in row['checks']})
                retry = self.sun(self.alice, 'push')
                self.assertNotIn('warning: check upload', retry.stderr)
                self.assertEqual(self.stored(self.remote)[c['id']], c)
                self.sun(self.bob, 'push')
                self.assert_row(self.bob, 'pass', [c], at=at)


if __name__ == '__main__':
    unittest.main()
