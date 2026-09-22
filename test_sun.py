"""Unit tests for sun. Run with: python3 -m unittest test_sun -v"""
import contextlib, io, json, os, shutil, subprocess, sys, tempfile, time, unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sun

AGENT = "emma/agent:claude/session12345"


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


def read(path):
    with open(path) as f:
        return f.read()


def read_json(path):
    with open(path) as f:
        return json.load(f)


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
        subprocess.run(["git", "add", "README.md"], check=True)
        subprocess.run(["git", "commit", "-q", "-m", "normal baseline"], check=True)
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
        return self.git("log", "-1", "--pretty=%s", sun.shadow_ref()).strip()

    def sun_head(self):
        return self.git("rev-parse", sun.shadow_ref()).strip()

    def plumbing_commit(self, parent, files, message="rewritten"):
        index = os.path.join(self.dir, ".git", "sun", "test-index")
        if os.path.exists(index): os.remove(index)
        env = {**os.environ, "GIT_INDEX_FILE": index}
        subprocess.run(["git", "read-tree", parent], env=env, check=True)
        subprocess.run(["git", "add", "-A", "--", *files], env=env, check=True)
        tree = subprocess.run(["git", "write-tree"], env=env, check=True,
                              capture_output=True, text=True).stdout.strip()
        return subprocess.run(["git", "commit-tree", tree, "-p", parent, "-m", message],
                              env=env, check=True, capture_output=True, text=True).stdout.strip()

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

    def test_init_creates_state_and_hooks(self):
        self.assertTrue(os.path.isdir(".git/sun"))
        self.assertEqual(self.head_subject(), "sun: initial state")
        cfg = read_json(".claude/settings.json")
        for event in ("SessionStart", "UserPromptSubmit", "PreToolUse",
                      "PostToolUse", "Stop"):
            self.assertIn("sun hook", [h["command"] for g in cfg["hooks"][event]
                                       for h in g["hooks"]])
        self.assertEqual(sun.events()[0]["type"], "init")
        self.assertEqual(sun.events()[0]["actor"], "emma/local")
        self.assertFalse(sun.cfg_share_sessions())
        self.assertFalse(os.path.exists(".git/sun/viz.html"))
        self.assertTrue(os.path.exists(".git/hooks/pre-push"))

    def test_help_lists_public_workflows_without_internal_hook(self):
        out = io.StringIO()
        with self.assertRaisesRegex(SystemExit, "0"), contextlib.redirect_stdout(out):
            sun.main(["--help"])
        text = out.getvalue()
        self.assertIn("restore", text)
        self.assertIn("manage explicitly shared agent transcripts", text)
        self.assertNotIn("agent-harness hook entrypoint", text)
        self.assertNotIn("\n    gc ", text)
        self.assertNotIn("\n    import ", text)

        out = io.StringIO()
        with self.assertRaisesRegex(SystemExit, "0"), contextlib.redirect_stdout(out):
            sun.main(["sessions", "--help"])
        self.assertIn("prune", out.getvalue())
        self.assertIn("store new or changed native transcripts", out.getvalue())

    def test_init_is_idempotent_for_hooks(self):
        run("init", "--no-claude-md")
        self.assertEqual(len(read_json(".claude/settings.json")["hooks"]["Stop"]), 1)

    def test_init_adds_refspec_when_remote_exists(self):
        bare = tempfile.mkdtemp()
        subprocess.run(["git", "init", "-q", "--bare", bare], check=True)
        subprocess.run(["git", "remote", "add", "origin", bare], check=True)
        run("init", "--no-claude-md")
        specs = self.git("config", "--get-all", "remote.origin.fetch")
        self.assertIn("refs/sun/events/*:refs/sun/events/*", specs)
        self.assertIn("refs/sun/ops/*:refs/sun/ops/*", specs)
        self.assertIn("+refs/sun/heads/*:refs/sun/remotes/origin/*", specs)
        self.assertNotIn("refs/sun/sessions", specs)
        self.assertNotIn("refs/sun/sessions", read(".git/hooks/pre-push"))
        run("init", "--share-sessions", "--no-claude-md")
        self.assertIn("+refs/sun/sessions/*:refs/sun/sessions/*",
                      self.git("config", "--get-all", "remote.origin.fetch"))
        self.assertIn('sun push "$1"', read(".git/hooks/pre-push"))
        shutil.rmtree(bare, ignore_errors=True)

    def test_init_claude_md_flag(self):
        run("init", "--share-sessions", "--claude-md")
        self.assertIn(sun.CLAUDE_LINE, read("CLAUDE.md"))
        run("init", "--share-sessions", "--claude-md")  # idempotent: one copy
        self.assertEqual(read("CLAUDE.md").count(".git/sun/sessions/"), 1)

    def test_codex_init_installs_hooks_and_agents_md(self):
        out = run("init", "--codex", "--share-sessions", "--instructions")
        self.assertIn("hooks: codex (.codex/hooks.json)", out)
        self.assertIn("open `/hooks`", out)
        self.assertIn("trust the Sun hooks", out)
        cfg = read_json(".codex/hooks.json")
        for event in sun.CODEX_HOOK_EVENTS:
            self.assertIn("sun hook --harness codex",
                          [h["command"] for g in cfg["hooks"][event] for h in g["hooks"]])
        self.assertEqual(sun.configured_harnesses(), ["codex"])
        self.assertIn(sun.CODEX_LINE, read("AGENTS.md"))
        run("init", "--codex", "--share-sessions", "--instructions")
        self.assertEqual(len(read_json(".codex/hooks.json")["hooks"]["Stop"]), 1)

    def test_init_includes_its_instruction_file_in_the_initial_snapshot(self):
        subprocess.run(["git", "update-ref", "-d", sun.shadow_ref()], check=True)
        run("init", "--codex", "--share-sessions", "--instructions")
        commits = self.git("rev-list", sun.shadow_ref()).splitlines()
        self.assertEqual(len(commits), 1)
        self.assertIn(sun.CODEX_LINE, self.git("show", f"{sun.shadow_ref()}:AGENTS.md"))
        self.assertEqual(sun.changed_files(), [])

    def test_init_installs_all_detected_harnesses(self):
        # setUp's SUN_PROJECTS + SUN_CODEX_SESSIONS dirs exist -> both detected
        self.assertEqual(sun.configured_harnesses(), ["claude", "codex"])
        for path, cmd in ((".claude/settings.json", "sun hook"),
                          (".codex/hooks.json", "sun hook --harness codex")):
            cfg = read_json(path)
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
        self.assertNotIn("sun hook", read(".codex/hooks.json"))
        self.assertIn("sun hook", read(".claude/settings.json"))

    def test_declined_instructions_hint_keeps_harness_flags(self):
        out = run("init", "--codex", "--share-sessions", "--no-instructions")
        self.assertIn("`sun init --codex --instructions`", out)

    def test_old_single_harness_config_still_read(self):
        sun.save_state("config.json", {"harness": "codex", "track_sessions": True})
        self.assertEqual(sun.configured_harnesses(), ["codex"])

    # --------------------------------------------------------- shadow history

    def test_shadow_history_is_independent_and_leaves_git_untouched(self):
        normal = self.git("rev-parse", "HEAD").strip()
        initial = self.sun_head()
        self.assertEqual(len(self.git("rev-list", "--parents", "-n1", initial).split()), 1)
        self.assertNotEqual(initial, normal)
        self.assertNotEqual(subprocess.run(
            ["git", "merge-base", initial, normal], capture_output=True).returncode, 0)

        write("shadow.txt", "one\n")
        real_index = self.git("write-tree").strip()
        run("sync")
        shadow = self.git("rev-parse", sun.shadow_ref()).strip()
        self.assertEqual(self.git("rev-parse", "HEAD").strip(), normal)
        self.assertEqual(self.git("write-tree").strip(), real_index)
        self.assertNotEqual(shadow, initial)
        self.assertEqual(self.git("show", f"{shadow}:shadow.txt"), "one\n")
        self.assertIn("shadow.txt", self.git("status", "--porcelain"))

    def test_shadow_history_keeps_per_call_commits_and_drives_viz(self):
        normal = self.git("rev-parse", "HEAD").strip()
        self.agent_turn("session12345", [("a.ts", "1\n"), ("b.ts", "2\n")])
        commits = self.git("rev-list", sun.shadow_ref()).splitlines()
        self.assertEqual(len(commits), 2)  # initial snapshot + squashed turn
        self.assertEqual(len(sun.refs("refs/sun/ops/")), 3)  # initial + per-call snapshots survive
        self.assertEqual(self.git("rev-parse", "HEAD").strip(), normal)
        data = sun.viz_data()
        self.assertEqual([c["hash"] for c in data["commits"]], commits)
        self.assertEqual(data["summary"]["operations"], 3)  # init + two generated calls
        self.assertTrue(all(c["hash"] != normal for c in data["commits"]))

    def test_shadow_history_fetches_to_remote_tracking_ref(self):
        bare = tempfile.mkdtemp()
        try:
            subprocess.run(["git", "init", "-q", "--bare", bare], check=True)
            subprocess.run(["git", "remote", "add", "origin", bare], check=True)
            run("init", "--no-claude-md")
            specs = self.git("config", "--get-all", "remote.origin.fetch")
            self.assertIn("+refs/sun/heads/*:refs/sun/remotes/origin/*", specs)
            hook_text = read(".git/hooks/pre-push")
            self.assertIn('sun push "$1"', hook_text)
            self.assertNotIn('|| true', hook_text)
            subprocess.run(["git", "push", "--no-verify", "origin",
                            f"{sun.shadow_ref()}:{sun.shadow_ref()}"], check=True,
                           capture_output=True)
            subprocess.run(["git", "fetch", "-q", "origin",
                            "+refs/sun/heads/*:refs/sun/remotes/origin/*"], check=True)
            self.assertEqual(self.git("rev-parse", sun.remote_ref()),
                             self.git("rev-parse", sun.shadow_ref()))
        finally:
            shutil.rmtree(bare, ignore_errors=True)

    def test_push_joins_divergent_shadow_history_without_merging_files(self):
        bare = tempfile.mkdtemp()
        try:
            subprocess.run(["git", "init", "-q", "--bare", bare], check=True)
            subprocess.run(["git", "remote", "add", "origin", bare], check=True)
            normal = self.git("rev-parse", "HEAD").strip()
            base = self.sun_head()
            write("remote.txt", "remote\n")
            remote = self.plumbing_commit(base, ["remote.txt"], "remote shadow edit")
            os.remove("remote.txt")
            write("local.txt", "local\n")
            local = self.plumbing_commit(base, ["local.txt"], "local shadow edit")
            subprocess.run(["git", "update-ref", sun.shadow_ref(), local], check=True)
            subprocess.run(["git", "push", "-q", "--no-verify", "origin",
                            f"{remote}:{sun.shadow_ref()}"], check=True, capture_output=True)

            # Normal Git brings in the remote file; push joins the DAG and keeps the local snapshot.
            write("remote.txt", "remote\n")
            run("push")
            joined = self.sun_head()
            self.assertEqual(self.git("rev-list", "--parents", "-n1", joined).split()[1:],
                             [local, remote])
            self.assertEqual(self.git("show", f"{joined}:local.txt"), "local\n")
            self.assertNotIn("remote.txt", self.git("ls-tree", "--name-only", joined).split())
            self.assertEqual(self.git("--git-dir", bare, "rev-parse", sun.shadow_ref()).strip(), joined)
            self.assertEqual(self.git("rev-parse", "HEAD").strip(), normal)
            ev = sun.events()[-1]
            self.assertEqual((ev["type"], ev["parents"], ev["edits"]), ("merge", [local, remote], []))
            self.assertIn("remote.txt", sun.changed_files())  # a later sync observes it, not push
            run("sync")
            self.assertEqual(self.git("show", f"{self.sun_head()}:remote.txt"), "remote\n")
        finally:
            shutil.rmtree(bare, ignore_errors=True)

    # ------------------------------------------------------- local edit sync

    def test_log_commits_pending_local_edits(self):
        write("a.txt", "v1\n")
        out = run("log")
        self.assertEqual(self.head_subject(), "sun: emma/local edits a.txt")
        self.assertIn("[emma/local]", out.splitlines()[0])
        ev = sun.events()[-1]
        self.assertEqual(ev["actor"], "emma/local")
        self.assertEqual(ev["edits"][0]["attribution"]["method"], "sync")
        self.assertIn("+v1", ev["edits"][0]["patch"])
        self.assertTrue(ev["patch_id"])
        sha = self.git("rev-parse", f"refs/sun/events/{ev['id']}").strip()
        self.assertIn(ev["id"], self.git("cat-file", "blob", sha))

    def test_local_edit_commit_names_files_truncated(self):
        for f in ("a.txt", "b.txt", "c.txt", "d.txt"):
            write(f, "x\n")
        run("sync")
        self.assertEqual(self.head_subject(),
                         "sun: emma/local edits a.txt, b.txt, c.txt +1 more")

    def test_sync_commits_both_sides_of_rename(self):
        write("b.ts", "x\n")
        run("sync")
        os.rename("b.ts", "c.ts")
        run("sync")
        ns = self.git("show", "--name-status", "--format=", sun.shadow_ref()).split()
        self.assertIn("b.ts", ns)  # rename shows as R b.ts c.ts (or D+A), never A alone
        self.assertIn("c.ts", ns)
        self.assertEqual(sun.changed_files(), [])

    # ------------------------------------------------------------ agent turns

    def test_tool_call_creates_attributed_commit(self):
        hook("UserPromptSubmit")
        self.tool_call("session12345", "foo.ts", "export const x = 1\n")
        self.assertEqual(self.head_subject(), f"sun: {AGENT} Write")
        ev = sun.events()[-1]
        self.assertEqual((ev["actor"], ev["turn"]), (AGENT, "turn1"))
        self.assertEqual(ev["session_id"], "session12345")
        self.assertEqual(ev["edits"][0]["tool_call_id"], "tool0")
        self.assertEqual(ev["edits"][0]["attribution"]["method"], "hook")
        self.assertEqual(ev["tool_calls"], [{"id": "tool0", "tool": "Write",
                                             "input": {"file": "foo.ts"}}])
        self.assertEqual(self.git("rev-parse", f"refs/sun/ops/{ev['commit']}").strip(),
                         ev["commit"])

    def test_stop_squashes_tool_calls_into_one_turn_commit(self):
        start = self.sun_head()
        hook("UserPromptSubmit", "session12345")
        self.tool_call("session12345", "a.ts", "1\n", 0)
        self.tool_call("session12345", "b.ts", "2\n", 1)
        originals = sun.events()[-2:]
        hook("Stop", "session12345")
        self.assertEqual(self.head_subject(), f"sun: {AGENT} turn 1 (2 tool calls)")
        self.assertEqual(self.git("rev-parse", f"{sun.shadow_ref()}^").strip(), start)
        calls = sun.events()[-2:]
        self.assertEqual([c["id"] for c in calls], [c["id"] for c in originals])
        raw = sun.events()
        self.assertEqual([sum(e.get("id") == c["id"] for e in raw) for c in calls], [1, 1])
        self.assertEqual([c["commit"] for c in calls], [self.sun_head()] * 2)
        self.assertEqual([c["snapshot"] for c in calls], [c["commit"] for c in originals])
        self.assertEqual([c["tool_calls"][0]["id"] for c in calls], ["tool0", "tool1"])
        self.assertIn(f"[{AGENT} turn1]", run("log").splitlines()[0])
        for c in calls:  # hidden snapshots survive in the op log
            self.assertIn(c["snapshot"], self.git("log", "--all", "--pretty=%H"))
            self.assertIn("tool_call_id", run("show", c["snapshot"]))

    def test_stop_twice_does_not_squash_twice(self):
        self.agent_turn("session12345", [("a.ts", "1\n")])
        before = self.sun_head()
        hook("Stop")
        self.assertEqual(self.sun_head(), before)

    def test_turn_numbers_increment_per_session(self):
        self.agent_turn("session12345", [("a.ts", "1\n")])
        self.agent_turn("session12345", [("a.ts", "2\n")])
        self.assertEqual(sun.events()[-1]["turn"], "turn2")

    def test_missed_stop_squashes_turn_on_next_prompt(self):
        run("init", "--share-sessions", "--no-instructions")
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
        self.assertEqual(self.git("log", "-2", "--pretty=%s", sun.shadow_ref()).splitlines(),
                         [f"sun: {AGENT} turn 2 (1 tool calls)",
                          f"sun: {AGENT} turn 1 (1 tool calls)"])
        ref = "refs/sun/sessions/emma/session12345"  # neither turn's transcript is lost
        self.assertEqual(self.git("ls-tree", "-r", "--name-only", ref).split(),
                         ["turn-0001.jsonl", "turn-0002.jsonl"])
        self.assertIn('{"turn":1}', self.git("cat-file", "blob", f"{ref}:turn-0001.jsonl"))

    def test_missed_stop_without_commits_keeps_transcript(self):
        run("init", "--share-sessions", "--no-instructions")
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
        run("init", "--share-sessions", "--no-instructions")
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
        write(tp, '{"type": "user", "message": {"content": "one"}}\n')
        self.tool_call("session12345", "a.ts", "1\n", 0)
        with open(tp, "a") as f:  # queued message riding on a tool_result record
            f.write('{"type": "user", "message": {"content": [{"type": "tool_result", '
                    '"content": "ok"}, {"type": "text", "text": "now b"}]}}\n')
        self.tool_call("session12345", "b.ts", "2\n", 1)
        hook("Stop", transcript_path=tp)
        self.assertEqual(self.head_subject(), f"sun: {AGENT} turn 2 (1 tool calls)")
        real = ('{"type": "user", "message": {"content": '
                '[{"type": "tool_result", "content": "ok"}]}}\n')
        self.assertFalse(sun.prompt_line(real))  # tool-result-only records are not prompts
        self.assertTrue(sun.prompt_line(  # merely mentioning tool_result still is one
            '{"type": "user", "message": {"content": "check the tool_result"}}\n'))

    def test_queued_prompt_gets_its_own_turn(self):
        run("init", "--share-sessions", "--no-instructions")
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
        self.assertEqual(self.git("log", "-2", "--pretty=%s", sun.shadow_ref()).splitlines(),
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
        codex_agent = "emma/agent:codex/codex-queued-sess"
        self.assertEqual(self.git("log", "-2", "--pretty=%s", sun.shadow_ref()).splitlines(),
                         [f"sun: {codex_agent} turn 2 (1 tool calls)",
                          f"sun: {codex_agent} turn 1 (1 tool calls)"])

    def test_queued_prompt_with_text_only_turn_splits_at_stop(self):
        run("init", "--share-sessions", "--no-instructions")
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
        write(tp, '{"type": "user", "message": {"content": "one"}}\n')
        self.tool_call("session12345", "a.ts", "1\n", 0)
        write("local.txt", "h\n")  # human edit while the second prompt is queued
        with open(tp, "a") as f:
            f.write('{"type": "user", "message": {"content": "two"}}\n')
        self.tool_call("session12345", "b.ts", "2\n", 1)
        hook("Stop", transcript_path=tp)
        self.assertEqual(self.git("log", "-3", "--pretty=%s", sun.shadow_ref()).splitlines(),
                         [f"sun: {AGENT} turn 2 (1 tool calls)",
                          "sun: emma/local edits local.txt",
                          f"sun: {AGENT} turn 1 (1 tool calls)"])

    def test_codex_task_started_marks_chunk_boundary(self):
        run("init", "--codex", "--share-sessions", "--no-instructions")
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
                         {"emma/agent:codex/codex-session-123", "emma/local"})
        agent_ev = next(e for e in evs if "agent:codex" in e["actor"])
        self.assertEqual(agent_ev["tool_calls"][0]["input"], {"file": "agent.ts"})
        hook("Stop", sid, harness="codex")
        self.assertIn("agent:codex/codex-session-123 turn 1", self.head_subject())

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
        ev = sun.events()[-1]  # human operation re-pointed at the turn commit
        self.assertEqual((ev["actor"], ev["commit"]),
                         ("emma/local", self.sun_head()))
        self.assertIn("[emma/local]", run("log").splitlines()[0])

    def test_local_edits_mid_turn_join_squash_and_keep_operation_commit(self):
        sid = "session12345"
        hook("UserPromptSubmit", sid)
        start = self.sun_head()
        self.tool_call(sid, "a.ts", "1\n", 0)
        write("local.txt", "h\n")
        self.tool_call(sid, "b.ts", "2\n", 1)  # PreToolUse commits local.txt
        original = sun.events()[-3:]
        human = next(e for e in original if e["actor"] == "emma/local")
        hook("Stop", sid)
        self.assertEqual(self.git("rev-parse", f"{sun.shadow_ref()}^").strip(), start)
        self.assertEqual(self.head_subject(), f"sun: {AGENT} turn 1 (2 tool calls)")
        updated = sun.events()[-3:]
        self.assertEqual([e["id"] for e in updated], [e["id"] for e in original])
        self.assertEqual({e["commit"] for e in updated}, {self.sun_head()})
        self.assertEqual(next(e for e in updated if e["actor"] == "emma/local")["id"],
                         human["id"])
        for before, after in zip(original, updated):
            self.assertEqual(after["snapshot"], before["commit"])
            self.assertEqual(self.git("rev-parse", f"refs/sun/ops/{after['snapshot']}").strip(),
                             after["snapshot"])
        actors = {a["id"] for a in sun.viz_data()["commits"][0]["attribution"]["actors"]}
        self.assertEqual(actors, {AGENT, "emma/local"})

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
        run("init", "--share-sessions", "--no-instructions")
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
        out = run("sessions", "list")
        self.assertIn("session12345  emma", out)
        self.assertIn('{"turn":1}', run("sessions", "show", "session12345"))

    def test_transcript_stays_local_by_default(self):
        tp = os.path.join(self.proj, "local.jsonl")
        write(tp, "")
        hook("UserPromptSubmit", transcript_path=tp)
        write(tp, '{"private":true}\n')
        hook("Stop", transcript_path=tp)
        self.assertFalse(sun.refs("refs/sun/sessions/"))

    def test_sessions_export_layout_and_index(self):
        sun.store_chunks("sess-x", {"turn-0001.jsonl": '{"x":1}\n',
                                    "subagents/sub-1/turn-0001.jsonl": '{"s":1}\n'}, u="zoe")
        run("sessions", "export")
        base = os.path.join(".git/sun/sessions", sun.enc(sun.root()))
        self.assertEqual(read(os.path.join(base, "zoe/sess-x.jsonl")), '{"x":1}\n')
        self.assertTrue(os.path.exists(os.path.join(base, "zoe/sess-x/subagents/sub-1.jsonl")))
        idx = read_json(os.path.join(base, "sessions-index.json"))
        self.assertEqual((idx[0]["user"], idx[0]["origin"]), ("zoe", "team"))

    def test_sessions_show_requires_a_unique_prefix(self):
        sun.store_chunks("shared-prefix-a", {"turn-0001.jsonl": "a\n"})
        sun.store_chunks("shared-prefix-b", {"turn-0001.jsonl": "b\n"})
        with self.assertRaisesRegex(SystemExit, "ambiguous"):
            run("sessions", "show", "shared-prefix")
        self.assertEqual(run("sessions", "show", "shared-prefix-a"), "a\n")

    def test_codex_subagent_transcript_is_stored_and_exported(self):
        run("init", "--codex", "--share-sessions", "--no-instructions")
        tp = os.path.join(self.codex, "subagent.jsonl")
        write(tp, '{"subagent":true}\n')
        hook("SubagentStop", "parent-session", harness="codex", agent_id="child-1",
             agent_transcript_path=tp)
        ref = "refs/sun/sessions/emma/parent-session"
        self.assertIn("subagents/child-1/transcript.jsonl",
                      self.git("ls-tree", "-r", "--name-only", ref))
        run("sessions", "export")
        base = os.path.join(".git/sun/sessions", sun.enc(sun.root()))
        self.assertFalse(os.path.exists(os.path.join(base, "parent-session")))
        entry = read_json(os.path.join(base, "sessions-index.json"))[0]
        self.assertEqual(entry["subagents"]["child-1"], tp)

    def test_codex_stop_stores_turn_transcript(self):
        run("init", "--codex", "--share-sessions", "--no-instructions")
        sid, tp = "codex-live-session", os.path.join(self.codex, "live.jsonl")
        write(tp, "")
        hook("UserPromptSubmit", sid, harness="codex", transcript_path=tp)
        write(tp, '{"turn":"codex"}\n')
        self.assertEqual(hook("Stop", sid, harness="codex", transcript_path=tp), "")
        self.assertIn('"codex"', run("sessions", "show", sid))

    def test_events_read_teammates_operation_ref(self):
        ev = {"id": "0" * 32, "timestamp": "2099-01-01T00:00:00+0000", "type": "edit",
              "actor": "zoe/local", "commit": self.sun_head(), "edits": []}
        sha = sun.blob(json.dumps(ev) + "\n")
        self.git("update-ref", f"refs/sun/events/{ev['id']}", sha)
        self.assertIn("zoe/local", [e["actor"] for e in sun.events()])

    def test_sessions_prune_only_drops_own_old_refs_and_exports(self):
        os.environ["GIT_COMMITTER_DATE"] = "2000-01-01T00:00:00"
        sun.store_chunks("old-sess", {"turn-0001.jsonl": "x\n"})
        sun.store_chunks("team-sess", {"turn-0001.jsonl": "z\n"}, u="zoe")
        del os.environ["GIT_COMMITTER_DATE"]
        sun.store_chunks("new-sess", {"turn-0001.jsonl": "y\n"})
        run("sessions", "export")
        old_copy = os.path.join(sun.session_export_dir(), "old-sess.jsonl")
        self.assertFalse(os.path.exists(old_copy))
        self.assertIn("pruned 1 local session refs",
                      run("sessions", "prune", "--older-than", "30"))
        self.assertEqual({r[0].split("/")[-1] for r in sun.refs("refs/sun/sessions/")},
                         {"new-sess", "team-sess"})
        self.assertFalse(os.path.exists(old_copy))

    # ---------------------------------------------------------------- import

    def test_import_stores_sessions_without_attributing_old_commits(self):
        run("init", "--share-sessions", "--no-instructions")
        write("src/foo.ts", "x\n")
        subprocess.run(["git", "add", "-A"], check=True)
        subprocess.run(["git", "commit", "-q", "-m", "manual agent commit"], check=True)
        pdir = os.path.join(self.proj, sun.enc(sun.root()))
        write(os.path.join(pdir, "sess-import-42.jsonl"),
              transcript_line(os.path.abspath("src/foo.ts")))
        out = run("sessions", "import")
        self.assertIn("stored 1 sessions", out)
        self.assertNotIn(self.git("rev-parse", "HEAD").strip(),
                         {e.get("commit") for e in sun.events()})
        self.assertTrue(sun.refs("refs/sun/sessions/emma/sess-import-42"))
        n = len(sun.events())
        run("sessions", "import")  # idempotent: nothing new
        self.assertEqual(len(sun.events()), n)

    def test_import_keeps_sessions_local_by_default(self):
        pdir = os.path.join(self.proj, sun.enc(sun.root()))
        write(os.path.join(pdir, "private-session.jsonl"),
              transcript_line(os.path.abspath("private.ts")))
        with self.assertRaisesRegex(SystemExit, "session sharing is disabled"):
            run("sessions", "import")
        self.assertFalse(sun.refs("refs/sun/sessions/"))

    def test_import_does_not_infer_agent_attribution_for_git_commit(self):
        write("other.txt", "y\n")
        subprocess.run(["git", "add", "-A"], check=True)
        subprocess.run(["git", "commit", "-q", "-m", "no transcript"], check=True)
        with self.assertRaisesRegex(SystemExit, "session sharing is disabled"):
            run("sessions", "import")
        first = run("log").splitlines()[0]
        self.assertIn("sun: observed repository state  [unknown]", first)
        self.assertNotIn("agent:", first)

    def test_codex_import_stores_sessions_without_attributing_old_commits(self):
        run("init", "--codex", "--share-sessions", "--no-instructions")
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
        out = run("sessions", "import")
        self.assertIn("stored 1 sessions", out)
        self.assertNotIn(self.git("rev-parse", "HEAD").strip(),
                         {e.get("commit") for e in sun.events()})
        self.assertTrue(sun.refs(f"refs/sun/sessions/emma/{sid}"))

    # ------------------------------------------------------------------ show

    def test_show_prints_operations_for_commit(self):
        self.agent_turn("session12345", [("foo.ts", "x\n")])
        out = run("show", self.sun_head()[:8])
        self.assertIn("foo.ts", out)
        self.assertIn(AGENT, out)

    def test_normal_commit_is_not_in_shadow_history(self):
        shadow = self.sun_head()
        write("x.txt", "1\n")
        subprocess.run(["git", "add", "-A"], check=True)
        subprocess.run(["git", "commit", "-q", "-m", "manual"], check=True)
        normal = self.git("rev-parse", "HEAD").strip()
        self.assertEqual(self.sun_head(), shadow)
        self.assertNotIn(normal, self.git("rev-list", sun.shadow_ref()).splitlines())

    def test_show_matches_moved_sha_by_patch_id(self):
        write("a.txt", "v1\n")
        run("sync")
        original, op = self.sun_head(), sun.events()[-1]["id"]
        parent = self.git("rev-parse", f"{original}^").strip()
        moved = self.plumbing_commit(parent, ["a.txt"], "rewritten")
        self.assertNotEqual(moved, original)
        self.assertIn(op, run("show", moved))

    # ----------------------------------------------------------------- blame

    def blame_turn(self, tp, edits, prompt):
        run("init", "--share-sessions", "--no-instructions")
        write(tp, "")
        hook("UserPromptSubmit", transcript_path=tp)
        with open(tp, "a") as fh:
            fh.write(json.dumps({"type": "user",
                                 "message": {"role": "user", "content": prompt}}) + "\n")
        for i, (f, text, say) in enumerate(edits):
            with open(tp, "a") as fh:
                fh.write(json.dumps({"type": "assistant", "message": {
                    "role": "assistant", "content": [
                        {"type": "text", "text": say},
                        {"type": "tool_use", "id": f"tool{i}", "name": "Write",
                         "input": {"file_path": os.path.abspath(f)}}]}}) + "\n")
            self.tool_call("session12345", f, text, i)
        hook("Stop", transcript_path=tp)

    def test_blame_finds_originating_prompt(self):
        tp = os.path.join(self.proj, "t.jsonl")
        self.blame_turn(tp, [("foo.ts", "export const x = 1\n", "Creating foo.ts now.")],
                        "add an x constant")
        out = run("blame", "foo.ts", "1")
        self.assertIn(AGENT, out)
        self.assertIn("user: add an x constant", out)
        self.assertIn("agent: Creating foo.ts now.", out)
        self.assertIn("[Write tool0]", out)

    def test_blame_squashed_turn_picks_matching_tool_call(self):
        tp = os.path.join(self.proj, "t.jsonl")
        self.blame_turn(tp, [("a.ts", "1\n", "First a.ts."), ("b.ts", "2\n", "Then b.ts.")],
                        "make two files")
        self.assertIn("(2 tool calls)", self.head_subject())  # squashed turn
        out = run("blame", "b.ts", "1")
        self.assertIn("user: make two files", out)
        self.assertIn("agent: Then b.ts.", out)
        self.assertIn("[Write tool1]", out)

    def test_blame_prefers_local_overlay_in_squashed_turn(self):
        hook("UserPromptSubmit")
        inp = {"file_path": os.path.abspath("a.ts")}
        hook("PreToolUse", tool_name="Write", tool_input=inp, tool_use_id="tool0")
        write("a.ts", "agent line\n")
        write("human.txt", "human line\n")  # concurrent local edit during the call
        hook("PostToolUse", tool_name="Write", tool_input=inp, tool_use_id="tool0")
        hook("Stop")
        self.assertIn("(1 tool calls)", self.head_subject())  # squashed turn
        self.assertIn(AGENT, run("blame", "a.ts", "1"))
        out = run("blame", "human.txt", "1")
        self.assertIn("emma/local", out)
        self.assertIn("human edit", out)

    def test_blame_squashed_bash_calls_resolve_per_call(self):
        run("init", "--share-sessions", "--no-instructions")
        tp = os.path.join(self.proj, "t.jsonl")
        write(tp, "")
        hook("UserPromptSubmit", transcript_path=tp)
        with open(tp, "a") as fh:
            fh.write(json.dumps({"type": "user",
                                 "message": {"role": "user", "content": "two scripts"}}) + "\n")
        for i, (f, text, say) in enumerate([("a.sh", "echo a\n", "First script."),
                                            ("b.sh", "echo b\n", "Second script.")]):
            inp = {"command": f"make {f}"}  # no file/files key: unscoped like Bash
            with open(tp, "a") as fh:
                fh.write(json.dumps({"type": "assistant", "message": {
                    "role": "assistant", "content": [
                        {"type": "text", "text": say},
                        {"type": "tool_use", "id": f"tool{i}", "name": "Bash",
                         "input": inp}]}}) + "\n")
            hook("PreToolUse", tool_name="Bash", tool_input=inp, tool_use_id=f"tool{i}")
            write(f, text)
            hook("PostToolUse", tool_name="Bash", tool_input=inp, tool_use_id=f"tool{i}")
        hook("Stop", transcript_path=tp)
        self.assertIn("(2 tool calls)", self.head_subject())
        out = run("blame", "b.sh", "1")
        self.assertIn("agent: Second script.", out)
        self.assertIn("[Bash tool1]", out)

    def test_blame_identical_lines_resolve_by_position(self):
        tp = os.path.join(self.proj, "t.jsonl")
        self.blame_turn(tp, [("f.py", "pass\n", "First write."),
                             ("f.py", "pass\npass\n", "Second write.")], "two passes")
        out = run("blame", "f.py", "1")
        self.assertIn("agent: First write.", out)
        self.assertIn("[Write tool0]", out)
        out = run("blame", "f.py", "2")
        self.assertIn("agent: Second write.", out)
        self.assertIn("[Write tool1]", out)

    def test_blame_follows_renames(self):
        tp = os.path.join(self.proj, "t.jsonl")
        self.blame_turn(tp, [("a.ts", "1\n", "First a.ts."), ("b.ts", "2\n", "Then b.ts.")],
                        "make two files")
        os.rename("b.ts", "c.ts")
        out = run("blame", "c.ts", "1")
        self.assertIn("agent: Then b.ts.", out)
        self.assertIn("[Write tool1]", out)

    def test_blame_from_subdirectory(self):
        self.agent_turn("session12345", [("sub/foo.ts", "x\n")])
        write("foo.ts", "y\n")  # same basename at the root
        run("sync")
        os.chdir("sub")
        try: out = run("blame", "foo.ts", "1")
        finally: os.chdir(sun.root())
        self.assertIn(AGENT, out)

    def test_blame_non_ascii_filename(self):
        tp = os.path.join(self.proj, "t.jsonl")
        self.blame_turn(tp, [("a.ts", "1\n", "First a.ts."),
                             ("café.ts", "2\n", "Then café.ts.")], "make two files")
        out = run("blame", "café.ts", "1")
        self.assertIn("agent: Then café.ts.", out)
        self.assertIn("[Write tool1]", out)

    def test_blame_moved_sha_translates_line_numbers(self):
        tp = os.path.join(self.proj, "t.jsonl")
        base = "".join(f"l{i}\n" for i in range(1, 7))
        write("f.py", base)
        run("sync")
        pre = self.sun_head()
        self.blame_turn(tp, [("f.py", base + "one\n", "Adding one."),
                             ("f.py", base + "one\ntwo\n", "Adding two.")], "two lines")
        original = self.sun_head()
        write("f.py", "zero\n" + base)  # shift the squash's lines down by one
        shifted = self.plumbing_commit(pre, ["f.py"], "insert zero")
        write("f.py", "zero\n" + base + "one\ntwo\n")
        moved = self.plumbing_commit(shifted, ["f.py"], "rewritten squash")
        self.assertEqual(sun.patch_id(original), sun.patch_id(moved))
        subprocess.run(["git", "update-ref", sun.shadow_ref(), moved, original], check=True)
        out = run("blame", "f.py", "8")
        self.assertIn("agent: Adding one.", out)
        self.assertIn("[Write tool0]", out)
        out = run("blame", "f.py", "9")
        self.assertIn("agent: Adding two.", out)
        self.assertIn("[Write tool1]", out)

    def test_blame_moved_sha_whitespace_rewrite(self):
        tp = os.path.join(self.proj, "t.jsonl")
        base = "".join(f"l{i}\n" for i in range(1, 7))
        write("f.py", base)
        run("sync")
        pre = self.sun_head()
        self.blame_turn(tp, [("f.py", base + "one\n", "Adding one."),
                             ("f.py", base + "one\n  x = 2\n", "Adding two.")], "two lines")
        original = self.sun_head()
        write("f.py", base + "one\nx  =  2\n")  # same change reformatted: same patch-id
        moved = self.plumbing_commit(pre, ["f.py"], "reformatted squash")
        self.assertEqual(sun.patch_id(original), sun.patch_id(moved))
        subprocess.run(["git", "update-ref", sun.shadow_ref(), moved, original], check=True)
        out = run("blame", "f.py", "8")
        self.assertIn("agent: Adding two.", out)
        self.assertIn("[Write tool1]", out)

    def test_blame_rename_within_turn(self):
        run("init", "--share-sessions", "--no-instructions")
        tp = os.path.join(self.proj, "t.jsonl")
        write(tp, "")
        hook("UserPromptSubmit", transcript_path=tp)
        with open(tp, "a") as fh:
            fh.write(json.dumps({"type": "user",
                                 "message": {"role": "user", "content": "files"}}) + "\n")
        calls = [("Write", {"file_path": os.path.abspath("a.ts")}, "First a.ts.",
                  lambda: write("a.ts", "1\n")),
                 ("Write", {"file_path": os.path.abspath("b.ts")}, "Then b.ts.",
                  lambda: write("b.ts", "2\n")),
                 ("Bash", {"command": "mv b.ts c.ts"}, "Renaming.",
                  lambda: os.rename("b.ts", "c.ts"))]
        for i, (tool, inp, say, do) in enumerate(calls):
            with open(tp, "a") as fh:
                fh.write(json.dumps({"type": "assistant", "message": {
                    "role": "assistant", "content": [
                        {"type": "text", "text": say},
                        {"type": "tool_use", "id": f"tool{i}", "name": tool,
                         "input": inp}]}}) + "\n")
            hook("PreToolUse", tool_name=tool, tool_input=inp, tool_use_id=f"tool{i}")
            do()
            hook("PostToolUse", tool_name=tool, tool_input=inp, tool_use_id=f"tool{i}")
        hook("Stop", transcript_path=tp)
        self.assertIn("(3 tool calls)", self.head_subject())
        out = run("blame", "c.ts", "1")
        self.assertIn("agent: Then b.ts.", out)
        self.assertIn("[Write tool1]", out)

    def test_blame_symlink_itself(self):
        self.agent_turn("session12345", [("target.txt", "x\n")])
        os.symlink("target.txt", "link.txt")
        run("sync")
        out = run("blame", "link.txt", "1")
        self.assertIn("emma/local", out)
        self.assertIn("human edit", out)

    def test_blame_codex_transcript(self):
        run("init", "--codex", "--share-sessions", "--no-instructions")
        sid, tp = "codex-blame-session", os.path.join(self.codex, "live.jsonl")
        write(tp, "")
        hook("UserPromptSubmit", sid, harness="codex", transcript_path=tp)
        patch = "*** Begin Patch\n*** Add File: c.ts\n+x\n*** End Patch"
        hook("PreToolUse", sid, harness="codex", tool_name="apply_patch",
             tool_input={"command": patch}, tool_use_id="call-9")
        write("c.ts", "x\n")
        lines = [
            {"type": "response_item", "payload": {"type": "message", "role": "user",
             "content": [{"type": "input_text", "text": "please add c.ts"}]}},
            {"type": "response_item", "payload": {"type": "message", "role": "assistant",
             "content": [{"type": "output_text", "text": "Adding c.ts."}]}},
            {"type": "response_item", "payload": {"type": "custom_tool_call",
             "name": "apply_patch", "call_id": "call-9", "input": patch}}]
        write(tp, "".join(json.dumps(line) + "\n" for line in lines))
        hook("PostToolUse", sid, harness="codex", tool_name="apply_patch",
             tool_input={"command": patch}, tool_use_id="call-9")
        hook("Stop", sid, harness="codex", transcript_path=tp)
        out = run("blame", "c.ts", "1")
        self.assertIn("agent:codex/codex-bl", out)
        self.assertIn("user: please add c.ts", out)
        self.assertIn("agent: Adding c.ts.", out)
        self.assertIn("[apply_patch call-9]", out)

    def test_blame_local_edit(self):
        write("a.txt", "v1\n")
        run("sync")
        out = run("blame", "a.txt", "1")
        self.assertIn("emma/local", out)
        self.assertIn("human edit", out)

    def test_blame_snapshots_normal_commit_as_observed_state(self):
        write("x.txt", "1\n")
        subprocess.run(["git", "add", "-A"], check=True)
        subprocess.run(["git", "commit", "-q", "-m", "manual"], check=True)
        out = run("blame", "x.txt", "1")
        self.assertIn("  unknown  op ", out.splitlines()[0])
        self.assertIn("observed change; author unknown", out)
        self.assertNotIn("emma/local", out)

    # ------------------------------------------------------------------ undo

    def test_undo_latest_op(self):
        write("a.txt", "v1\n")
        run("sync")
        write("a.txt", "v2\n")
        run("sync")
        self.assertIn("undid op", run("undo"))
        self.assertEqual(read("a.txt"), "v1\n")
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
        target = self.sun_head()
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
        self.assertEqual(read("a.txt"), "A2\n")  # untouched, not half-undone

    def test_undo_dry_run_checks_without_changing_history_or_files(self):
        write("a.txt", "v1\n")
        run("sync")
        write("a.txt", "v2\n")
        run("sync")
        before, event_count = self.sun_head(), len(sun.events())
        self.assertIn("can undo op", run("undo", "--dry-run"))
        self.assertEqual(read("a.txt"), "v2\n")
        self.assertEqual(self.sun_head(), before)
        self.assertEqual(len(sun.events()), event_count)

    def test_restore_recreates_an_old_state_as_new_history(self):
        write("a.txt", "v1\n")
        run("sync")
        target = self.sun_head()
        write("a.txt", "v2\n")
        run("sync")
        previous = self.sun_head()
        self.assertIn("restored", run("restore", target))
        self.assertEqual(read("a.txt"), "v1\n")
        self.assertNotEqual(self.sun_head(), previous)
        ev = sun.events()[-1]
        self.assertEqual((ev["type"], ev["target_commit"]), ("restore", target))
        self.assertIn("restore", run("log").splitlines()[0])

    # ------------------------------------------------------------------- viz

    def test_data_defaults_to_json_with_null_stdin(self):
        with open(os.devnull) as stdin, mock.patch("sys.stdin", stdin):
            for command in ("data",):
                data = json.loads(run(command))
                self.assertIn("commits", data)
                self.assertIn("sessions", data)

    def test_data_resolves_native_and_team_paths_without_own_copy(self):
        tp = os.path.join(self.proj, "native.jsonl")
        write(tp, "local transcript\n")
        self.agent_turn("session12345", [("foo.ts", "x\n")], tpath=tp)
        sun.store_chunks("session12345", {"turn-0001.jsonl": "stale copy\n"})
        sun.store_chunks("session12345", {"turn-0001.jsonl": "team copy\n"}, u="zoe")
        base = sun.session_export_dir()
        write(os.path.join(base, "session12345.jsonl"), "legacy\n")
        write(os.path.join(base, "session12345/subagents/child.jsonl"), "legacy\n")
        data = json.loads(run("data"))
        own = next(s for s in data["sessions"] if s["user"] == "emma")
        team = next(s for s in data["sessions"] if s["user"] == "zoe")
        self.assertEqual(own["path"], tp)
        self.assertEqual(read(team["path"]), "team copy\n")
        self.assertFalse(os.path.exists(os.path.join(base, "session12345.jsonl")))
        self.assertFalse(os.path.exists(os.path.join(base, "session12345")))
        self.assertEqual(data["commits"][0]["operations"][0]["session_path"], tp)
        os.remove(tp)
        own = next(s for s in json.loads(run("data"))["sessions"] if s["user"] == "emma")
        self.assertIsNone(own["path"])  # never fall back to duplicating our shared ref

    def test_data_discovers_native_sessions_without_sharing(self):
        claude = os.path.join(self.proj, sun.enc(sun.root()), "claude-local.jsonl")
        codex = os.path.join(self.codex, "rollout.jsonl")
        write(claude, "{}\n")
        write(codex, json.dumps({"type": "session_meta", "payload": {
            "id": "codex-local", "cwd": sun.root()}}) + "\n")
        paths = {s["id"]: s["path"] for s in json.loads(run("data"))["sessions"]}
        self.assertEqual(paths, {"claude-local": claude, "codex-local": codex})
        self.assertFalse(os.path.exists(sun.session_export_dir()))

    def test_data_redirected_output_is_not_synced(self):
        old = os.dup(1)
        fd = os.open("data.json", os.O_CREAT | os.O_WRONLY, 0o600)
        os.dup2(fd, 1)
        os.close(fd)
        try: json.loads(run("data"))
        finally:
            os.dup2(old, 1)
            os.close(old)
        self.assertTrue(all(d["file"] != "data.json" for e in sun.events()
                            for d in e.get("edits", [])))

    def test_viz_output_is_not_synced_back(self):
        run("viz", "-o", "viz.html")
        run("viz", "-o", "viz.html")
        self.assertTrue(all(d["file"] != "viz.html" for e in sun.events()
                            for d in e.get("edits", [])))

    def test_viz_writes_selfcontained_html(self):
        self.agent_turn("session12345", [("foo.ts", "x\n")])
        run("viz", "-o", "viz.html")
        html = read("viz.html")
        self.assertIn(self.git("rev-parse", "--short", sun.shadow_ref()).strip(), html)
        self.assertIn(AGENT, html)
        self.assertIn("replay", html)
        self.assertIn("generated by", html)
        self.assertNotIn("__DATA__", html)

    def test_viz_defaults_to_tui(self):
        seen, old = [], sun.run_viz_tui
        sun.run_viz_tui = lambda data: seen.append(data)
        try: run("viz")
        finally: sun.run_viz_tui = old
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0]["summary"]["commits"], 1)

    def test_viz_releases_lock_before_tui(self):
        held, old_lock, old_tui = [False], sun.lock, sun.run_viz_tui

        @contextlib.contextmanager
        def tracked_lock():
            with old_lock() as lk:
                held[0] = True
                try: yield lk
                finally: held[0] = False

        sun.lock = tracked_lock
        sun.run_viz_tui = lambda data: self.assertFalse(held[0])
        try: run("viz")
        finally: sun.lock, sun.run_viz_tui = old_lock, old_tui

    def test_viz_data_attributes_commit_and_operations(self):
        self.agent_turn("session12345", [("foo.ts", "x\n")])
        data = sun.viz_data()
        commit = data["commits"][0]
        self.assertEqual(commit["git_author"]["name"], AGENT)
        self.assertEqual(commit["attribution"]["actors"][0], {
            "id": AGENT, "user": "emma", "kind": "agent", "harness": "claude",
            "session": "session12345"})
        operation = commit["operations"][0]
        self.assertEqual(operation["actor"], AGENT)
        self.assertEqual(operation["session_id"], "session12345")
        self.assertEqual(operation["attribution_methods"], ["hook"])
        self.assertEqual(operation["tool_calls"][0]["tool"], "Write")
        self.assertNotIn("generated_operations", operation)
        self.assertEqual(data["actors"][0]["operations"], 1)

    def test_viz_uses_sun_commit_instead_of_normal_git_commit(self):
        write("manual.txt", "x\n")
        subprocess.run(["git", "add", "-A"], check=True)
        subprocess.run(["git", "commit", "-q", "-m", "manual"], check=True)
        normal = self.git("rev-parse", "HEAD").strip()
        data = sun.viz_data()
        commit = data["commits"][0]
        detail = "\n".join(sun.commit_lines(commit))
        self.assertNotIn(normal, [c["hash"] for c in data["commits"]])
        self.assertIn("subject       initial state", detail)
        self.assertIn("git identity  emma <sun@sun>", detail)
        self.assertIn("attributed to emma", detail)
        self.assertIn("edited by     emma", detail)
        self.assertNotIn("git committer", detail)
        self.assertNotIn("source        human", detail)
        self.assertNotIn("attribution   ", detail)

    def test_viz_tui_renders_commit_and_operation_attribution(self):
        self.agent_turn("session12345", [("foo.ts", "x\n")])
        class Screen:
            def __init__(self): self.writes = []
            def keypad(self, enabled): pass
            def erase(self): pass
            def getmaxyx(self): return 30, 140
            def addnstr(self, y, x, text, width, attr=0): self.writes.append(text[:width])
            def refresh(self): pass
            def timeout(self, milliseconds): pass
            def getch(self): return ord("q")
        screen = Screen()
        with mock.patch("curses.has_colors", return_value=True), \
                mock.patch("curses.start_color"), \
                mock.patch("curses.use_default_colors") as defaults:
            sun.viz_tui(screen, sun.viz_data())
        rendered = "\n".join(screen.writes)
        defaults.assert_called_once_with()
        self.assertIn("sun viz", rendered)
        self.assertIn("Claude Code", rendered)
        self.assertIn("edited by", rendered)
        self.assertIn("session       session12345", rendered)
        self.assertIn("timestamp", rendered)
        self.assertNotIn(AGENT, rendered)
        self.assertNotIn("source        agent", rendered)
        self.assertNotIn("observed", rendered)

    def test_viz_shows_branch_history_without_sun_refs(self):
        self.agent_turn("session12345", [("a.ts", "1\n")])
        sun.store_chunks("sess-viz", {"turn-0001.jsonl": "{}\n"})
        run("viz", "-o", "viz.html")
        html = read("viz.html")
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
            with mock.patch("sun.installed_git_source", return_value=(None, None)):
                self.assertIn("sun: Updated sun v0.1.0", run("update"))
        finally:
            sun.quiet = old
            os.chdir(self.dir)
            shutil.rmtree(outside, ignore_errors=True)
        self.assertEqual(calls, [("uv", "tool", "upgrade", "sun")])

    def test_update_skips_uv_when_git_head_is_installed(self):
        head = "a" * 40
        with mock.patch("sun.installed_git_source", return_value=("https://repo", head)), \
                mock.patch("sun.quiet", return_value=subprocess.CompletedProcess(
                    (), 0, stdout=f"{head}\tHEAD\n", stderr="")) as quiet:
            self.assertEqual(run("update"), "sun: already up to date\n")
        quiet.assert_called_once_with("git", "ls-remote", "https://repo", "HEAD")

    # ---------------------------------------------------------------- export

    def test_export_pairs_prompt_with_edits(self):
        run("init", "--share-sessions", "--no-instructions")
        tp = os.path.join(self.proj, "t.jsonl")
        write(tp, "")
        hook("UserPromptSubmit", transcript_path=tp)
        self.tool_call("session12345", "a.ts", "1\n")
        write(tp, json.dumps({"type": "user",
                              "message": {"role": "user", "content": "add feature"}}) + "\n" +
              transcript_line("a.ts", tid="tool0"))
        hook("Stop", transcript_path=tp)
        write("local.txt", "h\n")
        run("export", "-o", "dump.jsonl")
        recs = [json.loads(line) for line in read("dump.jsonl").splitlines()]
        turn = next(r for r in recs if r["actor"] == AGENT)
        self.assertEqual((turn["session"], turn["turn"], turn["prompt"]),
                         ("session12345", "turn1", "add feature"))
        self.assertEqual(turn["tool_calls"][0]["tool"], "Write")
        self.assertIn("+1", turn["edits"][0]["patch"])
        self.assertEqual(len([r for r in recs if r["actor"] == AGENT]), 1)  # squash subsumes
        loc = next(r for r in recs if r["edits"][0]["file"] == "local.txt")
        self.assertEqual((loc["actor"], loc["prompt"]), ("emma/local", None))

    def test_export_keeps_mid_turn_local_edit_out_of_agent_record(self):
        sid = "session12345"
        hook("UserPromptSubmit", sid)
        self.tool_call(sid, "a.ts", "1\n", 0)
        write("local.txt", "h\n")
        self.tool_call(sid, "b.ts", "2\n", 1)
        hook("Stop", sid)
        records = list(map(json.loads, run("export").splitlines()))
        turns = [r for r in records if r["actor"] == AGENT]
        self.assertEqual(len(turns), 1)
        self.assertEqual([c["id"] for c in turns[0]["tool_calls"]], ["tool0", "tool1"])
        self.assertEqual({d["file"] for d in turns[0]["edits"]}, {"a.ts", "b.ts"})
        local = next(r for r in records if r["actor"] == "emma/local")
        self.assertEqual([d["file"] for d in local["edits"]], ["local.txt"])

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
        self.assertEqual(self.git("show", "--name-only", "--format=", sun.shadow_ref()).split(),
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
        shutil.rmtree(".git/sun"); shutil.rmtree(".claude"); shutil.rmtree(".codex", ignore_errors=True)
        hook("PreToolUse")  # must not raise, and must not set up a repository nobody initialized
        self.assertFalse(os.path.exists(".git/sun"))
        os.makedirs(".git/sun")

    def test_sessionstart_only_prints_context_when_sharing(self):
        self.assertEqual(hook("SessionStart"), "")
        run("init", "--share-sessions", "--no-instructions")
        self.assertIn(".git/sun/sessions/", hook("SessionStart"))

    def test_codex_sessionstart_prints_codex_context_line(self):
        run("init", "--codex", "--share-sessions", "--no-instructions")
        out = hook("SessionStart", harness="codex")
        self.assertIn("sun data", out)


if __name__ == "__main__":
    unittest.main()
