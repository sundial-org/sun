"""Regression tests for concurrent hooks, branch isolation, and shared Git refs."""
import json, os, subprocess, sys, tempfile, unittest
from concurrent.futures import ThreadPoolExecutor
from unittest import mock
import test_sun as fixtures
from test_sun import run, hook, write, read, sun


class ReliabilityTest(unittest.TestCase):
    setUp, tearDown = fixtures.SunTest.setUp, fixtures.SunTest.tearDown
    git, sun_head, tool_call = fixtures.SunTest.git, fixtures.SunTest.sun_head, fixtures.SunTest.tool_call
    plumbing_commit = fixtures.SunTest.plumbing_commit

    def test_failed_call_releases_claim_and_retry_is_recorded(self):
        hook("UserPromptSubmit")
        inp = {"file_path": "a.txt"}
        hook("PreToolUse", tool_name="Write", tool_input=inp, tool_use_id="failed")
        hook("PostToolUseFailure", tool_name="Write", tool_input=inp, tool_use_id="failed")
        self.tool_call("session12345", "a.txt", "retry\n")
        self.assertEqual(sun.state("active.json", {}), {})
        self.assertEqual(sun.events()[-1]["actor"], sun.agent("session12345"))
        self.assertIn("+retry", sun.events()[-1]["edits"][0]["patch"])

    def test_codex_retry_is_not_hidden_by_missing_failure_callback(self):
        inp = {"file_path": "a.txt"}
        for tid in ("failed", "retry"):
            hook("PreToolUse", harness="codex", tool_name="Write", tool_input=inp, tool_use_id=tid)
        write("a.txt", "retry\n")
        hook("PostToolUse", harness="codex", tool_name="Write", tool_input=inp, tool_use_id="retry")
        ev = sun.events()[-1]
        self.assertEqual(ev["actor"], sun.agent("session12345", "codex"))
        self.assertEqual(ev["tool_calls"][0]["id"], "retry")
        self.assertEqual(ev["edits"][0]["attribution"]["method"], "uncertain")
        hook("Stop", harness="codex")
        self.assertFalse(sun.state("active.json", {}))
        self.assertNotIn("PostToolUseFailure", sun.CODEX_HOOK_EVENTS)

    def test_interrupted_call_is_recovered_without_guessing_actor(self):
        hook("PreToolUse", tool_name="Write", tool_input={"file_path": "a.txt"})
        write("a.txt", "partial\n")
        hook("Stop")
        self.assertFalse(sun.state("active.json", {}))
        self.assertEqual(sun.events()[-1]["actor"], "unknown")

    def test_read_tool_cannot_claim_human_edit(self):
        hook("PreToolUse", tool_name="Read", tool_input={"file_path": "README.md"})
        write("README.md", "human\n")
        hook("PostToolUse", tool_name="Read", tool_input={"file_path": "README.md"})
        self.assertEqual(sun.events()[-1]["actor"], sun.local())

    def test_parallel_hook_processes_keep_distinct_files_attributed(self):
        def invoke(event, sid):
            payload = {"cwd": os.getcwd(), "hook_event_name": event, "session_id": sid,
                       "tool_name": "Write", "tool_use_id": sid,
                       "tool_input": {"file_path": sid + ".txt"}}
            return subprocess.run([sys.executable, sun.__file__, "hook"],
                                  input=json.dumps(payload), capture_output=True, text=True, check=True)
        with ThreadPoolExecutor(2) as pool:
            list(pool.map(lambda sid: invoke("PreToolUse", sid), ("a", "b")))
            write("a.txt", "a\n")
            write("b.txt", "b\n")
            list(pool.map(lambda sid: invoke("PostToolUse", sid), ("a", "b")))
        changes = {d["file"]: e["actor"] for e in sun.events() for d in e.get("edits", [])}
        self.assertEqual(changes, {"a.txt": sun.agent("a"), "b.txt": sun.agent("b")})

    def test_explicit_recovery_releases_dead_session(self):
        hook("PreToolUse", "dead", tool_name="Bash", tool_use_id="dead")
        write("partial.txt", "partial\n")
        run("sync", "--recover")
        self.assertFalse(sun.state("active.json", {}))
        self.assertEqual(sun.events()[-1]["actor"], "unknown")

    def test_order_is_ancestry_not_clock_and_multiple_identities_do_not_duplicate(self):
        write("a.txt", "a\n")
        with mock.patch("sun.time.strftime", return_value="2099-01-01T00:00:00+0000"):
            run("sync")
        first = sun.events()[-1]["id"]
        self.git("config", "user.name", "Zoe")
        write("b.txt", "b\n")
        with mock.patch("sun.time.strftime", return_value="1999-01-01T00:00:00+0000"):
            run("sync")
        evs = sun.events()
        self.assertEqual(evs[-2]["id"], first)
        self.assertEqual(evs[-1]["actor"], "zoe/local")
        self.assertEqual(len({e["id"] for e in evs}), len(evs))

    def test_normal_git_commit_does_not_hide_a_human_operation(self):
        write("human.txt", "human\n")
        self.git("add", ".")
        self.git("commit", "-m", "human edit")
        run("log")
        ev = sun.events()[-1]
        self.assertEqual(ev["type"], "edit")
        self.assertEqual(ev["edits"][0]["file"], "human.txt")

    def test_call_keeps_identity_from_pre_hook(self):
        hook("PreToolUse", tool_name="Write", tool_input={"file_path": "a.txt"})
        self.git("config", "user.name", "Zoe")
        write("a.txt", "a\n")
        hook("PostToolUse", tool_name="Write", tool_input={"file_path": "a.txt"})
        self.assertEqual(sun.events()[-1]["actor"], "emma/agent:claude/session12345")

    def test_old_logs_do_not_block_recording(self):
        self.git("update-ref", "refs/sun/log/emma", sun.blob("old data\n"))
        write(os.path.join(sun.sun_dir(), "events.jsonl"), "old data\n")
        before = self.sun_head()
        run("init", "--no-instructions")
        self.assertEqual(self.sun_head(), before)
        write("new.txt", "new edit\n")
        run("sync")
        self.assertEqual(sun.events()[-1]["edits"][0]["file"], "new.txt")
        self.assertEqual(self.git("cat-file", "blob", "refs/sun/log/emma"), "old data\n")

    def test_overlapping_writes_are_explicitly_uncertain(self):
        for sid in ("a", "b"):
            hook("PreToolUse", sid, tool_name="Write", tool_use_id=sid,
                 tool_input={"file_path": "same.txt"})
        write("same.txt", "combined\n")
        for sid in ("a", "b"):
            hook("PostToolUse", sid, tool_name="Write", tool_use_id=sid,
                 tool_input={"file_path": "same.txt"})
        ev = sun.events()[-1]
        self.assertEqual(ev["actor"], "unknown")
        self.assertEqual(ev["edits"][0]["attribution"]["method"], "uncertain")

    def test_shell_edits_cannot_be_stolen_by_another_pre_hook(self):
        hook("PreToolUse", "shell", tool_name="Bash", tool_use_id="shell-call")
        write("shell.txt", "shell\n")
        self.tool_call("other", "other.txt", "other\n")
        hook("PostToolUse", "shell", tool_name="Bash", tool_use_id="shell-call")
        changes = {d["file"]: e["actor"] for e in sun.events() for d in e.get("edits", [])}
        self.assertEqual(changes["shell.txt"], sun.agent("shell"))
        # The unknown-scope shell overlaps this call, so do not invent precise attribution.
        self.assertEqual(changes["other.txt"], "unknown")

    def test_failed_publication_keeps_head_and_claim_retryable(self):
        hook("UserPromptSubmit")
        inp = {"file_path": "a.txt"}
        hook("PreToolUse", tool_name="Write", tool_input=inp, tool_use_id="call")
        before = self.sun_head()
        write("a.txt", "a\n")
        with mock.patch("sun.publish", side_effect=RuntimeError("interrupted")):
            with self.assertRaises(RuntimeError):
                hook("PostToolUse", tool_name="Write", tool_input=inp, tool_use_id="call")
        self.assertEqual(self.sun_head(), before)
        self.assertTrue(sun.state("active.json", {}))
        hook("PostToolUse", tool_name="Write", tool_input=inp, tool_use_id="call")
        count = len(sun.events())
        hook("PostToolUse", tool_name="Write", tool_input=inp, tool_use_id="call")
        self.assertEqual(len(sun.events()), count)

    def test_interrupted_squash_keeps_original_operation_snapshots(self):
        hook("UserPromptSubmit")
        self.tool_call("session12345", "a.txt", "a\n", 0)
        self.tool_call("session12345", "b.txt", "b\n", 1)
        original = [e["commit"] for e in sun.events() if e.get("session_id")]
        save = sun.save_state
        def interrupted(name, obj):
            if name == "turns.json" and any(t.get("squashed") for t in obj.values()):
                raise RuntimeError("crash after commit")
            save(name, obj)
        with mock.patch("sun.save_state", side_effect=interrupted):
            with self.assertRaises(RuntimeError): hook("Stop")
        tip = self.sun_head()
        hook("Stop")
        self.assertEqual(self.sun_head(), tip)
        self.assertEqual([e["snapshot"] for e in sun.events() if e.get("session_id")], original)

    def test_binary_and_unusual_filenames_roundtrip(self):
        name = "tab\tline\n[*].bin"
        with open(name, "wb") as f: f.write(b"\x00before\xff")
        run("sync")
        with open(name, "wb") as f: f.write(b"\x00after\xfe")
        run("sync")
        ev = sun.events()[-1]
        self.assertEqual(ev["edits"][0]["file"], name)
        self.assertIn("GIT binary patch", ev["edits"][0]["patch"])
        run("undo", "--op", ev["id"])
        with open(name, "rb") as f: self.assertEqual(f.read(), b"\x00before\xff")

    def test_literal_filenames_have_separate_patches(self):
        write("a[1].txt", "literal\n")
        write("a1.txt", "plain\n")
        run("sync")
        edits = {ed["file"]: ed["patch"] for ed in sun.events()[-1]["edits"]}
        self.assertNotIn("plain", edits["a[1].txt"])
        self.assertNotIn("literal", edits["a1.txt"])

    def test_new_branch_inherits_then_isolates_history(self):
        self.git("add", ".")
        self.git("commit", "-m", "track installed hooks")
        run("log")
        old_ref, old_tip = sun.shadow_ref(), self.sun_head()
        self.git("switch", "-c", "feature")
        run("log")
        self.assertEqual(self.sun_head(), old_tip)
        self.tool_call("agent", "feature.txt", "feature\n")
        self.git("add", ".")
        self.git("commit", "-m", "feature")
        run("log")
        feature_tip = self.sun_head()
        self.git("switch", old_ref.removeprefix("refs/sun/heads/"))
        run("log")
        self.assertEqual(self.sun_head(), old_tip)
        self.assertNotIn("feature.txt", {d["file"] for e in sun.events() for d in e.get("edits", [])})
        self.git("switch", "feature")
        run("log")
        self.assertEqual(self.sun_head(), feature_tip)

    def test_fetch_never_changes_local_baseline(self):
        before = self.sun_head()
        write("remote.txt", "remote\n")
        remote = self.plumbing_commit(before, ["remote.txt"])
        os.remove("remote.txt")
        self.git("update-ref", sun.remote_ref(), remote)
        run("log")
        self.assertEqual(self.sun_head(), before)
        self.assertFalse(any(e.get("edits") for e in sun.events()))
        run("merge")
        self.assertEqual(read("remote.txt"), "remote\n")
        self.assertEqual(sun.events()[-1]["edits"], [])

    def test_merge_conflict_requires_explicit_resolution(self):
        base = self.sun_head()
        write("README.md", "remote\n")
        remote = self.plumbing_commit(base, ["README.md"])
        write("README.md", "local\n")
        run("sync")
        self.git("update-ref", sun.remote_ref(), remote)
        with self.assertRaisesRegex(SystemExit, "merge conflicts"):
            run("merge")
        self.assertIn("<<<<<<<", read("README.md"))
        write("README.md", "resolved\n")
        run("merge", "--continue")
        self.assertEqual(self.git("show", f"{self.sun_head()}:README.md"), "resolved\n")
        self.assertEqual(sun.events()[-1]["edits"][0]["attribution"]["method"], "resolution")

    def test_linked_worktree_uses_git_paths(self):
        with tempfile.TemporaryDirectory() as path:
            self.git("worktree", "add", "-b", "linked", path)
            try:
                os.chdir(path)
                run("init", "--no-instructions")
                self.tool_call("linked-agent", "linked.txt", "linked\n")
                self.assertTrue(sun.sun_dir().endswith("/sun"))
                self.assertEqual(sun.events()[-1]["actor"], sun.agent("linked-agent"))
            finally: os.chdir(self.dir)

    def test_native_codex_prompt_matches_tool_not_turn_number(self):
        tp = os.path.join(self.codex, "native.jsonl")
        rows = [{"type": "session_meta", "payload": {"id": "s", "cwd": os.getcwd()}}]
        for prompt, tid in (("old prompt", "old-call"), ("new prompt", "tool0")):
            rows += [{"type": "event_msg", "payload": {"type": "task_started"}},
                     {"type": "event_msg", "payload": {"type": "user_message", "message": prompt}},
                     {"type": "event_msg", "payload": {"type": "item_completed", "item": {
                         "type": "FileChange", "id": tid}}}]
        write(tp, "\n".join(map(json.dumps, rows)))
        self.assertEqual(len(sun.scan_codex_transcript(tp)), 2)
        ev = {"actor": sun.agent("s", "codex"), "session_id": "s", "turn": "turn1"}
        _, chunk = sun.operation_transcript(ev, "tool0")
        self.assertEqual(sun.blame_context(chunk, "tool0"), ("new prompt", None, "apply_patch"))
        self.assertFalse(sun.refs("refs/sun/sessions/"))

    def test_two_clones_same_identity_keep_all_operations(self):
        with tempfile.TemporaryDirectory() as remote, tempfile.TemporaryDirectory() as clone:
            self.git("init", "--bare", remote)
            self.git("remote", "add", "origin", remote)
            self.git("add", ".")
            self.git("commit", "-m", "installed hooks")
            self.git("push", "--no-verify", "origin", "HEAD")
            run("push")
            self.git("clone", remote, clone)
            try:
                os.chdir(clone)
                run("init", "--no-instructions")
                write("b.txt", "b\n")
                run("sync")
                b = sun.events()[-1]["id"]
                os.chdir(self.dir)
                write("a.txt", "a\n")
                run("sync")
                a = sun.events()[-1]["id"]
                run("push")
                os.chdir(clone)
                before = self.sun_head()
                with self.assertRaises(SystemExit): run("push")
                self.assertEqual(self.git("--git-dir", remote, "for-each-ref", "--format=%(refname)",
                                          f"refs/sun/events/{b}"), "")
                self.git("fetch", "origin")
                run("log")
                self.assertEqual(self.sun_head(), before)
                run("merge")
                run("push")
                os.chdir(self.dir)
                run("merge")
                evs = sun.events()
                self.assertEqual(sum(e["id"] == a for e in evs), 1)
                self.assertEqual(sum(e["id"] == b for e in evs), 1)
                self.assertEqual(read("a.txt") + read("b.txt"), "a\nb\n")
                self.assertTrue(all(e["edits"] == [] for e in evs if e["type"] == "merge"))
            finally: os.chdir(self.dir)

    def test_push_during_turn_prevents_squashing_published_calls(self):
        with tempfile.TemporaryDirectory() as remote:
            self.git("init", "--bare", remote)
            self.git("remote", "add", "origin", remote)
            hook("UserPromptSubmit")
            self.tool_call("session12345", "a.txt", "a\n", 0)
            published = self.sun_head()
            run("push")
            self.tool_call("session12345", "b.txt", "b\n", 1)
            hook("Stop")
            self.git("merge-base", "--is-ancestor", published, self.sun_head())
            run("push")
            self.assertEqual(len([e for e in sun.events() if e.get("session_id")]), 2)


if __name__ == "__main__": unittest.main()
