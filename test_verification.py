"""Isolated subprocess tests for the verification CLI. No real sessions or models."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


CLI = str(Path(__file__).with_name("sun.py"))


class VerificationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}
        self.env.pop("GIT_DIR", None)
        self.env.pop("GIT_WORK_TREE", None)
        self.write("paper.md", "We achieve 81%.\nThe improvement is significant.\n")
        self.write("results.json", '{"accuracy": 0.78, "baseline": 0.75}\n')
        self.cli("init", "--record-only")

    def tearDown(self):
        self.temp.cleanup()

    def write(self, path, content):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def git(self, *args, check=True):
        return subprocess.run(["git", *args], cwd=self.root, env=self.env,
                              text=True, capture_output=True, check=check)

    def cli(self, *args, payload=None, raw=None, success=True):
        result = subprocess.run([sys.executable, CLI, *args], cwd=self.root, env=self.env,
                                input=json.dumps(payload) if payload is not None else raw,
                                text=True, capture_output=True)
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertIn("error", json.loads(result.stderr))
        return result.stderr

    def snapshot(self):
        return self.cli("verify", "snapshot", "paper.md", "results.json", "--json")

    def request(self, snapshot=None):
        snapshot = snapshot or self.snapshot()
        target = {"snapshot_id": snapshot["id"], "path": "paper.md"}
        evidence = {"snapshot_id": snapshot["id"], "path": "results.json"}
        return {"request_id": "fixture/check-1", "actor": {"id": "verifier", "kind": "agent"},
                "module": {"id": "claim-verification", "version": "1.0.0", "digest": "a" * 64},
                "run_id": "run-1", "parent_run_id": "experiment-1", "targets": [target],
                "findings": [{"id": "accuracy", "criterion": "Accuracy matches the experiment",
                              "tier": "numeric-consistency", "verdict": "contradicted",
                              "rationale": "Paper says 81%; recorded result is 78%.",
                              "citations": [{**target, "start_line": 1, "end_line": 1}, evidence]}],
                "synthetic": True, "metadata": {"fixture": "paper-consistency"}}

    def record(self, payload=None):
        return self.cli("verify", "record", "--json", payload=payload or self.request())

    def review(self, check):
        return {"request_id": "fixture/review-1", "actor": {"id": "fixture-human", "kind": "simulated_human"},
                "verification_id": check["id"], "finding_ids": ["accuracy"], "decision": "accept-correction",
                "rationale": "Keep the correction, not the unsupported significance claim.", "synthetic": True}

    def receipt(self, synthetic=True, row_id=1):
        return self.cli("record", "--json", payload={
            "request_id": f"fixture/process/{row_id}", "synthetic": synthetic,
            "source": {"installation_id": "fixture", "project_id": "project", "stream": "processes", "row_id": row_id},
            "actor": {"id": "fixture-runner", "kind": "program"}, "run_id": "run-1",
            "payload": {"stdout": "fixture output\n", "stderr": "diagnostic\n", "exit_code": 7,
                        "path": "temporary-output.log", "truncated": False}})

    def test_record_only_has_no_hooks_imports_or_commits(self):
        self.assertTrue((self.root / ".git/sun").is_dir())
        for name in (".claude", ".codex", "AGENTS.md", "CLAUDE.md", ".git/hooks/pre-push"):
            self.assertFalse((self.root / name).exists(), name)
        self.assertFalse(self.git("rev-parse", "--verify", "HEAD", check=False).returncode == 0)
        self.assertEqual(self.git("for-each-ref", "refs/sun").stdout, "")
        self.assertEqual(self.git("config", "--get-regexp", "sun|remote", check=False).stdout, "")

    def test_paginated_checks_include_reviews_and_keep_legacy_list(self):
        checks = []
        for index in range(5):
            request = self.request()
            request["request_id"] = f"page/{index}"
            checks.append(self.record(request))
        self.cli("verify", "review", payload=self.review(checks[-1]))
        first = self.cli("verify", "list", "--limit", "2")
        self.assertEqual([v["id"] for v in first["records"]], [v["id"] for v in checks[-2:]])
        self.assertEqual(len(first["records"][-1]["reviews"]), 1)
        self.assertEqual((first["offset"], first["total"]), (0, 5))
        second = self.cli("verify", "list", "--limit", "2", "--before", first["next_cursor"])
        self.assertEqual([v["id"] for v in second["records"]], [v["id"] for v in checks[1:3]])
        last = self.cli("verify", "list", "--limit", "2", "--before", second["next_cursor"])
        self.assertEqual([v["id"] for v in last["records"]], [checks[0]["id"]])
        self.assertIsNone(last["next_cursor"])
        self.assertEqual(last["offset"], 4)
        self.assertEqual(len(self.cli("verify", "list")["records"]), 6)
        self.cli("verify", "list", "--limit", "0", success=False)
        self.cli("verify", "list", "--limit", "101", success=False)
        self.cli("verify", "list", "--limit", "2", "--before", "f" * 64, success=False)
        self.cli("verify", "list", "--before", checks[0]["id"], success=False)

    def test_pagination_does_not_compute_unselected_evidence_freshness(self):
        old = self.record()
        request = self.request()
        request["request_id"] = "new/check"
        request["findings"][0]["citations"] = [{"record_id": self.receipt()["id"]}]
        newer = self.record(request)
        # A missing external receipt fails only pages that actually inspect it.
        self.git("update-ref", "-d", "refs/sun/records/" + request["findings"][0]["citations"][0]["record_id"])
        page = self.cli("verify", "list", "--limit", "1", "--before", newer["id"])
        self.assertEqual(page["records"][0]["id"], old["id"])
        self.cli("verify", "list", "--limit", "1", success=False)

    def test_batched_list_validates_each_blob_and_handles_unicode(self):
        request = self.request()
        request["metadata"] = {"text": "évidence\n日本語"}
        check = self.record(request)
        self.assertEqual(self.cli("verify", "list", "--limit", "1")["records"][0]["metadata"], request["metadata"])
        self.write("corrupt.json", "{}")
        blob = self.git("hash-object", "-w", "corrupt.json").stdout.strip()
        self.git("update-ref", "refs/sun/verification/" + check["id"], blob)
        self.cli("verify", "list", "--limit", "1", success=False)

    def test_record_only_preserves_existing_configuration(self):
        self.write(".claude/settings.json", '{"hooks":{"Stop":[]}}')
        self.write(".git/sun/config.json", '{"track_sessions":false}')
        self.write(".git/hooks/pre-push", "#!/bin/sh\nexit 0\n")
        self.git("config", "remote.origin.url", "https://example.invalid/never-fetch")
        before = {p: (self.root / p).read_bytes() for p in
                  (".claude/settings.json", ".git/sun/config.json", ".git/config", ".git/hooks/pre-push")}
        self.cli("init", "--record-only")
        self.assertEqual(before, {p: (self.root / p).read_bytes() for p in before})

    def test_expected_root_guards_nested_projects_before_any_writes(self):
        child = self.root / "nested-project"
        child.mkdir()
        before = {str(p.relative_to(self.root)): p.read_bytes() for p in (self.root / ".git").rglob("*") if p.is_file()}
        for args in (("init", "--record-only"), ("verify", "list"),
                     ("verify", "snapshot", "paper.md")):
            result = subprocess.run([sys.executable, CLI, "--expected-root", str(child), *args],
                                    cwd=child, env=self.env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn("open the repository root", json.loads(result.stderr)["error"])
        after = {str(p.relative_to(self.root)): p.read_bytes() for p in (self.root / ".git").rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        self.assertFalse((child / ".git").exists())

    def test_expected_root_accepts_exact_root_and_preserves_normal_subdir_cli(self):
        self.cli("--expected-root", str(self.root), "init", "--record-only")
        self.assertEqual(self.cli("--expected-root", str(self.root), "verify", "list")["records"], [])
        child = self.root / "nested-project"
        child.mkdir()
        result = subprocess.run([sys.executable, CLI, "verify", "snapshot", "paper.md"], cwd=child,
                                env=self.env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["files"][0]["path"], "paper.md")
        self.cli("--expected-root", ".", "verify", "list", success=False)

    def test_expected_root_initializes_new_folder_without_git_identity(self):
        with tempfile.TemporaryDirectory() as fresh:
            result = subprocess.run([sys.executable, CLI, "--expected-root", fresh, "init", "--record-only"],
                                    cwd=fresh, env=self.env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((Path(fresh) / ".git/sun").is_dir())

    def test_snapshot_is_immutable_unicode_and_content_addressed(self):
        self.write("paper.md", "Évidence: 78%\r\n")
        snapshot = self.snapshot()
        self.assertEqual(snapshot, self.snapshot())
        self.assertNotIn("content", snapshot["files"][0])
        expected = hashlib.sha256((self.root / "paper.md").read_bytes()).hexdigest()
        self.assertEqual(next(f["sha256"] for f in snapshot["files"] if f["path"] == "paper.md"), expected)
        self.write("paper.md", "Changed\n")
        self.git("gc", "--prune=now")
        evidence = self.cli("verify", "evidence", snapshot["id"], "paper.md")
        self.assertEqual(evidence["content"], "Évidence: 78%\r\n")
        self.assertNotEqual(snapshot["id"], self.snapshot()["id"])

    def test_snapshot_accepts_explicit_path_separator_and_dash_names(self):
        self.write("--evidence.md", "Explicit path argument\n")
        snapshot = self.cli("verify", "snapshot", "--json", "--", "--evidence.md", "paper.md")
        self.assertEqual({f["path"] for f in snapshot["files"]}, {"--evidence.md", "paper.md"})

    def test_idempotency_does_not_conflate_boolean_and_numeric_metadata(self):
        request = self.request()
        request["metadata"] = {"value": True}
        self.record(request)
        request["metadata"] = {"value": 1}
        self.assertIn("different content", self.cli("verify", "record", payload=request, success=False))

    def test_reads_and_records_leave_index_and_head_alone(self):
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.invalid")
        self.git("add", "paper.md")
        self.git("commit", "-qm", "existing work")
        self.write("paper.md", "Uncommitted correction\n")
        self.git("add", "results.json")
        before = self.git("rev-parse", "HEAD").stdout, self.git("diff", "--cached").stdout, self.git("status", "--porcelain").stdout
        check = self.record()
        self.cli("verify", "list")
        self.cli("verify", "show", check["id"])
        after = self.git("rev-parse", "HEAD").stdout, self.git("diff", "--cached").stdout, self.git("status", "--porcelain").stdout
        self.assertEqual(before, after)

    def test_tiered_findings_and_declared_attribution_roundtrip(self):
        request = self.request()
        request["findings"][0]["verdict"] = "statement verified / proof open"
        request["findings"][0]["tier"] = "axiom-inspection"
        check = self.record(request)
        self.assertEqual(check["module"], request["module"])
        self.assertEqual(check["actor"], request["actor"])
        self.assertEqual(check["attribution"], "caller-declared")
        self.assertEqual(check["findings"], request["findings"])
        self.assertEqual(check["run_id"], "run-1")
        self.assertEqual(self.cli("verify", "show", check["id"])["freshness"]["status"], "current")

    def test_whole_record_and_mixed_citations_roundtrip_idempotently(self):
        receipt = self.receipt()
        request = self.request()
        citations = request["findings"][0]["citations"]
        citations.append({"record_id": receipt["id"]})
        check = self.record(request)
        self.assertEqual(check, self.record(request))
        self.assertEqual(self.cli("verify", "show", check["id"])["findings"][0]["citations"], citations)
        self.assertEqual(self.cli("records", "show", receipt["id"]), receipt)
        request["request_id"] = "fixture/receipt-only"
        request["findings"][0]["citations"] = [{"record_id": receipt["id"]}]
        check = self.record(request)
        self.assertEqual(self.cli("verify", "show", check["id"])["freshness"]["status"], "current")
        request["findings"][0]["citations"] = [{"record_id": self.receipt(row_id=2)["id"]}]
        self.assertIn("different content", self.cli("verify", "record", payload=request, success=False))

    def test_record_citation_freshness_uses_source_targets_not_payload_paths(self):
        request = self.request()
        receipt = self.receipt()
        request["findings"][0]["citations"] = [{"record_id": receipt["id"]}]
        request["targets"].append({"snapshot_id": request["targets"][0]["snapshot_id"], "path": "results.json"})
        check = self.record(request)
        view = self.cli("verify", "show", check["id"])
        self.assertEqual(view["freshness"]["status"], "current")
        self.assertEqual({f["path"] for f in view["freshness"]["files"]}, {"paper.md", "results.json"})
        self.assertFalse((self.root / "temporary-output.log").exists())
        self.write("results.json", '{"accuracy":0.72}\n')
        self.assertEqual(self.cli("verify", "show", check["id"])["freshness"]["status"], "stale")
        self.assertEqual(self.cli("records", "show", receipt["id"]), receipt)

    def test_record_citations_require_existing_external_record_and_exclusive_shape(self):
        request = self.request()
        receipt = self.receipt()
        for citation in ({"record_id": "f" * 64}, {"record_id": "../HEAD"}, {"record_id": None},
                         {"record_id": "A" * 64}, {"record_id": request["targets"][0]["snapshot_id"]},
                         {"record_id": receipt["id"], "path": "paper.md"},
                         {"record_id": receipt["id"], "snapshot_id": request["targets"][0]["snapshot_id"]},
                         {"record_id": receipt["id"], "start_line": 1, "end_line": 1},
                         {"record_id": receipt["id"], "field": "stdout"}, {}, None, []):
            with self.subTest(citation=citation):
                request["findings"][0]["citations"] = [citation]
                self.cli("verify", "record", payload=request, success=False)
        request["findings"][0]["citations"] = [{"record_id": receipt["id"]}]
        request["targets"] = [{"record_id": receipt["id"]}]
        self.cli("verify", "record", payload=request, success=False)
        self.assertEqual(self.cli("verify", "list")["records"], [])

    def test_synthetic_evidence_cannot_be_laundered_through_checks_or_reviews(self):
        request = self.request()
        synthetic, genuine = self.receipt(), self.receipt(synthetic=False, row_id=2)
        request["synthetic"] = False
        request["findings"][0]["citations"].extend([{"record_id": genuine["id"]}, {"record_id": synthetic["id"]}])
        self.assertIn("synthetic", self.cli("verify", "record", payload=request, success=False))
        request["findings"][0]["citations"].pop()
        self.assertFalse(self.record(request)["synthetic"])
        request["request_id"] = "fixture/synthetic-check"
        request["synthetic"] = True
        request["findings"][0]["citations"].append({"record_id": synthetic["id"]})
        check = self.record(request)
        self.assertTrue(check["synthetic"])
        review = self.review(check)
        self.cli("verify", "review", payload={**review, "synthetic": False}, success=False)
        self.assertTrue(self.cli("verify", "review", payload=review)["synthetic"])

    def test_missing_or_corrupt_receipt_fails_check_creation_and_coverage_reads(self):
        receipt = self.receipt()
        request = self.request()
        request["findings"][0]["citations"] = [{"record_id": receipt["id"]}]
        check = self.record(request)
        ref = "refs/sun/records/" + receipt["id"]
        original = self.git("rev-parse", ref).stdout.strip()
        for raw in ("not json", "[]", json.dumps({**receipt, "synthetic": "false"}),
                    json.dumps({**receipt, "type": "snapshot"})):
            with self.subTest(raw=raw):
                blob = subprocess.run(["git", "hash-object", "-w", "--stdin"], cwd=self.root, env=self.env,
                                      input=raw, text=True, capture_output=True, check=True).stdout.strip()
                self.git("update-ref", ref, blob)
                self.assertIn("corrupt", self.cli("verify", "record", payload=request, success=False))
                self.assertIn("corrupt", self.cli("verify", "show", check["id"], success=False))
                self.assertIn("corrupt", self.cli("verify", "list", success=False))
        self.git("update-ref", "-d", ref)
        self.assertIn("unknown external", self.cli("verify", "show", check["id"], success=False))
        self.cli("verify", "record", payload=request, success=False)
        self.git("update-ref", ref, original)
        self.assertEqual(self.cli("verify", "show", check["id"])["freshness"]["status"], "current")

    def test_external_citations_survive_gc_and_explicit_ref_transfer(self):
        receipt = self.receipt()
        request = self.request()
        request["findings"][0]["citations"].append({"record_id": receipt["id"]})
        check = self.record(request)
        self.git("gc", "--prune=now")
        with tempfile.TemporaryDirectory() as destination:
            subprocess.run(["git", "init", "-q", destination], check=True, env=self.env)
            subprocess.run(["git", "-C", destination, "fetch", str(self.root), "+refs/sun/*:refs/sun/*"],
                           check=True, env=self.env, capture_output=True)
            subprocess.run([sys.executable, CLI, "init", "--record-only"], cwd=destination,
                           env=self.env, check=True, capture_output=True)
            for args in (("records", "show", receipt["id"]), ("verify", "show", check["id"])):
                result = subprocess.run([sys.executable, CLI, *args, "--json"], cwd=destination,
                                        env=self.env, text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                imported = json.loads(result.stdout)
                if args[0] == "records": self.assertEqual(imported, receipt)
                else:
                    self.assertEqual(imported["findings"], check["findings"])
                    self.assertEqual(imported["freshness"]["status"], "missing")

    def test_changed_evidence_stales_unchanged_target(self):
        check = self.record()
        self.write("results.json", '{"accuracy":0.77}\n')
        view = self.cli("verify", "show", check["id"])
        self.assertEqual(view["freshness"]["status"], "stale")
        self.assertEqual({f["path"]: f["status"] for f in view["freshness"]["files"]},
                         {"paper.md": "current", "results.json": "stale"})
        self.assertEqual(self.cli("verify", "evidence", check["targets"][0]["snapshot_id"], "results.json")["content"],
                         '{"accuracy": 0.78, "baseline": 0.75}\n')

    def test_missing_and_unavailable_evidence_are_not_current(self):
        check = self.record()
        (self.root / "results.json").unlink()
        self.assertEqual(self.cli("verify", "show", check["id"])["freshness"]["status"], "missing")
        (self.root / "results.json").symlink_to(self.root / "paper.md")
        self.assertEqual(self.cli("verify", "show", check["id"])["freshness"]["status"], "unavailable")

    def test_idempotent_records_reviews_and_explicit_conflict(self):
        request = self.request()
        check = self.record(request)
        self.assertEqual(check, self.record(request))
        review = self.review(check)
        recorded = self.cli("verify", "review", payload=review)
        self.assertEqual(recorded, self.cli("verify", "review", payload=review))
        self.assertEqual(self.cli("verify", "show", check["id"])["reviews"], [recorded])
        self.assertEqual(len(self.cli("verify", "list")["records"]), 2)
        request["findings"][0]["verdict"] = "supported"
        self.assertIn("different content", self.cli("verify", "record", payload=request, success=False))
        self.assertEqual(len(self.cli("verify", "list")["records"]), 2)

    def test_unknown_snapshot_path_ranges_and_ids_are_rejected(self):
        request = self.request()
        mutations = [lambda r: r["targets"][0].update(snapshot_id="f" * 64),
                     lambda r: r["targets"][0].update(path="missing.md"),
                     lambda r: r["targets"][0].update(snapshot_id="../../HEAD"),
                     lambda r: r["findings"][0]["citations"][0].update(end_line=99),
                     lambda r: r["findings"][0]["citations"][0].update(start_line=True),
                     lambda r: r["findings"][0]["citations"][0].pop("end_line"),
                     lambda r: r["findings"][0].update(citations=[]),
                     lambda r: r["findings"].append(copy.deepcopy(r["findings"][0]))]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                invalid = copy.deepcopy(request)
                mutate(invalid)
                self.cli("verify", "record", payload=invalid, success=False)
        self.assertEqual(self.cli("verify", "list")["records"], [])

    def test_invalid_reviews_are_rejected(self):
        check = self.record()
        review = self.review(check)
        for key, bad in (("verification_id", "f" * 64), ("finding_ids", ["unknown"]),
                         ("finding_ids", ["accuracy", "accuracy"]), ("synthetic", False)):
            with self.subTest(key=key, bad=bad):
                self.cli("verify", "review", payload={**review, key: bad}, success=False)
        recorded = self.cli("verify", "review", payload=review)
        self.cli("verify", "review", payload={**review, "request_id": "review-a-review",
                                               "verification_id": recorded["id"]}, success=False)

    def test_unsafe_paths_and_nonregular_files_are_rejected(self):
        (self.root / "alias.md").symlink_to(self.root / "paper.md")
        (self.root / "alias-dir").symlink_to(self.root)
        (self.root / "directory").mkdir()
        os.mkfifo(self.root / "pipe")
        for path in ("../paper.md", "/etc/passwd", "a/../paper.md", "./paper.md", "a//paper.md",
                     ".git/config", ".GIT/config", "a\\paper.md", "alias.md", "alias-dir/paper.md",
                     "directory", "pipe", "new\nline", "missing.md"):
            with self.subTest(path=path):
                self.cli("verify", "snapshot", path, success=False)
        self.assertEqual(self.git("for-each-ref", "refs/sun/evidence").stdout, "")

    def test_bounded_and_strict_json_input(self):
        for raw in ('{}', '{"a":1,"a":2}', '{"number":NaN}', '[]', '"' + "x" * (1024 * 1024) + '"'):
            self.cli("verify", "record", raw=raw, success=False)
        request = self.request()
        for key, bad in (("synthetic", "false"), ("actor", "human"), ("targets", []), ("metadata", [])):
            self.cli("verify", "record", payload={**request, key: bad}, success=False)
        self.cli("verify", "record", payload={**request, "recorded_by": "spoof"}, success=False)
        self.cli("verify", "snapshot", "paper.md", "paper.md", success=False)
        self.write("too-large.txt", "x" * (1024 * 1024 + 1))
        self.cli("verify", "snapshot", "too-large.txt", success=False)
        (self.root / "binary").write_bytes(b"\xff\xfe")
        self.cli("verify", "snapshot", "binary", success=False)

    def test_concurrent_writers_retry_exactly_once(self):
        request = self.request()
        request["findings"][0]["citations"].append({"record_id": self.receipt()["id"]})
        processes = [subprocess.Popen([sys.executable, CLI, "verify", "record"], cwd=self.root,
                                      env=self.env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE, text=True) for _ in range(6)]
        for process in processes:
            process.stdin.write(json.dumps(request))
            process.stdin.close()
            process.stdin = None
        values = []
        for process in processes:
            stdout, stderr = process.communicate(timeout=15)
            self.assertEqual(process.returncode, 0, stderr)
            values.append(json.loads(stdout))
        self.assertTrue(all(v == values[0] for v in values))
        self.assertEqual(len(self.cli("verify", "list")["records"]), 1)

    def test_separate_requests_are_not_lost_under_concurrency(self):
        request = self.request()
        processes = []
        for index in range(6):
            process = subprocess.Popen([sys.executable, CLI, "verify", "record"], cwd=self.root,
                                       env=self.env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, text=True)
            process.stdin.write(json.dumps({**request, "request_id": f"parallel/{index}"}))
            process.stdin.close()
            process.stdin = None
            processes.append(process)
        for process in processes:
            stdout, stderr = process.communicate(timeout=15)
            self.assertEqual(process.returncode, 0, stderr)
        self.assertEqual(len(self.cli("verify", "list")["records"]), 6)

    def test_records_and_snapshots_roundtrip_through_git_refs(self):
        check = self.record()
        with tempfile.TemporaryDirectory() as destination:
            subprocess.run(["git", "init", "-q", destination], check=True, env=self.env)
            subprocess.run(["git", "-C", destination, "fetch", str(self.root), "+refs/sun/*:refs/sun/*"],
                           check=True, env=self.env, capture_output=True)
            result = subprocess.run([sys.executable, CLI, "init", "--record-only"], cwd=destination,
                                    env=self.env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([sys.executable, CLI, "verify", "show", check["id"]], cwd=destination,
                                    env=self.env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            imported = json.loads(result.stdout)
            self.assertEqual(imported["findings"], check["findings"])
            self.assertEqual(imported["freshness"]["status"], "missing")

    def test_record_only_and_concurrent_idempotency_in_linked_worktree(self):
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.invalid")
        self.git("add", ".")
        self.git("commit", "-qm", "initial experiment")
        request = self.request()
        with tempfile.TemporaryDirectory() as worktree:
            self.git("worktree", "add", "--detach", worktree)
            setup = subprocess.run([sys.executable, CLI, "init", "--record-only"], cwd=worktree,
                                   env=self.env, capture_output=True, text=True)
            self.assertEqual(setup.returncode, 0, setup.stderr)
            processes = []
            for directory in (self.root, worktree, self.root, worktree):
                process = subprocess.Popen([sys.executable, CLI, "verify", "record"], cwd=directory,
                                           env=self.env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                           stderr=subprocess.PIPE, text=True)
                process.stdin.write(json.dumps(request))
                process.stdin.close()
                process.stdin = None
                processes.append(process)
            values = []
            for process in processes:
                stdout, stderr = process.communicate(timeout=15)
                self.assertEqual(process.returncode, 0, stderr)
                values.append(json.loads(stdout))
            self.assertTrue(all(v == values[0] for v in values))
            self.assertEqual(len(self.cli("verify", "list")["records"]), 1)

    def test_corrupt_snapshot_is_rejected_without_writing_a_check(self):
        request = self.request()
        identifier = request["targets"][0]["snapshot_id"]
        blob = subprocess.run(["git", "hash-object", "-w", "--stdin"], cwd=self.root, env=self.env,
                              input=json.dumps({"schema_version": 1, "id": identifier,
                                                "type": "snapshot", "files": []}),
                              text=True, capture_output=True, check=True).stdout.strip()
        self.git("update-ref", "refs/sun/evidence/" + identifier, blob)
        self.assertIn("corrupt", self.cli("verify", "record", payload=request, success=False))
        self.assertEqual(self.cli("verify", "list")["records"], [])


if __name__ == "__main__":
    unittest.main()
