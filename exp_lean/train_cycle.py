"""Report-only LoRA SFT on shared reviewer targets. No scorer import."""
from __future__ import annotations
import json
import math
from pathlib import Path
import random
import time
from engine import MODEL, canonical, digest, save


def training_rows(engine, reviews, records):
    byid = {r["sid"]: r for r in records}
    rows = []
    for review in reviews:
        if review.get("failed"):
            continue
        record = byid[review["sid"]]
        if record["retrieved_reviews"]:
            raise ValueError("Shared training pool must have no feedback in its prompt")
        if review["source_commit"] != record["sun"]["commit"]:
            raise ValueError("Review provenance mismatch")
        messages = record["report_messages"] + [{"role": "assistant", "content": review["corrected_report"]}]
        rows.append({"sid": review["sid"], "messages": messages,
                     "source_commit": review["source_commit"], "check_ids": review["check_ids"],
                     "human_reviewed": False, "prompt_hash": digest(record["report_messages"])})
    return rows


def train(engine, checkpoint, rows, seed=31, label=None):
    import tinker
    from tinker.lib.retry_handler import RetryConfig
    from tinker_cookbook.renderers import TrainOnWhat
    from tinker_cookbook.supervised.data import conversation_to_datum
    label = label or f"checkpoint-{checkpoint}"
    folder = engine.run / "training" / label
    receipt_path = folder / "checkpoint.json"
    if receipt_path.exists():
        receipt = json.loads(receipt_path.read_text())
        return engine.service.create_sampling_client(model_path=receipt["sampling_path"],
            retry_config=RetryConfig(enable_retry_logic=False, progress_timeout=600)), receipt
    if (folder / "started.json").exists():
        raise RuntimeError(f"Training {label} started but has no completed checkpoint; inspect before replay")
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "rows.jsonl").open("w") as file:
        for row in rows:
            file.write(canonical(row) + "\n")
    renderer = engine.renderers[MODEL]
    datums = []
    for row in rows:
        with engine.tokenizer_lock:
            datums.append(conversation_to_datum(row["messages"], renderer, None,
                           TrainOnWhat.LAST_ASSISTANT_MESSAGE, reduction="mean"))
    lengths = [d.model_input.length for d in datums]
    if not datums or max(lengths) > 32000:
        raise ValueError("Training data empty or too long; no silent truncation")
    # Assert that all loss-bearing tokens lie within the corrected final turn.
    for row, datum in zip(rows, datums):
        with engine.tokenizer_lock:
            _, all_weights = renderer.build_supervised_example(row["messages"],
                                            train_on_what=TrainOnWhat.LAST_ASSISTANT_MESSAGE)
            generation = renderer.build_generation_prompt(row["messages"][:-1])
        weights = all_weights.tolist() if hasattr(all_weights, "tolist") else list(all_weights)
        first_weight = next(i for i, w in enumerate(weights) if w > 0)
        if first_weight < generation.length:
            raise AssertionError("Training loss leaked into the trajectory")
    batches = math.ceil(len(rows) / 16)
    epochs = max(3, math.ceil(30 / batches))
    planned_steps = epochs * batches
    token_count = epochs * sum(lengths)
    engine.reserve("train/" + label, MODEL, train=token_count)
    plan = {"rows": len(rows), "row_hash": digest((folder / "rows.jsonl").read_text()),
            "epochs": epochs, "steps": planned_steps, "training_tokens": token_count,
            "max_sequence_tokens": max(lengths), "rank": 16, "learning_rate": 4e-4,
            "batch_size": 16, "seed": seed, "loss": "LAST_ASSISTANT_MESSAGE",
            "base_model": MODEL, "retrain_from_base": True}
    save(folder / "started.json", plan)
    engine.log("training_start", checkpoint=checkpoint, label=label, **plan)
    start = time.monotonic()
    client = engine.service.create_lora_training_client(base_model=MODEL, rank=16, seed=seed,
        train_mlp=True, train_attn=True, train_unembed=True,
        user_metadata={"experiment": "ten-provers-lean", "checkpoint": str(checkpoint),
                       "dataset_sha": plan["row_hash"]})
    steps = 0
    for epoch in range(epochs):
        order = list(range(len(rows)))
        random.Random(seed + epoch).shuffle(order)
        for offset in range(0, len(order), 16):
            indices = order[offset:offset + 16]
            fb_future = client.forward_backward([datums[i] for i in indices], "cross_entropy")
            opt_future = client.optim_step(tinker.types.AdamParams(learning_rate=4e-4))
            fb = fb_future.result(timeout=1200)
            opt = opt_future.result(timeout=1200)
            item = {"step": steps, "epoch": epoch, "rows": indices, "metrics": fb.metrics,
                    "optimizer_metrics": opt.metrics, "elapsed_seconds": time.monotonic() - start}
            with (folder / "steps.jsonl").open("a") as file:
                file.write(canonical(item) + "\n")
            steps += 1
            if steps % 5 == 0 or steps == planned_steps:
                engine.log("training_progress", checkpoint=checkpoint, step=steps,
                           planned=planned_steps, elapsed_seconds=round(time.monotonic() - start, 1))
    state = client.save_state(name=label + "-state", ttl_seconds=7 * 86400).result(timeout=600)
    sampler = client.save_weights_for_sampler(name=label + "-sampling", ttl_seconds=7 * 86400).result(timeout=600)
    receipt = {**plan, "state_path": state.path, "sampling_path": sampler.path,
               "elapsed_seconds": time.monotonic() - start, "completed_steps": steps}
    save(receipt_path, receipt)
    engine.log("training_complete", checkpoint=checkpoint, steps=steps, seconds=receipt["elapsed_seconds"])
    sampling_client = engine.service.create_sampling_client(model_path=sampler.path,
                       retry_config=RetryConfig(enable_retry_logic=False, progress_timeout=600))
    return sampling_client, receipt
