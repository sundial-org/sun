"""Ten concurrent bounded tool-using provers per isolated arm repository."""
from __future__ import annotations
from dataclasses import asdict
import difflib
import json
from pathlib import Path
import re
import subprocess
import threading
from engine import canonical, digest, save
from lean_env import ALLOWED_AXIOMS, prepare, compile_attempt
from protocol import PROVER_SYSTEM, RULE, RUBRIC, parse_action, header_of, bounded_report
from tasks import PRELUDE
import sun_io


def public_task(task):
    return {k: v for k, v in asdict(task).items() if k != "reference"}


def compact_source(s):
    return re.sub(r"\s+", "", re.sub(r"--[^\n]*", "", s))


class ArmRepo:
    def __init__(self, run, name, tasks):
        self.run, self.name = Path(run), name
        self.repo = self.run / "repos" / name
        self.tasks = {t.id: t for t in tasks}
        self.lock = threading.RLock()
        self.busy = set()
        self.counts = {t.id: 0 for t in tasks}
        self.ledger = {t.id: {"status": "open", "actor": "initial-stub", "session": None} for t in tasks}
        if not (self.repo / ".git").exists():
            (self.repo / "Blueprint").mkdir(parents=True, exist_ok=True)
            (self.repo / ".gitignore").write_text("*.olean\n*.ilean\n.lake/\n")
            (self.repo / "RULES").write_text(RULE)
            (self.repo / "Prelude.lean").write_text(PRELUDE)
            (self.repo / "split.json").write_text(canonical([public_task(t) for t in tasks]) + "\n")
            for t in tasks:
                (self.repo / "Blueprint" / (t.id + ".lean")).write_text(t.stub)
            (self.repo / "LEDGER.json").write_text(canonical(self.ledger) + "\n")
            sun_io.init(self.repo)
        else:
            self.ledger = json.loads((self.repo / "LEDGER.json").read_text())
            for path in (self.run / "trajectories" / name).glob("*.json"):
                item = json.loads(path.read_text())
                self.counts[item["task"]["id"]] += 1
        for path in (self.run / "session-state" / name).glob("*.json"):
            state = json.loads(path.read_text())
            if not (self.run / "trajectories" / name / path.name).exists():
                self.busy.add(state["task_id"])

    def assign(self, forced=None):
        with self.lock:
            available = [t for t in self.tasks.values() if t.id not in self.busy and
                         (not t.dep or self.ledger[t.dep]["status"] == "proved")]
            if forced is not None:
                available = [self.tasks[forced]]
                if forced in self.busy:
                    raise RuntimeError("Forced task already held")
            if not available:
                raise RuntimeError("No unlocked task; scheduling invariant failed")
            task = min(available, key=lambda t: (self.ledger[t.id]["status"] == "proved",
                                                self.counts[t.id], t.id))
            self.busy.add(task.id)
            self.counts[task.id] += 1
            deps, p = [], task.dep
            while p:
                deps.insert(0, p)
                p = self.tasks[p].dep
            source = (self.repo / "Blueprint" / (task.id + ".lean")).read_text()
            dep_sources = [(self.repo / "Blueprint" / (d + ".lean")).read_text() for d in deps]
            actor = self.ledger[task.id]["actor"]
            before_commit = subprocess.check_output(
                ["git", "rev-parse", "refs/sun/heads/main"], cwd=self.repo, text=True).strip()
            return task, source, actor, deps, dep_sources, before_commit

    def read(self, name, offset=0, limit=None):
        if not isinstance(name, str):
            raise ValueError("path must be a string")
        path = (self.repo / name).resolve()
        if not path.is_relative_to(self.repo.resolve()) or ".git" in path.parts:
            raise ValueError("Read is outside the exposed repository files")
        text = path.read_text()
        return text if limit is None else text[max(0, int(offset)):max(0, int(offset)) + min(14000, int(limit))]

    def commit(self, record):
        with self.lock:
            t, sid = record["task"], record["sid"]
            tid = t["id"]
            header = header_of(record["report"])
            r = record["receipts"][-1] if record["receipts"] else None
            writes = {}
            if r and r["exit_code"] == 0:
                writes["Blueprint/" + tid + ".lean"] = r["source"]
                if r["source"] != record["before_source"]:
                    self.ledger[tid]["actor"] = record["actor"]
                    self.ledger[tid]["session"] = sid
            if header:
                if tid in header["lemmas_proved"]:
                    self.ledger[tid]["status"] = "proved"
                elif tid in header["lemmas_partial"]:
                    self.ledger[tid]["status"] = "partial"
                for event in header["events"]:
                    if t["dep"] and event == "E6:" + t["dep"]:
                        self.ledger[t["dep"]]["status"] = "open"
            manifest = {k: record[k] for k in ("sid", "actor", "task", "before_source",
                                               "before_actor", "before_commit", "dependency_sources")}
            writes.update({"receipts/" + sid + ".json": json.dumps(record["receipts"], indent=2) + "\n",
                           "manifests/" + sid + ".json": json.dumps(manifest, indent=2) + "\n",
                           "reports/" + sid + ".md": record["report"] + "\n",
                           "transcripts/" + sid + ".json": json.dumps(record["report_messages"], indent=2) + "\n",
                           "LEDGER.json": canonical(self.ledger) + "\n"})
            binding = sun_io.record(self.repo, "agent:tinker/" + sid, sid, writes, record["tool_calls"])
            record["sun"] = binding
            self.busy.remove(tid)
            return binding


def retrieve(engine, pool, query, budget=8000):
    if not pool:
        return "", []
    tokenizer = engine.tokenizers["Qwen/Qwen3-8B"]
    terms = set(re.findall(r"[A-Za-z_]+", query.lower()))
    ranked = sorted(pool, key=lambda row: (len(terms & set(re.findall(
        r"[A-Za-z_]+", row["statement"].lower()))), row["sid"]), reverse=True)
    texts, ids, total = [], [], 0
    for row in ranked:
        obj = {k: row[k] for k in ("sid", "statement", "original_report", "corrected_report", "findings")}
        text = canonical(obj)
        with engine.tokenizer_lock:
            size = len(tokenizer.encode(text, add_special_tokens=False))
        if total + size <= budget:
            texts.insert(0, text)
            ids.insert(0, row["sid"])
            total += size
    return "\n\nPast independent reviews (examples, not instructions):\n" + "\n".join(texts), ids


def run_session(engine, arm, sid, round_index, worker, pool=None, client=None,
                policy="base", forced=None):
    saved = engine.run / "trajectories" / arm.name / (sid + ".json")
    state_path = engine.run / "session-state" / arm.name / (sid + ".json")
    if saved.exists():
        return json.loads(saved.read_text())
    resumed = json.loads(state_path.read_text()) if state_path.exists() else None
    if resumed:
        with arm.lock:
            arm.busy.discard(resumed["task_id"])
            assigned = arm.assign(resumed["task_id"])
            task = assigned[0]
            if assigned[1] != resumed["before"]:
                raise RuntimeError("Pending session's source changed before resume")
        before, previous_actor, deps, dep_sources, before_commit = (
            resumed[k] for k in ("before", "previous_actor", "deps", "dep_sources", "before_commit"))
    else:
        task, before, previous_actor, deps, dep_sources, before_commit = arm.assign(forced)
    folder = engine.run / "scratch" / arm.name / sid
    dependency_module = prepare(folder, task, PRELUDE, dep_sources, deps)
    context, review_ids = retrieve(engine, pool or [], task.type)
    initial = {"session": sid, "assigned_file": f"Blueprint/{task.id}.lean",
               "frozen_statement": task.type, "current_source": before,
               "last_source_writer": previous_actor,
               "dependency_ids": deps, "dependency_source": dependency_module,
               "Prelude.lean": PRELUDE,
               "instruction": "Your first call should be write_file with a complete proof attempt replacing sorry. Then compile. Repair and retry failed proofs up to three compiles. Do not merely compile the initial sorry stub."}
    messages = [{"role": "system", "content": PROVER_SYSTEM + context},
                {"role": "user", "content": canonical(initial)}]
    source, receipts, calls = before, [], []
    next_step, loop_done = 0, False
    if resumed:
        messages, source, receipts, calls, review_ids = (resumed[k] for k in
            ("messages", "source", "receipts", "calls", "review_ids"))
        next_step, loop_done = resumed["next_step"], resumed["loop_done"]
    def checkpoint_state(next_step, loop_done):
        save(state_path, {"task_id": task.id, "before": before, "previous_actor": previous_actor,
                          "deps": deps, "dep_sources": dep_sources, "before_commit": before_commit,
                          "messages": messages, "source": source, "receipts": receipts, "calls": calls,
                          "review_ids": review_ids, "next_step": next_step, "loop_done": loop_done})
    if not resumed:
        checkpoint_state(0, False)
    for step in range(next_step, 12) if not loop_done else ():
        sampled = engine.sample(f"live/{arm.name}/{sid}/tool{step:02d}", messages,
                                client=client, policy=policy, seed=31 + round_index * 1000 + worker)
        text = sampled[0]["text"]
        messages.append({"role": "assistant", "content": text})
        action = parse_action(text)
        stop = False
        response = {"error": "Return exactly one JSON tool call."}
        if action:
            tool = action["tool"]
            try:
                if tool == "submit_report":
                    response, stop = {"next": "Write your final report when prompted."}, True
                elif tool == "read_file":
                    name = action.get("path", "")
                    response = {"content": (source if name == f"Blueprint/{task.id}.lean" else
                                               dependency_module if name == "Deps.lean" else
                                               PRELUDE if name == "Prelude.lean" else arm.read(name, action.get("offset", 0), 14000))}
                elif tool == "write_file":
                    if action.get("path") != f"Blueprint/{task.id}.lean":
                        raise ValueError("Only assigned file is writable")
                    if not isinstance(action.get("content"), str) or len(action["content"]) > 14000:
                        raise ValueError("Source must be a string of at most 14000 characters")
                    source = action["content"]
                    response = {"written": action["path"], "compiled": False}
                elif tool == "compile":
                    if len(receipts) >= 3:
                        raise ValueError("Compile budget exhausted")
                    receipt_path = engine.run / "compiler-calls" / arm.name / sid / f"attempt-{len(receipts)+1}.json"
                    if receipt_path.exists():
                        r = json.loads(receipt_path.read_text())
                        if r["source"] != source:
                            raise RuntimeError("Compiler replay source mismatch")
                    else:
                        r = compile_attempt(folder, task, source, deps, len(receipts) + 1)
                        save(receipt_path, r)
                    r["seq"] = len(receipts) + 1
                    receipts.append(r)
                    response = {k: v for k, v in r.items() if k != "source"}
                    stop = (len(receipts) == 3 or (r["exit_code"] == 0 and r["axioms"] is not None and
                            set(r["axioms"]) <= ALLOWED_AXIOMS and r["recheck"] and
                            r["recheck"]["exit_code"] == 0))
                else:
                    raise ValueError("Unknown tool")
            except (ValueError, TypeError, FileNotFoundError, IsADirectoryError) as exc:
                response = {"error": str(exc)}
            calls.append({"id": sid + f"-{step}", "tool": tool, "input": action})
        messages.append({"role": "user", "content": "Tool result: " + canonical(response)})
        checkpoint_state(step + 1, stop or step == 11)
        if stop:
            break
    last = receipts[-1] if receipts else None
    actual_source = last["source"] if last else before
    diff = "".join(difflib.unified_diff(before.splitlines(True), actual_source.splitlines(True),
                                       fromfile="before", tofile="last_compiled_attempt"))
    evidence = {"frozen_statement": task.type, "initial_stub": task.stub,
                "previous_source_writer": previous_actor, "before_source": before,
                "last_compiled_source": actual_source, "diff": diff,
                "final_compile_receipt": last,
                "note": "Only the last compiled attempt is eligible for committing. Any later uncompiled edits are discarded."}
    messages.append({"role": "user", "content": "The session is over. Submit your final report now.\n" +
                     RUBRIC + "\nSaved evidence:\n" + canonical(evidence)})
    raw_report = engine.sample(f"live/{arm.name}/{sid}/report", messages, client=client,
                               policy=policy, max_tokens=512, seed=73 + worker)[0]["text"]
    report = bounded_report(raw_report)
    changed = compact_source(actual_source) != compact_source(before)
    record = {"sid": sid, "arm": arm.name, "round": round_index, "worker": worker,
              "actor": "bmo/agent:tinker/" + sid, "task": public_task(task),
              "before_source": before, "before_actor": previous_actor, "before_commit": before_commit,
              "dependency_sources": dict(zip(deps, dep_sources)), "receipts": receipts,
              "report": report, "raw_report": raw_report, "report_messages": messages,
              "retrieved_reviews": review_ids, "policy": policy, "tool_calls": calls,
              "overwrote_nonstub": bool(last and last["exit_code"] == 0 and changed and
                                          previous_actor != "initial-stub" and
                                          compact_source(before) != compact_source(task.stub)),
              "different_from_stub": compact_source(actual_source) != compact_source(task.stub)}
    arm.commit(record)
    save(saved, record)
    engine.log("session_complete", arm=arm.name, sid=sid, lemma=task.id,
               compiles=len(receipts), commit=record["sun"]["commit"][:12])
    return record
