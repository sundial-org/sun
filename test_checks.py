"""Tests for rules, checks and coverage: judgments recorded over the operation history."""
import json, os, shutil, subprocess, sys, tempfile, time, unittest
import test_sun as fixtures
from test_sun import run, hook, write, read, sun


def terminal_env():  # an agent's shell, a judge, or Codex may be running these tests
    for k in list(os.environ):
        if k in ("CLAUDECODE", "SUN_CHECKING") or k.startswith("CODEX_SANDBOX"): del os.environ[k]
def base_branch():
    return subprocess.run(["git", "symbolic-ref", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()


class ChecksTest(unittest.TestCase):
    tearDown = fixtures.SunTest.tearDown
    git, sun_head, tool_call = fixtures.SunTest.git, fixtures.SunTest.sun_head, fixtures.SunTest.tool_call
    agent_turn = fixtures.SunTest.agent_turn

    def setUp(self):
        fixtures.SunTest.setUp(self)
        terminal_env()  # the tests are a person at a terminal, even when an agent runs them
        write("RULES", "# how work should go here\nhonest: The report lists what was proved.\n"
                       "tidy: No stray files.\n")
        run("sync")

    def check(self, *reqs, **fields):
        return json.loads(run("check", "--json", stdin=list(reqs) or fields))["checks"]

    def row(self, commit, rule="honest"):
        commits = {c["commit"]: c for c in json.loads(run("coverage", "--json", "-n", "0"))["commits"]}
        return next(r for r in commits[commit]["rules"] if r["rule"] == rule)

    def refused(self, *reqs, **fields):
        before = sun.refs("refs/sun/checks/")
        with self.assertRaises(SystemExit) as raised: self.check(*reqs, **fields)
        self.assertEqual(sun.refs("refs/sun/checks/"), before)  # nothing was written
        return str(raised.exception)

    def test_a_program_a_judge_and_a_person_write_the_same_shape(self):
        tip = self.sun_head()
        self.check(rule="honest", verdict="contradicted", actor="program:lean", note="sorry in L003",
                   cites=[{"at": tip, "file": "RULES", "lines": [2, 2]}], meta={"synthetic": True})
        self.check(rule="honest", verdict="supported", actor="agent:judge", cites=[{"at": tip}])
        self.assertIn("honest supported", run("check", "honest", "supported", "-m", "read it"))
        stored = list(sun.checks().values())
        self.assertEqual({c["actor"] for c in stored}, {"emma/program:lean", "emma/agent:judge", "emma/local"})
        self.assertEqual({tuple(sorted(set(c) - {"note", "meta"})) for c in stored},
                         {("actor", "cites", "id", "rule", "rule_text", "timestamp", "type", "verdict", "via")})
        self.assertEqual({c["via"] for c in stored}, {"stdin", "terminal"})
        self.assertTrue(all(ref.startswith("refs/sun/checks/emma/") for ref, _ in sun.refs("refs/sun/checks/")))

    def test_a_check_must_cite_recorded_state(self):
        tip, normal = self.sun_head(), self.git("rev-parse", "HEAD").strip()  # Sun never recorded `normal`
        good = {"rule": "honest", "verdict": "pass", "actor": "program:t", "cites": [{"at": tip}]}
        for change, message in [(dict(cites=[]), "must cite"), (dict(cites=[{"at": normal}]), "nothing recorded"),
                                (dict(cites=[{"at": tip, "file": "missing.txt"}]), "is not in"),
                                (dict(cites=[{"check": "0" * 32}]), "a cite is"), (dict(cites=[{"check": [1]}]), "a cite is"),
                                (dict(rule="unknown"), "no rule"),
                                (dict(verdict=""), "verdict"), (dict(actor=None), "declares an actor"),
                                (dict(actor="agent:x/local"), "declares an actor"),
                                (dict(note="x" * (16 << 10)), "16 KiB")]:
            self.assertIn(message, self.refused({**good, **change}))
        self.assertIn("no rule", self.refused(good, {**good, "rule": "unknown"}))  # a batch is all or nothing

    def test_the_same_check_twice_is_one_check(self):
        req = dict(rule="honest", verdict="pass", actor="program:t", cites=[{"at": self.sun_head()}])
        first, = self.check(**req)
        time.sleep(1.1)  # a retry, a second later
        self.assertEqual(self.check(**req), [first])
        self.assertEqual(len(sun.checks()), 1)

    def test_layer_one_never_sees_checks(self):
        self.agent_turn("session12345", [("a.txt", "a\n")])
        before = [run("log"), run("show", "HEAD"), run("export"), json.dumps(sun.events())]
        self.check(rule="tidy", verdict="pass", actor="program:t",
                   cites=[{"at": self.sun_head(), "file": "a.txt", "lines": [1, 1]}])
        self.assertEqual([run("log"), run("show", "HEAD"), run("export"), json.dumps(sun.events())], before)

    def test_a_check_written_mid_turn_lands_on_the_squashed_turn(self):
        hook("UserPromptSubmit")
        self.tool_call("session12345", "a.txt", "a\n", 0)
        mid = self.sun_head()
        self.check(rule="honest", verdict="pass", actor="program:t", cites=[{"at": mid, "file": "a.txt"}])
        self.tool_call("session12345", "b.txt", "b\n", 1)
        hook("Stop")
        turn = self.sun_head()
        self.assertNotIn(mid, self.git("rev-list", sun.shadow_ref()).split())  # the squash replaced it
        self.assertEqual(self.row(turn)["status"], "pass")
        self.assertEqual(self.git("show", f"{mid}:a.txt"), "a\n")  # the cited state is still readable

    def test_coverage_is_unchecked_a_verdict_or_mixed(self):
        first = self.sun_head()
        self.agent_turn("session12345", [("a.txt", "a\n")])
        turn = self.sun_head()
        self.assertEqual(self.row(turn)["status"], "unchecked")
        self.check(rule="honest", verdict="supported", actor="agent:judge", cites=[{"at": turn}])
        self.assertEqual(self.row(turn)["status"], "supported")
        self.check(rule="honest", verdict="contradicted", actor="program:lean", cites=[{"at": turn}])
        self.assertEqual(self.row(turn)["status"], "mixed")
        self.assertEqual((self.row(turn, "tidy")["status"], self.row(first)["status"]), ("unchecked",) * 2)
        self.assertIn("mixed", run("coverage"))
        self.assertEqual(len(run("coverage", "-n", "1").splitlines()), 3)  # one commit, two rules

    def test_a_review_replaces_the_check_it_cites(self):
        turn = self.sun_head()
        judge, = self.check(rule="honest", verdict="supported", actor="agent:judge", cites=[{"at": turn}])
        review, = self.check(verdict="contradicted", actor="agent:second", cites=[{"check": judge["id"]}])
        self.assertEqual((review["rule"], review["cites"]), ("honest", [{"check": judge["id"]}]))
        self.assertEqual(self.row(turn)["status"], "contradicted")
        self.assertEqual({c["id"] for c in self.row(turn)["checks"]}, {judge["id"], review["id"]})
        self.assertIn("keeps the rule", self.refused(rule="tidy", verdict="x", actor="agent:second",
                                                     cites=[{"check": judge["id"]}]))

    def test_a_long_chain_of_reviews_still_folds(self):
        turn = self.sun_head()
        last, = self.check(rule="honest", verdict="v0", actor="agent:a", cites=[{"at": turn}])
        chain, files = [], tempfile.mkdtemp()
        for n in range(1, 1100):  # deeper than Python's recursion limit; each hashes to its own ID
            c = {"type": "check", "actor": "emma/agent:a", "rule": "honest", "verdict": f"v{n}",
                 "cites": [{"check": last["id"]}]}
            last = {**c, "id": sun.check_id(c)}
            write(os.path.join(files, last["id"]), json.dumps(last))
            chain.append(last["id"])
        blobs = subprocess.run(["git", "hash-object", "-w", "--stdin-paths"], text=True, check=True,
                               input="".join(os.path.join(files, i) + "\n" for i in chain),
                               capture_output=True).stdout.split()
        subprocess.run(["git", "update-ref", "--stdin"], text=True, check=True, input="".join(
            f"create refs/sun/checks/emma/{i} {sha}\n" for i, sha in zip(chain, blobs)))
        self.assertEqual(self.row(turn)["status"], "v1099")

    def test_only_a_person_at_the_terminal_counts_as_eyes(self):
        turn = self.sun_head()
        judge, = self.check(rule="honest", verdict="pass", actor="human:ana", cites=[{"at": turn}])  # declared
        self.assertFalse(self.row(turn)["eyes"])
        call = dict(tool_name="Bash", tool_input={"command": "sun check honest pass"}, tool_use_id="bash0")
        hook("PreToolUse", **call)
        with self.assertRaises(SystemExit): run("check", "honest", "pass")  # an agent's shell is not you
        hook("PostToolUse", **call)
        run("check", "honest", "fail", judge["id"][:8], "-m", "the receipt shows sorry")  # you review the judge
        self.assertEqual((self.row(turn)["status"], self.row(turn)["eyes"]), ("fail", "terminal"))
        mine = next(c for c in sun.checks().values() if c["actor"] == "emma/local")
        self.check(verdict="pass", actor="agent:second", cites=[{"check": mine["id"]}])
        self.assertFalse(self.row(turn)["eyes"])  # your check was replaced, so it needs your eyes again

    def test_a_person_checks_what_they_see(self):
        write("draft.txt", "not yet recorded\n")
        run("check", "tidy", "fail", "-m", "stray draft")
        tip = self.sun_head()
        self.assertEqual(self.git("show", f"{tip}:draft.txt"), "not yet recorded\n")
        self.assertEqual(self.row(tip, "tidy")["status"], "fail")

    def test_a_tampered_or_malformed_fetched_check_is_ignored(self):
        turn = self.sun_head()
        real, = self.check(rule="honest", verdict="fail", actor="program:t", cites=[{"at": turn}])
        odd = {"rule": "honest", "verdict": "pass", "actor": "x/local", "cites": [{"at": []}]}  # hashes fine
        odd["id"] = sun.check_id(odd)
        self.git("update-ref", "refs/sun/checks/" + odd["id"], sun.blob(json.dumps(odd)))
        for i, fake in enumerate(["not json", "[" * 100000, json.dumps({**real, "verdict": "pass"}), json.dumps([1])]):
            self.git("update-ref", f"refs/sun/checks/emma/{i:032x}", sun.blob(fake))
        stray = {**real, "actor": "ana/local"}; stray["id"] = sun.check_id(stray)  # pushed under the wrong name
        self.git("update-ref", "refs/sun/checks/emma/" + stray["id"], sun.blob(json.dumps(stray)))
        self.git("update-ref", sun.check_ref(real), sun.blob(json.dumps({**real, "verdict": "pass"})))
        self.assertEqual(sun.checks(), {})
        self.assertEqual(self.row(turn)["status"], "unchecked")

    def test_checks_travel_and_never_block_history(self):
        with tempfile.TemporaryDirectory() as remote, tempfile.TemporaryDirectory() as clone:
            self.git("init", "--bare", remote)
            self.git("remote", "add", "origin", remote)
            self.git("add", "."); self.git("commit", "-m", "rules and hooks")
            self.git("push", "--no-verify", "origin", "HEAD")
            run("log")
            turn = self.sun_head()
            twin = dict(rule="tidy", verdict="pass", actor="program:t", cites=[{"at": turn}])
            mine, = self.check(rule="honest", verdict="pass", actor="program:t", cites=[{"at": turn}])
            run("push")
            self.git("clone", remote, clone)
            try:
                os.chdir(clone)
                self.git("config", "user.name", "emma")  # the same person on a second machine
                run("init", "--no-instructions")  # configures the fetch refspecs, then fetches
                self.assertEqual(sun.checks()[mine["id"]], mine)
                self.check(verdict="fail", actor="agent:second", cites=[{"check": mine["id"]}])
                self.check(**twin)
                run("push")
            finally:
                os.chdir(self.dir)
            with tempfile.TemporaryDirectory() as behind:  # a clone whose Sun history has diverged
                self.git("clone", remote, behind)
                os.chdir(behind)
                try:
                    subprocess.run(["git", "config", "user.name", "carol"], check=True)
                    write("c.txt", "c\n")  # the clone's own initial state differs from the shared tip
                    run("init", "--no-instructions")
                    stranded, = self.check(rule="tidy", verdict="pass", actor="program:t", cites=[{"at": turn}])
                    run("push")  # a diverged history is fetched and joined, never rejected
                finally:
                    os.chdir(self.dir)
            self.assertIn(stranded["id"], self.git("--git-dir", remote, "for-each-ref", "refs/sun/checks/"))
            time.sleep(1.1)
            self.check(**twin)  # the same check, recorded on two machines: one ID, two timestamps
            write("later.txt", "later\n"); run("sync")
            run("push")  # the remote keeps its copy of the twin, and history is still published
            self.assertEqual(self.git("--git-dir", remote, "rev-parse", sun.shadow_ref()).strip(), self.sun_head())
            self.git("fetch", "origin", *sun.refspecs())  # this clone ran init before origin existed
            self.assertEqual(self.row(turn)["status"], "fail")
            self.assertIn(stranded["id"], [c["id"] for c in self.row(turn, "tidy")["checks"]])

    def test_a_slow_producer_does_not_hold_the_lock(self):
        req = json.dumps({"rule": "honest", "verdict": "pass", "actor": "program:t",
                          "cites": [{"at": self.sun_head()}]})
        slow = subprocess.Popen([sys.executable, sun.__file__, "check"], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, text=True)
        try:
            time.sleep(0.5)  # the checker is running and waiting on its input
            subprocess.run([sys.executable, sun.__file__, "log"], stdout=subprocess.DEVNULL,
                           check=True, timeout=10)  # a held lock would be a timeout, not a hang
            self.assertIn("honest pass", slow.communicate(req, timeout=30)[0])
        finally:
            slow.kill(); slow.communicate()


if __name__ == "__main__":
    unittest.main()


JUDGE = """import json, sys
p = sys.stdin.read()
ok = "Rule `honest`" in p and "Diff:" in p and "File notes.md" in p
print("chatter"); print(json.dumps({"verdict": "pass" if ok else "fail", "note": "saw the diff" if ok else "bad prompt",
                                   "cites": [{"file": "notes.md", "lines": [1, 1]}, {"file": "missing.md"}]}))
"""
EXTRACTOR = """import json, sys
p = sys.stdin.read()
reply = p.split("The person's reply:\\n", 1)[1].split("\\n\\nInstructions:", 1)[0]
out = []
if "look right" in reply: out.append({"rule": "honest", "verdict": "pass", "quote": "the notes look right", "files": ["notes.md"]})
if "stray" in reply: out.append({"rule": "tidy", "verdict": "fail", "quote": "not what they said", "files": []})
print(json.dumps(out))
"""
LOWERCASE = """#!/bin/sh
for f in $SUN_FILES; do git show "$SUN_AT:$f" | grep -q '^[A-Z]' && { echo "$f: uppercase"; exit 1; }; done
echo "rule=$SUN_RULE since=$SUN_SINCE"
"""


class RulesTest(unittest.TestCase):
    """RULES.md: rules that name a command, a model, or an agent, run on request or from hooks."""
    tearDown = fixtures.SunTest.tearDown
    git, sun_head, tool_call = fixtures.SunTest.git, fixtures.SunTest.sun_head, fixtures.SunTest.tool_call
    agent_turn = fixtures.SunTest.agent_turn
    row, check = ChecksTest.row, ChecksTest.check

    def setUp(self):
        fixtures.SunTest.setUp(self)
        terminal_env()
        write("judge.py", JUDGE); write("extract.py", EXTRACTOR); write("scripts/lowercase.sh", LOWERCASE)
        os.chmod("scripts/lowercase.sh", 0o755)
        self.rules(extract="python3 extract.py")
        run("sync")

    def rules(self, **front):
        head = "---\n" + "".join(f"{k}: {v}\n" for k, v in front.items()) + "---\n" if front else ""
        write("RULES.md", head + "# Rules\n\n## honest\n---\nmodel: python3 judge.py\non: turn\n---\n"
              "The notes report what was measured.\n\n## lowercase\n---\nrun: scripts/lowercase.sh\non: call\n"
              "files: \"*.md\"\n---\nEvery line starts with a lowercase character.\n\n## tidy\nNo stray files.\n"
              "\n## Not a rule\ntext under a heading that is not a rule name\n")

    def test_rules_md_front_matter_and_legacy_rules(self):
        config, rs = sun.read_rules()
        self.assertEqual(config, {"extract": "python3 extract.py"})
        self.assertEqual(sorted(rs), ["honest", "lowercase", "tidy"])
        self.assertEqual((rs["honest"]["runner"], rs["honest"]["command"], rs["honest"]["on"]), ("model", "python3 judge.py", "turn"))
        self.assertEqual((rs["lowercase"]["files"], rs["lowercase"]["feedback"]), (["*.md"], True))
        self.assertEqual((rs["tidy"]["runner"], rs["tidy"]["text"]), (None, "No stray files."))
        self.assertEqual(rs["honest"]["text"], "The notes report what was measured.")
        before = rs["honest"]["hash"]
        write("RULES.md", read("RULES.md").replace("model: python3 judge.py", "agent: python3 judge.py"))
        self.assertNotEqual(sun.read_rules()[1]["honest"]["hash"], before)  # the runner is part of the rule
        os.remove("RULES.md"); write("RULES", "honest: The report lists what was proved.\n")
        self.assertEqual(sun.rules(), {"honest": "The report lists what was proved."})

    def test_run_records_a_verdict_per_rule_and_fails_the_shell(self):
        write("notes.md", "Results: 12 points\n"); run("sync")
        with self.assertRaisesRegex(SystemExit, "1"): run("check", "--run")
        rows = {r["rule"]: r for r in json.loads(run("coverage", "--json", "-n", "1"))["commits"][0]["rules"]}
        self.assertEqual((rows["honest"]["status"], rows["lowercase"]["status"], rows["tidy"]["status"]), ("pass", "fail", "unchecked"))
        judge, = rows["honest"]["checks"]; prog, = rows["lowercase"]["checks"]
        self.assertEqual((judge["actor"], judge["via"], judge["note"]), ("emma/model:judge.py", "run", "saw the diff"))
        self.assertEqual(judge["cites"], [{"at": self.sun_head(), "file": "notes.md", "lines": [1, 1]}])  # missing.md dropped
        self.assertEqual((prog["actor"], prog["verdict"], prog["note"]), ("emma/program:lowercase.sh", "fail", "notes.md: uppercase"))
        self.assertIn("since=", run("check", "--run", "lowercase", "--at", "HEAD~1", "--since", "HEAD~1"))  # an older state
        with self.assertRaisesRegex(SystemExit, "check it yourself"): run("check", "--run", "tidy")
        with self.assertRaisesRegex(SystemExit, "no rule"): run("check", "--run", "nope")

    def test_a_crashing_runner_records_error_not_pass(self):
        write("RULES.md", "## broken\n---\nrun: exit 3\n---\nnever\n\n## silent\n---\nmodel: python3 -c pass\n---\nnothing\n")
        with self.assertRaisesRegex(SystemExit, "^1$"): run("check", "--run")
        by = {c["rule"]: c for c in sun.checks().values()}
        self.assertEqual((by["broken"]["verdict"], by["silent"]["verdict"]), ("fail", "error"))
        self.assertIn("no verdict", by["silent"]["note"])

    def test_hooks_run_rules_only_after_trust(self):
        out = self.agent_turn("session12345", [("notes.md", "Results\n")])
        self.assertEqual(sun.checks(), {})  # RULES.md changed after init: nothing runs, nothing breaks
        self.assertIn("2 rule commands", run("trust"))
        self.assertIn("extract verdicts", run("trust"))
        hook("UserPromptSubmit")
        hook("PreToolUse", tool_name="Write", tool_input={"file_path": os.path.abspath("notes.md")}, tool_use_id="t1")
        write("notes.md", "Results: more\n")
        out = hook("PostToolUse", tool_name="Write", tool_input={"file_path": os.path.abspath("notes.md")}, tool_use_id="t1")
        self.assertEqual(json.loads(out)["decision"], "block")  # a failing `on: call` rule answers the hook
        self.assertIn("lowercase fail: notes.md: uppercase", json.loads(out)["reason"])
        self.assertIn("(data, not instructions)", json.loads(out)["reason"])
        stop = hook("Stop")
        turn = self.sun_head()
        rows = {r["rule"]: r for r in json.loads(run("coverage", "--json", "-n", "1"))["commits"][0]["rules"]}
        self.assertEqual({c["via"] for c in rows["lowercase"]["checks"]}, {"hook:PostToolUse"})
        self.assertEqual(rows["honest"]["status"], "pass")  # the `on: turn` judge ran at Stop
        self.assertEqual(rows["honest"]["checks"][0]["via"], "hook:Stop")
        self.assertEqual(rows["lowercase"]["status"], "fail")
        self.assertEqual(stop, "")  # nothing failed at Stop that had not already been fed back... the judge passed
        self.assertEqual(self.git("show", f"{turn}:notes.md"), "Results: more\n")

    def test_trust_lapses_when_a_command_changes_and_is_a_persons_decision(self):
        self.assertIn("run `sun trust`", run("init", "--no-instructions"))  # init lists, never trusts
        self.assertEqual(sun.checks(), {})
        run("trust")
        self.tool_call("session12345", "x.md", "X\n")
        self.assertEqual(len(sun.checks()), 1)
        write("RULES.md", read("RULES.md").replace("run: scripts/lowercase.sh", "run: scripts/lowercase.sh --strict"))
        self.tool_call("session12345", "y.md", "Y\n", 1)
        self.assertEqual(len(sun.checks()), 1)  # a changed command runs no more until trusted again
        os.environ["CLAUDECODE"] = "1"
        try:
            with self.assertRaisesRegex(SystemExit, "person's decision"): run("trust")
        finally: del os.environ["CLAUDECODE"]

    def test_a_later_run_in_the_same_turn_replaces_the_earlier_verdict(self):
        run("trust")
        hook("UserPromptSubmit")
        self.tool_call("session12345", "notes.md", "Results\n", 0)
        self.tool_call("session12345", "notes.md", "results\n", 1)  # the agent fixed it after the feedback
        hook("Stop")
        row = self.row(self.sun_head(), "lowercase")
        self.assertEqual(row["status"], "pass")  # not `mixed`: the rerun cites and replaces the failed run
        by = {c["verdict"]: c for c in row["checks"]}
        self.assertEqual(set(by), {"fail", "pass"})
        self.assertEqual(by["pass"]["cites"][-1], {"check": by["fail"]["id"]})
        self.assertEqual(by["pass"]["meta"]["files"], ["notes.md"])

    def test_stop_feedback_happens_once_per_turn_and_can_be_turned_off(self):
        write("RULES.md", "## honest\n---\nrun: exit 1\non: turn\n---\nnever passes\n\n## quiet\n---\nrun: exit 1\non: turn\nfeedback: false\n---\nsilent\n")
        run("trust")
        hook("UserPromptSubmit"); self.tool_call("session12345", "a.txt", "a\n")
        first = json.loads(hook("Stop"))
        self.assertEqual(first["decision"], "block")
        self.assertIn("honest fail", first["reason"]); self.assertNotIn("quiet", first["reason"])
        self.tool_call("session12345", "a.txt", "aa\n", 1)
        self.assertEqual(hook("Stop", stop_hook_active=True), "")  # recorded, but the agent may stop now
        self.assertEqual(len(sun.checks()), 4)
        os.environ["SUN_CHECKING"] = "1"  # a judge's own session runs no rules
        try:
            self.tool_call("session12345", "a.txt", "aaa\n", 2)
            self.assertEqual(hook("Stop"), "")
        finally: del os.environ["SUN_CHECKING"]
        self.assertEqual(len(sun.checks()), 4)

    def test_text_only_turns_and_unmatched_files_run_nothing(self):
        run("trust")
        hook("UserPromptSubmit"); hook("Stop")
        self.tool_call("session12345", "code.py", "X = 1\n")  # `files: *.md` does not match
        self.assertEqual(sun.checks(), {})

    def transcript(self, *records):
        tp = os.path.join(self.proj, "s.jsonl")
        with open(tp, "a") as f:
            for role, text in records:
                f.write(json.dumps({"type": role, "uuid": f"u{len(text)}", "timestamp": "2026-09-22T10:00:00.000Z",
                                    "message": {"role": role, "content": [{"type": "text", "text": text}]}}) + "\n")
        return tp

    def test_verdicts_in_your_replies_become_chat_checks(self):
        run("trust")
        tp = self.transcript(("user", "write the notes"))
        self.agent_turn("session12345", [("notes.md", "results: 2 points\n")], tpath=tp)
        seen = self.sun_head()
        self.transcript(("assistant", "I wrote the notes."), ("user", "the notes look right, thanks. also nice work"))
        self.agent_turn("session12345", [("notes.md", "results: 2 points\n\n")], tpath=tp)
        chat = [c for c in sun.checks().values() if c["actor"] == "emma/chat"]
        self.assertEqual(len(chat), 1)
        c, = chat
        self.assertEqual((c["rule"], c["verdict"], c["note"], c["via"]), ("honest", "pass", "the notes look right", "extract"))
        self.assertEqual(c["cites"], [{"at": seen, "file": "notes.md"}])  # the state she was looking at
        self.assertEqual(c["meta"]["at_method"], "turn")
        self.assertEqual(c["meta"]["extractor"], {"model": "extract.py", "version": "sun-extract/1"})
        self.assertEqual((self.row(seen)["status"], self.row(seen)["eyes"]), ("pass", "chat"))
        self.assertIn("chat only", run("coverage"))
        self.assertIn("recorded 0 verdicts", run("extract"))  # already read
        self.transcript(("assistant", "ok"), ("user", "there is a stray file"))  # a quote that is not her words is dropped
        self.assertIn("recorded 0 verdicts", run("extract", "--session", "session12345"))
        self.assertEqual(len([c for c in sun.checks().values() if c["actor"] == "emma/chat"]), 1)
        run("check", "honest", "pass", c["id"][:8], "-m", "confirmed")  # a terminal review promotes it
        self.assertEqual(self.row(seen)["eyes"], "terminal")

    def test_extract_refuses_an_agent_shell_and_an_undeclared_chat_actor(self):
        hook("PreToolUse", tool_name="Bash", tool_input={"command": "sun extract"}, tool_use_id="b")
        with self.assertRaisesRegex(SystemExit, "belongs to an agent"): run("extract")
        hook("PostToolUse", tool_name="Bash", tool_input={"command": "sun extract"}, tool_use_id="b")
        os.environ["CLAUDECODE"] = "1"
        try:
            with self.assertRaisesRegex(SystemExit, "belongs to an agent"): run("check", "tidy", "pass")
        finally: del os.environ["CLAUDECODE"]
        for actor in ("chat", "agent:claude/session12345"):
            with self.assertRaisesRegex(SystemExit, "declares an actor"):
                run("check", stdin={"rule": "tidy", "verdict": "pass", "actor": actor, "cites": [{"at": self.sun_head()}]})

    def test_codex_transcripts_are_read_too(self):
        tp = os.path.join(self.codex, "rollout.jsonl")
        lines = [{"type": "event_msg", "timestamp": "2026-09-22T10:00:00Z", "payload": {"type": "user_message", "message": "start"}},
                 {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "start"}]}},
                 {"type": "event_msg", "payload": {"type": "agent_message", "message": "done"}},
                 {"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "done"}]}},
                 {"type": "event_msg", "payload": {"type": "user_message", "message": "the notes look right"}}]
        write(tp, "".join(json.dumps(l) + "\n" for l in lines))
        recs = sun.transcript_records(tp, "codex")
        self.assertEqual([(r["role"], r["text"]) for r in recs], [("user", "start"), ("assistant", "done"), ("user", "the notes look right")])

    def test_outdated_checks_stay_visible_and_a_review_refreshes_them(self):
        tip = self.sun_head()
        mine, = self.check(rule="tidy", verdict="pass", actor="program:t", cites=[{"at": tip}])
        write("RULES.md", read("RULES.md").replace("No stray files.", "No stray files, ever."))
        self.assertEqual((self.row(tip, "tidy")["status"], self.row(tip, "tidy")["eyes"]), ("outdated", None))
        self.assertIn("rule changed since", run("coverage", "-n", "2"))  # the RULES.md edit is a commit too
        run("check", "tidy", "pass", mine["id"][:8], "-m", "still holds")
        self.assertEqual((self.row(tip, "tidy")["status"], self.row(tip, "tidy")["eyes"]), ("pass", "terminal"))

    def test_pr_summary_says_who_checked_what(self):
        run("trust")
        tp = self.transcript(("user", "go"))
        self.agent_turn("session12345", [("notes.md", "results\n")], tpath=tp)
        seen = self.sun_head()
        self.transcript(("assistant", "done"), ("user", "the notes look right"))
        self.agent_turn("session12345", [("b.md", "b\n")], tpath=tp)
        run("check", "tidy", "pass", "-m", "clean")
        md = run("pr")
        self.assertIn("## Checks recorded by sun", md)
        self.assertIn("by emma at a terminal", md)
        self.assertIn("Checked at a terminal:\n- tidy pass on", md)
        self.assertIn("Said in chat, not yet confirmed at a terminal:\n- honest pass on " + seen[:7], md)
        self.assertIn('"the notes look right", extracted by extract.py; confirm with `sun check honest pass', md)
        self.assertIn(f"Sun commits on `{base_branch()}`", md)
        self.assertIn("Checked only by programs, models, or declared actors:", md)
        self.assertIn("Not yet checked:", md)
        self.assertEqual(json.loads(run("pr", "--json"))["base"], base_branch())
        call = dict(tool_name="Bash", tool_input={"command": "sun pr"}, tool_use_id="bash0")
        hook("PreToolUse", **call)
        self.assertIn("by emma at a terminal", run("pr"))  # a person's terminal while an agent works
        os.environ["CLAUDECODE"] = "1"
        try:
            self.assertIn("by an agent tool call in session session12345", run("pr"))
            with self.assertRaisesRegex(SystemExit, "a person runs `sun trust`"):
                write("RULES.md", read("RULES.md") + "\n## new\n---\nrun: true\n---\nnot yet trusted\n"); run("check", "--run", "new")
            write("RULES.md", read("RULES.md").replace("\n## new\n---\nrun: true\n---\nnot yet trusted\n", ""))
            run("check", "--run", "lowercase")  # the agent checks its own turn from its own shell
        finally: del os.environ["CLAUDECODE"]
        hook("PostToolUse", **call)
        self.assertIn("Self-checked by the agent that made the change:\n- lowercase", run("pr"))
        mine = [c for c in sun.checks().values() if c.get("from")]
        self.assertEqual({c["from"] for c in mine}, {"session12345"})

    def test_show_prints_a_check_by_id(self):
        c, = self.check(rule="tidy", verdict="pass", actor="program:t", cites=[{"at": self.sun_head()}], note="clean")
        self.assertEqual(json.loads(run("show", c["id"][:10]))["note"], "clean")


class SetupTest(unittest.TestCase):
    """Publishing on git push, and worktrees and clones that set themselves up."""
    setUp, tearDown, git, sun_head = (fixtures.SunTest.setUp, fixtures.SunTest.tearDown,
                                      fixtures.SunTest.git, fixtures.SunTest.sun_head)

    def on_path(self):  # the Git hook and adoption call `sun`; point them at this checkout
        bin_dir = tempfile.mkdtemp()
        write(os.path.join(bin_dir, "sun"), f"#!/bin/sh\nexec {sys.executable} {sun.__file__} \"$@\"\n")
        os.chmod(os.path.join(bin_dir, "sun"), 0o755)
        os.environ["PATH"] = bin_dir + os.pathsep + os.environ["PATH"]
        return bin_dir

    def test_git_push_publishes_sun_history(self):
        self.on_path()
        with tempfile.TemporaryDirectory() as remote:
            self.git("init", "--bare", remote)
            self.git("remote", "add", "origin", remote)
            run("init", "--no-instructions")
            write("a.txt", "a\n"); run("sync")
            self.git("add", "a.txt"); self.git("commit", "-q", "-m", "a")
            out = subprocess.run(["git", "push", "origin", "HEAD"], capture_output=True, text=True, check=True)
            self.assertNotIn("not published", out.stderr)
            self.assertEqual(self.git("--git-dir", remote, "rev-parse", sun.shadow_ref()).strip(), self.sun_head())
            no_sun = os.pathsep.join([os.path.dirname(shutil.which("git")), "/usr/bin", "/bin"])  # git, but no `sun`
            self.git("commit", "-q", "--allow-empty", "-m", "again")
            self.assertIn("not published", subprocess.run(["git", "push", "origin", "HEAD"], capture_output=True, text=True,
                                                          env={**os.environ, "PATH": no_sun}).stderr)
            self.git("checkout", "-q", "-b", "nosun"); self.git("commit", "-q", "--allow-empty", "-m", "x")
            self.git("update-ref", "-d", "refs/sun/heads/nosun")
            subprocess.run(["git", "push", "origin", "nosun"], capture_output=True, text=True, check=True)  # no history: skipped quietly

    def test_a_worktree_sets_itself_up_and_inherits_history(self):
        write("a.txt", "a\n"); run("sync")  # recorded on the base branch, but not committed: the worktree will lack it
        base = base_branch()
        self.git("branch", "aaa-sibling")  # alphabetically first, no Sun history of its own
        wt = os.path.join(tempfile.mkdtemp(), "wt")
        self.git("worktree", "add", "-q", "-b", "feature", wt, base)
        os.chdir(wt)
        try:
            sun._r.clear()
            self.assertIn("edits a.txt", run("log"))  # adopted without `sun init`, history inherited
            self.assertEqual(sun.events()[-1]["actor"], "unknown")  # the missing a.txt is observed, not authored
            self.assertEqual(sun.events()[-1]["type"], "observe")
            write("b.txt", "b\n"); run("sync")
            self.assertEqual(sun.events()[-1]["actor"], "emma/local")
            self.assertTrue(os.path.isfile(os.path.join(self.dir, ".git", "worktrees", "wt", "sun", "config.json")))
        finally:
            os.chdir(self.dir); sun._r.clear()
        self.assertNotEqual(self.git("rev-parse", "refs/sun/heads/feature").strip(), self.git("rev-parse", f"refs/sun/heads/{base}").strip())

    def test_a_new_branch_continues_its_parent_history(self):
        write("a.txt", "a\n"); run("sync"); self.git("add", "-A"); self.git("commit", "-q", "-m", "a")
        base, main = base_branch(), self.sun_head()
        self.git("checkout", "-q", "-b", "feature")
        self.assertNotIn("recording starts now", run("init", "--no-instructions"))  # init on a new branch inherits
        self.assertEqual(self.git("rev-parse", "refs/sun/heads/feature").strip(), main)
        write("b.txt", "b\n"); self.git("add", "-A"); self.git("commit", "-q", "-m", "b"); run("sync")
        self.git("checkout", "-q", "-b", "fix", base)  # created from another branch's commit
        self.assertIn("edits a.txt", run("log"))
        self.assertEqual(self.git("rev-parse", "refs/sun/heads/fix").strip(), main)
        self.git("checkout", "-q", base); write("c.txt", "c\n"); self.git("add", "-A"); self.git("commit", "-q", "-m", "c")
        self.git("checkout", "-q", "-b", "later")  # after a commit Sun never saw
        self.assertIn("edits a.txt", run("log"))
        self.assertEqual((sun.events()[-1]["type"], sun.events()[-1]["actor"]), ("observe", "unknown"))
        self.assertIn("c.txt", json.dumps(sun.events()[-1]["edits"]))

    def test_a_clone_with_committed_hooks_sets_itself_up_on_the_first_hook(self):
        self.on_path()
        self.git("add", "-A"); self.git("commit", "-q", "-m", "hooks")
        clone = os.path.join(tempfile.mkdtemp(), "clone")
        self.git("clone", "-q", self.dir, clone)
        os.chdir(clone)
        try:
            sun._r.clear()
            subprocess.run(["git", "config", "user.name", "ana"], check=True)
            self.assertEqual(hook("SessionStart", sid="s2"), "")
            self.assertTrue(os.path.isdir(".git/sun"))
            self.assertIn("refs/sun/checks/*:refs/sun/checks/*", self.git("config", "--get-all", "remote.origin.fetch"))
            self.assertTrue(os.path.exists(".git/hooks/pre-push"))
            self.assertIn("initial state", run("log"))
        finally:
            os.chdir(self.dir); sun._r.clear()
        with tempfile.TemporaryDirectory() as plain:  # a repository nobody set up stays untouched
            subprocess.run(["git", "init", "-q", plain], check=True)
            os.chdir(plain)
            try:
                sun._r.clear()
                self.assertEqual(hook("SessionStart"), "")
                self.assertFalse(os.path.isdir(".git/sun"))
                with self.assertRaisesRegex(SystemExit, "sun init"): run("log")
            finally:
                os.chdir(self.dir); sun._r.clear()


class MigrateTest(unittest.TestCase):
    """sun migrate: history rebuilt from the sessions and commits that predate sun init."""
    tearDown, git, sun_head = fixtures.SunTest.tearDown, fixtures.SunTest.git, fixtures.SunTest.sun_head

    def setUp(self):
        fixtures.SunTest.setUp(self)  # the baseline commit is now; the sessions and commits below come after it
        self.T = [time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(time.time() + 60 * i)) for i in range(10)]

    def claude_transcript(self, sid, records):  # [(role, ts, payload)] -> a native transcript for this repo
        d = os.path.join(self.proj, sun.enc(os.getcwd())); os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, sid + ".jsonl"), "a") as f:
            for role, ts, payload in records:
                content = [payload] if isinstance(payload, dict) else [{"type": "text", "text": payload}]
                f.write(json.dumps({"type": role, "timestamp": ts, "uuid": ts, "cwd": os.getcwd(),
                                    "message": {"role": role, "content": content}}) + "\n")

    def commit_at(self, ts, message):
        env = {**os.environ, "GIT_AUTHOR_DATE": ts, "GIT_COMMITTER_DATE": ts}
        subprocess.run(["git", "add", "-A"], check=True)
        subprocess.run(["git", "commit", "-q", "-m", message], check=True, env=env)

    def test_migrate_replays_edits_and_observes_the_rest(self):
        self.commit_at(self.T[0], "hooks")  # what sun init wrote, committed before the sessions
        a = os.path.abspath("a.txt")
        self.claude_transcript("s1", [
            ("user", self.T[1], "write a"),
            ("assistant", self.T[1], {"type": "tool_use", "id": "w1", "name": "Write", "input": {"file_path": a, "content": "one\n"}}),
            ("user", self.T[3], "now edit it"),
            ("assistant", self.T[3], {"type": "tool_use", "id": "e1", "name": "Edit",
                                     "input": {"file_path": a, "old_string": "one", "new_string": "two"}}),
            ("assistant", self.T[4], {"type": "tool_use", "id": "e2", "name": "Edit",
                                     "input": {"file_path": a, "old_string": "gone", "new_string": "x"}}),  # never applied
            ("assistant", self.T[5], {"type": "tool_use", "id": "b1", "name": "Bash", "input": {"command": "echo three >> a.txt"}}),
        ])
        write("a.txt", "one\n"); write("b.txt", "b\n"); self.commit_at(self.T[2], "a and b")  # between the calls
        write("a.txt", "two\nthree\n"); self.commit_at(self.T[6], "after the shell")
        self.assertIn("would replay 3 tool calls from 1 sessions across 2 Git commits", run("migrate", "--dry-run"))
        out = run("migrate")
        self.assertIn("replayed 2 tool calls", out); self.assertIn("could not replay 1", out)
        log = run("log")
        self.assertIn("turn 1 (1 tool calls)", log); self.assertIn("turn 2 (1 tool calls)", log)
        self.assertEqual(log.count("observed repository state"), 2)
        evs = sun.events()
        self.assertEqual(evs[0]["type"], "init")
        replayed = [e for e in evs if e.get("edits") and e["edits"][0]["attribution"]["method"] == "replay"]
        self.assertEqual([(e["turn"], e["tool_calls"][0]["id"]) for e in replayed], [("turn1", "w1"), ("turn2", "e1")])
        self.assertTrue(all(e["actor"] == "emma/agent:claude/s1" for e in replayed))
        observed = [e for e in evs if e["type"] == "observe"]
        self.assertEqual([sorted(d["file"] for d in e["edits"]) for e in observed], [["b.txt"], ["a.txt"]])  # b.txt, then the shell's line
        self.assertEqual(observed[0]["git_author"], "emma")
        self.assertEqual(self.git("show", f"{self.sun_head()}:a.txt"), "two\nthree\n")
        self.assertIn("emma/agent:claude/s1 turn2  op", run("blame", "a.txt", "1"))
        self.assertIn("author unknown", run("blame", "a.txt", "2"))
        with self.assertRaisesRegex(SystemExit, "before anything is recorded"): run("migrate")

    def test_migrate_replays_codex_patches(self):
        rollout = os.path.join(self.codex, "2026", "01", "01", "rollout-2026-01-01T00-00-00-c1.jsonl")
        os.makedirs(os.path.dirname(rollout))
        patch = "*** Begin Patch\n*** Add File: n.md\n+hello\n+world\n*** End Patch"
        patch2 = "*** Begin Patch\n*** Update File: n.md\n@@\n hello\n-world\n+there\n*** End Patch"
        lines = [{"type": "session_meta", "timestamp": self.T[1], "payload": {"id": "c1", "cwd": os.getcwd()}},
                 {"type": "event_msg", "timestamp": self.T[1], "payload": {"type": "user_message", "message": "go"}},
                 {"type": "response_item", "timestamp": self.T[1], "payload": {"type": "custom_tool_call", "name": "apply_patch", "call_id": "p1", "input": patch}},
                 {"type": "response_item", "timestamp": self.T[2], "payload": {"type": "function_call", "name": "shell", "call_id": "p2",
                                                                              "arguments": json.dumps({"command": ["apply_patch", patch2]})}}]
        write(rollout, "".join(json.dumps(l) + "\n" for l in lines))
        write("n.md", "hello\nthere\n")  # as the agent left it on disk
        self.assertIn("replayed 2 tool calls", run("migrate"))
        self.assertEqual(self.git("show", f"{self.sun_head()}:n.md"), "hello\nthere\n")
        replayed = [e for e in sun.events() if e["type"] == "edit"]
        self.assertEqual([e["tool_calls"][0]["id"] for e in replayed], ["p1", "p2"])
        self.assertEqual(replayed[0]["actor"], "emma/agent:codex/c1")
