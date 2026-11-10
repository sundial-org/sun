"""Coverage navigation uses real Sun commits and check records, without a terminal."""
import contextlib
import unittest
from unittest import mock

from sun import checks, coverage_tui, git_store
import test_checks as fixtures
from test_sun import run, write


class CoverageTuiTest(unittest.TestCase):
    setUp, tearDown = fixtures.ChecksTest.setUp, fixtures.ChecksTest.tearDown
    git, sun_head = fixtures.ChecksTest.git, fixtures.ChecksTest.sun_head
    check = fixtures.ChecksTest.check

    def browser(self):
        return coverage_tui.Browser(checks.coverage(), '')

    def test_drilldown_loads_diff_only_on_request_and_preserves_selection(self):
        H = self.sun_head()
        self.check(rule='honest', verdict='pass', actor='program:test', cites=[{'at': H, 'file': 'RULES', 'lines': [2, 2]}])
        browser = self.browser()
        self.assertIn('missing or outdated', browser.rows()[0][0])
        browser.open()  # gaps
        browser.open()  # commit
        self.assertEqual(browser.page, ('commit', H))
        self.assertFalse(browser.diffs)
        browser.selected = next(i for i, r in enumerate(browser.rows()) if r[0].startswith('honest:'))
        browser.open()
        self.assertIn('RULES:2-2', '\n'.join(r[0] for r in browser.rows()))
        browser.selected = len(browser.rows()) - 1
        browser.open()
        self.assertIn('honest:', '\n'.join(r[0] for r in browser.rows()))
        self.assertIn(H, browser.diffs)
        browser.back()
        self.assertEqual(browser.page[0], 'rule')
        self.assertEqual(browser.selected, len(browser.rows()) - 1)

    def test_superseded_and_outdated_failures_do_not_request_revision(self):
        H = self.sun_head()
        failed, = self.check(rule='honest', verdict='fail', actor='program:test', cites=[{'at': H}])
        self.assertTrue(coverage_tui.needs_revision(self.browser().commits[H]))
        self.check(verdict='pass', actor='agent:reviewer', cites=[{'check': failed['id']}])
        self.assertFalse(coverage_tui.needs_revision(self.browser().commits[H]))
        self.check(rule='tidy', verdict='fail', actor='program:test', cites=[{'at': H}])
        write('RULES', 'honest: The report lists what was proved.\ntidy: A changed rule.\n')
        run('sync')
        self.assertFalse(coverage_tui.needs_revision(self.browser().commits[H]))

    def test_join_retains_both_parents_without_inheriting_checks(self):
        H = self.sun_head()
        self.check(rule='honest', verdict='pass', actor='program:test', cites=[{'at': H}])
        tree = self.git('rev-parse', H + '^{tree}').strip()
        other = self.git('commit-tree', tree, '-p', H, '-m', 'other session').strip()
        join = self.git('commit-tree', tree, '-p', H, '-p', other, '-m', 'join').strip()
        self.git('update-ref', git_store.shadow_ref(), join)
        data = checks.coverage()
        row = next(c for c in data if c['commit'] == join)
        self.assertEqual(row['parents'], [H, other])
        self.assertTrue(all(r['status'] == 'unchecked' for r in row['rules']))
        graph = self.git('log', '--graph', '--format=%H', join)
        browser = coverage_tui.Browser(data, graph)
        browser.page = ('map', None)
        self.assertEqual({r[1][1] for r in browser.rows() if r[1]}, {c['commit'] for c in data})
        browser.page = ('diff', join)
        self.assertEqual(browser.rows()[0][0], 'No tree changes against first parent.')

    def test_cli_releases_lock_before_opening_terminal(self):
        held = []
        original = git_store.lock
        @contextlib.contextmanager
        def lock():
            with original():
                held.append(True)
                try: yield
                finally: held.pop()
        def wrapper(fn, browser):
            self.assertFalse(held)
            self.assertTrue(browser.commits)
            self.assertIn('Commit map', '\n'.join(r[0] for r in browser.rows()))
        with mock.patch.object(git_store, 'lock', lock), mock.patch('sys.stdin.isatty', return_value=True), \
                mock.patch('sys.stdout.isatty', return_value=True), mock.patch('curses.wrapper', side_effect=wrapper) as opened:
            run('coverage', '--tui')
        opened.assert_called_once()

    def test_nonterminal_is_actionable_and_json_remains_available(self):
        with self.assertRaisesRegex(SystemExit, 'sun coverage --json'):
            run('coverage', '--tui')
        self.assertIn('parents', run('coverage', '--json'))
        with self.assertRaises(SystemExit): run('coverage', '--tui', '--json')

    def test_terminal_navigation_and_empty_history(self):
        class Screen:
            def __init__(self):
                self.keys = iter([10, 10, 27, ord('q')])
                self.writes = []
            def keypad(self, enabled): pass
            def erase(self): pass
            def getmaxyx(self): return 22, 100
            def addnstr(self, y, x, text, width, attr=0): self.writes.append(text[:width])
            def refresh(self): pass
            def getch(self): return next(self.keys)
        screen = Screen()
        with mock.patch('curses.curs_set'):
            coverage_tui.tui(screen, self.browser())
        self.assertIn('sun coverage / commit', '\n'.join(screen.writes))
        empty = coverage_tui.Browser([], '')
        empty.open()
        self.assertEqual(empty.rows(), [('None in loaded history.', None)])
