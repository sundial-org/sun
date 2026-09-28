"""Frozen-report evaluation. Its scores never flow into training targets."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
import copy
import json
from engine import save, digest
from provers import retrieve
from protocol import bounded_report
from scorer import facts, score


def evaluate(engine, traces, checkpoint, arm, pool=None, client=None, policy="base"):
    def one(record):
        messages = copy.deepcopy(record["report_messages"])
        selected = []
        if arm == "context":
            extra, selected = retrieve(engine, pool or [], record["task"]["type"] + "\n" + messages[-1]["content"])
            messages[0]["content"] += extra
        samples = engine.sample(f"eval/k{checkpoint}/{arm}/{record['sid']}/samples", messages,
                                client=client, policy=policy, max_tokens=512, temperature=.7, seed=731, n=5)
        greedy = engine.sample(f"eval/k{checkpoint}/{arm}/{record['sid']}/greedy", messages,
                               client=client, policy=policy, max_tokens=512, temperature=0, seed=731)[0]
        truth = facts(record)
        return {"sid": record["sid"], "lemma": record["task"]["id"], "family": record["task"]["family"],
                "truth": sorted(truth), "prompt_hash": digest(messages), "retrieved_review_ids": selected,
                "scores": [score(bounded_report(s["text"]), truth, record["task"]["id"]) for s in samples],
                "greedy": score(bounded_report(greedy["text"]), truth, record["task"]["id"]),
                "reports": [bounded_report(s["text"]) for s in samples], "greedy_report": bounded_report(greedy["text"])}
    with ThreadPoolExecutor(max_workers=10) as workers:
        results = list(workers.map(one, traces))
    output = {"checkpoint": checkpoint, "arm": arm, "reviews": 120 * checkpoint,
              "policy": policy, "traces": len(results), "results": results,
              "mean_F": sum(sum(x["F"] for x in r["scores"]) / len(r["scores"]) for r in results) / len(results)}
    save(engine.run / "evaluation" / f"k{checkpoint}-{arm}.json", output)
    engine.log("evaluation_complete", checkpoint=checkpoint, arm=arm, traces=len(results), mean_F=output["mean_F"])
    return output
