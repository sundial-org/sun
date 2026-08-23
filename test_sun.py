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


class SunTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
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

    def git(self, *args):
        return subprocess.run(["git", *args], capture_output=True,
                              text=True, check=True).stdout

    def head_subject(self):
        return self.git("log", "-1", "--pretty=%s").strip()

    def tool_call(self, sid, f, text, i=0, tool="Write"):
        """One agent tool call: PreToolUse, the write, PostToolUse."""
        inp = {"file_path": os.path.abspath(f)}
        hook("PreToolUse", sid, tool_name=tool, tool_input=inp, tool_use_id=f"tool{i}")
        write(f, text)
        hook("PostToolUse", sid, tool_name=tool, tool_input=inp, tool_use_id=f"tool{i}")

    def agent_turn(self, sid, edits, human_edits=()):
        """A full agent turn: prompt, one tool call per edit, Stop (squash)."""
        hook("UserPromptSubmit", sid)
        for i, (f, text) in enumerate(edits):
            self.tool_call(sid, f, text, i)
        for f, text in human_edits:  # human edits landing mid-turn
            write(f, text)
        hook("Stop", sid)

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

    def test_tool_call_creates_attributed_commit(self):
        sid = "session12345"
        hook("UserPromptSubmit", sid)
        self.tool_call(sid, "foo.ts", "export const x = 1\n")
        self.assertEqual(self.head_subject(), "sun: agent:claude/session1 Write")
        ev = sun.events()[-1]
        self.assertEqual(ev["actor"], "agent:claude/session1")
        self.assertEqual(ev["turn"], "turn1")
        self.assertEqual(ev["edits"][0]["file"], "foo.ts")
        self.assertEqual(ev["edits"][0]["tool_call_id"], "tool0")
        self.assertEqual(ev["edits"][0]["attribution"]["method"], "edit_tool")
        self.assertEqual(ev["tool_calls"], [{"id": "tool0", "tool": "Write",
                                             "input": {"file": "foo.ts"}}])
        self.assertEqual(self.git("rev-parse", f"refs/sun/ops/{ev['commit']}")
                         .strip(), ev["commit"])

    def test_stop_squashes_tool_calls_into_one_turn_commit(self):
        start = self.git("rev-parse", "HEAD").strip()
        self.agent_turn("session12345", [("a.ts", "1\n"), ("b.ts", "2\n")])
        self.assertEqual(self.head_subject(),
                         "sun: agent:claude/session1 turn 1 (2 tool calls)")
        self.assertEqual(self.git("rev-parse", "HEAD^").strip(), start)
        turn, calls = sun.events()[-1], sun.events()[-3:-1]
        self.assertEqual(turn["squashes"], [c["id"] for c in calls])
        self.assertEqual([t["id"] for t in turn["tool_calls"]], ["tool0", "tool1"])
        self.assertEqual({e["file"] for e in turn["edits"]}, {"a.ts", "b.ts"})
        self.assertIn("[agent:claude/session1 turn1]", run("log").splitlines()[0])
        for c in calls:  # per-call commits survive the squash in the op log
            self.assertIn(c["commit"], self.git("log", "--all", "--pretty=%H"))
            self.assertIn("tool_call_id", run("show", c["commit"]))

    def test_stop_twice_does_not_squash_twice(self):
        self.agent_turn("session12345", [("a.ts", "1\n")])
        before = self.git("rev-parse", "HEAD").strip()
        hook("Stop", "session12345")
        self.assertEqual(self.git("rev-parse", "HEAD").strip(), before)

    def test_turn_numbers_increment_per_session(self):
        self.agent_turn("session12345", [("a.ts", "1\n")])
        self.agent_turn("session12345", [("a.ts", "2\n")])
        self.assertEqual(sun.events()[-1]["turn"], "turn2")

    def test_bash_tool_edits_are_agent_hook_diff(self):
        sid = "session12345"
        hook("UserPromptSubmit", sid)
        hook("PreToolUse", sid, tool_name="Bash", tool_input={"command": "sed"})
        write("via_sed.txt", "x\n")
        hook("PostToolUse", sid, tool_name="Bash", tool_input={"command": "sed"})
        ev = sun.events()[-1]
        self.assertEqual(ev["actor"], "agent:claude/session1")
        self.assertEqual(ev["edits"][0]["attribution"]["method"], "hook_diff")

    def test_human_edit_during_edit_tool_yields_two_events_one_commit(self):
        sid = "session12345"
        hook("UserPromptSubmit", sid)
        inp = {"file_path": os.path.abspath("agent.ts")}
        hook("PreToolUse", sid, tool_name="Write", tool_input=inp)
        write("agent.ts", "a\n")
        write("human.txt", "h\n")  # overlay: can't have come from Write
        hook("PostToolUse", sid, tool_name="Write", tool_input=inp)
        evs = sun.events()[-2:]
        self.assertEqual({e["actor"] for e in evs},
                         {"agent:claude/session1", "human:emma"})
        self.assertEqual(evs[0]["commit"], evs[1]["commit"])
        agent_ev = next(e for e in evs if e["actor"].startswith("agent"))
        self.assertEqual([e["file"] for e in agent_ev["edits"]], ["agent.ts"])

    def test_human_overlay_follows_squash(self):
        sid, inp = "session12345", {"file_path": os.path.abspath("a.ts")}
        hook("UserPromptSubmit", sid)
        hook("PreToolUse", sid, tool_name="Write", tool_input=inp)
        write("a.ts", "a\n")
        write("h.txt", "h\n")
        hook("PostToolUse", sid, tool_name="Write", tool_input=inp)
        hook("Stop", sid)
        self.assertIn("turn 1 (1 tool calls)", self.head_subject())
        ev = sun.events()[-1]
        self.assertEqual((ev["actor"], ev["commit"]), ("human:emma", self.git("rev-parse", "HEAD").strip()))
        self.assertIn("[human:emma]", run("log").splitlines()[0])

    def test_human_edits_mid_turn_block_squash(self):
        sid = "session12345"
        hook("UserPromptSubmit", sid)
        self.tool_call(sid, "a.ts", "1\n", 0)
        write("human.txt", "h\n")
        self.tool_call(sid, "b.ts", "2\n", 1)  # PreToolUse commits human.txt
        hook("Stop", sid)
        subjects = self.git("log", "-3", "--pretty=%s").splitlines()
        self.assertEqual(subjects, ["sun: agent:claude/session1 Write",
                                    "sun: human edits",
                                    "sun: agent:claude/session1 Write"])
        self.assertNotIn("squashes", sun.events()[-1])

    def test_human_edit_after_last_call_stays_dirty_through_squash(self):
        self.agent_turn("session12345", [("a.ts", "1\n")],
                        human_edits=[("late.txt", "h\n")])
        self.assertIn("late.txt", self.git("status", "--porcelain"))
        run("sync")
        self.assertEqual(sun.events()[-1]["actor"], "human:emma")

    def test_pretooluse_claims_file_before_write(self):
        sid, other = "session12345", "sessionB"
        hook("UserPromptSubmit", sid)
        hook("PreToolUse", sid, tool_name="Write",
             tool_input={"file_path": os.path.abspath("planned.ts")})
        write("planned.ts", "x\n")
        write("theirs.txt", "y\n")
        hook("PreToolUse", other, tool_name="Read", tool_input={})  # concurrent sync
        self.assertEqual([e["file"] for e in sun.events()[-1]["edits"]],
                         ["theirs.txt"])  # planned.ts was not stolen
        hook("PostToolUse", other, tool_name="Read", tool_input={})
        hook("PostToolUse", sid, tool_name="Write",
             tool_input={"file_path": os.path.abspath("planned.ts")})
        ev = sun.events()[-1]
        self.assertEqual(ev["actor"], "agent:claude/session1")
        self.assertEqual(ev["edits"][0]["file"], "planned.ts")

    def test_concurrent_agents_each_get_their_own_commit(self):
        a, b = "sessionAAA", "sessionBBB"
        hook("UserPromptSubmit", a)
        hook("UserPromptSubmit", b)
        ia = {"file_path": os.path.abspath("a.ts")}
        ib = {"file_path": os.path.abspath("b.ts")}
        hook("PreToolUse", a, tool_name="Write", tool_input=ia)
        hook("PreToolUse", b, tool_name="Write", tool_input=ib)
        write("a.ts", "a\n")
        write("b.ts", "b\n")
        hook("PostToolUse", b, tool_name="Write", tool_input=ib)  # B finishes first
        hook("PostToolUse", a, tool_name="Write", tool_input=ia)
        eb, ea = sun.events()[-2:]
        self.assertEqual([e["file"] for e in eb["edits"]], ["b.ts"])
        self.assertEqual([e["file"] for e in ea["edits"]], ["a.ts"])
        self.assertNotEqual(ea["commit"], eb["commit"])

    def test_parallel_subagents_share_session_id(self):
        sid = "session12345"
        hook("UserPromptSubmit", sid)
        ia = {"file_path": os.path.abspath("a.ts")}
        ib = {"file_path": os.path.abspath("b.ts")}
        hook("PreToolUse", sid, tool_name="Write", tool_input=ia, tool_use_id="t1")
        hook("PreToolUse", sid, tool_name="Write", tool_input=ib, tool_use_id="t2")
        write("a.ts", "a\n")
        write("b.ts", "b\n")
        hook("PostToolUse", sid, tool_name="Write", tool_input=ia, tool_use_id="t1")
        self.assertEqual([e["file"] for e in sun.events()[-1]["edits"]], ["a.ts"])
        hook("PostToolUse", sid, tool_name="Write", tool_input=ib, tool_use_id="t2")
        self.assertEqual([e["file"] for e in sun.events()[-1]["edits"]], ["b.ts"])

    def test_tool_use_id_only_in_posttooluse(self):
        sid, inp = "session12345", {"file_path": os.path.abspath("x.ts")}
        hook("UserPromptSubmit", sid)
        hook("PreToolUse", sid, tool_name="Write", tool_input=inp)
        write("x.ts", "x\n")
        hook("PostToolUse", sid, tool_name="Write", tool_input=inp, tool_use_id="t9")
        self.assertEqual(sun.events()[-1]["edits"][0]["tool_call_id"], "t9")
        self.assertEqual(sun.state("active.json", {}), {})  # no leaked claim

    def test_posttooluse_without_pretooluse_still_attributes_agent(self):
        hook("UserPromptSubmit", "session12345")
        write("x.ts", "x\n")
        hook("PostToolUse", "session12345", tool_name="Edit",
             tool_input={"file_path": os.path.abspath("x.ts")})
        self.assertEqual(sun.events()[-1]["actor"], "agent:claude/session1")

    def test_per_call_commits_survive_gc(self):
        self.agent_turn("session12345", [("a.ts", "1\n")])
        call = sun.events()[-2]["commit"]
        self.git("gc", "-q", "--prune=now")
        self.assertEqual(self.git("cat-file", "-t", call).strip(), "commit")

    def test_no_human_sync_while_tool_call_in_flight(self):
        hook("UserPromptSubmit", "session12345")
        hook("PreToolUse", "session12345", tool_name="Bash", tool_input={})
        write("pending.txt", "x\n")
        before = self.head_subject()
        run("log")
        self.assertEqual(self.head_subject(), before)

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

    # ------------------------------------------------------------ edge cases

    def test_hook_ignores_uninitialized_repo(self):
        shutil.rmtree(".git/sun")
        hook("SessionStart")  # must not raise
        os.makedirs(".git/sun")


if __name__ == "__main__":
    unittest.main()
