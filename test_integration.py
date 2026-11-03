"""Real Git transport tests for the optional shell wrapper."""

import os
import subprocess
import sys
import tempfile
import unittest

import test_sun as fixtures
from test_sun import run, write, read


class IntegrationTest(unittest.TestCase):
    setUp, tearDown = fixtures.SunTest.setUp, fixtures.SunTest.tearDown
    git, sun_head = fixtures.SunTest.git, fixtures.SunTest.sun_head

    def wrapped(self, directory, *args, check=True):
        result = subprocess.run([sys.executable, "-m", "sun", "git", "-C", directory, *args],
                                capture_output=True, text=True)
        if check:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertNotIn("automatic Git integration failed", result.stderr)
            self.assertNotIn("was not published", result.stderr)
            self.assertNotIn("Sun history was not joined", result.stderr)
        return result

    def remote(self, directory):
        bare = os.path.join(directory, "remote.git")
        self.git("init", "--bare", "-q", bare)
        self.git("remote", "add", "origin", bare)
        self.git("add", ".")
        self.git("commit", "-qm", "track hooks")
        run("sync")
        branch = self.git("branch", "--show-current").strip()
        self.wrapped(self.dir, "push", "-u", "origin", branch)
        return bare, branch

    def test_up_to_date_push_publishes_sun_only_edits(self):
        with tempfile.TemporaryDirectory() as temp:
            bare, branch = self.remote(temp)
            write("README.md", "recorded but not Git committed\n")
            run("sync")
            tip = self.sun_head()
            normal = self.git("rev-parse", "HEAD")
            result = self.wrapped(self.dir, "push")
            self.assertIn("[up to date]", result.stdout)
            self.assertEqual(self.git("--git-dir", bare, "rev-parse", "refs/sun/heads/" + branch).strip(), tip)
            self.assertEqual(self.git("rev-parse", "HEAD"), normal)

    def test_noop_pull_initializes_clone_and_joins_divergent_sun_history(self):
        with tempfile.TemporaryDirectory() as temp:
            bare, branch = self.remote(temp)
            clone = os.path.join(temp, "clone")
            self.git("clone", "-q", "-b", branch, bare, clone)
            self.wrapped(clone, "pull", "--ff-only")
            cfg = os.path.join(clone, ".git", "sun", "config.json")
            self.assertTrue(os.path.exists(cfg))
            self.assertIn('"share_sessions": false', read(cfg))
            write(os.path.join(clone, "local.txt"), "local only\n")
            subprocess.run([sys.executable, "-m", "sun", "sync"], cwd=clone,
                           capture_output=True, check=True)
            local = self.git("-C", clone, "rev-parse", "refs/sun/heads/" + branch).strip()
            write("remote.txt", "remote Sun only\n")
            run("sync")
            remote = self.sun_head()
            run("push")
            self.wrapped(clone, "pull", "--ff-only")
            joined = self.git("-C", clone, "rev-parse", "refs/sun/heads/" + branch).strip()
            parents = self.git("-C", clone, "show", "-s", "--format=%P", joined).split()
            self.assertEqual(parents, [local, remote])
            self.assertEqual(self.git("-C", clone, "rev-parse", joined + "^{tree}"),
                             self.git("-C", clone, "rev-parse", local + "^{tree}"))
            self.assertFalse(os.path.exists(os.path.join(clone, "remote.txt")))
            log = subprocess.run([sys.executable, "-m", "sun", "log", "-n", "100"],
                                 cwd=clone, capture_output=True, text=True, check=True).stdout
            self.assertIn(remote[:7], log)

    def test_push_destination_name_and_dry_run(self):
        with tempfile.TemporaryDirectory() as temp:
            bare, branch = self.remote(temp)
            write("README.md", "new Sun snapshot\n")
            run("sync")
            tip = self.sun_head()
            self.wrapped(self.dir, "push", "--dry-run", "origin", branch + ":preview")
            self.assertEqual(self.git("--git-dir", bare, "for-each-ref", "--format=%(refname)",
                                      "refs/sun/heads/preview"), "")
            self.wrapped(self.dir, "push", "origin", branch + ":published")
            self.assertEqual(self.git("--git-dir", bare, "rev-parse", "refs/sun/heads/published").strip(), tip)

    def test_failed_pull_does_not_join_remote_sun_history(self):
        with tempfile.TemporaryDirectory() as temp:
            bare, branch = self.remote(temp)
            clone = os.path.join(temp, "clone")
            self.git("clone", "-q", "-b", branch, bare, clone)
            self.wrapped(clone, "pull", "--ff-only")
            self.git("-C", clone, "commit", "--allow-empty", "-qm", "local divergence")
            before = self.git("-C", clone, "rev-parse", "refs/sun/heads/" + branch)
            write("README.md", "remote divergence\n")
            self.git("add", "README.md")
            self.git("commit", "-qm", "remote divergence")
            run("sync")
            self.wrapped(self.dir, "push")
            result = self.wrapped(clone, "pull", "--ff-only", check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self.git("-C", clone, "rev-parse", "refs/sun/heads/" + branch), before)

    def test_first_push_initializes_plain_repo(self):
        with tempfile.TemporaryDirectory() as temp:
            bare = os.path.join(temp, "bare.git")
            clone = os.path.join(temp, "plain")
            self.git("init", "--bare", "-q", bare)
            self.git("init", "-q", clone)
            self.git("-C", clone, "commit", "--allow-empty", "-qm", "initial")
            self.git("-C", clone, "remote", "add", "origin", bare)
            branch = self.git("-C", clone, "branch", "--show-current").strip()
            self.wrapped(clone, "push", "--dry-run", "origin", branch)
            self.assertFalse(os.path.exists(os.path.join(clone, ".git", "sun", "config.json")))
            self.wrapped(clone, "-c", "user.name=wrapper user", "push", "-u", "origin", branch)
            self.assertTrue(os.path.exists(os.path.join(clone, ".git", "sun", "config.json")))
            self.assertTrue(self.git("--git-dir", bare, "rev-parse", "refs/sun/heads/" + branch))

    def test_rebase_pull_joins_history_and_keeps_git_result(self):
        with tempfile.TemporaryDirectory() as temp:
            bare, branch = self.remote(temp)
            clone = os.path.join(temp, "clone")
            self.git("clone", "-q", "-b", branch, bare, clone)
            self.wrapped(clone, "pull", "--ff-only")
            write(os.path.join(clone, "local.txt"), "local committed\n")
            self.git("-C", clone, "add", "local.txt")
            self.git("-C", clone, "commit", "-qm", "local change")
            subprocess.run([sys.executable, "-m", "sun", "sync"], cwd=clone,
                           capture_output=True, check=True)
            write("remote.txt", "remote committed\n")
            self.git("add", "remote.txt")
            self.git("commit", "-qm", "remote change")
            run("sync")
            remote = self.sun_head()
            self.wrapped(self.dir, "push")
            self.wrapped(clone, "pull", "--rebase", "-n", "origin", branch)
            tip = self.git("-C", clone, "rev-parse", "refs/sun/heads/" + branch).strip()
            self.git("-C", clone, "merge-base", "--is-ancestor", remote, tip)
            self.assertEqual(self.git("-C", clone, "rev-parse", tip + "^{tree}"),
                             self.git("-C", clone, "rev-parse", "HEAD^{tree}"))
            self.assertEqual(read(os.path.join(clone, "local.txt")), "local committed\n")
            self.assertEqual(read(os.path.join(clone, "remote.txt")), "remote committed\n")

    def test_push_uses_push_url_and_head_destination(self):
        with tempfile.TemporaryDirectory() as temp:
            fetch_remote, branch = self.remote(temp)
            push_remote = os.path.join(temp, "push.git")
            self.git("clone", "--bare", "-q", fetch_remote, push_remote)
            self.git("remote", "set-url", "--push", "origin", push_remote)
            write("README.md", "publish to push URL\n")
            run("sync")
            tip = self.sun_head()
            self.wrapped(self.dir, "push", "origin", "HEAD:destination")
            self.assertEqual(self.git("--git-dir", push_remote, "rev-parse", "refs/sun/heads/destination").strip(), tip)
            self.assertEqual(self.git("--git-dir", fetch_remote, "for-each-ref", "--format=%(refname)",
                                      "refs/sun/heads/destination"), "")


if __name__ == "__main__":
    unittest.main()
