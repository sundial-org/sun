"""Tests for rules, checks and coverage: judgments recorded over the operation history."""
import json, os, subprocess, sys, tempfile, time, unittest
import test_sun as fixtures
from test_sun import run, hook, write, sun


class ChecksTest(unittest.TestCase):
    tearDown = fixtures.SunTest.tearDown
    git, sun_head, tool_call = fixtures.SunTest.git, fixtures.SunTest.sun_head, fixtures.SunTest.tool_call
    agent_turn = fixtures.SunTest.agent_turn

    def setUp(self):
        fixtures.SunTest.setUp(self)
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
                         {("actor", "cites", "id", "rule", "timestamp", "type", "verdict")})

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
            f"create refs/sun/checks/{i} {sha}\n" for i, sha in zip(chain, blobs)))
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
        self.assertEqual((self.row(turn)["status"], self.row(turn)["eyes"]), ("fail", True))
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
            self.git("update-ref", f"refs/sun/checks/{i:032x}", sun.blob(fake))
        self.git("update-ref", "refs/sun/checks/" + real["id"], sun.blob(json.dumps({**real, "verdict": "pass"})))
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
                    with self.assertRaises(SystemExit): run("push")  # history is rejected, non-fast-forward
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
