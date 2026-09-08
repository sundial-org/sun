"""External-ledger ingestion: exact payload, durable identities, and no file edits."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import test_verification as support


class RecordTest(unittest.TestCase):
    setUp = support.VerificationTest.setUp
    tearDown = support.VerificationTest.tearDown
    write = support.VerificationTest.write
    git = support.VerificationTest.git
    cli = support.VerificationTest.cli

    def request(self, row=1, stream="local_edits"):
        return {"request_id": f"desktop-install/project/{stream}/{row}",
                "source": {"installation_id": "desktop-install", "project_id": "project",
                           "stream": stream, "row_id": row},
                "actor": {"id": "alice", "kind": "user"}, "synthetic": True,
                "payload": {"id": row, "project_id": "project", "path": "paper.md", "actor": "user",
                            "author_id": "alice", "content_text": "Révised, 78%.\r\n",
                            "update_b64": "AAEC/w==", "chat_id": None, "message_id": None,
                            "edit_mode": "edit", "created_at": "2026-09-06T10:01:00.123Z"}}

    def test_exact_recorded_payload_not_later_disk_contents(self):
        request = self.request()
        self.write("paper.md", "Completely different later file contents\n")
        record = self.cli("record", "--json", payload=request)
        self.assertEqual(record["payload"], request["payload"])
        self.assertEqual(record["actor"], request["actor"])
        self.assertEqual(record["attribution"], "caller-declared")
        self.assertEqual(self.cli("records", "show", record["id"]), record)
        self.assertEqual((self.root / "paper.md").read_text(), "Completely different later file contents\n")
        self.assertEqual(self.cli("verify", "list")["records"], [])

    def test_request_and_source_identity_idempotency(self):
        request = self.request()
        record = self.cli("record", payload=request)
        self.assertEqual(record, self.cli("record", payload=request))
        original_refs = self.git("for-each-ref", "refs/sun").stdout
        for mutate in (lambda r: r.update(request_id="different-request"),
                       lambda r: r["payload"].update(content_text="Different content"),
                       lambda r: r["actor"].update(id="someone-else"),
                       lambda r: r["source"].update(row_id=2),
                       lambda r: r.update(synthetic=False)):
            invalid = copy.deepcopy(request)
            mutate(invalid)
            self.cli("record", payload=invalid, success=False)
            self.assertEqual(self.git("for-each-ref", "refs/sun").stdout, original_refs)

    def test_no_worktree_index_head_or_hook_mutation(self):
        self.git("config", "user.name", "Recorder")
        self.git("config", "user.email", "recorder@example.invalid")
        self.git("add", "paper.md")
        self.git("commit", "-qm", "existing work")
        self.write("paper.md", "Dirty user changes\n")
        self.git("add", "results.json")
        before = self.git("rev-parse", "HEAD").stdout, (self.root / ".git/index").read_bytes(), self.git("status", "--porcelain").stdout
        self.cli("--expected-root", str(self.root), "record", payload=self.request())
        self.cli("--expected-root", str(self.root), "records", "list")
        after = self.git("rev-parse", "HEAD").stdout, (self.root / ".git/index").read_bytes(), self.git("status", "--porcelain").stdout
        self.assertEqual(before, after)
        self.assertFalse((self.root / ".git/hooks/pre-push").exists())

    def test_module_and_run_provenance_roundtrip(self):
        request = self.request()
        request.update(module={"id": "paper-writer", "version": "1.0.0", "digest": "c" * 64},
                       run_id="run-1", parent_run_id="experiment-1")
        record = self.cli("record", payload=request)
        self.assertEqual(record["module"], request["module"])
        self.assertEqual(record["run_id"], "run-1")
        self.assertEqual(record["parent_run_id"], "experiment-1")

    def test_pagination_and_independent_streams(self):
        records = [self.cli("record", payload=self.request(i)) for i in range(1, 6)]
        self.cli("record", payload=self.request(1, "local_decisions"))
        seen, cursor = [], None
        while True:
            args = ["records", "list", "--limit", "2", "--stream", "local_edits"]
            if cursor: args += ["--after", cursor]
            page = self.cli(*args)
            seen += page["records"]
            cursor = page["next_cursor"]
            if cursor is None: break
        self.assertEqual(seen, records)
        self.assertEqual(len(self.cli("records", "list")["records"]), 6)
        final = self.cli("records", "list", "--stream", "local_edits", "--after", records[-1]["id"])
        self.assertEqual(final["records"], [])
        self.assertIsNone(final["next_cursor"])
        self.cli("records", "list", "--stream", "local_decisions", "--after", records[0]["id"], success=False)

    def test_invalid_payloads_and_pagination_do_not_write_refs(self):
        request = self.request()
        mutations = (lambda r: r.update(payload=[]), lambda r: r.update(synthetic="false"),
                     lambda r: r.update(actor={"id": "x"}), lambda r: r["source"].update(row_id=True),
                     lambda r: r["source"].update(row_id=0), lambda r: r["source"].update(row_id="1"),
                     lambda r: r["source"].update(row_id=9007199254740992),
                     lambda r: r["source"].update(installation_id=""), lambda r: r.update(recorded_by="spoof"))
        for mutate in mutations:
            invalid = copy.deepcopy(request)
            mutate(invalid)
            self.cli("record", payload=invalid, success=False)
        self.cli("record", raw='{"x":1,"x":2}', success=False)
        request["payload"]["content_text"] = "x" * (1024 * 1024)
        self.cli("record", payload=request, success=False)
        for limit in ("0", "1001", "-1"):
            self.cli("records", "list", "--limit", limit, success=False)
        self.cli("records", "list", "--after", "f" * 64, success=False)
        self.cli("records", "show", "../../HEAD", success=False)
        self.assertEqual(self.git("for-each-ref", "refs/sun").stdout, "")

    def test_concurrent_source_retries_and_distinct_records(self):
        payloads = [self.request()] * 4 + [self.request(i) for i in range(2, 6)]
        processes = []
        for payload in payloads:
            process = subprocess.Popen([sys.executable, support.CLI, "record"], cwd=self.root,
                                       env=self.env, text=True, stdin=subprocess.PIPE,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            process.stdin.write(json.dumps(payload))
            process.stdin.close()
            process.stdin = None
            processes.append(process)
        output = []
        for process in processes:
            stdout, stderr = process.communicate(timeout=15)
            self.assertEqual(process.returncode, 0, stderr)
            output.append(json.loads(stdout))
        self.assertTrue(all(r == output[0] for r in output[:4]))
        self.assertEqual(len(self.cli("records", "list")["records"]), 5)
        self.assertEqual(len(self.git("for-each-ref", "refs/sun/record-requests").stdout.splitlines()), 5)

    def test_conflicting_request_concurrency_commits_only_one_source(self):
        first, second = self.request(), self.request(2)
        second["request_id"] = first["request_id"]
        processes = []
        for payload in (first, second):
            process = subprocess.Popen([sys.executable, support.CLI, "record"], cwd=self.root,
                                       env=self.env, text=True, stdin=subprocess.PIPE,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            process.stdin.write(json.dumps(payload))
            process.stdin.close()
            process.stdin = None
            processes.append(process)
        codes = []
        for process in processes:
            process.communicate(timeout=15)
            codes.append(process.returncode)
        self.assertEqual(sorted(codes), [0, 2])
        self.assertEqual(len(self.cli("records", "list")["records"]), 1)
        self.assertEqual(len(self.git("for-each-ref", "refs/sun/record-requests").stdout.splitlines()), 1)

    def test_atomic_transaction_failure_has_no_partial_record(self):
        blob = self.git("hash-object", "-w", "paper.md").stdout.strip()
        self.git("update-ref", "refs/sun/record-requests", blob)  # block creation of child refs
        self.assertIn("transaction failed", self.cli("record", payload=self.request(), success=False))
        self.assertEqual(self.git("for-each-ref", "refs/sun/records/").stdout, "")

    def test_explicit_ref_transfer_preserves_payload_and_idempotency(self):
        request = self.request()
        record = self.cli("record", payload=request)
        self.git("gc", "--prune=now")
        with tempfile.TemporaryDirectory() as destination:
            subprocess.run(["git", "init", "-q", destination], check=True, env=self.env)
            subprocess.run(["git", "-C", destination, "fetch", str(self.root), "+refs/sun/*:refs/sun/*"],
                           check=True, env=self.env, capture_output=True)
            for args, payload in ((("init", "--record-only"), None), (("record",), request),
                                  (("records", "show", record["id"]), None)):
                result = subprocess.run([sys.executable, support.CLI, *args], cwd=destination,
                                        env=self.env, input=json.dumps(payload) if payload else None,
                                        text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                if args[0] != "init": self.assertEqual(json.loads(result.stdout), record)

    def test_payload_paths_are_data_not_file_operations(self):
        request = self.request()
        request["payload"] = {"path": "../outside/.git/config", "content_text": "not written"}
        self.cli("record", payload=request)
        self.assertFalse((self.root.parent / "outside").exists())

    def test_missing_request_index_is_not_silently_repaired(self):
        request = self.request()
        self.cli("record", payload=request)
        self.git("update-ref", "-d", "refs/sun/record-requests/" + hashlib.sha256(request["request_id"].encode()).hexdigest())
        self.assertIn("missing or inconsistent", self.cli("record", payload=request, success=False))

    def test_missing_order_index_does_not_silently_hide_a_record(self):
        request = self.request()
        self.cli("record", payload=request)
        order_ref = self.git("for-each-ref", "--format=%(refname)", "refs/sun/record-order/").stdout.strip()
        self.git("update-ref", "-d", order_ref)
        self.assertIn("missing or inconsistent", self.cli("records", "list", success=False))
        self.assertIn("missing or inconsistent", self.cli("record", payload=request, success=False))


if __name__ == "__main__":
    unittest.main()
