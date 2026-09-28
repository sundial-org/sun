"""Offline rejection checks. This cannot authorize or launch a v2 experiment.

The legacy adapter reads original evidence with the original scorer. A future
v2 runner must emit equivalent evidence using its separately validated scorer,
and enforce all the additional protocol gates before making paid requests.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from protocol import parse_action
from scorer import facts, score


def check_evidence(evidence, design):
    checks = []

    def check(name, key, predicate, required):
        observed = evidence.get(key)
        passed = observed is not None and predicate(observed)
        checks.append({"check": name, "passed": bool(passed),
                       "observed": observed, "required": required,
                       "missing_evidence": observed is None})

    sealed = design["sealed_natural_gates"]
    dev = design["development_gates"]
    for name, key, minimum in [
        ("independent evaluation groups", "independent_groups", sealed["min_independent_groups"]),
        ("evaluation traces", "traces", sealed["min_traces"]),
        ("proved coverage", "proved_fraction", sealed["min_proved_fraction"]),
        ("unproved coverage", "unproved_fraction", sealed["min_unproved_fraction"]),
        ("complete corrected reports", "complete_review_fraction", dev["reviewer_min_complete_report_rate"]),
    ]:
        check(name, key, lambda x, n=minimum: x >= n, f">= {minimum}")
    for name, key, maximum in [
        ("truth-pattern concentration", "largest_truth_pattern_fraction", sealed["max_truth_pattern_fraction"]),
        ("exit-rule shortcut", "exit_rule_score", sealed["max_exit_rule_score"]),
        ("invalid tool calls", "invalid_tool_fraction", dev["max_invalid_tool_call_fraction"]),
        ("wrong-path sessions", "wrong_path_fraction", dev["max_wrong_path_session_fraction"]),
        ("no-compile sessions", "no_compile_fraction", dev["max_no_compile_fraction"]),
    ]:
        check(name, key, lambda x, n=maximum: x <= n, f"<= {maximum}")
    for name, key in [
        ("disjoint template families", "disjoint_families"),
        ("unique session seeds", "unique_session_seeds"),
        ("reviewer qualification", "reviewer_qualified"),
        ("human smoke test", "human_smoke_test_complete"),
        ("development power calibration", "power_calibration_passed"),
        ("challenge coverage", "challenge_coverage_passed"),
        ("Sun history-case coverage", "sun_coverage_passed"),
    ]:
        check(name, key, lambda x: x is True, "documented true")
    return {
        "protocol_version": design["version"],
        "diagnostic_checks_passed": all(x["passed"] for x in checks),
        "ready_for_new_paid_run": False,
        "scope": "Retrospective rejection checks, not a v2 launch certificate",
        "implementation_blockers": design["required_before_new_paid_run"],
        "checks": checks,
    }


def legacy_evidence(run):
    run = Path(run)
    hashes = {}

    def read(path):
        raw = path.read_bytes()
        hashes[str(path.relative_to(run))] = hashlib.sha256(raw).hexdigest()
        return json.loads(raw)

    traces = [read(p) for p in sorted((run / "trajectories/heldout").glob("*.json"))]
    if not traces:
        raise ValueError("No held-out evidence; a missing dataset cannot pass")
    truths = [facts(t) for t in traces]
    patterns = Counter(tuple(sorted(x.split(":")[0] for x in truth)) for truth in truths)
    n = len(traces)
    exit_scores, seeds = [], []
    invalid = tool_turns = 0
    for trace, truth in zip(traces, truths):
        last = trace["receipts"][-1] if trace["receipts"] else None
        event = "E4" if not last or last["exit_code"] != 0 or last["timeout"] else "E5"
        report = json.dumps({"lemmas_proved": [], "lemmas_partial": [], "events": [event]})
        # v2 coverage checks use exact header agreement, not the v1 P*R score.
        exit_scores.append(score(report, truth, trace["task"]["id"])["strict"])
        for message in trace["report_messages"]:
            if message["role"] == "assistant":
                tool_turns += 1
                invalid += parse_action(message["content"]) is None
        path = run / "samples/live/heldout" / trace["sid"] / "tool00.json"
        if path.exists():
            seeds.append(read(path)["seed"])
    catalogue = read(run / "catalogue.json")
    family_sets = [{t["family"] for t in catalogue[split]} for split in ("train", "dev", "heldout")]
    pool = read(run / "review-pools/round-4.json")
    smoke = read(run / "human-smoke-test.json")
    return {
        "source": str(run.resolve()), "legacy_scorer": "v1, unchanged",
        "independent_groups": len({t["task"]["family"] for t in traces}),
        "traces": n,
        "proved_fraction": sum(any(x.startswith("proved:") for x in truth) for truth in truths) / n,
        "unproved_fraction": sum(not any(x.startswith(("proved:", "partial:")) for x in truth) for truth in truths) / n,
        "largest_truth_pattern_fraction": max(patterns.values()) / n,
        "exit_rule_score": sum(exit_scores) / n,
        "exit_rule_metric": "exact_header_match",
        "invalid_tool_fraction": invalid / tool_turns if tool_turns else 1.0,
        "wrong_path_fraction": sum(any(c["tool"] == "write_file" and
            c["input"].get("path") != "Blueprint/" + t["task"]["id"] + ".lean"
            for c in t["tool_calls"]) for t in traces) / n,
        "no_compile_fraction": sum(not t["receipts"] for t in traces) / n,
        "complete_review_fraction": sum(bool("\n".join(r["corrected_report"].splitlines()[1:]).strip())
                                        for r in pool) / len(pool),
        "disjoint_families": not any(family_sets[i] & family_sets[j] for i in range(3) for j in range(i)),
        "unique_session_seeds": len(seeds) == n and len(set(seeds)) == n,
        "human_smoke_test_complete": smoke.get("human_reviewed") is True,
        # Other checks intentionally remain absent, never assumed to have passed.
        "input_sha256": hashes,
        "legacy_scorer_sha256": hashlib.sha256((ROOT / "scorer.py").read_bytes()).hexdigest(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy-run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    design_path = Path(__file__).with_name("design.json")
    design = json.loads(design_path.read_text())
    evidence = legacy_evidence(args.legacy_run)
    result = check_evidence(evidence, design)
    result["evidence"] = evidence
    result["design_sha256"] = hashlib.sha256(design_path.read_bytes()).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"passed": result["diagnostic_checks_passed"],
                      "failed_checks": [x["check"] for x in result["checks"] if not x["passed"]],
                      "ready_for_new_paid_run": False}, indent=2))
    return 0 if result["diagnostic_checks_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
