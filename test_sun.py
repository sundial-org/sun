"""Unit tests for sun. Run with: python3 -m unittest test_sun -v"""
import contextlib, io, json, os, shutil, subprocess, sys, tempfile, unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sun


def run(*argv, stdin=None):
    """Run a sun command, returning captured stdout."""
    out = io.StringIO()
    old_stdin = sys.stdin
    if stdin is not None:
        sys.stdin = io.StringIO(json.dumps(stdin))
    try:
        with contextlib.redirect_stdout(out):
            sun.main(list(argv))
    finally:
        sys.stdin = old_stdin
    return out.getvalue()


def hook(event, sid="session12345", **extra):
    return run("hook", stdin={"hook_event_name": event, "session_id": sid,
                              "cwd": os.getcwd(), **extra})


def write(path, text):
    with open(path, "w") as f:
        f.write(text)


def transcript(path, *files):
    """Append to a fake Claude Code transcript, one Write tool_use per file."""
    with open(path, "a") as f:
        f.write(json.dumps({"type": "user", "message": {"content": "hi"}}) + "\n")
        for i, fp in enumerate(files):
            f.write(json.dumps({"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": f"tool{i}", "name": "Write",
                 "input": {"file_path": os.path.abspath(fp)}}]}}) + "\n")


class SunTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.tdir = tempfile.mkdtemp()  # transcripts live outside the repo
        self.old_cwd = os.getcwd()
        os.chdir(self.dir)
        for k in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
            os.environ[k] = "emma"
        for k in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
            os.environ[k] = "emma@test"
        subprocess.run(["git", "init", "-q"], check=True)
        subprocess.run(["git", "config", "user.name", "emma"], check=True)
        subprocess.run(["git", "config", "user.email", "emma@test"], check=True)
        write("README.md", "hello\n")
        run("init")

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.dir, ignore_errors=True)
        shutil.rmtree(self.tdir, ignore_errors=True)

    def git(self, *args):
        return subprocess.run(["git", *args], capture_output=True,
                              text=True, check=True).stdout

    def head_subject(self):
        return self.git("log", "-1", "--pretty=%s").strip()

    def agent_turn(self, sid, edits, human_edits=(), tpath=None):
        """Simulate a full agent turn: prompt, edits + PostToolUse hooks, Stop."""
        tpath = tpath or os.path.join(self.tdir, "t.jsonl")
        hook("UserPromptSubmit", sid, transcript_path=tpath)
        transcript(tpath, *[f for f, _ in edits])
        for f, text in edits:
            write(f, text)
            hook("PostToolUse", sid, tool_name="Write",
                 tool_input={"file_path": os.path.abspath(f)})
        for f, text in human_edits:
            write(f, text)
        hook("Stop", sid, transcript_path=os.path.abspath(tpath))

    # ------------------------------------------------------------------ init

    def test_init_creates_state_and_hooks(self):
        self.assertTrue(os.path.isdir(".git/sun"))
        self.assertEqual(self.head_subject(), "sun: initial state")
        cfg = json.load(open(".claude/settings.json"))
        for event in ("SessionStart", "UserPromptSubmit", "PreToolUse",
                      "PostToolUse", "Stop"):
            cmds = [h["command"] for g in cfg["hooks"][event]
                    for h in g["hooks"]]
            self.assertIn("sun hook", cmds)
        self.assertEqual(sun.events()[0]["type"], "init")

    def test_init_is_idempotent_for_hooks(self):
        run("init")
        cfg = json.load(open(".claude/settings.json"))
        self.assertEqual(len(cfg["hooks"]["Stop"]), 1)

    # ------------------------------------------------------- human edit sync

    def test_log_commits_pending_human_edits(self):
        write("a.txt", "v1\n")
        out = run("log")
        self.assertEqual(self.head_subject(), "sun: human edits")
        self.assertIn("[human:emma]", out.splitlines()[0])
        ev = sun.events()[-1]
        self.assertEqual(ev["actor"], "human:emma")
        self.assertEqual(ev["edits"][0]["file"], "a.txt")
        self.assertIn("+v1", ev["edits"][0]["patch"])

    def test_char_edits_match_proposal_example(self):
        patch = ('@@ -10,2 +10,2 @@\n-const name = "Alice";\n'
                 '+const name = "Emma";\n console.log(name);')
        edits = sun.char_edits(patch)
        self.assertEqual(len(edits), 1)
        self.assertEqual(edits[0]["old_line"], 10)
        self.assertEqual(edits[0]["new_line"], 10)
        self.assertEqual(edits[0]["old_text"], "Alice")
        self.assertEqual(edits[0]["new_text"], "Emma")

    # ------------------------------------------------------------ agent turns

    def test_agent_turn_creates_attributed_commit(self):
        self.agent_turn("session12345", [("foo.ts", "export const x = 1\n")])
        self.assertEqual(self.head_subject(),
                         "sun: agent:claude/session1 turn 1")
        ev = sun.events()[-1]
        self.assertEqual(ev["actor"], "agent:claude/session1")
        self.assertEqual(ev["turn"], "turn1")
        self.assertEqual(ev["edits"][0]["file"], "foo.ts")
        self.assertEqual(ev["edits"][0]["tool_call_id"], "tool0")
        self.assertEqual(ev["edits"][0]["attribution"]["method"], "edit_tool")
        self.assertEqual(ev["tool_calls"][0]["tool"], "Write")
        self.assertIn("[agent:claude/session1 turn1]",
                      run("log").splitlines()[0])

    def test_turn_numbers_increment_per_session(self):
        self.agent_turn("session12345", [("a.ts", "1\n")])
        self.agent_turn("session12345", [("a.ts", "2\n")])
        self.assertEqual(sun.events()[-1]["turn"], "turn2")

    def test_mixed_turn_yields_two_events_one_commit(self):
        self.agent_turn("session12345", [("agent.ts", "a\n")],
                        human_edits=[("human.txt", "h\n")])
        evs = sun.events()[-2:]
        self.assertEqual({e["actor"] for e in evs},
                         {"agent:claude/session1", "human:emma"})
        self.assertEqual(evs[0]["commit"], evs[1]["commit"])
        agent_ev = next(e for e in evs if e["actor"].startswith("agent"))
        self.assertEqual([e["file"] for e in agent_ev["edits"]], ["agent.ts"])

    def test_pretooluse_commits_human_edits_separately(self):
        sid = "session12345"
        hook("UserPromptSubmit", sid)
        write("agent.ts", "a\n")
        hook("PostToolUse", sid, tool_name="Write",
             tool_input={"file_path": os.path.abspath("agent.ts")})
        write("human.txt", "h\n")
        hook("PreToolUse", sid, tool_name="Edit",
             tool_input={"file_path": os.path.abspath("agent.ts")})
        self.assertEqual(self.head_subject(), "sun: human edits")
        self.assertEqual([e["file"] for e in sun.events()[-1]["edits"]],
                         ["human.txt"])  # agent.ts stays pending in the turn
        hook("Stop", sid)
        self.assertEqual(sun.events()[-1]["actor"], "agent:claude/session1")

    def test_pretooluse_claims_file_before_write(self):
        sid = "session12345"
        hook("UserPromptSubmit", sid)
        hook("PreToolUse", sid, tool_name="Write",
             tool_input={"file_path": os.path.abspath("planned.ts")})
        write("planned.ts", "x\n")
        run("sync")  # a concurrent sync must not steal the claimed file
        stolen = [ed["file"] for e in sun.events() for ed in e.get("edits", [])]
        self.assertNotIn("planned.ts", stolen)
        hook("Stop", sid)
        ev = sun.events()[-1]
        self.assertEqual(ev["actor"], "agent:claude/session1")
        self.assertEqual(ev["edits"][0]["file"], "planned.ts")

    def test_no_human_sync_while_turn_active(self):
        hook("UserPromptSubmit", "session12345")
        write("pending.txt", "x\n")
        before = self.head_subject()
        run("log")
        self.assertEqual(self.head_subject(), before)
        hook("Stop", "session12345")

    def test_transcript_scoped_to_turn(self):
        self.agent_turn("session12345", [("one.ts", "1\n")])
        self.agent_turn("session12345", [("two.ts", "2\n")])
        files = [c["input"]["file"] for c in sun.events()[-1]["tool_calls"]]
        self.assertEqual([f.split("/")[-1] for f in files], ["two.ts"])

    def test_undo_refuses_stale_patch_atomically(self):
        write("a.txt", "A\n")
        write("b.txt", "B\n")
        run("sync")
        write("a.txt", "A2\n")
        write("b.txt", "B2\n")
        run("sync")
        op = sun.events()[-1]["id"]
        write("b.txt", "CONFLICT\n")
        run("sync")
        with self.assertRaises(SystemExit):
            run("undo", "--op", op)
        self.assertEqual(open("a.txt").read(), "A2\n")  # untouched, not half-undone

    def test_undo_merge_commit(self):
        subprocess.run(["git", "checkout", "-qb", "side"], check=True)
        write("s.txt", "s\n")
        subprocess.run(["git", "add", "-A"], check=True)
        subprocess.run(["git", "commit", "-qm", "side"], check=True)
        subprocess.run(["git", "checkout", "-q", "-"], check=True)
        subprocess.run(["git", "merge", "-q", "--no-ff", "-m", "m", "side"],
                       check=True)
        run("undo", "--commit", "HEAD")
        self.assertFalse(os.path.exists("s.txt"))
        self.assertEqual(sun.events()[-1]["type"], "undo")

    # ------------------------------------------------------------------ show

    def test_show_prints_operations_for_commit(self):
        self.agent_turn("session12345", [("foo.ts", "x\n")])
        commit = self.git("rev-parse", "HEAD").strip()
        out = run("show", commit[:8])
        self.assertIn("foo.ts", out)
        self.assertIn("agent:claude/session1", out)
        self.assertIn('"attribution"', out)

    def test_show_untracked_commit(self):
        write("x.txt", "1\n")
        subprocess.run(["git", "add", "-A"], check=True)
        subprocess.run(["git", "commit", "-q", "-m", "manual"], check=True)
        out = run("show", "HEAD")
        self.assertIn("no sun operations recorded", out)

    # ------------------------------------------------------------------ undo

    def test_undo_latest_op(self):
        write("a.txt", "v1\n")
        run("sync")
        write("a.txt", "v2\n")
        run("sync")
        out = run("undo")
        self.assertIn("undid op", out)
        self.assertEqual(open("a.txt").read(), "v1\n")
        ev = sun.events()[-1]
        self.assertEqual(ev["type"], "undo")
        self.assertEqual(ev["target_op"], sun.events()[-2]["id"])

    def test_undo_specific_op(self):
        write("a.txt", "v1\n")
        run("sync")
        op = sun.events()[-1]["id"]
        run("undo", "--op", op)
        self.assertFalse(os.path.exists("a.txt"))

    def test_undo_latest_commit(self):
        write("a.txt", "v1\n")
        run("sync")
        target = self.git("rev-parse", "HEAD").strip()
        out = run("undo", "--commit")
        self.assertIn("undid commit", out)
        self.assertFalse(os.path.exists("a.txt"))
        ev = sun.events()[-1]
        self.assertEqual(ev["type"], "undo")
        self.assertEqual(ev["target_commit"], target)
        self.assertIn("undo", run("log").splitlines()[0])

    # ------------------------------------------------------------------- viz

    def test_viz_writes_selfcontained_html(self):
        self.agent_turn("session12345", [("foo.ts", "x\n")])
        out = run("viz", "-o", "viz.html")
        self.assertIn("viz.html", out)
        html = open("viz.html").read()
        self.assertIn(self.git("rev-parse", "--short", "HEAD").strip(), html)
        self.assertIn("agent:claude/session1", html)
        self.assertIn("replay", html)
        self.assertNotIn("__DATA__", html)

    # ------------------------------------------------- transcript edge cases

    def test_hook_ignores_uninitialized_repo(self):
        shutil.rmtree(".git/sun")
        hook("SessionStart")  # must not raise
        os.makedirs(".git/sun")

    def test_transcript_with_garbage_lines(self):
        write("t.jsonl", "not json\n" + json.dumps(
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "t1", "name": "Edit",
                 "input": {"file_path": "/x/foo.ts"}}]}}) + "\n")
        calls = sun.transcript_calls("t.jsonl")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["input"]["file"], "/x/foo.ts")


if __name__ == "__main__":
    unittest.main()
