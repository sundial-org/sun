"""Four-round experiment orchestration, with durable phase boundaries."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
import importlib.metadata
import hashlib
import json
from pathlib import Path
import subprocess
import time
from engine import MODEL, REVIEWER, RATES, PRICING_SOURCE, digest, save
from tasks import catalogue
from provers import ArmRepo, run_session, public_task
from review import review_one
from train_cycle import training_rows, train
from evaluate import evaluate
from audit_history import run_audit
import sun_io


def snapshot(engine, phase):
    # Raw call files remain on disk and are bound by one SHA-256 manifest.
    # Per-session source, reports, receipts and reviews have their own Sun refs.
    bulk = ["samples", "provider-outputs", "submissions", "session-state", "compiler-calls",
            "trajectories", "reviews", "pilot-reviews", "training", "history-audit",
            "evaluation", "review-pools"]
    ignore = engine.run / ".gitignore"
    text = ignore.read_text() if ignore.exists() else ""
    for name in bulk:
        if name + "/" not in text.splitlines():
            text += name + "/\n"
    ignore.write_text(text)
    hashes = {str(p.relative_to(engine.run)): hashlib.sha256(p.read_bytes()).hexdigest()
              for name in bulk for p in sorted((engine.run / name).rglob("*")) if p.is_file()}
    save(engine.run / "evidence-manifest.json", {"phase": phase, "files": hashes,
                                               "count": len(hashes)})
    binding = sun_io.record(engine.run, "program:experiment", phase, None)
    engine.log("run_snapshot", phase=phase, commit=binding["commit"])


def freeze(engine):
    root = Path(__file__).parent
    tasks = catalogue()
    config = {"rounds": 4, "sessions_per_round_per_arm": 120, "workers_per_arm": 10,
              "arms": ["a0", "a1", "a2"], "model": MODEL, "reviewer": REVIEWER,
              "reviewer_temperature": 0, "max_compiles": 3, "max_tool_calls": 12,
              "review_tool_budget": 15, "context_token_budget": 8000,
              "pool": "Identical cumulative a0 reviewer examples for a1 and a2",
              "training": {"rank": 16, "learning_rate": .0004, "batch_size": 16,
                           "epochs": "max(3,ceil(30/ceil(rows/16)))", "seed": 31,
                           "loss": "corrected final report only", "retrain_from_base": True},
              "heldout_traces": 120, "heldout_lemmas": 40, "analysis_clusters": "20 lemma families",
              "evaluation_samples": 5, "evaluation_temperature": .7, "secondary_greedy": True,
              "primary_test": "Final paired mean F(weights)-F(context), 95% family bootstrap, 10000 draws",
              "score": "precision * recall over status and E1-E6 claims",
              "scorer_not_used_for_training": True, "history_audit_sessions": 120,
              "history_conditions": ["T: transcripts", "Tplus: transcripts + git log", "S: transcripts + Sun"],
              "history_primary": "E3/E6 inconsistency recall: S minus Tplus; precision and specificity reported",
              "cost_reservation_cap_usd": 450, "rates_usd_per_million": RATES,
              "pricing_source": PRICING_SOURCE, "pricing_checked": "2026-09-25",
              "toolchain": "leanprover/lean4:v4.24.0",
              "sun_commit": "2eb500744d6d8ba0d9734a6c2e2ce87a5f0d005c",
              "versions": {k: importlib.metadata.version(k) for k in ("tinker", "tinker-cookbook", "transformers")},
              "implementation_hashes": {p.name: digest(p.read_text()) for p in sorted(root.glob("*.py"))},
              "split_hashes": {k: digest([public_task(t) for t in v]) for k, v in tasks.items()},
              "limitations": ["Shared base-arm feedback pool; not on-policy LoRA data collection",
                              "One live run and one training seed per checkpoint",
                              "Parameterized task families overlap across splits; bootstrap clusters by family",
                              "Core list lemmas and simple dependent conjunctions; not a theorem-proving benchmark",
                              "Deterministic lexical review retrieval, not the attachment's BM25 implementation",
                              "Local timestamped freeze, not an external preregistration",
                              "Human smoke test recorded separately; never inferred from agent checks",
                              "No self-label, shuffled-label, or program-label training controls"]}
    path = engine.run / "frozen-config.json"
    if path.exists():
        previous = json.loads(path.read_text())
        if previous["implementation_hashes"] != config["implementation_hashes"]:
            amendments_path = engine.run / "protocol-amendments.json"
            amendments = json.loads(amendments_path.read_text()) if amendments_path.exists() else []
            if not amendments or amendments[-1]["implementation_hashes"] != config["implementation_hashes"]:
                raise RuntimeError("Implementation changed after freeze; record a protocol amendment before proceeding")
            engine.log("protocol_amendment_applied", amendment=amendments[-1]["id"])
        return previous
    save(path, {**config, "frozen_at": time.time()})
    save(engine.run / "catalogue.json", {k: [public_task(t) for t in v] for k, v in tasks.items()})
    save(engine.run / "reference-proofs.json", {t.id: t.reference for group in tasks.values() for t in group})
    save(engine.run / "human-smoke-test.json", {"status": "not_yet_completed", "human_reviewed": False})
    engine.log("protocol_frozen", config_sha=digest(path.read_text()))
    snapshot(engine, "protocol-freeze")
    return config


def frozen_traces(engine, tasks):
    arm = ArmRepo(engine.run, "heldout", tasks)
    all_traces = []
    for repeat in range(3):
        def one(item):
            index, task = item
            return run_session(engine, arm, f"heldout-t{index % 10:02d}-s{repeat * len(tasks)+index:04d}",
                               0, index % 10, forced=task.id)
        with ThreadPoolExecutor(max_workers=10) as workers:
            all_traces.extend(workers.map(one, enumerate(tasks)))
    # No compiler-derived score is revealed to a model or the training path.
    save(engine.run / "frozen-traces.json", {"count": len(all_traces),
         "sha256": digest(all_traces), "ids": [r["sid"] for r in all_traces]})
    engine.log("heldout_frozen", count=len(all_traces), sha256=digest(all_traces))
    return all_traces


def execute(engine):
    engine.setup(MODEL)
    engine.setup(REVIEWER)
    config = freeze(engine)
    tasks = catalogue()
    pilot = json.loads((engine.run / "pilot-results.json").read_text())
    if len(pilot) < 10 or any(x["reviewed"] is None for x in pilot):
        raise RuntimeError("Pilot requires ten completed reviews before execution")
    traces = frozen_traces(engine, tasks["heldout"])
    evaluate(engine, traces, 0, "base")
    snapshot(engine, "baseline-evaluated")
    arms = {name: ArmRepo(engine.run, name, tasks["train"]) for name in ("a0", "a1", "a2")}
    pool, shared_records, all_records = [], [], []
    weights_client, policy = None, "base"
    for round_index in range(1, 5):
        pool_at_start = list(pool)
        engine.log("round_start", round=round_index, cumulative_reviews=len(pool), weights_policy=policy)
        def worker(job):
            name, worker_id = job
            arm = arms[name]
            records, reviews = [], []
            for local in range(12):
                sid = f"{name}-r{round_index}-t{worker_id:02d}-s{local:02d}"
                record = run_session(engine, arm, sid, round_index, worker_id,
                                     pool=pool_at_start if name == "a1" else None,
                                     client=weights_client if name == "a2" else None,
                                     policy=policy if name == "a2" else "base")
                reviewed = review_one(engine, arm, record)
                records.append(record)
                reviews.append(reviewed)
            return name, records, reviews
        with ThreadPoolExecutor(max_workers=30) as workers:
            completed = list(workers.map(worker, [(name, i) for name in arms for i in range(10)]))
        for name, records, reviews in completed:
            all_records.extend(records)
            if name == "a0":
                shared_records.extend(records)
                pool.extend(reviews)
        pool.sort(key=lambda x: x["sid"])
        if any(r.get("failed") for r in pool):
            raise RuntimeError("A shared-pool review failed; fix or disclose missing feedback before continuing")
        save(engine.run / "review-pools" / f"round-{round_index}.json", pool)
        for arm in arms.values():
            subprocess.run(["git", "pack-refs", "--all"], cwd=arm.repo, check=True)
        engine.log("round_sessions_complete", round=round_index, sessions=360, cumulative_reviews=len(pool))
        rows = training_rows(engine, pool, shared_records)
        # Context evaluation is independent of training and can run while it trains.
        with ThreadPoolExecutor(max_workers=1) as overlap:
            ctx_future = overlap.submit(evaluate, engine, traces, round_index, "context", pool=pool)
            weights_client, receipt = train(engine, round_index, rows)
            policy = receipt["sampling_path"]
            ctx_future.result()
        evaluate(engine, traces, round_index, "weights", client=weights_client, policy=policy)
        snapshot(engine, "checkpoint-" + str(round_index))
        save(engine.run / "progress.json", {"completed_rounds": round_index, "sessions": len(all_records),
                                           "reviews_in_pool": len(pool), "checkpoint": policy})
    history = run_audit(engine, arms, all_records, config["history_audit_sessions"])
    save(engine.run / "completed.json", {"rounds": 4, "live_sessions": len(all_records),
                                        "review_pool": len(pool), "history_episodes": len(history),
                                        "finished_at": time.time()})
    snapshot(engine, "completed-experiment")
    return {"event": "experiment_complete", "rounds": 4, "sessions": len(all_records),
            "history_episodes": len(history)}
