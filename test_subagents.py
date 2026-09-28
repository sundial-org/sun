"""Claude Code subagents (Agent tool, ultracode workflows) recorded as their own actors.

Payload shapes follow what Claude Code sends: inside a subagent every hook carries the parent's
session_id and transcript_path plus agent_id and agent_type; SubagentStop adds
agent_transcript_path. Run with: python3 -m unittest test_subagents -v"""
import json, os, subprocess, sys, unittest
from concurrent.futures import ThreadPoolExecutor
import test_sun as fixtures
from test_sun import run, hook, write, read, read_json
from sun import checks, git_store, history, hooks, output, sessions

SID = "session12345"
PARENT = "emma/agent:claude/session12345"


def sub_hook(event, agent, sid=SID, agent_type="workflow-subagent", **extra):
    return hook(event, sid, agent_id=agent, agent_type=agent_type, **extra)


class SubagentTest(unittest.TestCase):
    setUp, tearDown = fixtures.SunTest.setUp, fixtures.SunTest.tearDown
    git, head_subject, tool_call = fixtures.SunTest.git, fixtures.SunTest.head_subject, fixtures.SunTest.tool_call

    def pre(self, agent, f, tid, tool="Write", **extra):
        inp = {"file_path": os.path.abspath(f)} if f else {"command": "true"}
        sub_hook("PreToolUse", agent, tool_name=tool, tool_input=inp, tool_use_id=tid, **extra)

    def post(self, agent, f, tid, tool="Write", **extra):
        inp = {"file_path": os.path.abspath(f)} if f else {"command": "true"}
        sub_hook("PostToolUse", agent, tool_name=tool, tool_input=inp, tool_use_id=tid, **extra)

    def sub_call(self, agent, f, text, tid, tool="Write", **extra):
        self.pre(agent, f, tid, tool, **extra)
        write(f, text)
        self.post(agent, f, tid, tool, **extra)

    def changes(self):  # file -> (actor, method) of its latest recorded edit
        return {d["file"]: (e["actor"], d["attribution"]["method"])
                for e in history.events() for d in e.get("edits") or []}

    def claim_lanes(self):
        return sorted(c["lane"] for c in git_store.state("active.json", {}).values())

    def project(self):  # stands in for ~/.claude/projects/<this repo>
        d = os.path.join(self.proj, sessions.enc(git_store.root()))
        os.makedirs(d, exist_ok=True)
        return d

    # ------------------------------------------------------------ actor ids

    def test_subagent_actor_extends_the_session_actor(self):
        actor = git_store.agent(SID, sub="a1")
        self.assertEqual(actor, PARENT + "/a1")
        info = git_store.actor_info(actor)
        self.assertEqual((info["kind"], info["harness"], info["session"], info["agent"], info["parent"]),
                         ("agent", "claude", SID, "a1", PARENT))
        self.assertEqual((git_store.actor_info(PARENT)["agent"], git_store.actor_info(PARENT)["parent"]), (None, None))
        self.assertIsNone(git_store.actor_info("emma/local")["agent"])
        self.assertTrue(git_store.in_session(actor, SID) and git_store.in_session(PARENT, SID))
        # A longer session id sharing the prefix is a different session.
        self.assertFalse(git_store.in_session(PARENT + "6", SID))
        self.assertFalse(git_store.in_session("zoe/agent:claude/session12345/a1", SID))
        self.assertEqual(checks.check_level(actor), "agent")

    def test_agent_id_is_one_safe_path_segment(self):
        self.assertEqual(hooks.agent_of({"agent_id": "../x/y"}), "___x_y")
        self.assertEqual(hooks.agent_of({"agent_id": ".."}), "__")
        self.assertIsNone(hooks.agent_of({}))
        self.sub_call("../evil", "safe.txt", "x\n", "t1")
        self.assertEqual(self.changes()["safe.txt"][0], PARENT + "/___evil")

    def test_init_hooks_subagent_events_for_claude(self):
        cfg = read_json(".claude/settings.json")
        for event in ("SubagentStart", "SubagentStop"):
            self.assertIn("sun hook", [h["command"] for g in cfg["hooks"][event] for h in g["hooks"]])
        self.assertEqual(len(hooks.CODEX_HOOK_EVENTS), len(set(hooks.CODEX_HOOK_EVENTS)))
        self.assertIn("SubagentStop", hooks.CODEX_HOOK_EVENTS)
        self.assertNotIn("PostToolUseFailure", hooks.CODEX_HOOK_EVENTS)

    # ------------------------------------------------------------ attribution

    def test_workflow_subagents_and_parent_are_distinct_actors(self):
        hook("UserPromptSubmit", SID)
        hook("PreToolUse", SID, tool_name="Workflow", tool_input={"script": "..."}, tool_use_id="wf")
        self.assertEqual(git_store.state("active.json", {}), {})
        hook("PostToolUse", SID, tool_name="Workflow", tool_input={"script": "..."}, tool_use_id="wf")
        for agent in ("a1", "a2"): sub_hook("SubagentStart", agent)
        self.pre("a1", "a.txt", "t1")
        self.pre("a2", "b.txt", "t2")
        self.assertEqual(self.claim_lanes(), [SID + "/a1", SID + "/a2"])
        write("a.txt", "a\n")
        write("b.txt", "b\n")
        self.post("a2", "b.txt", "t2")
        self.post("a1", "a.txt", "t1")
        self.tool_call(SID, "c.txt", "c\n", 9)
        self.assertEqual(self.changes(), {"a.txt": (PARENT + "/a1", "hook"), "b.txt": (PARENT + "/a2", "hook"),
                                          "c.txt": (PARENT, "hook")})
        agent_events = [e for e in history.events() if "/agent:" in e["actor"]]
        self.assertEqual({e["session_id"] for e in agent_events}, {SID})
        self.assertEqual({e["turn"] for e in agent_events}, {"turn1"})
        self.assertEqual({e["tool_calls"][0]["id"] for e in agent_events}, {"t1", "t2", "tool9"})
        actors = {a["id"]: a for a in json.loads(run("data"))["actors"]}
        self.assertEqual(actors[PARENT + "/a1"]["agent"], "a1")
        self.assertEqual(actors[PARENT + "/a2"]["parent"], PARENT)
        self.assertIsNone(actors[PARENT]["agent"])

    def test_delegating_call_claims_nothing_and_subagent_edits_are_certain(self):
        hook("UserPromptSubmit", SID)
        hook("PreToolUse", SID, tool_name="Agent", tool_input={"prompt": "go"}, tool_use_id="spawn")
        self.assertEqual(git_store.state("active.json", {}), {})  # sync, undo and viz are not blocked
        write("human.txt", "typed while the subagent ran\n")
        sub_hook("SubagentStart", "a1", agent_type="general-purpose")
        self.sub_call("a1", "s.txt", "subagent\n", "t1", agent_type="general-purpose")
        run("undo", "--dry-run")  # would refuse if the Agent call held a claim
        sub_hook("SubagentStop", "a1", agent_type="general-purpose")
        before = len(history.events())
        hook("PostToolUse", SID, tool_name="Agent", tool_input={"prompt": "go"}, tool_use_id="spawn")
        self.assertEqual(len(history.events()), before)
        self.assertEqual(self.changes()["s.txt"], (PARENT + "/a1", "hook"))
        self.assertEqual(self.changes()["human.txt"], ("emma/local", "hook"))

    def test_read_only_harness_tools_do_not_blur_sibling_edits(self):
        self.pre("a1", None, "search", tool="ToolSearch")
        self.sub_call("a2", "t.txt", "x\n", "t2")
        self.post("a1", None, "search", tool="ToolSearch")
        self.assertEqual(self.changes()["t.txt"], (PARENT + "/a2", "hook"))

    def test_sibling_shell_never_absorbs_a_file_another_subagent_names(self):
        self.pre("a1", None, "sh", tool="Bash")
        self.pre("a2", "named.txt", "w")
        write("named.txt", "from a2's Write\n")
        write("shell.txt", "from a1's shell\n")
        self.post("a1", None, "sh", tool="Bash")  # finishes first, with named.txt already on disk
        self.assertNotIn("named.txt", self.changes())
        self.assertEqual(self.changes()["shell.txt"], (PARENT + "/a1", "hook"))
        self.post("a2", "named.txt", "w")
        # The shell could have touched it too: the named call keeps it, marked uncertain.
        self.assertEqual(self.changes()["named.txt"], (PARENT + "/a2", "uncertain"))

    def test_same_session_shell_does_not_absorb_the_parents_named_file(self):
        self.pre("a1", None, "sh", tool="Bash")
        hook("PreToolUse", SID, tool_name="Edit", tool_use_id="p", tool_input={"file_path": os.path.abspath("p.txt")})
        write("p.txt", "parent\n")
        self.post("a1", None, "sh", tool="Bash")
        hook("PostToolUse", SID, tool_name="Edit", tool_use_id="p", tool_input={"file_path": os.path.abspath("p.txt")})
        self.assertEqual(self.changes()["p.txt"], (PARENT, "uncertain"))

    def test_overlapping_sibling_calls_credit_the_session_not_a_guessed_subagent(self):
        self.pre("a1", None, "sh1", tool="Bash")
        self.pre("a2", None, "sh2", tool="Bash")
        write("either.txt", "who knows\n")
        self.post("a2", None, "sh2", tool="Bash")
        self.post("a1", None, "sh1", tool="Bash")
        self.assertEqual(self.changes()["either.txt"], (PARENT, "uncertain"))
        self.pre("a1", "same.txt", "w1")
        self.pre("a2", "same.txt", "w2")
        write("same.txt", "both wrote\n")
        self.post("a1", "same.txt", "w1")
        self.post("a2", "same.txt", "w2")
        self.assertEqual(self.changes()["same.txt"], (PARENT, "uncertain"))
        self.assertEqual(git_store.state("active.json", {}), {})

    def test_same_lane_calls_keep_the_subagent(self):
        self.pre("a1", None, "sh1", tool="Bash")
        self.pre("a1", None, "sh2", tool="Bash")  # one subagent's parallel shells
        write("mine.txt", "a1\n")
        self.post("a1", None, "sh1", tool="Bash")
        self.post("a1", None, "sh2", tool="Bash")
        self.assertEqual(self.changes()["mine.txt"], (PARENT + "/a1", "uncertain"))

    def test_another_sessions_overlap_is_still_unknown(self):
        hook("PreToolUse", "other-session", tool_name="Bash", tool_use_id="sh", tool_input={})
        self.pre("a1", "w.txt", "w")
        write("w.txt", "x\n")
        self.post("a1", "w.txt", "w")
        self.assertEqual(self.changes()["w.txt"], ("unknown", "uncertain"))

    def test_parallel_subagent_hook_processes(self):
        agents = [f"agent{i}" for i in range(6)]
        def invoke(event, agent):
            payload = {"cwd": os.getcwd(), "hook_event_name": event, "session_id": SID, "agent_id": agent,
                       "agent_type": "workflow-subagent", "tool_name": "Write", "tool_use_id": "t-" + agent,
                       "tool_input": {"file_path": os.path.abspath(agent + ".txt")}}
            env = {**os.environ, "PYTHONPATH": os.path.dirname(os.path.abspath(__file__))}
            subprocess.run([sys.executable, "-m", "sun", "hook"], env=env, input=json.dumps(payload),
                           capture_output=True, text=True, check=True)
        with ThreadPoolExecutor(len(agents)) as pool:
            list(pool.map(lambda agent: invoke("SubagentStart", agent), agents))
            list(pool.map(lambda agent: invoke("PreToolUse", agent), agents))
            for agent in agents: write(agent + ".txt", agent + "\n")
            list(pool.map(lambda agent: invoke("PostToolUse", agent), agents))
        self.assertEqual(self.changes(), {a + ".txt": (f"{PARENT}/{a}", "hook") for a in agents})
        self.assertEqual(git_store.state("active.json", {}), {})

    # ------------------------------------------------------------ claim release

    def test_parent_stop_keeps_a_running_subagents_call(self):
        hook("UserPromptSubmit", SID)
        sub_hook("SubagentStart", "a1")
        self.pre("a1", "late.txt", "t1")
        hook("Stop", SID)  # workflow subagents outlive the parent's turn
        hook("UserPromptSubmit", SID)  # a background task notification
        self.assertEqual(self.claim_lanes(), [SID + "/a1"])
        write("late.txt", "done after the parent stopped\n")
        self.post("a1", "late.txt", "t1")
        self.assertEqual(self.changes()["late.txt"], (PARENT + "/a1", "hook"))
        sub_hook("SubagentStop", "a1")
        self.assertEqual(git_store.state("subagents.json", {}), {})

    def test_subagent_stop_releases_only_its_own_calls(self):
        for agent in ("a1", "a2"): sub_hook("SubagentStart", agent)
        self.pre("a1", "p.txt", "t1")
        self.pre("a2", "q.txt", "t2")
        hook("PreToolUse", SID, tool_name="Write", tool_use_id="pp", tool_input={"file_path": os.path.abspath("r.txt")})
        write("p.txt", "interrupted\n")
        sub_hook("SubagentStop", "a1")  # a1 was stopped mid-call: no PostToolUse
        self.assertEqual(self.claim_lanes(), [SID, SID + "/a2"])
        self.assertEqual(self.changes()["p.txt"], ("unknown", "uncertain"))
        self.assertEqual(git_store.state("subagents.json", {}), {SID: {"a2": "workflow-subagent"}})
        write("q.txt", "q\n")
        self.post("a2", "q.txt", "t2")
        self.assertEqual(self.changes()["q.txt"], (PARENT + "/a2", "hook"))

    def test_parent_stop_releases_subagents_it_never_saw_start(self):
        # Hook configurations from before SubagentStart was installed: fall back to the old release.
        self.pre("a1", "r.txt", "t1")
        write("r.txt", "abandoned\n")
        hook("Stop", SID)
        self.assertEqual(git_store.state("active.json", {}), {})
        self.assertEqual(self.changes()["r.txt"], ("unknown", "uncertain"))

    def test_session_start_releases_every_lane_except_on_compaction(self):
        sub_hook("SubagentStart", "a1")
        self.pre("a1", "c.txt", "t1")
        hook("SessionStart", SID, source="compact")
        self.assertEqual(self.claim_lanes(), [SID + "/a1"])
        hook("SessionStart", SID, source="resume")
        self.assertEqual(git_store.state("active.json", {}), {})
        self.assertEqual(git_store.state("subagents.json", {}), {})

    def test_legacy_claims_without_lanes_are_released_and_compared(self):
        # A claim written by an earlier Sun: key <session>/<call>, no session/lane/agent fields.
        hook("PreToolUse", SID, tool_name="Write", tool_use_id="old", tool_input={"file_path": os.path.abspath("o.txt")})
        active = git_store.state("active.json", {})
        for field in ("session", "lane", "agent"): active[SID + "/old"].pop(field)
        git_store.save_state("active.json", active)
        sub_hook("SubagentStart", "a1")
        self.pre("a1", "o.txt", "new")  # names the same file from a sibling lane
        self.assertTrue(git_store.state("active.json", {})[SID + "/old"]["ambiguous_agent"])
        hook("Stop", SID)
        self.assertEqual(self.claim_lanes(), [SID + "/a1"])

    # ------------------------------------------------------------ turns and checks

    def test_turn_squash_includes_subagent_calls(self):
        hook("UserPromptSubmit", SID)
        self.tool_call(SID, "parent.txt", "p\n", 1)
        sub_hook("SubagentStart", "a1")
        self.sub_call("a1", "child.txt", "c\n", "t1")
        sub_hook("SubagentStop", "a1")  # a foreground Agent call returns before the parent stops
        hook("Stop", SID)
        self.assertEqual(self.head_subject(), f"sun: {PARENT} turn 1 (2 tool calls)")
        head = self.git("rev-parse", git_store.shadow_ref()).strip()
        evs = [e for e in history.events() if e["commit"] == head]
        self.assertEqual({e["actor"] for e in evs}, {PARENT, PARENT + "/a1"})
        self.assertTrue(all(e.get("snapshot") for e in evs))  # each call stays inspectable
        t = git_store.state("turns.json", {})[SID]
        self.assertEqual(hooks.turn_unit(SID, "claude", t)["files"], ["child.txt", "parent.txt"])

    def test_turn_of_only_subagent_work_still_squashes(self):
        hook("UserPromptSubmit", SID)
        for i, agent in enumerate(("a1", "a2")):
            self.sub_call(agent, f"{agent}.txt", "x\n", f"t{i}")
        hook("Stop", SID)
        self.assertEqual(self.head_subject(), f"sun: {PARENT} turn 1 (2 tool calls)")

    def test_turn_waits_for_running_subagents_before_squashing(self):
        hook("UserPromptSubmit", SID)
        sub_hook("SubagentStart", "a1")
        self.tool_call(SID, "parent.txt", "p\n", 1)
        hook("Stop", SID)  # the workflow keeps running after the parent's turn ends
        self.sub_call("a1", "late.txt", "x\n", "t1")
        self.assertNotIn(" turn 1 ", self.head_subject())
        sub_hook("SubagentStop", "a1")
        self.assertEqual(self.head_subject(), f"sun: {PARENT} turn 1 (2 tool calls)")
        self.assertEqual(hooks.turn_unit(SID, "claude", git_store.state("turns.json", {})[SID])["files"],
                         ["late.txt", "parent.txt"])

    def test_next_prompt_squashes_a_turn_left_open_for_subagents(self):
        hook("UserPromptSubmit", SID)
        sub_hook("SubagentStart", "a1")
        self.sub_call("a1", "one.txt", "x\n", "t1")
        hook("Stop", SID)
        hook("UserPromptSubmit", SID)  # a background task notification while a1 still runs
        self.assertEqual(self.head_subject(), f"sun: {PARENT} turn 1 (1 tool calls)")
        self.sub_call("a1", "two.txt", "x\n", "t2")
        sub_hook("SubagentStop", "a1")  # the parent's turn 2 is still going: no squash yet
        self.assertNotIn(" turn 2 ", self.head_subject())
        hook("Stop", SID)
        self.assertEqual(self.head_subject(), f"sun: {PARENT} turn 2 (1 tool calls)")

    def test_in_flight_session_counts_subagent_calls_as_the_session(self):
        hook("PreToolUse", SID, tool_name="Bash", tool_use_id="p", tool_input={})
        self.pre("a1", "x.txt", "t1")
        self.assertEqual(checks.in_flight_session(), SID)
        hook("PreToolUse", "other-session", tool_name="Read", tool_use_id="r", tool_input={})
        self.assertIsNone(checks.in_flight_session())

    # ------------------------------------------------------------ transcripts and output

    def workflow_transcripts(self):
        d = self.project()
        parent = os.path.join(d, SID + ".jsonl")
        run_dir = os.path.join(d, SID, "subagents", "workflows", "wf_1")
        child = os.path.join(run_dir, "agent-a1.jsonl")
        write(parent, json.dumps({"type": "user", "message": {"role": "user", "content": "ultracode: fan out"}}) + "\n")
        write(child, json.dumps({"type": "user", "message": {"role": "user", "content": "write the probe file"}}) + "\n"
              + json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [
                  {"type": "text", "text": "Writing it now."},
                  {"type": "tool_use", "id": "t1", "name": "Write", "input": {"file_path": "probe.txt"}}]}}) + "\n")
        write(child[:-6] + ".meta.json", json.dumps({"agentType": "workflow-subagent", "description": "probe:0",
                                                      "workflowPhase": "Probe", "spawnDepth": 1}))
        write(os.path.join(run_dir, "journal.jsonl"), json.dumps({"type": "launched"}) + "\n")
        write(os.path.join(d, SID, "subagents", "workflows", "wf_2", "journal.jsonl"), "{}\n")
        return parent, child

    def test_subagent_transcript_found_before_it_stops(self):
        parent, child = self.workflow_transcripts()
        sub_hook("SubagentStart", "a1", transcript_path=parent)
        entry = git_store.state("session-paths.json", {})[SID]
        self.assertEqual((entry["path"], entry["subagents"]), (parent, {"a1": child}))
        self.assertEqual(entry["agents"]["a1"]["type"], "workflow-subagent")
        other = os.path.join(self.project(), SID, "subagents", "agent-a2.jsonl")
        write(other, "{}\n")
        sub_hook("SubagentStop", "a2", agent_type="general-purpose", transcript_path=parent,
                 agent_transcript_path=other)
        self.assertEqual(git_store.state("session-paths.json", {})[SID]["subagents"], {"a1": child, "a2": other})

    def test_transcript_discovery_skips_workflow_journals(self):
        parent, child = self.workflow_transcripts()
        found = sorted(((sid, sub) for _, sid, sub in sessions.transcript_sources("claude")), key=str)
        self.assertEqual(found, [(SID, "a1"), (SID, None)])
        entry = next(s for s in json.loads(run("data"))["sessions"] if s["id"] == SID)
        self.assertEqual(entry["subagents"], {"a1": child})
        self.assertEqual(entry["agents"]["a1"], {"type": "workflow-subagent", "label": "probe:0", "phase": "Probe"})

    def test_blame_viz_and_export_show_the_subagent(self):
        parent, child = self.workflow_transcripts()
        hook("UserPromptSubmit", SID, transcript_path=parent)
        sub_hook("SubagentStart", "a1", transcript_path=parent)
        self.sub_call("a1", "probe.txt", "probe line\n", "t1", transcript_path=parent)
        hook("Stop", SID, transcript_path=parent)
        out = run("blame", "probe.txt", "1")
        self.assertIn(PARENT + "/a1", out)
        self.assertIn(f"session {SID} subagent a1 ({child})", out)
        self.assertIn("user: write the probe file", out)
        self.assertIn("agent: Writing it now.", out)
        op = next(o for c in output.viz_data()["commits"] for o in c["operations"] if o["actor"] == PARENT + "/a1")
        self.assertEqual(op["subagent"], {"id": "a1", "type": "workflow-subagent", "label": "probe:0",
                                          "phase": "Probe", "path": child})
        self.assertEqual(op["session_path"], parent)
        lines = output.operation_lines(op)
        self.assertIn("edited by     Claude Code subagent a1", lines)
        self.assertIn("subagent      a1  workflow-subagent  probe:0", lines)
        record = json.loads(run("export").splitlines()[-1])
        self.assertEqual((record["actor"], record["session"], record["prompt"]), (PARENT + "/a1", SID, "write the probe file"))

    def test_shared_subagent_transcript_is_stored_under_its_id(self):
        run("init", "--share-sessions", "--no-instructions")
        parent, child = self.workflow_transcripts()
        sub_hook("SubagentStop", "a1", transcript_path=parent, agent_transcript_path=child)
        names = self.git("ls-tree", "-r", "--name-only", f"refs/sun/sessions/emma/{SID}").split()
        self.assertEqual(names, ["subagents/a1/transcript.jsonl"])
        run("sessions", "import")
        names = self.git("ls-tree", "-r", "--name-only", f"refs/sun/sessions/emma/{SID}").split()
        self.assertNotIn("journal", " ".join(names))
        self.assertIn("subagents/a1/turn-0001.jsonl", names)


if __name__ == "__main__":
    unittest.main()
