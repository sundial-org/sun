"""Review only the current diff, carrying file checks across unrelated turns."""
import contextlib
import json
import os
import unittest
from unittest import mock

import test_checks as fixtures
from sun import checks, cli, git_store, review
from test_sun import run, write


class ReviewTest(unittest.TestCase):
    tearDown = fixtures.ChecksTest.tearDown
    git, sun_head, check = fixtures.ChecksTest.git, fixtures.ChecksTest.sun_head, fixtures.ChecksTest.check

    def setUp(self):
        fixtures.ChecksTest.setUp(self)
        self.base = self.sun_head()

    def change(self, text='current\n', path='a.txt'):
        write(path, text)
        run('sync')
        return self.sun_head()

    def data(self):
        return review.review_data(self.base)

    def passed(self, H, file=None, **extra):
        return self.check(rule='honest', verdict='pass', actor='program:test',
                          cites=[{'at': H, **({'file': file} if file else {}), **extra}])

    def test_current_diff_contains_each_file_once_and_no_intermediate_code(self):
        self.change('obsolete intermediate version\n')
        self.change('current version\n')
        item, = self.data()['items']
        self.assertEqual(item['file'], 'a.txt')
        self.assertNotIn('obsolete', item['patch'])
        self.assertIn('+current version', item['patch'])
        self.assertIn('No check', item['reason'])
        os.unlink('a.txt')
        run('sync')
        self.assertEqual(self.data()['files'], 0)  # transient file isn't part of the current diff

    def test_later_turn_check_covers_earlier_file_changes(self):
        self.change()
        later = self.change('other\n', 'b.txt')
        self.passed(later, 'a.txt')
        data = self.data()
        self.assertEqual([i['file'] for i in data['items']], ['b.txt'])
        self.assertEqual([i['file'] for i in data['hidden_files']], ['a.txt'])

    def test_checked_file_stays_hidden_across_unrelated_turns_then_returns_when_edited(self):
        H = self.change()
        self.passed(H)
        self.change('other\n', 'b.txt')
        self.assertEqual([i['file'] for i in self.data()['items']], ['b.txt'])
        self.change('changed again\n')
        item = next(i for i in self.data()['items'] if i['file'] == 'a.txt')
        self.assertIn('changed since', item['reason'])
        self.assertIn('+changed again', item['patch'])

    def test_partial_checks_keep_the_whole_file_diff_with_reason(self):
        H = self.change('one\ntwo\n')
        self.passed(H, 'a.txt', lines=[1, 1])
        item, = self.data()['items']
        self.assertIn('Only part', item['reason'])
        self.assertIn('+one', item['patch'])
        self.assertIn('+two', item['patch'])

    def test_conflicting_current_check_keeps_file_visible(self):
        H = self.change()
        self.passed(H)
        self.check(rule='tidy', verdict='fail', actor='agent:judge', cites=[{'at': H, 'file': 'a.txt'}])
        item, = self.data()['items']
        self.assertIn('nonpassing', item['reason'])

    def test_updated_rule_makes_existing_check_stale(self):
        H = self.change()
        self.passed(H)
        write('RULES', 'honest: New criteria.\ntidy: No stray files.\n')
        item, = self.data()['items']
        self.assertIn('definition changed', item['reason'])

    def test_review_inherits_scope_and_supersedes_failure(self):
        H = self.change()
        failed, = self.check(rule='honest', verdict='fail', actor='program:test', cites=[{'at': H}])
        self.check(verdict='pass', actor='agent:reviewer', cites=[{'check': failed['id']}])
        self.assertEqual(self.data()['items'], [])

    def test_rule_filter_limits_whole_commit_check(self):
        write('RULES.md', '## limited\n---\nfiles: a.txt\n---\nCheck A.\n')
        self.change()
        H = self.change('b\n', 'b.txt')
        self.check(rule='limited', verdict='pass', actor='program:test', cites=[{'at': H}])
        paths = {i['file'] for i in self.data()['items']}
        self.assertNotIn('a.txt', paths)
        self.assertIn('b.txt', paths)

    def test_deletion_is_not_hidden_by_a_check_before_the_file_existed(self):
        self.passed(self.base)
        self.base = self.change()
        os.unlink('a.txt')
        run('sync')
        item, = self.data()['items']
        self.assertIn('deleted file mode', item['patch'])
        self.passed(self.sun_head())
        self.assertEqual(self.data()['items'], [])

    def test_mode_change_invalidates_file_check(self):
        H = self.change()
        self.base = H
        self.passed(H)
        os.chmod('a.txt', 0o755)
        run('sync')
        item, = self.data()['items']
        self.assertIn('changed since', item['reason'])
        self.assertIn('new mode', item['patch'])

    def test_unrelated_branch_check_cannot_hide_identical_file(self):
        H = self.change()
        self.passed(H)
        self.git('update-ref', git_store.shadow_ref(), self.base)
        write('b.txt', 'different branch\n')
        run('sync')
        self.assertNotEqual(H, self.sun_head())
        self.assertIn('a.txt', {i['file'] for i in self.data()['items']})

    def test_default_base_is_git_branch_merge_base(self):
        self.git('branch', '-M', 'main')
        expected = self.git('rev-parse', 'HEAD').strip()
        self.git('checkout', '-b', 'experiment')
        write('committed.txt', 'branch change\n')
        self.git('add', 'committed.txt')
        self.git('commit', '-m', 'branch work')
        self.change('uncommitted\n')
        data = json.loads(run('review', '--json'))
        self.assertEqual(data['base'], expected)
        self.assertIn('committed.txt', {i['file'] for i in data['items']})
        self.assertIn('a.txt', {i['file'] for i in data['items']})

    def test_vim_shows_current_diff_and_reason_without_changing_source_or_checks(self):
        self.change()
        item, = self.data()['items']
        before, paths = checks.checks(), []
        def launch(args):
            self.assertIn('set nomodeline noexrc', args)
            self.assertIn('-M', args)
            self.assertIn('syntax on', args)
            paths.append(args[-1])
            with open(args[-1]) as f: text = f.read()
            self.assertIn('Why: No check', text)
            self.assertIn('+current', text)
            return mock.Mock(returncode=0)
        with mock.patch('shutil.which', return_value='/usr/bin/vim'), mock.patch('subprocess.run', side_effect=launch):
            self.assertEqual(review.open_vim(item), '')
        self.assertFalse(os.path.exists(paths[0]))
        self.assertEqual(checks.checks(), before)
        with open('a.txt') as f: self.assertEqual(f.read(), 'current\n')

    def test_queue_releases_lock_before_terminal(self):
        self.change()
        held, original = [], git_store.lock
        @contextlib.contextmanager
        def lock():
            with original():
                held.append(True)
                try: yield
                finally: held.pop()
        def wrapper(fn, data):
            self.assertFalse(held)
            self.assertTrue(data['items'])
        with mock.patch.object(git_store, 'lock', lock), mock.patch('sys.stdin.isatty', return_value=True), \
                mock.patch('sys.stdout.isatty', return_value=True), mock.patch('curses.wrapper', side_effect=wrapper):
            cli.main(['review', '--base', self.base])
        with self.assertRaisesRegex(SystemExit, 'review --json'): run('review')
