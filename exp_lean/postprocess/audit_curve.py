"""Offline diagnostic of coverage and saturation, never a training input.

Preserves all original samples, scores, traces, and the frozen protocol. The
exit-code rule is explicitly post hoc and is not a preregistered baseline.
"""
from collections import Counter, defaultdict
import argparse
import hashlib
import json
from pathlib import Path
from statistics import mean
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from protocol import bounded_report, header_of
from scorer import facts, score


def sha(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def prose(text):
    return "\n".join(text.splitlines()[1:]).strip()


def audit(run):
    run = Path(run)
    inputs = {}

    def read(path):
        inputs[str(path.relative_to(run))] = sha(path)
        return json.loads(path.read_text())

    traces = {t["sid"]: t for t in (read(p) for p in sorted(
        (run / "trajectories/heldout").glob("*.json")))}
    if not traces:
        raise ValueError("No frozen held-out trajectories")
    truth = {sid: facts(t) for sid, t in traces.items()}
    pattern = lambda value: "+".join(sorted(x.split(":")[0] for x in value))
    rules = {}
    for sid, t in traces.items():
        last = t["receipts"][-1] if t["receipts"] else None
        event = "E4" if not last or last["exit_code"] != 0 or last["timeout"] else "E5"
        rules[sid] = {"lemmas_proved": [], "lemmas_partial": [], "events": [event]}
    rule_f = mean(score(json.dumps(rules[sid]), truth[sid], t["task"]["id"])["F"]
                  for sid, t in traces.items())
    constant_f = mean(score(json.dumps({"lemmas_proved": [], "lemmas_partial": [],
                                       "events": ["E4"]}), truth[sid], t["task"]["id"])["F"]
                      for sid, t in traces.items())
    evaluations, cache, strata = {}, {}, {}
    checked_reports = 0
    for path in sorted((run / "evaluation").glob("*.json")):
        e = read(path)
        if {r["sid"] for r in e["results"]} != set(traces):
            raise AssertionError("Unpaired evaluation")
        by_class = defaultdict(list)
        for row in e["results"]:
            sid, t = row["sid"], traces[row["sid"]]
            assert row["truth"] == sorted(truth[sid]), "Compiler truth mismatch"
            for mode in ("samples", "greedy"):
                identity = f"eval/k{e['checkpoint']}/{e['arm']}/{sid}/{mode}"
                s = read(run / "samples" / (identity + ".json"))
                raw = read(run / "provider-outputs" / (identity + ".json"))
                assert s["identity"] == identity and s["policy"] == e["policy"]
                assert s["prompt_hash"] == row["prompt_hash"]
                expected = row["reports"] if mode == "samples" else [row["greedy_report"]]
                expected_scores = row["scores"] if mode == "samples" else [row["greedy"]]
                assert len(raw) == len(s["outputs"]) == len(expected)
                for a, b, report, saved_score in zip(raw, s["outputs"], expected, expected_scores):
                    assert all(a[key] == b[key] for key in ("tokens", "logprobs", "stop_reason"))
                    assert bounded_report(b["text"]) == report
                    assert score(report, truth[sid], t["task"]["id"]) == saved_score
                    checked_reports += 1
                if mode == "samples":
                    cache[(path.stem, sid)] = s
            by_class[pattern(truth[sid])].extend(x["F"] for x in row["scores"])
        recalculated = mean(mean(x["F"] for x in row["scores"]) for row in e["results"])
        assert abs(recalculated - e["mean_F"]) < 1e-12
        evaluations[path.stem] = e
        strata[path.stem] = {key: {"reports": len(v), "mean_F": mean(v)}
                           for key, v in sorted(by_class.items())}
    checkpoints = []
    for k in range(1, 5):
        e = evaluations[f"k{k}-weights"]
        headers = texts = logprobs = matches = blank = total = 0
        imperfect = []
        for row in e["results"]:
            sid = row["sid"]
            first, current = cache[("k1-weights", sid)], cache[(f"k{k}-weights", sid)]
            for a, b, report in zip(first["outputs"], current["outputs"], row["reports"]):
                headers += header_of(a["text"]) == header_of(b["text"])
                texts += a["text"] == b["text"]
                logprobs += a["logprobs"] == b["logprobs"]
                matches += header_of(report) == rules[sid]
                blank += not prose(report)
                total += 1
            if any(s["F"] < 1 for s in row["scores"]):
                imperfect.append({"sid": sid, "truth": row["truth"],
                                  "missing": sorted({x for s in row["scores"] for x in s["missing"]})})
        counts = [len(r["retrieved_review_ids"]) for r in evaluations[f"k{k}-context"]["results"]]
        pool = read(run / f"review-pools/round-{k}.json")
        checkpoints.append({"checkpoint": k, "policy": e["policy"], "reports": total,
                            "identical_headers_to_k1": headers, "identical_texts_to_k1": texts,
                            "identical_logprobs_to_k1": logprobs, "exit_rule_header_matches": matches,
                            "blank_prose_reports": blank, "imperfect_traces": imperfect,
                            "context_reviews": {"min": min(counts), "mean": mean(counts), "max": max(counts)},
                            "review_pool": len(pool),
                            "blank_corrected_target_prose": sum(not prose(r["corrected_report"]) for r in pool)})
    adapters = read(run / "downloaded-adapters.json")
    adapter_hashes = []
    for adapter in adapters:
        path = run / "adapters" / adapter["checkpoint"] / "adapter_model.safetensors"
        actual = sha(path)
        assert actual == adapter["files"][path.name]
        adapter_hashes.append(actual)
    assert len(set(adapter_hashes)) == 4
    assert len({c["policy"] for c in checkpoints}) == 4
    coverage = Counter(x.split(":")[0] for value in truth.values() for x in value)
    needed = ["proved", "partial", "E1", "E2", "E3", "E4", "E5", "E6"]
    by_lemma = defaultdict(list)
    for t in traces.values():
        by_lemma[t["task"]["id"]].append(t)
    result = {
        "audit_kind": "post_hoc_offline_diagnostic", "run": run.name,
        "original_samples_and_scorer_unchanged": True, "verified_reports": checked_reports,
        "traces": len(traces), "lemmas": len(by_lemma),
        "truth_patterns": dict(sorted(Counter(pattern(x) for x in truth.values()).items())),
        "fact_coverage": {key: coverage[key] for key in needed},
        "missing_fact_categories": [key for key in needed if not coverage[key]],
        "no_compile": sum(not t["receipts"] for t in traces.values()),
        "failed_final_compile": sum(bool(t["receipts"]) and t["receipts"][-1]["exit_code"] != 0
                                    for t in traces.values()),
        "wrong_write_path_sessions": sum(any(c["tool"] == "write_file" and
            c["input"].get("path") != "Blueprint/" + t["task"]["id"] + ".lean"
            for c in t["tool_calls"]) for t in traces.values()),
        "lemmas_with_identical_action_lists_across_repeats": sum(len({json.dumps(
            [c["input"] for c in t["tool_calls"]], sort_keys=True) for t in rows}) == 1
            for rows in by_lemma.values()),
        "always_E4_F": constant_f, "post_hoc_exit_code_rule_F": rule_f,
        "post_hoc_rule": "No compile, failure or timeout -> E4; otherwise -> E5. No status or E6.",
        "checkpoints": checkpoints, "stratified_scores": strata,
        "adapter_sha256": adapter_hashes,
        "interpretation": "Collapsed evaluation coverage; no defensible review-count crossover conclusion.",
        "input_sha256": inputs,
    }
    (run / "curve-audit.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("run", type=Path)
    args = parser.parse_args()
    result = audit(args.run)
    print(json.dumps({k: v for k, v in result.items() if k != "input_sha256"}, indent=2))
