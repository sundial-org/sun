"""Regression tests for concurrent hooks, branch isolation, and shared Git refs."""
import json, os, subprocess, sys, tempfile, unittest
from concurrent.futures import ThreadPoolExecutor
from unittest import mock
import test_sun as fixtures
from test_sun import run, hook, write, read
from sun import hooks, git_store, history, sessions


class ReliabilityTest(unittest.TestCase):
    setUp, tearDown = fixtures.SunTest.setUp, fixtures.SunTest.tearDown
    git, sun_head, tool_call = fixtures.SunTest.git, fixtures.SunTest.sun_head, fixtures.SunTest.tool_call
    plumbing_commit = fixtures.SunTest.plumbing_commit

    def test_module_and_callable_entrypoints_show_the_same_history(self):
        self.tool_call("writer", "note.md", "from a tool\n")
        source = os.path.dirname(os.path.abspath(__file__))
        env = {**os.environ, "PYTHONPATH": source}
        outputs = []
        for command in ([sys.executable, "-c", "from sun.cli import main; main()"],
                        [sys.executable, "-m", "sun"]):
            result = subprocess.run(command + ["data"], env=env, text=True,
                                    capture_output=True, check=True)
            outputs.append(json.loads(result.stdout))
        self.assertEqual(outputs[0], outputs[1])
        self.assertIn("+from a tool", outputs[0]["events"][-1]["edits"][0]["patch"])

    def test_read_only_shell_with_unsynced_active_file_records_nothing(self):
        hook("PreToolUse", "other", tool_name="Write", tool_input={"file_path": "note.md"})
        write("note.md", "already here before shell\n")
        before = self.sun_head()
        hook("PreToolUse", "reader", tool_name="Bash", tool_use_id="read")
        hook("PostToolUse", "reader", tool_name="Bash", tool_use_id="read")
        self.assertEqual(self.sun_head(), before)

    def test_tool_patch_excludes_text_present_before_call(self):
        hook("PreToolUse", "other", tool_name="Write", tool_input={"file_path": "note.md"})
        write("note.md", "existing text\n")
        hook("PreToolUse", "writer", tool_name="Bash", tool_use_id="edit")
        write("note.md", "existing text\nactual addition\n")
        hook("PostToolUse", "writer", tool_name="Bash", tool_use_id="edit")
        ev = history.events()[-1]
        self.assertNotIn("+existing text", ev["edits"][0]["patch"])
        self.assertIn("+actual addition", ev["edits"][0]["patch"])
        self.assertEqual(ev["actor"], "unknown")
        parent = self.git("rev-parse", ev["commit"] + "^").strip()
        self.assertEqual(self.git("show", parent + ":note.md"), "existing text\n")
        run("sync", "--recover")
        self.assertFalse(git_store.refs("refs/sun/pending/"))
        run("undo", "--op", ev["id"])
        self.assertEqual(read("note.md"), "existing text\n")

    def test_deletion_of_unsynced_file_is_an_edit_not_a_noop(self):
        hook("PreToolUse", "other", tool_name="Write", tool_input={"file_path": "note.md"})
        write("note.md", "existing text\n")
        hook("PreToolUse", "writer", tool_name="Bash", tool_use_id="delete")
        os.remove("note.md")
        hook("PostToolUse", "writer", tool_name="Bash", tool_use_id="delete")
        ev = history.events()[-1]
        self.assertIn("-existing text", ev["edits"][0]["patch"])
        self.assertIn("deleted file mode", ev["edits"][0]["patch"])

    def test_failed_call_releases_claim_and_retry_is_recorded(self):
        hook("UserPromptSubmit")
        inp = {"file_path": "a.txt"}
        hook("PreToolUse", tool_name="Write", tool_input=inp, tool_use_id="failed")
        hook("PostToolUseFailure", tool_name="Write", tool_input=inp, tool_use_id="failed")
        self.tool_call("session12345", "a.txt", "retry\n")
        self.assertEqual(git_store.state("active.json", {}), {})
        self.assertEqual(history.events()[-1]["actor"], git_store.agent("session12345"))
        self.assertIn("+retry", history.events()[-1]["edits"][0]["patch"])

    def test_codex_retry_is_not_hidden_by_missing_failure_callback(self):
        inp = {"file_path": "a.txt"}
        for tid in ("failed", "retry"):
            hook("PreToolUse", harness="codex", tool_name="Write", tool_input=inp, tool_use_id=tid)
        write("a.txt", "retry\n")
        hook("PostToolUse", harness="codex", tool_name="Write", tool_input=inp, tool_use_id="retry")
        ev = history.events()[-1]
        self.assertEqual(ev["actor"], git_store.agent("session12345", "codex"))
        self.assertEqual(ev["tool_calls"][0]["id"], "retry")
        self.assertEqual(ev["edits"][0]["attribution"]["method"], "uncertain")
        hook("Stop", harness="codex")
        self.assertFalse(git_store.state("active.json", {}))
        self.assertNotIn("PostToolUseFailure", hooks.CODEX_HOOK_EVENTS)

    def test_interrupted_call_is_recovered_without_guessing_actor(self):
        hook("PreToolUse", tool_name="Write", tool_input={"file_path": "a.txt"})
        write("a.txt", "partial\n")
        hook("Stop")
        self.assertFalse(git_store.state("active.json", {}))
        self.assertEqual(history.events()[-1]["actor"], "unknown")

    def test_read_tool_cannot_claim_human_edit(self):
        hook("PreToolUse", tool_name="Read", tool_input={"file_path": "README.md"})
        write("README.md", "human\n")
        hook("PostToolUse", tool_name="Read", tool_input={"file_path": "README.md"})
        self.assertEqual(history.events()[-1]["actor"], git_store.local())

    def test_parallel_hook_processes_keep_distinct_files_attributed(self):
        def invoke(event, sid):
            payload = {"cwd": os.getcwd(), "hook_event_name": event, "session_id": sid,
                       "tool_name": "Write", "tool_use_id": sid,
                       "tool_input": {"file_path": sid + ".txt"}}
            env = {**os.environ, "PYTHONPATH": os.path.dirname(os.path.abspath(__file__))}
            return subprocess.run([sys.executable, "-m", "sun", "hook"], env=env,
                                  input=json.dumps(payload), capture_output=True, text=True, check=True)
        with ThreadPoolExecutor(2) as pool:
            list(pool.map(lambda sid: invoke("PreToolUse", sid), ("a", "b")))
            write("a.txt", "a\n")
            write("b.txt", "b\n")
            list(pool.map(lambda sid: invoke("PostToolUse", sid), ("a", "b")))
        changes = {d["file"]: e["actor"] for e in history.events() for d in e.get("edits", [])}
        self.assertEqual(changes, {"a.txt": git_store.agent("a"), "b.txt": git_store.agent("b")})

    def test_explicit_recovery_releases_dead_session(self):
        hook("PreToolUse", "dead", tool_name="Bash", tool_use_id="dead")
        write("partial.txt", "partial\n")
        run("sync", "--recover")
        self.assertFalse(git_store.state("active.json", {}))
        self.assertEqual(history.events()[-1]["actor"], "unknown")

    def test_order_is_ancestry_not_clock_and_multiple_identities_do_not_duplicate(self):
        write("a.txt", "a\n")
        with mock.patch("sun.history.time.strftime", return_value="2099-01-01T00:00:00+0000"):
            run("sync")
        first = history.events()[-1]["id"]
        self.git("config", "user.name", "Zoe")
        write("b.txt", "b\n")
        with mock.patch("sun.history.time.strftime", return_value="1999-01-01T00:00:00+0000"):
            run("sync")
        evs = history.events()
        self.assertEqual(evs[-2]["id"], first)
        self.assertEqual(evs[-1]["actor"], "zoe/local")
        self.assertEqual(len({e["id"] for e in evs}), len(evs))

    def test_git_commit_observes_unrecorded_edits_and_preserves_captured_attribution(self):
        write("human.txt", "human\n")
        self.git("add", ".")
        self.git("commit", "-m", "human edit")
        run("log")
        ev = history.events()[-1]
        self.assertEqual(ev["type"], "observe")
        self.assertEqual(ev["actor"], "unknown")
        self.assertEqual(ev["edits"][0]["file"], "human.txt")
        self.assertEqual(ev["edits"][0]["attribution"]["method"], "observed")
        self.assertIn("+human", ev["edits"][0]["patch"])
        self.tool_call("writer", "agent.txt", "captured\n")
        captured = history.events()[-1]
        self.assertEqual(captured["actor"], git_store.agent("writer"))
        write("local.txt", "recorded before commit\n")
        run("sync")
        local = history.events()[-1]
        self.assertEqual(local["actor"], git_store.local())
        self.git("add", ".")
        self.git("commit", "-m", "already recorded edits")
        run("sync")
        evs = history.events()
        self.assertEqual([e for e in evs if e["id"] == captured["id"]], [captured])
        self.assertEqual([e for e in evs if e["id"] == local["id"]], [local])
        self.assertEqual(evs[-1]["id"], local["id"])

    def test_call_keeps_identity_from_pre_hook(self):
        hook("PreToolUse", tool_name="Write", tool_input={"file_path": "a.txt"})
        self.git("config", "user.name", "Zoe")
        write("a.txt", "a\n")
        hook("PostToolUse", tool_name="Write", tool_input={"file_path": "a.txt"})
        self.assertEqual(history.events()[-1]["actor"], "emma/agent:claude/session12345")

    def test_old_logs_are_ignored_and_left_untouched(self):
        old_event = {**history.events()[0], "id": "1234abcd"}
        old_log = json.dumps(old_event) + "\n"
        self.git("update-ref", "refs/sun/log/emma", git_store.blob(old_log))
        old_path = os.path.join(git_store.sun_dir(), "events.jsonl")
        write(old_path, old_log)
        before = self.sun_head()
        self.git("update-ref", "refs/sun/heads/main", before)
        run("init", "--no-instructions")
        hook("SessionStart")
        run("log")
        self.assertEqual(self.sun_head(), before)
        self.assertFalse(git_store.ref_oid("refs/sun/events/1234abcd"))
        self.assertNotIn("legacy_branch", git_store.state("config.json", {}))
        self.assertNotIn("1234abcd", {e["id"] for e in history.events()})
        write("new.txt", "new edit\n")
        run("sync")
        self.assertEqual(history.events()[-1]["edits"][0]["file"], "new.txt")
        self.assertEqual(self.git("cat-file", "blob", "refs/sun/log/emma"), old_log)
        self.assertEqual(read(old_path), old_log)

    def test_fresh_unborn_branches_keep_read_only_calls_empty(self):
        for branch in ("main", "master"):
            with self.subTest(branch=branch), tempfile.TemporaryDirectory() as repo:
                os.chdir(repo)
                try:
                    self.git("init", "-q", "--initial-branch=" + branch)
                    write("note.md", "already here\n")
                    run("init", "--no-instructions")
                    tip = self.sun_head()
                    self.assertEqual(git_store.shadow_ref(), "refs/sun/heads/" + branch)
                    hook("PreToolUse", tool_name="Bash", tool_use_id="read")
                    hook("PostToolUse", tool_name="Bash", tool_use_id="read")
                    self.assertEqual(self.sun_head(), tip)
                    self.assertFalse(git_store.ref_oid("HEAD"))
                    self.assertFalse(os.path.exists(".git/index"))
                    self.git("switch", "-c", "feature")
                    run("log")
                    self.assertEqual(self.sun_head(), tip)
                    self.tool_call("writer", "feature.txt", "new branch\n")
                    self.assertEqual(git_store.ref_oid("refs/sun/heads/" + branch), tip)
                    self.assertNotEqual(self.sun_head(), tip)
                    self.assertEqual(read("note.md"), "already here\n")
                finally:
                    os.chdir(self.dir)

    def test_overlapping_writes_are_explicitly_uncertain(self):
        for sid in ("a", "b"):
            hook("PreToolUse", sid, tool_name="Write", tool_use_id=sid,
                 tool_input={"file_path": "same.txt"})
        write("same.txt", "combined\n")
        for sid in ("a", "b"):
            hook("PostToolUse", sid, tool_name="Write", tool_use_id=sid,
                 tool_input={"file_path": "same.txt"})
        ev = history.events()[-1]
        self.assertEqual(ev["actor"], "unknown")
        self.assertEqual(ev["edits"][0]["attribution"]["method"], "uncertain")

    def test_shell_edits_cannot_be_stolen_by_another_pre_hook(self):
        hook("PreToolUse", "shell", tool_name="Bash", tool_use_id="shell-call")
        write("shell.txt", "shell\n")
        self.tool_call("other", "other.txt", "other\n")
        hook("PostToolUse", "shell", tool_name="Bash", tool_use_id="shell-call")
        changes = {d["file"]: e["actor"] for e in history.events() for d in e.get("edits", [])}
        self.assertEqual(changes["shell.txt"], git_store.agent("shell"))
        # The unknown-scope shell overlaps this call, so do not invent precise attribution.
        self.assertEqual(changes["other.txt"], "unknown")

    def test_failed_publication_keeps_head_and_claim_retryable(self):
        hook("UserPromptSubmit")
        inp = {"file_path": "a.txt"}
        hook("PreToolUse", tool_name="Write", tool_input=inp, tool_use_id="call")
        before = self.sun_head()
        write("a.txt", "a\n")
        with mock.patch("sun.history.publish", side_effect=RuntimeError("interrupted")):
            with self.assertRaises(RuntimeError):
                hook("PostToolUse", tool_name="Write", tool_input=inp, tool_use_id="call")
        self.assertEqual(self.sun_head(), before)
        self.assertTrue(git_store.state("active.json", {}))
        hook("PostToolUse", tool_name="Write", tool_input=inp, tool_use_id="call")
        count = len(history.events())
        hook("PostToolUse", tool_name="Write", tool_input=inp, tool_use_id="call")
        self.assertEqual(len(history.events()), count)

    def test_interrupted_squash_keeps_original_operation_snapshots(self):
        hook("UserPromptSubmit")
        self.tool_call("session12345", "a.txt", "a\n", 0)
        self.tool_call("session12345", "b.txt", "b\n", 1)
        original = [e["commit"] for e in history.events() if e.get("session_id")]
        save = git_store.save_state
        def interrupted(name, obj):
            if name == "turns.json" and any(t.get("squashed") for t in obj.values()):
                raise RuntimeError("crash after commit")
            save(name, obj)
        with mock.patch("sun.git_store.save_state", side_effect=interrupted):
            with self.assertRaises(RuntimeError): hook("Stop")
        tip = self.sun_head()
        hook("Stop")
        self.assertEqual(self.sun_head(), tip)
        self.assertEqual([e["snapshot"] for e in history.events() if e.get("session_id")], original)

    def test_binary_and_unusual_filenames_roundtrip(self):
        name = "tab\tline\n[*].bin"
        with open(name, "wb") as f: f.write(b"\x00before\xff")
        run("sync")
        with open(name, "wb") as f: f.write(b"\x00after\xfe")
        run("sync")
        ev = history.events()[-1]
        self.assertEqual(ev["edits"][0]["file"], name)
        self.assertIn("GIT binary patch", ev["edits"][0]["patch"])
        run("undo", "--op", ev["id"])
        with open(name, "rb") as f: self.assertEqual(f.read(), b"\x00before\xff")

    def test_literal_filenames_have_separate_patches(self):
        write("a[1].txt", "literal\n")
        write("a1.txt", "plain\n")
        run("sync")
        edits = {ed["file"]: ed["patch"] for ed in history.events()[-1]["edits"]}
        self.assertNotIn("plain", edits["a[1].txt"])
        self.assertNotIn("literal", edits["a1.txt"])

    def test_new_branch_inherits_then_isolates_history(self):
        self.git("add", ".")
        self.git("commit", "-m", "track installed hooks")
        run("log")
        old_ref, old_tip = git_store.shadow_ref(), self.sun_head()
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
        self.assertNotIn("feature.txt", {d["file"] for e in history.events() for d in e.get("edits", [])})
        self.git("switch", "feature")
        run("log")
        self.assertEqual(self.sun_head(), feature_tip)

    def test_fetch_never_changes_local_baseline(self):
        before = self.sun_head()
        normal = self.git("rev-parse", "HEAD")
        with open(self.git("rev-parse", "--git-path", "index").strip(), "rb") as f:
            index = f.read()
        write("remote.txt", "remote\n")
        remote = self.plumbing_commit(before, ["remote.txt"])
        os.remove("remote.txt")
        with tempfile.TemporaryDirectory() as bare:
            self.git("init", "--bare", bare)
            self.git("remote", "add", "origin", bare)
            self.git("push", "origin", f"{remote}:{git_store.shadow_ref()}")
            self.git("fetch", "origin", *git_store.refspecs())
        self.assertEqual(git_store.ref_oid(git_store.remote_ref()), remote)
        run("log")
        self.assertEqual(self.sun_head(), before)
        self.assertFalse(any(e.get("edits") for e in history.events()))
        self.assertFalse(os.path.exists("remote.txt"))
        self.assertEqual(read("README.md"), "hello\n")
        self.assertEqual(self.git("rev-parse", "HEAD"), normal)
        with open(self.git("rev-parse", "--git-path", "index").strip(), "rb") as f:
            self.assertEqual(f.read(), index)

    def test_push_joins_conflicting_snapshots_without_merging_files(self):
        base = self.sun_head()
        write("README.md", "remote\n")
        remote = self.plumbing_commit(base, ["README.md"])
        write("README.md", "local\n")
        run("sync")
        local, normal = self.sun_head(), self.git("rev-parse", "HEAD")
        with tempfile.TemporaryDirectory() as bare:
            self.git("init", "--bare", bare)
            self.git("remote", "add", "origin", bare)
            self.git("push", "origin", f"{remote}:{git_store.shadow_ref()}")
            run("push")
        self.assertEqual(self.git("rev-list", "--parents", "-n1", self.sun_head()).split()[1:],
                         [local, remote])
        self.assertEqual(read("README.md"), "local\n")
        self.assertEqual(self.git("show", f"{self.sun_head()}:README.md"), "local\n")
        self.assertEqual(self.git("show", f"{remote}:README.md"), "remote\n")
        self.assertEqual(self.git("rev-parse", "HEAD"), normal)
        self.assertEqual(history.events()[-1]["edits"], [])
        self.assertFalse(os.path.exists(os.path.join(git_store.sun_dir(), "merge.json")))

    def test_linked_worktree_uses_git_paths(self):
        with tempfile.TemporaryDirectory() as path:
            self.git("worktree", "add", "-b", "linked", path)
            try:
                os.chdir(path)
                run("init", "--no-instructions")
                self.tool_call("linked-agent", "linked.txt", "linked\n")
                self.assertTrue(git_store.sun_dir().endswith("/sun"))
                self.assertEqual(history.events()[-1]["actor"], git_store.agent("linked-agent"))
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
        self.assertEqual(len(sessions.scan_codex_transcript(tp)), 2)
        ev = {"actor": git_store.agent("s", "codex"), "session_id": "s", "turn": "turn1"}
        _, chunk = sessions.operation_transcript(ev, "tool0")
        self.assertEqual(sessions.blame_context(chunk, "tool0"), ("new prompt", None, "apply_patch"))
        self.assertFalse(git_store.refs("refs/sun/sessions/"))

    def test_two_clones_same_identity_keep_all_operations(self):
        with tempfile.TemporaryDirectory() as remote, tempfile.TemporaryDirectory() as clone:
            self.git("init", "--bare", remote)
            self.git("remote", "add", "origin", remote)
            self.git("add", ".")
            self.git("commit", "-m", "installed hooks")
            run("sync")  # establish the Git baseline before either clone makes its own edits
            self.git("push", "--no-verify", "origin", "HEAD")
            run("push")
            self.git("clone", remote, clone)
            try:
                os.chdir(clone)
                self.git("config", "user.name", "emma")
                run("init", "--no-instructions")
                write("b.txt", "b\n")
                run("sync")
                b = history.events()[-1]
                os.chdir(self.dir)
                write("a.txt", "a\n")
                run("sync")
                a = history.events()[-1]
                self.assertEqual(a["actor"], b["actor"])
                run("push")
                remote_git_refs = self.git("--git-dir", remote, "for-each-ref", "refs/heads/")
                for checkout, own, other in ((clone, "b", "a"), (self.dir, "a", "b")):
                    os.chdir(checkout)
                    before, normal = self.sun_head(), self.git("rev-parse", "HEAD")
                    tree = self.git("rev-parse", f"{before}^{{tree}}")
                    remote_tip = self.git("--git-dir", remote, "rev-parse", git_store.shadow_ref()).strip()
                    with open(self.git("rev-parse", "--git-path", "index").strip(), "rb") as f:
                        index = f.read()
                    run("push")
                    joined = self.sun_head()
                    self.assertEqual(self.git("rev-list", "--parents", "-n1", joined).split()[1:],
                                     [before, remote_tip])
                    self.assertEqual(self.git("rev-parse", f"{joined}^{{tree}}"), tree)
                    self.assertEqual(self.git("rev-parse", "HEAD"), normal)
                    with open(self.git("rev-parse", "--git-path", "index").strip(), "rb") as f:
                        self.assertEqual(f.read(), index)
                    self.assertEqual(read(own + ".txt"), own + "\n")
                    self.assertFalse(os.path.exists(other + ".txt"))
                    evs = history.events()
                    for original in (a, b):
                        self.assertEqual([e for e in evs if e["id"] == original["id"]], [original])
                        ref = "refs/sun/events/" + original["id"]
                        raw = self.git("--git-dir", remote, "cat-file", "blob", ref)
                        self.assertEqual(json.loads(raw), original)
                        snapshot = original.get("snapshot", original["commit"])
                        self.assertEqual(self.git("--git-dir", remote, "rev-parse", "refs/sun/ops/" + snapshot).strip(),
                                         snapshot)
                    self.assertTrue(all(e["edits"] == [] for e in evs if e["type"] == "merge"))
                    self.assertEqual(self.git("--git-dir", remote, "rev-parse", git_store.shadow_ref()).strip(), joined)
                    self.assertEqual(self.git("--git-dir", remote, "for-each-ref", "refs/heads/"), remote_git_refs)
                    run("push")  # retrying does not add another merge or duplicate operations
                    self.assertEqual(self.sun_head(), joined)
                    self.assertEqual(history.events(), evs)
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
            self.assertEqual(len([e for e in history.events() if e.get("session_id")]), 2)


if __name__ == "__main__": unittest.main()
