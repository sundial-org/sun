"""Exercise real Git hooks, branch creation and independent worktrees."""
import contextlib
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor

import test_sun as fixtures
from test_sun import run, hook, write, read
from sun import branches, git_store, history


class BranchTest(unittest.TestCase):
    setUp, tearDown = fixtures.SunTest.setUp, fixtures.SunTest.tearDown
    git, sun_head, tool_call = fixtures.SunTest.git, fixtures.SunTest.sun_head, fixtures.SunTest.tool_call
    plumbing_commit = fixtures.SunTest.plumbing_commit

    @contextlib.contextmanager
    def at(self, path):
        old = os.getcwd()
        try:
            os.chdir(path)
            yield
        finally:
            os.chdir(old)

    def baseline(self):
        self.git("add", ".")
        self.git("commit", "-qm", "track hook config")
        run("sync")
        return self.sun_head()

    def test_creation_pins_history_before_source_advances(self):
        old = self.baseline()
        self.git("branch", "later")
        self.assertEqual(git_store.ref_oid("refs/sun/heads/later"), old)
        write("README.md", "source advanced\n")
        run("sync")
        advanced = self.sun_head()
        self.git("restore", "README.md")
        self.git("switch", "later")
        self.assertEqual(self.sun_head(), old)
        self.assertNotEqual(self.sun_head(), advanced)
        run("sync")
        self.assertEqual(self.sun_head(), old)

    def test_explicit_local_and_remote_sources_with_identical_git_commits(self):
        local = self.baseline()
        main = self.git("branch", "--show-current").strip()
        write("README.md", "fetched remote Sun state\n")
        remote = self.plumbing_commit(local, ["README.md"])
        self.git("restore", "README.md")
        self.git("update-ref", "refs/remotes/origin/" + main, "HEAD")
        self.git("update-ref", "refs/sun/remotes/origin/" + main, remote)
        # Also leave Sun's last checkout on a different sibling at the same Git SHA.
        self.git("switch", "-c", "sibling")
        write("README.md", "sibling state\n")
        run("sync")
        self.git("branch", "from-local", main)
        self.git("branch", "from-remote", "origin/" + main)
        self.assertEqual(git_store.ref_oid("refs/sun/heads/from-local"), local)
        self.assertEqual(git_store.ref_oid("refs/sun/heads/from-remote"), remote)
        self.git("update-ref", "refs/sun/remotes/origin/" + main, local)
        self.assertEqual(git_store.ref_oid("refs/sun/heads/from-remote"), remote)

    def test_checkout_and_switch_create_named_histories(self):
        tip = self.baseline()
        for command in (("checkout", "-b", "one"), ("switch", "-c", "two")):
            self.git(*command)
            self.assertEqual(self.sun_head(), tip)
            run("log")
            self.assertEqual(self.sun_head(), tip)

    def test_new_worktree_inherits_without_init_and_records_only_actual_edit(self):
        parent = self.baseline()
        # Sun can contain edits Git has not committed; the checkout transition is observed.
        write("README.md", "uncommitted source content\n")
        run("sync")
        source = self.sun_head()
        original_ref = git_store.shadow_ref()
        git_store.save_state("active.json", {"parent-call": {"files": ["README.md"]}})
        git_store.save_state("turns.json", {"parent-turn": {"n": 1}})
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "linked")
            self.git("worktree", "add", "-b", "linked", path)
            with self.at(path):
                self.git("merge-base", "--is-ancestor", source, self.sun_head())
                self.assertEqual(git_store.state("active.json", {}), {})
                self.assertEqual(git_store.state("turns.json", {}), {})
                self.assertEqual(read("README.md"), "hello\n")
                self.assertEqual(self.git("diff", "--cached"), "")
                # A read-only Bash call observes the checkout, but isn't credited for it.
                hook("PreToolUse", tool_name="Bash", tool_use_id="read")
                hook("PostToolUse", tool_name="Bash", tool_use_id="read")
                ev = history.events()[-1]
                self.assertEqual(ev["type"], "observe")
                self.assertEqual(ev["actor"], "unknown")
                self.assertFalse(ev.get("tool_calls"))
                self.tool_call("writer", "README.md", "hello\nactual addition\n")
                patch = history.events()[-1]["edits"][0]["patch"]
                self.assertIn("+actual addition", patch)
                self.assertNotIn("+hello", patch)
                self.assertNotIn("uncommitted source", patch)
            self.assertEqual(git_store.ref_oid(original_ref), source)
            self.assertNotEqual(source, parent)

    def test_existing_branch_and_recreated_worktree_keep_the_same_history(self):
        self.baseline()
        self.git("branch", "existing")
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "linked")
            self.git("worktree", "add", path, "existing")
            with self.at(path):
                self.tool_call("writer", "README.md", "branch state\n")
                tip = self.sun_head()
            self.git("worktree", "remove", "--force", path)
            self.assertEqual(git_store.ref_oid("refs/sun/heads/existing"), tip)
            self.git("worktree", "add", path, "existing")
            with self.at(path): self.git("merge-base", "--is-ancestor", tip, self.sun_head())

    def test_worktree_explicit_source_and_no_checkout(self):
        source = self.baseline()
        main = self.git("branch", "--show-current").strip()
        self.git("switch", "-c", "sibling")
        write("README.md", "sibling only\n")
        run("sync")
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "linked")
            self.git("worktree", "add", "--no-checkout", "-b", "linked", path, main)
            self.assertEqual(git_store.ref_oid("refs/sun/heads/linked"), source)
            with self.at(path):
                self.git("reset", "--hard", "HEAD")
                # Even without post-checkout, CLI and agent hooks bootstrap local state.
                hook("PreToolUse", tool_name="Bash", tool_use_id="read")
                hook("PostToolUse", tool_name="Bash", tool_use_id="read")
                self.assertTrue(os.path.isdir(git_store.sun_dir()))
                self.assertEqual(self.sun_head(), source)

    def test_init_from_linked_worktree_shares_settings(self):
        self.baseline()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "linked")
            self.git("worktree", "add", "-b", "linked", path)
            with self.at(path):
                run("init", "--claude", "--no-instructions", "--no-share-sessions")
                self.assertEqual(git_store.configured_harnesses(), ["claude"])
            self.assertEqual(git_store.configured_harnesses(), ["claude"])

    def test_two_worktrees_write_concurrently_without_mixing_histories(self):
        source = self.baseline()
        with tempfile.TemporaryDirectory() as tmp:
            paths = [os.path.join(tmp, name) for name in ("alice", "bob")]
            for path in paths: self.git("worktree", "add", "-b", os.path.basename(path), path)
            def edit(path):
                write(os.path.join(path, os.path.basename(path) + ".txt"), path)
                return subprocess.run([sys.executable, "-m", "sun", "sync"], cwd=path, capture_output=True, text=True, timeout=30)
            with ThreadPoolExecutor(2) as pool: results = list(pool.map(edit, paths))
            for path, result in zip(paths, results):
                self.assertEqual(result.returncode, 0, result.stderr)
                own = os.path.basename(path)
                other = "alice" if own == "bob" else "bob"
                with self.at(path):
                    self.assertIn(own + ".txt", self.git("ls-tree", "-r", "--name-only", self.sun_head()))
                    self.assertNotIn(other + ".txt", self.git("ls-tree", "-r", "--name-only", self.sun_head()))
                    self.git("merge-base", "--is-ancestor", source, self.sun_head())
            self.assertEqual(self.sun_head(), source)

    def test_recreating_branch_does_not_reuse_its_old_tip(self):
        source = self.baseline()
        main = self.git("branch", "--show-current").strip()
        self.git("switch", "-c", "feature")
        write("README.md", "old feature\n")
        run("sync")
        old = self.sun_head()
        self.git("restore", "README.md")
        self.git("switch", main)
        self.git("branch", "-D", "feature")
        self.git("branch", "feature", main)
        self.assertEqual(git_store.ref_oid("refs/sun/heads/feature"), source)
        self.assertNotEqual(source, old)

    def test_commit_start_point_does_not_guess_from_equal_branches(self):
        source = self.baseline()
        sha = self.git("rev-parse", "HEAD").strip()
        result = subprocess.run(["git", "branch", "explicit-commit", sha], capture_output=True, text=True, check=True)
        tip = git_store.ref_oid("refs/sun/heads/explicit-commit")
        self.assertIn("no recorded Sun source", result.stderr)
        self.assertNotEqual(tip, source)
        self.assertEqual(self.git("rev-list", "--count", tip).strip(), "1")
        self.assertEqual(git_store.ref_oid(tip + "^{tree}"), git_store.ref_oid("HEAD^{tree}"))

    def test_missing_creation_hook_does_not_guess_source(self):
        self.baseline()
        self.git("-c", "core.hooksPath=/dev/null", "branch", "missed")
        self.git("switch", "missed")
        self.assertEqual(self.git("rev-list", "--count", self.sun_head()).strip(), "1")

    def test_custom_hooks_receive_arguments_stdin_and_can_reject_creation(self):
        self.baseline()
        with tempfile.TemporaryDirectory() as custom:
            log = os.path.join(custom, "log")
            refhook = os.path.join(custom, "reference-transaction")
            write(refhook, '#!/bin/sh\nprintf "%s\\n" "$1" >> "' + log + '"\ncat >> "' + log + '"\n')
            os.chmod(refhook, 0o755)
            self.git("config", "core.hooksPath", custom)
            branches.install_hooks()
            branches.install_hooks()  # Re-init must not chain back into itself.
            self.git("branch", "allowed")
            lines = read(log)
            self.assertIn("prepared\n", lines)
            self.assertIn("committed\n", lines)
            self.assertIn("refs/heads/allowed\n", lines)
            write(refhook, '#!/bin/sh\nif [ "$1" = prepared ]; then exit 1; fi\n')
            result = subprocess.run(["git", "branch", "denied"], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(git_store.ref_oid("refs/heads/denied"))
            self.assertFalse(git_store.ref_oid("refs/sun/heads/denied"))
            self.assertEqual(read(refhook), '#!/bin/sh\nif [ "$1" = prepared ]; then exit 1; fi\n')

    def test_relative_hooks_path_and_hooks_added_after_init(self):
        self.baseline()
        write("custom/post-checkout", '#!/bin/sh\nprintf "%s\\n" "$@" > checkout-args\n')
        os.chmod("custom/post-checkout", 0o755)
        self.git("config", "core.hooksPath", "custom")
        branches.install_hooks()
        write("custom/pre-commit", '#!/bin/sh\nexit 42\n')
        os.chmod("custom/pre-commit", 0o755)
        self.git("switch", "-c", "feature")
        self.assertEqual(read("checkout-args").splitlines()[-1], "1")
        result = subprocess.run(["git", "commit", "--allow-empty", "-m", "rejected"], capture_output=True)
        self.assertNotEqual(result.returncode, 0)

    def test_ordinary_commits_keep_existing_unborn_sun_history(self):
        with tempfile.TemporaryDirectory() as tmp, self.at(tmp):
            self.git("init", "-q", "--initial-branch=main")
            run("init", "--no-instructions")
            write("note", "before Git's first commit\n")
            run("sync")
            before = self.sun_head()
            self.git("add", ".")
            self.git("commit", "-qm", "first normal commit")
            self.assertEqual(self.sun_head(), before)

    def test_inherited_operations_survive_later_source_turn_squashing(self):
        self.baseline()
        hook("UserPromptSubmit")
        self.tool_call("session12345", "first.txt", "first\n")
        inherited = self.sun_head()
        event = history.events()[-1]
        self.git("branch", "child")
        self.tool_call("session12345", "second.txt", "second\n", 1)
        hook("Stop")
        self.assertEqual(git_store.ref_oid("refs/sun/heads/child"), inherited)
        child_events = history.events(scope=["refs/sun/heads/child"])
        self.assertIn(event["id"], {e["id"] for e in child_events})
        self.assertEqual(next(e for e in child_events if e["id"] == event["id"])["commit"], inherited)

    def test_main_and_master_are_equally_supported(self):
        for name in ("main", "master"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp, self.at(tmp):
                self.git("init", "-q", "--initial-branch=" + name)
                write("note", "existing\n")
                self.git("add", ".")
                self.git("commit", "-qm", "baseline")
                run("init", "--no-instructions")
                tip = self.sun_head()
                self.git("branch", "child", name)
                self.assertEqual(git_store.ref_oid("refs/sun/heads/child"), tip)

    def test_unborn_creation_finishes_before_an_early_sun_writer(self):
        with tempfile.TemporaryDirectory() as tmp, self.at(tmp):
            self.git("init", "-q", "--initial-branch=main")
            write("note", "already here\n")
            run("init", "--no-instructions")
            source = self.sun_head()
            # A user's committed hook runs before Sun's committed hook. This
            # deterministically exercises a writer entering that same window.
            original = self.git("config", "sun.originalHooksPath").strip()
            script = '#!/bin/sh\ninput=$(cat)\ncase "$1:$input" in committed:*"ref:refs/heads/child HEAD")\n'
            script += 'printf "concurrent\\n" > concurrent.txt\n' + shlex.quote(sys.executable) + ' -m sun sync\n;;\nesac\n'
            write(os.path.join(original, "reference-transaction"), script)
            os.chmod(os.path.join(original, "reference-transaction"), 0o755)
            self.git("switch", "-c", "child")
            self.assertEqual(git_store.ref_oid("refs/sun/heads/main"), source)
            self.assertNotEqual(self.sun_head(), source)
            self.git("merge-base", "--is-ancestor", source, self.sun_head())
            self.assertEqual(self.git("show", self.sun_head() + ":concurrent.txt"), "concurrent\n")
            self.assertFalse(git_store.state("branch-creation.json", {}))

    def test_rejected_unborn_switch_leaves_no_child_history(self):
        with tempfile.TemporaryDirectory() as tmp, self.at(tmp):
            self.git("init", "-q", "--initial-branch=main")
            run("init", "--no-instructions")
            source = self.sun_head()
            original = self.git("config", "sun.originalHooksPath").strip()
            path = os.path.join(original, "reference-transaction")
            write(path, '#!/bin/sh\ninput=$(cat)\ncase "$1:$input" in prepared:*"ref:refs/heads/child HEAD") exit 1;; esac\n')
            os.chmod(path, 0o755)
            result = subprocess.run(["git", "switch", "-c", "child"], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self.sun_head(), source)
            self.assertFalse(git_store.ref_oid("refs/sun/heads/child"))
            self.assertFalse(git_store.state("branch-creation.json", {}))

    def test_hooks_use_the_installation_even_if_the_checkout_shadows_sun(self):
        tip = self.baseline()
        write("sun.py", 'raise RuntimeError("must not import the checkout")\n')
        self.git("branch", "child")
        self.assertEqual(git_store.ref_oid("refs/sun/heads/child"), tip)

    def test_branch_creation_preserves_source_files_index_and_normal_history(self):
        self.baseline()
        write("README.md", "staged\n")
        self.git("add", "README.md")
        write("README.md", "unstaged\n")
        index = self.git("rev-parse", "--git-path", "index").strip()
        with open(index, "rb") as f: before = f.read()
        head = git_store.ref_oid("HEAD")
        count = self.git("rev-list", "--count", "HEAD")
        self.git("branch", "new")
        self.assertEqual(read("README.md"), "unstaged\n")
        with open(index, "rb") as f: self.assertEqual(f.read(), before)
        self.assertEqual(git_store.ref_oid("HEAD"), head)
        self.assertEqual(self.git("rev-list", "--count", "HEAD"), count)


if __name__ == "__main__": unittest.main()
