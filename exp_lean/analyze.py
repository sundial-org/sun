"""Recompute tables and uncertainty from saved samples, without model calls."""
from __future__ import annotations
from collections import Counter, defaultdict
import argparse
import json
from pathlib import Path
import random
import statistics
from engine import MODEL, REVIEWER, RATES, canonical, save
from scorer import facts, score
from protocol import header_of
import itertools


def mean(values):
    values = list(values)
    return sum(values) / len(values) if values else None


def interval(values):
    x = sorted(values)
    return [x[int(.025 * len(x))], x[min(len(x) - 1, int(.975 * len(x)))]] if x else [None, None]


def recompute_eval(path):
    data = json.loads(Path(path).read_text())
    for r in data["results"]:
        recalculated = [score(text, r["truth"], r["lemma"]) for text in r["reports"]]
        if recalculated != r["scores"]:
            raise AssertionError("Saved evaluation disagrees with deterministic rescore")
    return data


def paired(a, b, draws=10000):
    byid = {r["sid"]: r for r in b["results"]}
    groups = defaultdict(list)
    for r in a["results"]:
        other = byid[r["sid"]]
        groups[r["family"]].append(mean(x["F"] for x in r["scores"]) - mean(x["F"] for x in other["scores"]))
    values = [mean(groups[k]) for k in sorted(groups)]
    rng = random.Random(731)
    return {"delta": mean(values), "ci95": interval(mean(rng.choices(values, k=len(values))) for _ in range(draws)),
            "families": len(values), "per_family": values}


def detection_stats(rows, cross_only=False):
    tp = fp = fn = clean = correct_clean = 0
    for r in rows:
        expected, predicted = set(r["expected"]), set(r["predicted"])
        if cross_only:
            keep = lambda x: x == "E3" or x.startswith("E6:")
            expected = {x for x in expected if keep(x)}
            predicted = {x for x in predicted if keep(x)}
        tp += len(expected & predicted)
        fp += len(predicted - expected)
        fn += len(expected - predicted)
        if not expected:
            clean += 1
            correct_clean += int(not predicted)
    return {"tp": tp, "fp": fp, "fn": fn, "expected": tp + fn,
            "precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None,
            "specificity": correct_clean / clean if clean else None,
            "clean_sessions": clean, "episodes": len(rows),
            "completed": sum(bool(r["completed"]) for r in rows),
            "unfinished": sum(not r["completed"] for r in rows)}


def analyze(run):
    run = Path(run)
    data = {p.stem: recompute_eval(p) for p in sorted((run / "evaluation").glob("*.json"))}
    curve = []
    if "k0-base" in data:
        base = data["k0-base"]["mean_F"]
        curve.append({"reviews": 0, "base": base, "context": base, "weights": base, "delta": 0, "ci95": [0, 0]})
        for k in range(1, 5):
            a, b = data.get(f"k{k}-weights"), data.get(f"k{k}-context")
            if a and b:
                curve.append({"reviews": 120 * k, "base": base, "context": b["mean_F"],
                              "weights": a["mean_F"], **paired(a, b)})
    outcome = "incomplete"
    crossing = None
    if len(curve) == 5:
        last = curve[-1]
        if last["ci95"][0] > 0:
            outcome = "weights_above_context_at_480"
        elif last["ci95"][1] < 0:
            outcome = "context_above_weights_at_480"
        else:
            outcome = "inconclusive_difference_at_480"
        for i in range(1, len(curve)):
            if all(x["delta"] > 0 for x in curve[i:]):
                crossing = curve[i]["reviews"]
                break
    trajectories = [json.loads(p.read_text()) for arm in ("a0", "a1", "a2")
                    for p in sorted((run / "trajectories" / arm).glob("*.json"))]
    live = {}
    for arm in ("a0", "a1", "a2"):
        rows = [r for r in trajectories if r["arm"] == arm]
        counter = Counter(f.split(":")[0] for r in rows for f in facts(r))
        live[arm] = {"sessions": len(rows), "facts": dict(counter),
                     "mean_report_F": mean(score(r["report"], facts(r), r["task"]["id"])["F"] for r in rows)}
    review_quality = []
    for r in trajectories:
        path = run / "reviews" / r["arm"] / (r["sid"] + ".json")
        if path.exists():
            review = json.loads(path.read_text())
            review_quality.append(None if review.get("failed") else score(review["corrected_report"], facts(r), r["task"]["id"])["F"])
    audit_path = run / "history-audit" / "all-results.json"
    audit_rows = json.loads(audit_path.read_text()) if audit_path.exists() else []
    audit = {c: {"all": detection_stats([r for r in audit_rows if r["condition"] == c]),
                 "cross": detection_stats([r for r in audit_rows if r["condition"] == c], True)}
             for c in ("T", "Tplus", "S")}
    audit_difference = None
    if audit_rows:
        byfamily = defaultdict(list)
        for r in audit_rows:
            byfamily[r["family"]].append(r)
        families = sorted(byfamily)
        rng = random.Random(2731)
        diffs = []
        for _ in range(10000):
            selected = [r for f in rng.choices(families, k=len(families)) for r in byfamily[f]]
            s = detection_stats([r for r in selected if r["condition"] == "S"], True)["recall"]
            t = detection_stats([r for r in selected if r["condition"] == "Tplus"], True)["recall"]
            if s is not None and t is not None:
                diffs.append(s - t)
        sr, tr = audit["S"]["cross"]["recall"], audit["Tplus"]["cross"]["recall"]
        audit_difference = {"delta": sr - tr if sr is not None and tr is not None else None,
                            "ci95": interval(diffs), "instances": audit["S"]["cross"]["expected"]}
    tokens = defaultdict(lambda: {"prefill": 0, "sample": 0, "train": 0})
    for p in (run / "samples").rglob("*.json"):
        item = json.loads(p.read_text())
        tokens[item["model"]]["prefill"] += item["prompt_tokens"] * len(item["outputs"])
        tokens[item["model"]]["sample"] += sum(len(x["tokens"]) for x in item["outputs"])
    training = []
    for p in sorted((run / "training").glob("*/checkpoint.json")):
        item = json.loads(p.read_text())
        tokens[MODEL]["train"] += item["training_tokens"]
        training.append(item)
    token_cost = sum(sum(n * RATES[model][kind] / 1e6 for kind, n in count.items()) for model, count in tokens.items())
    reservations = sum(json.loads(x)["ceiling_usd"] for x in (run / "cost-reservations.jsonl").read_text().splitlines())
    constant = None
    pool_path = run / "review-pools" / "round-4.json"
    if pool_path.exists() and "k0-base" in data:
        pool = json.loads(pool_path.read_text())
        bysid = {r["sid"]: r for r in trajectories}
        from scorer import claims
        def constant_text(mode, events, tid, dep):
            return canonical({"lemmas_proved": [tid] if mode == "proved" else [],
                              "lemmas_partial": [tid] if mode == "partial" else [],
                              "events": ["E6:" + dep if e == "E6" and dep else e for e in events]})
        candidates = []
        for mode in ("proved", "partial", "neither"):
            for bits in itertools.product((False, True), repeat=6):
                events = [f"E{i+1}" for i, selected in enumerate(bits) if selected]
                scores = []
                for row in pool:
                    rec = bysid[row["sid"]]
                    truth = claims(header_of(row["corrected_report"]))
                    # A reviewer can incorrectly return an empty claim set.
                    # Such a target gives every constant candidate zero credit;
                    # compiler truth sets used for the main score are nonempty.
                    scores.append(score(constant_text(mode, events, rec["task"]["id"], rec["task"]["dep"]), truth, rec["task"]["id"])["F"] if truth else 0.0)
                candidates.append((mean(scores), mode, events))
        train_score, mode, events = max(candidates, key=lambda x: x[0])
        from tasks import catalogue
        taskmap = {t.id: t for t in catalogue()["heldout"]}
        held = data["k0-base"]["results"]
        held_score = mean(score(constant_text(mode, events, r["lemma"], taskmap[r["lemma"]].dep), r["truth"], r["lemma"])["F"] for r in held)
        constant = {"mode": mode, "events": events, "training_F": train_score, "heldout_F": held_score,
                    "empty_review_targets": sum(not claims(header_of(x["corrected_report"])) for x in pool),
                    "empty_target_policy": "Zero credit for every candidate; no compiler labels used for selection"}
    result = {"curve": curve, "outcome": outcome, "first_sustained_point_lead_reviews": crossing,
              "live": live, "reviewed_sessions": len(review_quality),
              "review_failures": sum(x is None for x in review_quality),
              "corrected_report_mean_F": mean(x for x in review_quality if x is not None),
              "corrected_report_strict_accuracy": mean(float(x == 1) for x in review_quality if x is not None),
              "history_audit": audit, "history_primary_difference": audit_difference,
              "training": training, "tokens": dict(tokens), "uncached_token_estimate_usd": token_cost,
              "best_constant_header": constant,
              "reserved_ceiling_usd": reservations, "billing_note": "Not an invoice; excludes storage and failed output retrieval; no cache discount applied",
              "human_smoke_test": json.loads((run / "human-smoke-test.json").read_text()) if (run / "human-smoke-test.json").exists() else {"status": "not_completed"}}
    save(run / "analysis.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("run")
    args = parser.parse_args()
    r = analyze(args.run)
    print(canonical({k: r[k] for k in ("outcome", "curve", "reviewed_sessions", "uncached_token_estimate_usd")}))
