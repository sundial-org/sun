"""The focused reviewer must omit checked content without hiding unproved changes."""
import contextlib
import json
import os
import unittest
from unittest import mock

import test_checks as fixtures
from sun import checks, cli, git_store, review
from test_sun import run, write


class ReviewTest(unittest.TestCase):
    setUp, tearDown = fixtures.ChecksTest.setUp, fixtures.ChecksTest.tearDown
    git, sun_head, check = fixtures.ChecksTest.git, fixtures.ChecksTest.sun_head, fixtures.ChecksTest.check

    def change(self, text='one\ntwo\nthree\n', path='a.txt'):
        write(path, text)
        run('sync')
        return self.sun_head()

    def items(self):
        return review.review_data(1)['items']

    def test_whole_commit_pass_hides_changes_and_descendant_does_not_inherit(self):
        H = self.change()
        self.check(rule='honest', verdict='pass', actor='program:test', cites=[{'at': H}])
        data = json.loads(run('review', '--json', '-n', '1'))
        self.assertEqual(data['items'], [])
        self.assertEqual((data['hidden_files'], data['hidden_lines']), (1, 3))
        self.change('one\ntwo\nchanged\n')
        self.assertIn('changed', '\n'.join(self.items()[0]['lines']))

    def test_line_scope_omits_only_checked_additions_and_keeps_deletions(self):
        self.change('old one\nold two\nold three\n')
        H = self.change()
        self.check(rule='honest', verdict='pass', actor='agent:judge',
                   cites=[{'at': H, 'file': 'a.txt', 'lines': [2, 2]}])
        item, = self.items()
        self.assertEqual((item['hidden'], item['remaining']), (1, 5))
        rendered = review.vim_text(item)
        self.assertNotIn('+      2 | two', rendered)
        self.assertIn('-      2 | old two', rendered)
        self.assertIn('+      1 | one', rendered)
        self.assertIn('+      3 | three', rendered)

    def test_conflicting_line_check_overrides_whole_commit_pass(self):
        H = self.change()
        self.check(rule='honest', verdict='pass', actor='program:test', cites=[{'at': H}])
        self.check(rule='tidy', verdict='fail', actor='agent:judge',
                   cites=[{'at': H, 'file': 'a.txt', 'lines': [2, 2]}])
        item, = self.items()
        self.assertEqual((item['hidden'], item['remaining']), (2, 1))
        self.assertIn('+      2 | two', '\n'.join(item['lines']))
        self.assertNotIn('+      1 | one', '\n'.join(item['lines']))

    def test_changed_rule_no_longer_hides_changes(self):
        H = self.change()
        self.check(rule='honest', verdict='pass', actor='program:test', cites=[{'at': H}])
        self.assertEqual(self.items(), [])
        write('RULES', 'honest: Different criteria.\ntidy: No stray files.\n')
        self.assertTrue(self.items())  # rule hash differs, even before another snapshot

    def test_review_inherits_scope_but_replacement_runner_uses_new_direct_scope(self):
        H = self.change()
        previous, = self.check(rule='honest', verdict='fail', actor='program:test', cites=[{'at': H}])
        passed, = self.check(verdict='pass', actor='agent:reviewer', cites=[{'check': previous['id']}])
        self.assertEqual(self.items(), [])
        self.check(rule='honest', verdict='pass', actor='program:test', cites=[
            {'at': H, 'file': 'a.txt', 'lines': [1, 1]}, {'check': passed['id']}])
        item, = self.items()
        self.assertEqual(item['hidden'], 1)
        self.assertEqual(item['remaining'], 2)

    def test_whole_commit_check_respects_rule_file_filter(self):
        write('RULES.md', '## limited\n---\nfiles: a.txt\n---\nCheck A.\n')
        write('a.txt', 'a\n')
        H = self.change('b\n', 'b.txt')
        self.check(rule='limited', verdict='pass', actor='program:test', cites=[{'at': H}])
        paths = {item['file'] for item in self.items()}
        self.assertNotIn('a.txt', paths)
        self.assertIn('b.txt', paths)

    def test_binary_and_deletion_changes_require_file_or_commit_scope(self):
        with open('blob.bin', 'wb') as f: f.write(b'\0binary')
        run('sync')
        H = self.sun_head()
        self.check(rule='honest', verdict='pass', actor='program:test', cites=[{'at': H, 'file': 'blob.bin', 'lines': [1, 1]}])
        self.assertTrue(self.items())
        self.check(rule='tidy', verdict='pass', actor='program:test', cites=[{'at': H, 'file': 'blob.bin'}])
        self.assertEqual(self.items(), [])
        os.unlink('blob.bin')
        run('sync')
        H = self.sun_head()
        self.assertTrue(self.items())
        self.check(rule='honest', verdict='pass', actor='program:test', cites=[{'at': H}])
        self.assertEqual(self.items(), [])

    def test_vim_gets_only_filtered_text_and_leaves_files_and_checks_untouched(self):
        H = self.change()
        self.check(rule='honest', verdict='pass', actor='program:test', cites=[{'at': H, 'file': 'a.txt', 'lines': [2, 2]}])
        item, = self.items()
        before = checks.checks()
        paths = []
        def launch(args):
            self.assertIn('set nomodeline noexrc', args)
            self.assertIn('-M', args)
            paths.append(args[-1])
            with open(args[-1]) as f: text = f.read()
            self.assertNotIn('+      2 | two', text)
            self.assertIn('+      1 | one', text)
            return mock.Mock(returncode=0)
        with mock.patch('shutil.which', return_value='/usr/bin/vim'), mock.patch('subprocess.run', side_effect=launch):
            self.assertEqual(review.open_vim(item), '')
        self.assertFalse(os.path.exists(paths[0]))
        self.assertEqual(checks.checks(), before)
        with open('a.txt') as f: self.assertEqual(f.read(), 'one\ntwo\nthree\n')

    def test_queue_releases_lock_before_terminal_and_vim(self):
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
            cli.main(['review', '-n', '1'])
        with self.assertRaisesRegex(SystemExit, 'review --json'): run('review')

    def test_hunk_context_and_snapshot_citations_do_not_hide_or_leak_content(self):
        patch = '@@ -0,0 +1,2 @@ secret already checked context\n+checked\n+remaining\n'
        result = review.excerpt(patch, [('check', True, [1, 1])])
        self.assertNotIn('checked', '\n'.join(result['lines']))
        self.assertIn('remaining', '\n'.join(result['lines']))
        c = {'id': 'c', 'verdict': 'pass', 'cites': [{'at': 'intermediate'}]}
        commit = {'commit': 'final', 'rules': [{'rule': 'r', 'checks': [c], 'outdated': []}]}
        self.assertEqual(review.file_scopes(commit, 'a.txt', {'c': c}, {'r': {'files': []}}), [])

    def test_ambiguous_negative_scope_blocks_hiding_and_newline_markers_survive(self):
        c = {'id': 'c', 'verdict': 'fail', 'cites': [{'at': 'H', 'file': 'a', 'lines': [3, 1]}]}
        commit = {'commit': 'H', 'rules': [{'rule': 'r', 'checks': [c], 'outdated': []}]}
        scopes = review.file_scopes(commit, 'a', {'c': c}, {'r': {'files': []}})
        self.assertEqual(review.covering(scopes + [('pass', True, None)], 1), set())
        patch = '@@ -0,0 +1 @@\n+remaining\n' + chr(92) + ' No newline at end of file\n'
        self.assertIn('No newline', '\n'.join(review.excerpt(patch, [])['lines']))
        self.assertEqual(review.excerpt(patch, [('p', True, None)])['lines'], [])
