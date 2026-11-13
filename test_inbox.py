"""PR transport mocked at GitHub; real Git histories and review coverage."""
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import test_review as fixtures
import test_sun
from sun import cli, git_store, inbox, review_web
from test_sun import run


class InboxTest(unittest.TestCase):
    setUp, tearDown = fixtures.ReviewTest.setUp, fixtures.ReviewTest.tearDown
    git, sun_head, check = fixtures.ReviewTest.git, fixtures.ReviewTest.sun_head, fixtures.ReviewTest.check
    tool_call, agent_turn = test_sun.SunTest.tool_call, test_sun.SunTest.agent_turn
    change, passed = fixtures.ReviewTest.change, fixtures.ReviewTest.passed

    def snapshot(self, evidence=True, stale=False):
        self.git('add', '-A')
        self.git('commit', '-m', 'rules baseline')
        base = self.git('rev-parse', 'HEAD').strip()
        self.agent_turn('inbox-session-one', [('a.txt', 'first\n')])
        self.agent_turn('inbox-session-two', [('a.txt', 'checked\n')])
        tip = self.sun_head()
        self.passed(tip)
        self.git('add', 'a.txt')
        self.git('commit', '-m', 'feature')
        head = self.git('rev-parse', 'HEAD').strip()
        if evidence:
            self.git('update-ref', 'refs/sun/reviews/' + head, self.base if stale else tip)
        source = os.getcwd()
        original = inbox.command
        def command(*args, **kwargs):
            args = tuple(source if x.startswith('https://github.com/') else x for x in args)
            return original(*args, **kwargs)
        info = {'headRefOid': head, 'baseRefOid': base,
                'headRepository': {'name': 'repo'}, 'headRepositoryOwner': {'login': 'owner'}}
        pr = {'number': 7, 'repository': {'nameWithOwner': 'owner/repo'}}
        before = self.git('status', '--porcelain')
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(inbox, 'gh', return_value=info), \
                mock.patch.object(inbox, 'command', side_effect=command):
            result = inbox.snapshot(pr, Path(directory) / 'snapshot')
            self.assertFalse((Path(directory) / 'snapshot' / 'a.txt').exists())
            self.assertEqual(os.getcwd(), source)
            self.assertEqual(self.git('status', '--porcelain'), before)
            return result

    def test_exact_published_revision_preserves_checks_and_covered_diff(self):
        data = self.snapshot()
        self.assertEqual(data['items'], [])
        self.assertEqual([x['file'] for x in data['hidden_files']], ['a.txt'])
        self.assertIn('+checked', data['hidden_files'][0]['patch'])
        self.assertEqual(data['coverage']['covered_files'], 1)
        self.assertEqual(data['coverage']['turns'], 2)
        self.assertEqual(data['coverage']['checked_turns'], 1)

    def test_missing_evidence_never_hides_changes(self):
        self.assert_uncovered(self.snapshot(False))

    def test_mismatched_evidence_never_hides_changes(self):
        self.assert_uncovered(self.snapshot(True, True))

    def assert_uncovered(self, data):
        self.assertTrue(data['items'])
        self.assertEqual(data['hidden_files'], [])
        self.assertIsNone(data['coverage']['covered_files'])
        self.assertTrue(data['coverage']['warning'])

    def test_inbox_runs_without_initializing_current_repository(self):
        with tempfile.TemporaryDirectory() as directory:
            old = os.getcwd()
            try:
                os.chdir(directory)
                with mock.patch.object(inbox, 'gh', return_value=[]):
                    self.assertEqual(json.loads(run('review', '--inbox', '--json')), {'prs': []})
                self.assertEqual(os.listdir(directory), [])
            finally:
                os.chdir(old)

    def test_send_existing_pr_requests_review_and_pins_evidence_after_push(self):
        self.git('add', '-A')
        self.git('commit', '-m', 'baseline')
        self.git('remote', 'add', 'origin', 'https://github.com/owner/repo.git')
        calls = []
        def gh(*args):
            if args[0] == 'repo': return {'defaultBranchRef': {'name': 'other-base'}}
            return [{'url': 'https://github.com/owner/repo/pull/7'}]
        with mock.patch.object(inbox, 'gh', side_effect=gh), \
                mock.patch.object(inbox, 'command', side_effect=lambda *a, **k: calls.append(a) or ''), \
                mock.patch.object(inbox.history, 'cmd_push') as push, \
                mock.patch.object(inbox.checks, 'cmd_pr'):
            inbox.send(SimpleNamespace(reviewer=['alice'], base=None, title=None, json=False, update=False, pr=None))
        self.assertEqual(calls[0][:3], ('git', 'push', '-u'))
        self.assertTrue(any('refs/sun/reviews/' in str(c) for c in calls))
        self.assertIn(('gh', 'pr', 'edit', 'https://github.com/owner/repo/pull/7',
                       '--add-reviewer', 'alice'), calls)
        push.assert_called_once()

    def test_inbox_failure_is_preserved_in_json(self):
        pr = {'url': 'https://github.com/owner/repo/pull/7'}
        with mock.patch.object(inbox, 'gh', return_value=[pr]), \
                mock.patch.object(inbox, 'snapshot', side_effect=RuntimeError('private repo unavailable')):
            data = json.loads(run('review', '--inbox', '--json'))
        self.assertEqual(data['prs'][0]['error'], 'private repo unavailable')

    def test_send_new_pr_passes_reviewers_and_title_without_shell_interpolation(self):
        self.git('add', '-A')
        self.git('commit', '-m', 'baseline')
        self.git('remote', 'add', 'origin', 'git@github.com:owner/repo.git')
        calls = []
        def command(*args, **kwargs):
            calls.append(args)
            return 'https://github.com/owner/repo/pull/8' if args[:3] == ('gh', 'pr', 'create') else ''
        args = SimpleNamespace(reviewer=['alice', 'org/team'], base='main', title='Literal $(title)',
                               json=False, update=False, pr=None)
        with mock.patch.object(inbox, 'gh', return_value=[]),                 mock.patch.object(inbox, 'command', side_effect=command),                 mock.patch.object(inbox.history, 'cmd_push'), mock.patch.object(inbox.checks, 'cmd_pr'):
            inbox.send(args)
        create = next(c for c in calls if c[:3] == ('gh', 'pr', 'create'))
        self.assertIn('Literal $(title)', create)
        self.assertEqual(create.count('--reviewer'), 2)
        self.assertIn('owner/repo', create)

    def test_send_cli_dispatch_and_dirty_checkout_refusal(self):
        with mock.patch.object(inbox, 'send') as send:
            run('pr', 'send', '--reviewer', 'alice')
        self.assertEqual(send.call_args[0][0].reviewer, ['alice'])
        self.git('remote', 'add', 'origin', 'https://github.com/owner/repo.git')
        args = SimpleNamespace(reviewer=['alice'], base='other-base', title=None,
                               json=False, update=False, pr=None)
        with mock.patch.object(inbox, 'gh', return_value=[]), mock.patch.object(inbox, 'command') as command:
            with self.assertRaisesRegex(SystemExit, 'Commit or stash'):
                inbox.send(args)
        command.assert_not_called()
