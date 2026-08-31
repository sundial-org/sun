"""Unit tests for sun. Run with: python3 -m unittest test_sun -v"""
import contextlib, io, json, os, shutil, subprocess, sys, tempfile, time, unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sun

AGENT = "emma/agent:claude/session1"  # session12345 truncated to 8 chars


def run(*argv, stdin=None):
    out, old = io.StringIO(), sys.stdin
    if stdin is not None:
        sys.stdin = io.StringIO(json.dumps(stdin))
    try:
        with contextlib.redirect_stdout(out):
            sun.main(list(argv))
    finally:
        sys.stdin = old
    return out.getvalue()


def hook(event, sid="session12345", harness="claude", **extra):
    args = ["hook"] + (["--harness", harness] if harness != "claude" else [])
    return run(*args, stdin={"hook_event_name": event, "session_id": sid,
                            "cwd": os.getcwd(), **extra})


def write(path, text):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


def transcript_line(file_path, tool="Edit", tid="tool0", ts=None):
    ts = ts or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return json.dumps({"type": "assistant", "timestamp": ts, "message": {"content": [
        {"type": "tool_use", "id": tid, "name": tool,
         "input": {"file_path": file_path}}]}}) + "\n"


class SunTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.proj = tempfile.mkdtemp()  # stands in for ~/.claude/projects
        self.codex = tempfile.mkdtemp()  # stands in for ~/.codex/sessions
        os.environ["SUN_PROJECTS"] = self.proj
        os.environ["SUN_CODEX_SESSIONS"] = self.codex
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
        run("init", "--no-claude-md")

    def tearDown(self):
        os.chdir(self.old_cwd)
        os.environ.pop("GIT_COMMITTER_DATE", None)
        shutil.rmtree(self.dir, ignore_errors=True)
        shutil.rmtree(self.proj, ignore_errors=True)
        shutil.rmtree(self.codex, ignore_errors=True)

    def git(self, *args):
        return subprocess.run(["git", *args], capture_output=True, text=True,
                              check=True).stdout

    def head_subject(self):
        return self.git("log", "-1", "--pretty=%s").strip()

    def tool_call(self, sid, f, text, i=0, tool="Write"):
        inp = {"file_path": os.path.abspath(f)}
        hook("PreToolUse", sid, tool_name=tool, tool_input=inp, tool_use_id=f"tool{i}")
        write(f, text)
        hook("PostToolUse", sid, tool_name=tool, tool_input=inp, tool_use_id=f"tool{i}")

    def agent_turn(self, sid, edits, local_edits=(), tpath=None):
        hook("UserPromptSubmit", sid, **({"transcript_path": tpath} if tpath else {}))
        for i, (f, text) in enumerate(edits):
            self.tool_call(sid, f, text, i)
        for f, text in local_edits:  # edits landing after the last tool call
            write(f, text)
        hook("Stop", sid, **({"transcript_path": tpath} if tpath else {}))

    # ------------------------------------------------------------------ init

    def test_init_creates_state_hooks_and_viz(self):
        self.assertTrue(os.path.isdir(".git/sun"))
        self.assertEqual(self.head_subject(), "sun: initial state")
        cfg = json.load(open(".claude/settings.json"))
        for event in ("SessionStart", "UserPromptSubmit", "PreToolUse",
                      "PostToolUse", "Stop"):
            self.assertIn("sun hook", [h["command"] for g in cfg["hooks"][event]
                                       for h in g["hooks"]])
        self.assertEqual(sun.events()[0]["type"], "init")
        self.assertEqual(sun.events()[0]["actor"], "emma/local")
        self.assertTrue(os.path.exists(".git/sun/viz.html"))
        self.assertTrue(os.path.exists(".git/hooks/pre-push"))

    def test_init_is_idempotent_for_hooks(self):
        run("init", "--no-claude-md")
        self.assertEqual(len(json.load(open(".claude/settings.json"))["hooks"]["Stop"]), 1)

    def test_init_adds_refspec_when_remote_exists(self):
        bare = tempfile.mkdtemp()
        subprocess.run(["git", "init", "-q", "--bare", bare], check=True)
        subprocess.run(["git", "remote", "add", "origin", bare], check=True)
        run("init", "--no-claude-md")
        self.assertIn("+refs/sun/*:refs/sun/*",
                      self.git("config", "--get-all", "remote.origin.fetch"))
        shutil.rmtree(bare, ignore_errors=True)

    def test_init_claude_md_flag(self):
        run("init", "--claude-md")
        self.assertIn(sun.CLAUDE_LINE, open("CLAUDE.md").read())
        run("init", "--claude-md")  # idempotent: one copy
        self.assertEqual(open("CLAUDE.md").read().count(".git/sun/sessions/"), 1)

    def test_codex_init_installs_hooks_and_agents_md(self):
        out = run("init", "--codex", "--instructions")
        self.assertIn("hooks: codex (.codex/hooks.json)", out)
        cfg = json.load(open(".codex/hooks.json"))
        for event in sun.CODEX_HOOK_EVENTS:
            self.assertIn("sun hook --harness codex",
                          [h["command"] for g in cfg["hooks"][event] for h in g["hooks"]])
        self.assertEqual(sun.configured_harnesses(), ["codex"])
        self.assertIn(sun.CODEX_LINE, open("AGENTS.md").read())
        run("init", "--codex", "--instructions")
        self.assertEqual(len(json.load(open(".codex/hooks.json"))["hooks"]["Stop"]), 1)

    def test_init_installs_all_detected_harnesses(self):
        # setUp's SUN_PROJECTS + SUN_CODEX_SESSIONS dirs exist -> both detected
        self.assertEqual(sun.configured_harnesses(), ["claude", "codex"])
        for path, cmd in ((".claude/settings.json", "sun hook"),
                          (".codex/hooks.json", "sun hook --harness codex")):
            cfg = json.load(open(path))
            self.assertIn(cmd, [h["command"] for g in cfg["hooks"]["Stop"]
                                for h in g["hooks"]])

    def test_detect_harnesses(self):
        home = tempfile.mkdtemp()
        old = {k: os.environ.pop(k, None)
               for k in ("HOME", "SUN_PROJECTS", "SUN_CODEX_SESSIONS")}
        os.environ["HOME"] = home
        try:
            self.assertEqual(sun.detect_harnesses(), ["claude"])  # none -> default
            os.makedirs(os.path.join(home, ".codex"))
            self.assertEqual(sun.detect_harnesses(), ["codex"])
            os.makedirs(os.path.join(home, ".claude"))
            self.assertEqual(sun.detect_harnesses(), ["claude", "codex"])
        finally:
            for k, v in old.items():
                os.environ.pop(k, None) if v is None else os.environ.update({k: v})
            shutil.rmtree(home, ignore_errors=True)

    def test_claude_flag_restricts_to_claude(self):
        shutil.rmtree(".codex")  # installed by setUp's all-harness init
        run("init", "--claude", "--no-claude-md")
        self.assertEqual(sun.configured_harnesses(), ["claude"])
        self.assertFalse(os.path.exists(".codex/hooks.json"))

    def test_restrictive_reinit_removes_other_harness_hook(self):
        run("init", "--claude", "--no-claude-md")  # setUp installed both
        self.assertNotIn("sun hook", open(".codex/hooks.json").read())
        self.assertIn("sun hook", open(".claude/settings.json").read())

    def test_declined_instructions_hint_keeps_harness_flags(self):
        out = run("init", "--codex", "--no-instructions")
        self.assertIn("`sun init --codex --instructions`", out)

    def test_old_single_harness_config_still_read(self):
        sun.save_state("config.json", {"harness": "codex", "track_sessions": True})
        self.assertEqual(sun.configured_harnesses(), ["codex"])

    # ------------------------------------------------------- local edit sync

    def test_log_commits_pending_local_edits(self):
        write("a.txt", "v1\n")
        out = run("log")
        self.assertEqual(self.head_subject(), "sun: emma/local edits a.txt")
        self.assertIn("[emma/local]", out.splitlines()[0])
        ev = sun.events()[-1]
        self.assertEqual(ev["actor"], "emma/local")
        self.assertEqual(ev["edits"][0]["attribution"]["method"], "hook")
        self.assertIn("+v1", ev["edits"][0]["patch"])
        self.assertTrue(ev["patch_id"])
        sha = self.git("rev-parse", "refs/sun/log/emma").strip()  # mirrored
        self.assertIn(ev["id"], self.git("cat-file", "blob", sha))

    def test_local_edit_commit_names_files_truncated(self):
        for f in ("a.txt", "b.txt", "c.txt", "d.txt"):
            write(f, "x\n")
        run("sync")
        self.assertEqual(self.head_subject(),
                         "sun: emma/local edits a.txt, b.txt, c.txt +1 more")

    def test_char_edits_match_proposal_example(self):
        patch = ('@@ -10,2 +10,2 @@\n-const name = "Alice";\n'
                 '+const name = "Emma";\n console.log(name);')
        edits = sun.char_edits(patch)
        self.assertEqual((edits[0]["old_line"], edits[0]["new_line"]), (10, 10))
        self.assertEqual((edits[0]["old_text"], edits[0]["new_text"]), ("Alice", "Emma"))

    # ------------------------------------------------------------ agent turns

    def test_tool_call_creates_attributed_commit(self):
        hook("UserPromptSubmit")
        self.tool_call("session12345", "foo.ts", "export const x = 1\n")
        self.assertEqual(self.head_subject(), f"sun: {AGENT} Write")
        ev = sun.events()[-1]
        self.assertEqual((ev["actor"], ev["turn"]), (AGENT, "turn1"))
        self.assertEqual(ev["edits"][0]["tool_call_id"], "tool0")
        self.assertEqual(ev["edits"][0]["attribution"]["method"], "hook")
        self.assertEqual(ev["tool_calls"], [{"id": "tool0", "tool": "Write",
                                             "input": {"file": "foo.ts"}}])
        self.assertEqual(self.git("rev-parse", f"refs/sun/ops/{ev['commit']}").strip(),
                         ev["commit"])

    def test_stop_squashes_tool_calls_into_one_turn_commit(self):
        start = self.git("rev-parse", "HEAD").strip()
        self.agent_turn("session12345", [("a.ts", "1\n"), ("b.ts", "2\n")])
        self.assertEqual(self.head_subject(), f"sun: {AGENT} turn 1 (2 tool calls)")
        self.assertEqual(self.git("rev-parse", "HEAD^").strip(), start)
        turn, calls = sun.events()[-1], sun.events()[-3:-1]
        self.assertEqual(turn["squashes"], [c["id"] for c in calls])
        self.assertEqual([t["id"] for t in turn["tool_calls"]], ["tool0", "tool1"])
        self.assertIn(f"[{AGENT} turn1]", run("log").splitlines()[0])
        for c in calls:  # per-call commits survive in the op log
            self.assertIn(c["commit"], self.git("log", "--all", "--pretty=%H"))
            self.assertIn("tool_call_id", run("show", c["commit"]))

    def test_stop_twice_does_not_squash_twice(self):
        self.agent_turn("session12345", [("a.ts", "1\n")])
        before = self.git("rev-parse", "HEAD").strip()
        hook("Stop")
        self.assertEqual(self.git("rev-parse", "HEAD").strip(), before)

    def test_turn_numbers_increment_per_session(self):
        self.agent_turn("session12345", [("a.ts", "1\n")])
        self.agent_turn("session12345", [("a.ts", "2\n")])
        self.assertEqual(sun.events()[-1]["turn"], "turn2")

    def test_missed_stop_squashes_turn_on_next_prompt(self):
        tp = os.path.join(self.proj, "missed.jsonl")
        write(tp, "")
        hook("UserPromptSubmit", transcript_path=tp)
        write(tp, '{"turn":1}\n')
        self.tool_call("session12345", "a.ts", "1\n", 0)  # interrupted: Stop never fires
        hook("UserPromptSubmit", transcript_path=tp)
        self.assertEqual(self.head_subject(), f"sun: {AGENT} turn 1 (1 tool calls)")
        with open(tp, "a") as f:
            f.write('{"turn":2}\n')
        self.tool_call("session12345", "b.ts", "2\n", 1)
        hook("Stop", transcript_path=tp)
        self.assertEqual(self.git("log", "-2", "--pretty=%s").splitlines(),
                         [f"sun: {AGENT} turn 2 (1 tool calls)",
                          f"sun: {AGENT} turn 1 (1 tool calls)"])
        ref = "refs/sun/sessions/emma/session12345"  # neither turn's transcript is lost
        self.assertEqual(self.git("ls-tree", "-r", "--name-only", ref).split(),
                         ["turn-0001.jsonl", "turn-0002.jsonl"])
        self.assertIn('{"turn":1}', self.git("cat-file", "blob", f"{ref}:turn-0001.jsonl"))

    def test_missed_stop_without_commits_keeps_transcript(self):
        tp = os.path.join(self.proj, "chat.jsonl")
        write(tp, "")
        hook("UserPromptSubmit", transcript_path=tp)
        write(tp, '{"type":"assistant","chat":1}\n')  # turn 1: no tool calls, no Stop
        hook("UserPromptSubmit", transcript_path=tp)
        with open(tp, "a") as f:
            f.write('{"chat":2}\n')
        self.tool_call("session12345", "a.ts", "1\n", 0)
        hook("Stop", transcript_path=tp)
        ref = "refs/sun/sessions/emma/session12345"
        self.assertEqual(self.git("ls-tree", "-r", "--name-only", ref).split(),
                         ["turn-0001.jsonl", "turn-0002.jsonl"])
        self.assertIn('"chat":1', self.git("cat-file", "blob", f"{ref}:turn-0001.jsonl"))

    def test_queued_prompt_before_first_tool_call(self):
        tp = os.path.join(self.proj, "early.jsonl")
        write(tp, "")
        hook("UserPromptSubmit", transcript_path=tp)
        with open(tp, "a") as f:  # three prompts land before the session's first tool call
            f.write('{"type": "user", "message": {"content": "one"}}\n'
                    '{"type": "user", "message": {"content": "two"}}\n'
                    '{"type": "user", "message": {"content": "three"}}\n')
        self.tool_call("session12345", "b.ts", "2\n", 0)
        hook("Stop", transcript_path=tp)
        self.assertEqual(self.head_subject(), f"sun: {AGENT} turn 3 (1 tool calls)")
        ref = "refs/sun/sessions/emma/session12345"  # one chunk per queued prompt
        self.assertEqual(self.git("ls-tree", "-r", "--name-only", ref).split(),
                         ["turn-0001.jsonl", "turn-0002.jsonl", "turn-0003.jsonl"])
        self.assertIn("two", self.git("cat-file", "blob", f"{ref}:turn-0002.jsonl"))

    def test_prompt_mentioning_tool_result_is_a_boundary(self):
        tp = os.path.join(self.proj, "tr.jsonl")
        write(tp, "")
        hook("UserPromptSubmit", transcript_path=tp)
        self.tool_call("session12345", "a.ts", "1\n", 0)
        with open(tp, "a") as f:  # queued prompt that mentions tool_result in its text
            f.write('{"type": "user", "message": {"content": "check the tool_result"}}\n')
        self.tool_call("session12345", "b.ts", "2\n", 1)
        hook("Stop", transcript_path=tp)
        self.assertEqual(self.head_subject(), f"sun: {AGENT} turn 2 (1 tool calls)")
        real = ('{"type": "user", "message": {"content": '
                '[{"type": "tool_result", "content": "ok"}]}}\n')
        self.assertFalse(sun.prompt_line(real))  # actual tool results are not prompts

    def test_queued_prompt_gets_its_own_turn(self):
        # neither Stop nor UserPromptSubmit fires between the two turns; the second
        # prompt only shows up in the transcript
        tp = os.path.join(self.proj, "queued.jsonl")
        write(tp, "")
        hook("UserPromptSubmit", transcript_path=tp)
        with open(tp, "a") as f:
            f.write('{"type": "user", "message": {"content": "one"}}\n')
        self.tool_call("session12345", "a.ts", "1\n", 0)
        with open(tp, "a") as f:
            f.write('{"type": "user", "message": {"content": "two"}}\n')
        self.tool_call("session12345", "b.ts", "2\n", 1)
        hook("Stop", transcript_path=tp)
        self.assertEqual(self.git("log", "-2", "--pretty=%s").splitlines(),
                         [f"sun: {AGENT} turn 2 (1 tool calls)",
                          f"sun: {AGENT} turn 1 (1 tool calls)"])
        self.assertEqual(sun.events()[-1]["turn"], "turn2")
        ref = "refs/sun/sessions/emma/session12345"  # one transcript chunk per turn
        self.assertEqual(self.git("ls-tree", "-r", "--name-only", ref).split(),
                         ["turn-0001.jsonl", "turn-0002.jsonl"])
        self.assertIn("one", self.git("cat-file", "blob", f"{ref}:turn-0001.jsonl"))
        self.assertIn("two", self.git("cat-file", "blob", f"{ref}:turn-0002.jsonl"))

    def test_codex_queued_prompt_gets_its_own_turn(self):
        run("init", "--codex", "--no-instructions")
        sid, tp = "codex-queued-sess", os.path.join(self.codex, "q.jsonl")
        write(tp, "")
        hook("UserPromptSubmit", sid, harness="codex", transcript_path=tp)
        user = ('{"type": "event_msg", "payload": {"type": "user_message", '
                '"message": "%s"}}\n{"type": "response_item", "payload": '
                '{"type": "message", "role": "user", "content": "%s"}}\n')
        with open(tp, "a") as f:
            f.write(user % ("one", "one"))
        for i, fn in enumerate(("a.ts", "b.ts")):
            inp = {"file_path": os.path.abspath(fn)}
            hook("PreToolUse", sid, harness="codex", tool_name="Write",
                 tool_input=inp, tool_use_id=f"t{i}")
            write(fn, f"{i}\n")
            hook("PostToolUse", sid, harness="codex", tool_name="Write",
                 tool_input=inp, tool_use_id=f"t{i}")
            if not i:  # queued mid-turn: no Stop/UserPromptSubmit before b.ts
                with open(tp, "a") as f:
                    f.write(user % ("two", "two"))
        hook("Stop", sid, harness="codex", transcript_path=tp)
        codex_agent = "emma/agent:codex/codex-qu"
        self.assertEqual(self.git("log", "-2", "--pretty=%s").splitlines(),
                         [f"sun: {codex_agent} turn 2 (1 tool calls)",
                          f"sun: {codex_agent} turn 1 (1 tool calls)"])

    def test_queued_prompt_with_text_only_turn_splits_at_stop(self):
        tp = os.path.join(self.proj, "textonly.jsonl")
        write(tp, "")
        hook("UserPromptSubmit", transcript_path=tp)
        with open(tp, "a") as f:
            f.write('{"type": "user", "message": {"content": "one"}}\n')
        self.tool_call("session12345", "a.ts", "1\n", 0)
        with open(tp, "a") as f:  # queued prompt answered without tool calls
            f.write('{"type": "user", "message": {"content": "two"}}\n')
        hook("Stop", transcript_path=tp)
        self.assertEqual(self.head_subject(), f"sun: {AGENT} turn 1 (1 tool calls)")
        ref = "refs/sun/sessions/emma/session12345"  # each turn keeps its own chunk
        self.assertEqual(self.git("ls-tree", "-r", "--name-only", ref).split(),
                         ["turn-0001.jsonl", "turn-0002.jsonl"])
        self.assertIn("two", self.git("cat-file", "blob", f"{ref}:turn-0002.jsonl"))

    def test_queued_prompt_with_dirty_local_edits_still_squashes(self):
        tp = os.path.join(self.proj, "dirty.jsonl")
        write(tp, "")
        hook("UserPromptSubmit", transcript_path=tp)
        self.tool_call("session12345", "a.ts", "1\n", 0)
        write("local.txt", "h\n")  # human edit while the second prompt is queued
        with open(tp, "a") as f:
            f.write('{"type": "user", "message": {"content": "two"}}\n')
        self.tool_call("session12345", "b.ts", "2\n", 1)
        hook("Stop", transcript_path=tp)
        self.assertEqual(self.git("log", "-3", "--pretty=%s").splitlines(),
                         [f"sun: {AGENT} turn 2 (1 tool calls)",
                          "sun: emma/local edits local.txt",
                          f"sun: {AGENT} turn 1 (1 tool calls)"])

    def test_codex_task_started_marks_chunk_boundary(self):
        run("init", "--codex", "--no-instructions")
        sid, tp = "codex-task-sess", os.path.join(self.codex, "t.jsonl")
        write(tp, "")
        hook("UserPromptSubmit", sid, harness="codex", transcript_path=tp)
        user = ('{"type": "event_msg", "payload": {"type": "task_started"}}\n'
                '{"type": "response_item", "payload": {"type": "message", '
                '"role": "user", "content": "%s"}}\n'  # canonical record before its mirror
                '{"type": "event_msg", "payload": {"type": "user_message", '
                '"message": "%s"}}\n')
        with open(tp, "a") as f:
            f.write(user % ("one", "one"))
        for i, fn in enumerate(("a.ts", "b.ts")):
            inp = {"file_path": os.path.abspath(fn)}
            hook("PreToolUse", sid, harness="codex", tool_name="Write",
                 tool_input=inp, tool_use_id=f"t{i}")
            write(fn, f"{i}\n")
            hook("PostToolUse", sid, harness="codex", tool_name="Write",
                 tool_input=inp, tool_use_id=f"t{i}")
            if not i:
                with open(tp, "a") as f:
                    f.write(user % ("two", "two"))
        hook("Stop", sid, harness="codex", transcript_path=tp)
        self.assertIn("turn 2 (1 tool calls)", self.head_subject())
        one = self.git("cat-file", "blob",
                       f"refs/sun/sessions/emma/{sid}:turn-0001.jsonl")
        self.assertIn("one", one)
        self.assertNotIn("two", one)  # turn 2's canonical record starts its own chunk

    def test_bash_tool_edits_are_agents(self):
        hook("UserPromptSubmit")
        hook("PreToolUse", tool_name="Bash", tool_input={"command": "sed"})
        write("via_sed.txt", "x\n")
        hook("PostToolUse", tool_name="Bash", tool_input={"command": "sed"})
        ev = sun.events()[-1]
        self.assertEqual(ev["actor"], AGENT)
        self.assertEqual(ev["edits"][0]["attribution"]["method"], "hook")

    def test_codex_apply_patch_tracks_agent_and_local_overlay(self):
        run("init", "--codex", "--no-instructions")
        sid = "codex-session-123"
        patch = "*** Begin Patch\n*** Add File: agent.ts\n+x\n*** End Patch"
        hook("UserPromptSubmit", sid, harness="codex")
        hook("PreToolUse", sid, harness="codex", tool_name="apply_patch",
             tool_input={"command": patch}, tool_use_id="call-1")
        write("agent.ts", "x\n")
        write("local.txt", "human\n")
        hook("PostToolUse", sid, harness="codex", tool_name="apply_patch",
             tool_input={"command": patch}, tool_use_id="call-1")
        evs = sun.events()[-2:]
        self.assertEqual({e["actor"] for e in evs},
                         {"emma/agent:codex/codex-se", "emma/local"})
        agent_ev = next(e for e in evs if "agent:codex" in e["actor"])
        self.assertEqual(agent_ev["tool_calls"][0]["input"], {"file": "agent.ts"})
        hook("Stop", sid, harness="codex")
        self.assertIn("agent:codex/codex-se turn 1", self.head_subject())

    def test_local_overlay_two_events_one_commit_and_follows_squash(self):
        sid, inp = "session12345", {"file_path": os.path.abspath("agent.ts")}
        hook("UserPromptSubmit", sid)
        hook("PreToolUse", sid, tool_name="Write", tool_input=inp)
        write("agent.ts", "a\n")
        write("local.txt", "h\n")  # overlay: can't have come from Write
        hook("PostToolUse", sid, tool_name="Write", tool_input=inp)
        evs = sun.events()[-2:]
        self.assertEqual({e["actor"] for e in evs}, {AGENT, "emma/local"})
        self.assertEqual(evs[0]["commit"], evs[1]["commit"])
        hook("Stop", sid)
        self.assertIn("turn 1 (1 tool calls)", self.head_subject())
        ev = sun.events()[-1]  # overlay re-pointed at the turn commit
        self.assertEqual((ev["actor"], ev["commit"]),
                         ("emma/local", self.git("rev-parse", "HEAD").strip()))
        self.assertIn("[emma/local]", run("log").splitlines()[0])

    def test_local_edits_mid_turn_block_squash(self):
        sid = "session12345"
        hook("UserPromptSubmit", sid)
        self.tool_call(sid, "a.ts", "1\n", 0)
        write("local.txt", "h\n")
        self.tool_call(sid, "b.ts", "2\n", 1)  # PreToolUse commits local.txt
        hook("Stop", sid)
        self.assertEqual(self.git("log", "-3", "--pretty=%s").splitlines(),
                         [f"sun: {AGENT} Write", "sun: emma/local edits local.txt",
                          f"sun: {AGENT} Write"])
        self.assertNotIn("squashes", sun.events()[-1])

    def test_local_edit_after_last_call_stays_dirty_through_squash(self):
        self.agent_turn("session12345", [("a.ts", "1\n")], local_edits=[("late.txt", "h\n")])
        self.assertIn("late.txt", self.git("status", "--porcelain"))
        run("sync")
        self.assertEqual(sun.events()[-1]["actor"], "emma/local")

    def test_pretooluse_claims_file_before_write(self):
        sid = "session12345"
        hook("UserPromptSubmit", sid)
        hook("PreToolUse", sid, tool_name="Write",
             tool_input={"file_path": os.path.abspath("planned.ts")})
        write("planned.ts", "x\n")
        write("theirs.txt", "y\n")
        hook("PreToolUse", "sessionB", tool_name="Read", tool_input={})  # concurrent sync
        self.assertEqual([e["file"] for e in sun.events()[-1]["edits"]], ["theirs.txt"])
        hook("PostToolUse", "sessionB", tool_name="Read", tool_input={})
        hook("PostToolUse", sid, tool_name="Write",
             tool_input={"file_path": os.path.abspath("planned.ts")})
        self.assertEqual(sun.events()[-1]["edits"][0]["file"], "planned.ts")

    def test_parallel_subagents_and_id_only_in_post(self):
        sid = "session12345"
        hook("UserPromptSubmit", sid)
        ia, ib = ({"file_path": os.path.abspath(f)} for f in ("a.ts", "b.ts"))
        hook("PreToolUse", sid, tool_name="Write", tool_input=ia, tool_use_id="t1")
        hook("PreToolUse", sid, tool_name="Write", tool_input=ib)  # id-less claim
        write("a.ts", "a\n")
        write("b.ts", "b\n")
        hook("PostToolUse", sid, tool_name="Write", tool_input=ia, tool_use_id="t1")
        self.assertEqual([e["file"] for e in sun.events()[-1]["edits"]], ["a.ts"])
        hook("PostToolUse", sid, tool_name="Write", tool_input=ib, tool_use_id="t2")
        self.assertEqual([e["file"] for e in sun.events()[-1]["edits"]], ["b.ts"])
        self.assertEqual(sun.state("active.json", {}), {})  # no leaked claims

    def test_no_sync_while_tool_call_in_flight(self):
        hook("UserPromptSubmit")
        hook("PreToolUse", tool_name="Bash", tool_input={})
        write("pending.txt", "x\n")
        before = self.head_subject()
        run("log")
        self.assertEqual(self.head_subject(), before)

    # -------------------------------------------------------- session storage

    def test_stop_appends_turn_chunks_to_session_ref(self):
        tp = os.path.join(self.proj, "t.jsonl")
        write(tp, "")
        self.agent_turn("session12345", [("a.ts", "1\n")], tpath=tp)
        write(tp, '{"turn":1}\n')  # harness appended this turn's lines
        hook("Stop", transcript_path=tp)
        names = self.git("ls-tree", "-r", "--name-only",
                         "refs/sun/sessions/emma/session12345").split()
        self.assertEqual(names, ["turn-0001.jsonl"])
        with open(tp, "a") as f:
            f.write('{"turn":2}\n')
        self.agent_turn("session12345", [("a.ts", "2\n")], tpath=tp)
        out = run("sessions")
        self.assertIn("session12345  emma", out)
        self.assertIn('{"turn":1}', run("sessions", "session12345"))

    def test_sessions_export_layout_and_index(self):
        sun.store_chunks("sess-x", {"turn-0001.jsonl": '{"x":1}\n',
                                    "subagents/sub-1/turn-0001.jsonl": '{"s":1}\n'})
        run("sessions", "export")
        base = os.path.join(".git/sun/sessions", sun.enc(sun.root()))
        self.assertEqual(open(os.path.join(base, "sess-x.jsonl")).read(), '{"x":1}\n')
        self.assertTrue(os.path.exists(os.path.join(base, "sess-x/subagents/sub-1.jsonl")))
        idx = json.load(open(os.path.join(base, "sessions-index.json")))
        self.assertEqual((idx[0]["user"], idx[0]["origin"]), ("emma", "local"))

    def test_codex_subagent_transcript_is_stored_and_exported(self):
        run("init", "--codex", "--no-instructions")
        tp = os.path.join(self.codex, "subagent.jsonl")
        write(tp, '{"subagent":true}\n')
        hook("SubagentStop", "parent-session", harness="codex", agent_id="child-1",
             agent_transcript_path=tp)
        ref = "refs/sun/sessions/emma/parent-session"
        self.assertIn("subagents/child-1/transcript.jsonl",
                      self.git("ls-tree", "-r", "--name-only", ref))
        run("sessions", "export")
        base = os.path.join(".git/sun/sessions", sun.enc(sun.root()))
        self.assertIn("subagent", open(os.path.join(
            base, "parent-session/subagents/child-1.jsonl")).read())

    def test_codex_stop_stores_turn_transcript(self):
        run("init", "--codex", "--no-instructions")
        sid, tp = "codex-live-session", os.path.join(self.codex, "live.jsonl")
        write(tp, "")
        hook("UserPromptSubmit", sid, harness="codex", transcript_path=tp)
        write(tp, '{"turn":"codex"}\n')
        self.assertEqual(hook("Stop", sid, harness="codex", transcript_path=tp), "")
        self.assertIn('"codex"', run("sessions", sid))

    def test_events_merge_teammates_log_ref(self):
        ev = {"id": "zoe00001", "timestamp": "2099-01-01T00:00:00+0000", "type": "edit",
              "actor": "zoe/local", "commit": "f" * 40, "edits": []}
        sha = sun.blob(json.dumps(ev) + "\n")
        self.git("update-ref", "refs/sun/log/zoe", sha)
        self.assertIn("zoe/local", [e["actor"] for e in sun.events()])

    def test_gc_drops_old_session_refs(self):
        os.environ["GIT_COMMITTER_DATE"] = "2000-01-01T00:00:00"
        sun.store_chunks("old-sess", {"turn-0001.jsonl": "x\n"})
        del os.environ["GIT_COMMITTER_DATE"]
        sun.store_chunks("new-sess", {"turn-0001.jsonl": "y\n"})
        self.assertIn("dropped 1", run("gc", "--older-than", "30"))
        self.assertEqual([r[0].split("/")[-1] for r in sun.refs("refs/sun/sessions/")],
                         ["new-sess"])

    # --------------------------------------------------------- import/backfill

    def test_import_backfills_and_stores_sessions(self):
        write("src/foo.ts", "x\n")
        subprocess.run(["git", "add", "-A"], check=True)
        subprocess.run(["git", "commit", "-q", "-m", "manual agent commit"], check=True)
        pdir = os.path.join(self.proj, sun.enc(sun.root()))
        write(os.path.join(pdir, "sess-import-42.jsonl"),
              transcript_line(os.path.abspath("src/foo.ts")))
        out = run("import")
        self.assertIn("imported 1 sessions", out)
        ev = next(e for e in sun.events() if e["actor"].startswith("emma/agent:claude/sess-imp"))
        self.assertEqual(ev["edits"][0]["attribution"]["method"], "transcript_backfill")
        self.assertTrue(sun.refs("refs/sun/sessions/emma/sess-import-42"))
        n = len(sun.events())
        run("import")  # idempotent: nothing new
        self.assertEqual(len(sun.events()), n)

    def test_import_unmatched_commit_is_local(self):
        write("other.txt", "y\n")
        subprocess.run(["git", "add", "-A"], check=True)
        subprocess.run(["git", "commit", "-q", "-m", "no transcript"], check=True)
        run("import")
        ev = next(e for e in sun.events() if e.get("commit") ==
                  self.git("rev-parse", "HEAD").strip())
        self.assertEqual(ev["actor"], "emma/local")
        self.assertEqual(ev["edits"][0]["attribution"]["method"], "import")

    def test_codex_import_backfills_and_stores_sessions(self):
        run("init", "--codex", "--no-instructions")
        write("src/codex.ts", "x\n")
        subprocess.run(["git", "add", "-A"], check=True)
        subprocess.run(["git", "commit", "-q", "-m", "manual codex commit"], check=True)
        sid = "codex-import-session"
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        path = os.path.join(self.codex, "2026", "08", "23", "rollout.jsonl")
        lines = [
            {"type": "session_meta", "timestamp": ts,
             "payload": {"id": sid, "cwd": sun.root(), "source": "cli"}},
            {"type": "event_msg", "timestamp": ts, "payload": {"type": "task_started"}},
            {"type": "response_item", "timestamp": ts, "payload": {
                "type": "custom_tool_call", "name": "apply_patch", "call_id": "call-1",
                "input": "*** Begin Patch\n*** Update File: src/codex.ts\n*** End Patch"}},
        ]
        write(path, "".join(json.dumps(line) + "\n" for line in lines))
        out = run("import")
        self.assertIn("imported 1 sessions", out)
        ev = next(e for e in sun.events() if e["actor"].startswith(
            "emma/agent:codex/codex-im"))
        self.assertEqual(ev["edits"][0]["attribution"]["method"], "transcript_backfill")
        self.assertTrue(sun.refs(f"refs/sun/sessions/emma/{sid}"))

    def test_dual_harness_import_attributes_codex_commits(self):
        # both harnesses configured (setUp default): the claude pass must not
        # backfill codex-authored commits as local before the codex index exists
        write("src/codex.ts", "x\n")
        subprocess.run(["git", "add", "-A"], check=True)
        subprocess.run(["git", "commit", "-q", "-m", "manual codex commit"], check=True)
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        lines = [
            {"type": "session_meta", "timestamp": ts,
             "payload": {"id": "codex-dual-session", "cwd": sun.root(), "source": "cli"}},
            {"type": "response_item", "timestamp": ts, "payload": {
                "type": "custom_tool_call", "name": "apply_patch", "call_id": "call-1",
                "input": "*** Begin Patch\n*** Update File: src/codex.ts\n*** End Patch"}},
        ]
        write(os.path.join(self.codex, "rollout.jsonl"),
              "".join(json.dumps(line) + "\n" for line in lines))
        run("import")
        ev = next(e for e in sun.events() if e.get("commit") ==
                  self.git("rev-parse", "HEAD").strip())
        self.assertEqual(ev["actor"], "emma/agent:codex/codex-du")
        self.assertEqual(ev["edits"][0]["attribution"]["method"], "transcript_backfill")

    def test_backfill_picks_nearest_call_across_harnesses(self):
        write("src/both.ts", "x\n")
        subprocess.run(["git", "add", "-A"], check=True)
        subprocess.run(["git", "commit", "-q", "-m", "codex-authored commit"], check=True)
        at = int(self.git("log", "-1", "--pretty=%at").strip())
        fmt = lambda t: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))
        pdir = os.path.join(self.proj, sun.enc(sun.root()))
        write(os.path.join(pdir, "sess-claude-far.jsonl"),  # 20 min off, indexed first
              transcript_line(os.path.abspath("src/both.ts"), ts=fmt(at - 1200)))
        lines = [
            {"type": "session_meta", "timestamp": fmt(at),
             "payload": {"id": "codex-near-session", "cwd": sun.root(), "source": "cli"}},
            {"type": "response_item", "timestamp": fmt(at), "payload": {
                "type": "custom_tool_call", "name": "apply_patch", "call_id": "call-1",
                "input": "*** Begin Patch\n*** Update File: src/both.ts\n*** End Patch"}},
        ]
        write(os.path.join(self.codex, "near.jsonl"),
              "".join(json.dumps(line) + "\n" for line in lines))
        run("import")
        ev = next(e for e in sun.events() if e.get("commit") ==
                  self.git("rev-parse", "HEAD").strip())
        self.assertEqual(ev["actor"], "emma/agent:codex/codex-ne")

    def test_backfill_multi_file_commit_actor_is_globally_nearest(self):
        write("a.ts", "x\n")
        write("b.ts", "y\n")
        subprocess.run(["git", "add", "-A"], check=True)
        subprocess.run(["git", "commit", "-q", "-m", "two-file commit"], check=True)
        at = int(self.git("log", "-1", "--pretty=%at").strip())
        fmt = lambda t: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))
        pdir = os.path.join(self.proj, sun.enc(sun.root()))
        write(os.path.join(pdir, "sess-claude-a.jsonl"),  # matches a.ts, 20 min off
              transcript_line(os.path.abspath("a.ts"), ts=fmt(at - 1200)))
        lines = [
            {"type": "session_meta", "timestamp": fmt(at),
             "payload": {"id": "codex-b-session", "cwd": sun.root(), "source": "cli"}},
            {"type": "response_item", "timestamp": fmt(at), "payload": {
                "type": "custom_tool_call", "name": "apply_patch", "call_id": "call-b",
                "input": "*** Begin Patch\n*** Update File: b.ts\n*** End Patch"}},
        ]
        write(os.path.join(self.codex, "b.jsonl"),
              "".join(json.dumps(line) + "\n" for line in lines))
        run("import")
        ev = next(e for e in sun.events() if e.get("commit") ==
                  self.git("rev-parse", "HEAD").strip())
        self.assertEqual(ev["actor"], "emma/agent:codex/codex-b-")

    # ------------------------------------------------------------------ show

    def test_show_prints_operations_for_commit(self):
        self.agent_turn("session12345", [("foo.ts", "x\n")])
        out = run("show", self.git("rev-parse", "HEAD").strip()[:8])
        self.assertIn("foo.ts", out)
        self.assertIn(AGENT, out)

    def test_show_untracked_commit(self):
        write("x.txt", "1\n")
        subprocess.run(["git", "add", "-A"], check=True)
        subprocess.run(["git", "commit", "-q", "-m", "manual"], check=True)
        self.assertIn("no sun operations recorded", run("show", "HEAD"))

    def test_show_matches_moved_sha_by_patch_id(self):
        write("a.txt", "v1\n")
        run("sync")
        op = sun.events()[-1]["id"]
        subprocess.run(["git", "checkout", "-qb", "side", "HEAD~1"], check=True)
        write("a.txt", "v1\n")  # same change, new sha (like a squash-merge)
        subprocess.run(["git", "add", "-A"], check=True)
        subprocess.run(["git", "commit", "-q", "-m", "squashed"], check=True)
        self.assertIn(op, run("show", "HEAD"))

    # ------------------------------------------------------------------ undo

    def test_undo_latest_op(self):
        write("a.txt", "v1\n")
        run("sync")
        write("a.txt", "v2\n")
        run("sync")
        self.assertIn("undid op", run("undo"))
        self.assertEqual(open("a.txt").read(), "v1\n")
        ev = sun.events()[-1]
        self.assertEqual((ev["type"], ev["actor"]), ("undo", "emma/local"))
        self.assertEqual(ev["target_op"], sun.events()[-2]["id"])

    def test_undo_specific_op(self):
        write("a.txt", "v1\n")
        run("sync")
        run("undo", "--op", sun.events()[-1]["id"])
        self.assertFalse(os.path.exists("a.txt"))

    def test_undo_latest_commit(self):
        write("a.txt", "v1\n")
        run("sync")
        target = self.git("rev-parse", "HEAD").strip()
        self.assertIn("undid commit", run("undo", "--commit"))
        self.assertFalse(os.path.exists("a.txt"))
        self.assertEqual(sun.events()[-1]["target_commit"], target)
        self.assertIn("undo", run("log").splitlines()[0])

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

    # ------------------------------------------------------------------- viz

    def test_viz_writes_selfcontained_html(self):
        self.agent_turn("session12345", [("foo.ts", "x\n")])
        run("viz", "-o", "viz.html")
        html = open("viz.html").read()
        self.assertIn(self.git("rev-parse", "--short", "HEAD").strip(), html)
        self.assertIn(AGENT, html)
        self.assertIn("replay", html)
        self.assertNotIn("__DATA__", html)

    def test_viz_shows_branch_history_without_sun_refs(self):
        self.agent_turn("session12345", [("a.ts", "1\n")])
        sun.store_chunks("sess-viz", {"turn-0001.jsonl": "{}\n"})
        run("viz", "-o", "viz.html")
        html = open("viz.html").read()
        data = json.loads(html.split("const D=", 1)[1].split(",cs=D.commits", 1)[0]
                          .replace("<\\/", "</"))
        subjects = [c["subject"] for c in data["commits"]]
        self.assertEqual(subjects.count("sun: initial state"), 1)
        self.assertIn(f"sun: {AGENT} turn 1 (1 tool calls)", subjects)
        self.assertNotIn(f"sun: {AGENT} Write", subjects)  # pre-squash refs/sun/ops
        self.assertNotIn("sess-viz", subjects)  # refs/sun/sessions storage commits

    # ---------------------------------------------------------------- update

    def test_update_runs_uv_upgrade_outside_repo(self):
        calls, old = [], sun.quiet
        sun.quiet = lambda *a, **k: calls.append(a) or subprocess.CompletedProcess(
            a, 0, stdout="", stderr="Updated sun v0.1.0\n")
        outside = tempfile.mkdtemp()  # no git repo, no .git/sun
        os.chdir(outside)
        try:
            self.assertIn("sun: Updated sun v0.1.0", run("update"))
        finally:
            sun.quiet = old
            os.chdir(self.dir)
            shutil.rmtree(outside, ignore_errors=True)
        self.assertEqual(calls, [("uv", "tool", "upgrade", "sun")])

    # ---------------------------------------------------------------- export

    def test_export_pairs_prompt_with_edits(self):
        tp = os.path.join(self.proj, "t.jsonl")
        write(tp, "")
        hook("UserPromptSubmit", transcript_path=tp)
        self.tool_call("session12345", "a.ts", "1\n")
        write(tp, json.dumps({"type": "user",
                              "message": {"role": "user", "content": "add feature"}}) + "\n")
        hook("Stop", transcript_path=tp)
        write("local.txt", "h\n")
        run("export", "-o", "dump.jsonl")
        recs = [json.loads(l) for l in open("dump.jsonl")]
        turn = next(r for r in recs if r["actor"] == AGENT)
        self.assertEqual((turn["session"], turn["turn"], turn["prompt"]),
                         ("session12345", "turn1", "add feature"))
        self.assertEqual(turn["tool_calls"][0]["tool"], "Write")
        self.assertIn("+1", turn["edits"][0]["patch"])
        self.assertEqual(len([r for r in recs if r["actor"] == AGENT]), 1)  # squash subsumes
        loc = next(r for r in recs if r["edits"][0]["file"] == "local.txt")
        self.assertEqual((loc["actor"], loc["prompt"]), ("emma/local", None))

    def test_export_backfilled_commit_reconstructs_patch(self):
        write("legacy.txt", "old\n")
        subprocess.run(["git", "add", "-A"], check=True)
        subprocess.run(["git", "commit", "-q", "-m", "pre-sun commit"], check=True)
        run("import")  # backfill stores patch: ""
        rec = next(r for r in map(json.loads, run("export").splitlines())
                   if r["edits"][0]["file"] == "legacy.txt")
        self.assertIn("+old", rec["edits"][0]["patch"])

    def test_export_groups_unsquashed_turn_events(self):
        sid = "session12345"
        hook("UserPromptSubmit", sid)
        self.tool_call(sid, "a.ts", "1\n", 0)
        write("local.txt", "h\n")
        self.tool_call(sid, "b.ts", "2\n", 1)  # mid-turn local edit blocks the squash
        hook("Stop", sid)
        turns = [r for r in map(json.loads, run("export").splitlines()) if r["actor"] == AGENT]
        self.assertEqual(len(turns), 1)  # one record per turn even without a squash
        self.assertEqual([c["id"] for c in turns[0]["tool_calls"]], ["tool0", "tool1"])
        self.assertEqual({d["file"] for d in turns[0]["edits"]}, {"a.ts", "b.ts"})

    def test_export_output_file_is_not_synced_back(self):
        run("export", "-o", "dump.jsonl")
        run("export", "-o", "dump.jsonl")  # first dump must not be committed or re-exported
        self.assertIn("dump.jsonl", self.git("status", "--porcelain"))
        self.assertTrue(all(d["file"] != "dump.jsonl" for e in sun.events()
                            for d in e.get("edits", [])))

    def test_staged_export_output_stays_out_of_sync_commit(self):
        run("export", "-o", "dump.jsonl")
        subprocess.run(["git", "add", "dump.jsonl"], check=True)
        write("other.txt", "x\n")
        run("export", "-o", "dump.jsonl")  # syncs other.txt; staged dump must not ride along
        self.assertEqual(self.git("show", "--name-only", "--format=", "HEAD").split(),
                         ["other.txt"])
        self.assertIn("dump.jsonl", self.git("status", "--porcelain"))

    def test_export_redirected_stdout_is_not_synced(self):
        old = os.dup(1)  # sun export > dump.jsonl: shell pre-creates the file on fd 1
        fd = os.open("dump.jsonl", os.O_CREAT | os.O_WRONLY)
        os.dup2(fd, 1); os.close(fd)
        try: run("export")
        finally: os.dup2(old, 1); os.close(old)
        self.assertTrue(all(d["file"] != "dump.jsonl" for e in sun.events()
                            for d in e.get("edits", [])))

    def test_export_backfilled_merge_resolution(self):
        base = self.git("rev-parse", "--abbrev-ref", "HEAD").strip()
        q = dict(capture_output=True)
        write("m.txt", "base\n")
        subprocess.run(["git", "add", "-A"], check=True); subprocess.run(
            ["git", "commit", "-q", "-m", "base"], check=True)
        subprocess.run(["git", "checkout", "-q", "-b", "side"], check=True)
        write("m.txt", "side\n"); subprocess.run(["git", "commit", "-qam", "side"], check=True)
        subprocess.run(["git", "checkout", "-q", base], check=True)
        write("m.txt", "trunk\n"); subprocess.run(["git", "commit", "-qam", "trunk"], check=True)
        subprocess.run(["git", "merge", "side"], **q)  # conflicts
        write("m.txt", "resolved\n")
        subprocess.run(["git", "add", "m.txt"], check=True)
        subprocess.run(["git", "commit", "-q", "--no-edit"], check=True)
        run("import")
        rec = next(r for r in map(json.loads, run("export").splitlines())
                   if any("resolved" in d["patch"] for d in r["edits"]))
        self.assertEqual(rec["edits"][0]["file"], "m.txt")

    def test_export_includes_undo_ops(self):
        self.agent_turn("session12345", [("a.ts", "1\n")])
        run("undo", "--op")
        rec = next(r for r in map(json.loads, run("export").splitlines())
                   if r["actor"] == "emma/local" and r["edits"][0]["file"] == "a.ts")
        self.assertIn("-1", rec["edits"][0]["patch"])

    def test_chunk_prompt_codex_formats(self):
        self.assertEqual(sun.chunk_prompt(json.dumps(
            {"type": "event_msg", "payload": {"type": "user_message",
                                              "message": "fix bug"}}) + "\n"), "fix bug")
        self.assertEqual(sun.chunk_prompt(json.dumps(
            {"type": "response_item", "payload": {"type": "message", "role": "user",
             "content": [{"type": "input_text", "text": "hi"}]}}) + "\n"), "hi")

    # ------------------------------------------------------------ edge cases

    def test_hook_ignores_uninitialized_repo(self):
        shutil.rmtree(".git/sun")
        hook("PreToolUse")  # must not raise
        os.makedirs(".git/sun")

    def test_sessionstart_prints_context_line(self):
        self.assertIn(".git/sun/sessions/", hook("SessionStart"))

    def test_codex_sessionstart_prints_codex_context_line(self):
        run("init", "--codex", "--no-instructions")
        out = hook("SessionStart", harness="codex")
        self.assertIn("~/.codex/sessions", out)


if __name__ == "__main__":
    unittest.main()
