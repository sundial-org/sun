"""Exercise automatic PR updates with real Git and a local GitHub CLI stub."""

import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import test_sun as fixtures
from test_sun import run, write, read
from sun import git_store, integration


class PrIntegrationTest(unittest.TestCase):
    setUp_base, tearDown = fixtures.SunTest.setUp, fixtures.SunTest.tearDown
    git, sun_head = fixtures.SunTest.git, fixtures.SunTest.sun_head

    def setUp(self):
        self.setUp_base()
        write("RULES.md", "## tidy\nNo stray files.\n")
        self.git("add", ".")
        self.git("commit", "-qm", "rules and hooks")
        run("sync")
        self.bin = tempfile.TemporaryDirectory()
        self.addCleanup(self.bin.cleanup)
        self.state_path = os.path.join(self.bin.name, "state.json")
        write(self.state_path, json.dumps({"calls": [], "prs": [], "body": "User description\n\nKeep this text."}))
        executable = os.path.join(self.bin.name, "gh")
        write(executable, "#!/bin/sh\nexec " + shlex.quote(sys.executable) + " " + shlex.quote(executable + ".py") + ' "$@"\n')
        os.chmod(executable, 0o755)
        write(executable + ".py", r'''
import datetime, json, os, subprocess, sys
path = os.environ['SUN_TEST_GH_STATE']
with open(path) as f: state = json.load(f)
args = sys.argv[1:]
state['calls'].append(args)
action = next((name for name in ('create', 'list', 'view', 'edit') if name in args), '')
if os.environ.get('SUN_TEST_GH_FAIL') == action:
    with open(path, 'w') as f: json.dump(state, f)
    print('injected gh failure', file=sys.stderr)
    sys.exit(7)
if action == 'create' and '--dry-run' not in args and '--web' not in args:
    branch = subprocess.check_output(['git', 'branch', '--show-current'], text=True).strip()
    sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    state['prs'].append(dict(url='https://github.com/team/repo/pull/12', headRefName=branch,
        headRefOid=sha, createdAt=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        baseRefName=branch, headRepositoryOwner={'login': 'team'}, isCrossRepository=False))
    print(state['prs'][-1]['url'])
elif action == 'list': print(json.dumps(state['prs']))
elif action == 'view': print(state['body'])
elif action == 'edit': state['body'] = sys.stdin.read()
with open(path, 'w') as f: json.dump(state, f)
''')
        env = mock.patch.dict(os.environ, {"PATH": self.bin.name + os.pathsep + os.environ["PATH"],
                                          "SUN_TEST_GH_STATE": self.state_path})
        env.start()
        self.addCleanup(env.stop)

    def state(self):
        return json.loads(read(self.state_path))

    def wrapped(self, *args):
        return subprocess.run([sys.executable, "-m", "sun", *args], capture_output=True, text=True)

    def test_create_targets_new_pr_preserves_body_and_does_not_sync_dirty_files(self):
        before = self.sun_head()
        state = self.state()
        state['prs'] = [dict(url='https://github.com/team/repo/pull/11',
                            headRefName=self.git('branch', '--show-current').strip(),
                            headRefOid=git_store.ref_oid('HEAD'), createdAt='2000-01-01T00:00:00Z',
                            baseRefName='main', headRepositoryOwner={'login': 'team'}, isCrossRepository=False)]
        write(self.state_path, json.dumps(state))
        write("private-draft.txt", "not recorded\n")
        result = self.wrapped("gh", "-R", "team/repo", "pr", "create", "--title", "Example", "--body", "Description")
        self.assertEqual(result.returncode, 0, result.stderr)
        state = self.state()
        self.assertIn("https://github.com/team/repo/pull/12", result.stdout)
        self.assertTrue(state['body'].startswith("User description\n\nKeep this text."))
        self.assertIn("## Checks recorded by sun", state['body'])
        self.assertIn("https://github.com/team/repo/pull/12", next(c for c in state['calls'] if 'edit' in c))
        self.assertIn("team/repo", next(c for c in state['calls'] if 'list' in c))
        self.assertEqual(self.sun_head(), before)
        self.assertNotIn("private-draft", state['body'])
        integration.refresh_prs()
        self.assertEqual(self.state()['body'].count("<!-- sun -->"), 1)

    def test_create_opt_out_dry_run_failure_and_unrelated_commands_do_not_update(self):
        for args, failure, code in [
            (["pr", "create", "--no-sun-pr"], "", 0),
            (["pr", "create", "--dry-run"], "", 0),
            (["pr", "create", "--web"], "", 0),
            (["pr", "create"], "create", 7),
            (["pr", "view"], "", 0),
        ]:
            with self.subTest(args=args), mock.patch.dict(os.environ, {"SUN_TEST_GH_FAIL": failure}):
                previous = len(self.state()['calls'])
                result = self.wrapped("gh", *args)
                self.assertEqual(result.returncode, code, result.stderr)
                calls = self.state()['calls'][previous:]
                self.assertEqual(len(calls), 1, calls)
                self.assertNotIn("--no-sun-pr", calls[0])

    def test_update_failure_does_not_fail_create_and_nonmatching_head_is_not_updated(self):
        with mock.patch.dict(os.environ, {"SUN_TEST_GH_FAIL": "edit"}):
            result = self.wrapped("gh", "pr", "create")
        self.assertEqual(result.returncode, 0)
        self.assertIn("automatic PR coverage update failed", result.stderr)
        state = self.state()
        state['prs'][0]['headRefOid'] = '0' * 40
        state['calls'] = []
        write(self.state_path, json.dumps(state))
        integration.refresh_prs()
        self.assertEqual([c[1] for c in self.state()['calls']], ['list'])

    def test_push_updates_existing_pr_and_opt_out_still_publishes_sun_history(self):
        self.assertEqual(self.wrapped("gh", "pr", "create", "--no-sun-pr").returncode, 0)
        with tempfile.TemporaryDirectory() as bare:
            self.git("init", "--bare", "-q", bare)
            self.git("remote", "add", "origin", bare)
            branch = self.git("branch", "--show-current").strip()
            result = self.wrapped("git", "push", "-u", "origin", branch)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("<!-- sun -->", self.state()['body'])
            calls = len(self.state()['calls'])
            write("recorded.txt", "new operation\n")
            run("sync")
            tip = self.sun_head()
            result = self.wrapped("git", "push", "--no-sun-pr")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(len(self.state()['calls']), calls)
            self.assertEqual(self.git("--git-dir", bare, "rev-parse", "refs/sun/heads/" + branch).strip(), tip)
            self.assertNotEqual(self.wrapped("git", "push", "missing-remote").returncode, 0)
            self.assertEqual(len(self.state()['calls']), calls)

    def test_shell_flags_are_independent(self):
        self.assertEqual(run("shell-init", "--no-gh-pr").splitlines(), [
            'git() { command sun git "$@"; }', 'gh() { command sun gh --no-sun-pr "$@"; }'])
        self.assertEqual(run("shell-init", "--no-git-pr").splitlines(), [
            'git() { command sun git --no-sun-pr "$@"; }', 'gh() { command sun gh "$@"; }'])


if __name__ == "__main__": unittest.main()
