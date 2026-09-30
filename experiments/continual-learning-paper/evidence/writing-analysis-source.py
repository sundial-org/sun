"""Recompute all reported results from saved drafts, edits, and samples."""
from collections import defaultdict
from datetime import datetime
import argparse
import itertools
import json
import math
from pathlib import Path
import statistics
import subprocess
import shutil

import numpy as np

from data import canonical, sha

ROOT = Path(__file__).resolve().parent


def read(path):
    return json.loads(Path(path).read_text())


def interval(values, seed=1701):
    values = np.asarray(values, dtype=float)
    if not len(values):
        return {"mean": None, "ci95": [None, None], "n": 0}
    rng = np.random.default_rng(seed)
    means = values[rng.integers(0, len(values), size=(10000, len(values)))].mean(axis=1)
    return {"mean": float(values.mean()), "ci95": np.quantile(means, [.025, .975]).tolist(), "n": len(values)}


def prompt_means(rows, guide="A", flipped=False):
    grouped = defaultdict(list)
    for row in rows:
        score = row["scores"][guide]
        value = score["S"]
        if flipped:
            applicable = [v for v in score["rules"][5:8] if v is not None]
            value = sum(applicable) / max(1, len(applicable))
        grouped[row["prompt"]["id"]].append(float(row["U"]) * value)
    return {k: statistics.mean(v) for k, v in grouped.items()}


def difference(left, right):
    if set(left) != set(right):
        raise ValueError("Unpaired prompt sets")
    return interval([left[k] - right[k] for k in sorted(left)])


def selection_probabilities(rewards, n):
    """Exact subset-averaged best-of-n, with uniform ties, without replacement."""
    m = len(rewards)
    total = math.comb(m, n)
    result = [0.] * m
    for reward in set(rewards):
        lo = sum(v < reward for v in rewards)
        hi = sum(v <= reward for v in rewards)
        probability = (math.comb(hi, n) - (math.comb(lo, n) if lo >= n else 0)) / total / (hi - lo)
        for i, value in enumerate(rewards):
            if value == reward:
                result[i] = probability
    if abs(sum(result) - 1) > 1e-9:
        raise ValueError("Selection probabilities do not sum to one")
    return result


def best_of_n(rows):
    grouped = defaultdict(dict)
    for row in sorted(rows, key=lambda r: r["id"]):
        if row["U"]:
            grouped[row["prompt"]["id"]].setdefault(row["story"], row)
    records = []
    for prompt, mapping in grouped.items():
        pool = list(mapping.values())
        if len(pool) < 4:
            continue
        s = [r["scores"]["S"] for r in pool]
        kept = [r["provenance"]["kept"] if r.get("editor_valid") else -1 for r in pool]
        p = selection_probabilities(kept, 4)
        oracle = selection_probabilities(s, 4)
        records.append({"prompt": prompt, "candidates": len(pool), "uniform": statistics.mean(s),
                        "selected": sum(a*b for a, b in zip(p, s)),
                        "oracle": sum(a*b for a, b in zip(oracle, s)),
                        "uniform_words": statistics.mean(r["scores"]["words"] for r in pool),
                        "selected_words": sum(a*r["scores"]["words"] for a, r in zip(p, pool)),
                        "kl_nats": sum(a*math.log(a*len(pool)) for a in p if a)})
    return {"prompts": records, "uniform": interval([r["uniform"] for r in records]),
            "selected": interval([r["selected"] for r in records]),
            "gain": interval([r["selected"]-r["uniform"] for r in records]),
            "oracle_gain": interval([r["oracle"]-r["uniform"] for r in records]),
            "words_change": interval([r["selected_words"]-r["uniform_words"] for r in records]),
            "total_samples": len(rows), "valid_samples": sum(r["U"] for r in rows)}


def analyze(run):
    evaluations = {p.stem: read(p) for p in (run / "evaluations").glob("*.json")}
    if "base" not in evaluations:
        raise ValueError("No held-out evaluation yet")
    base = prompt_means(evaluations["base"])
    curve, counts = [], {}
    for x in [15, 30, 60, 120, 240, 360, 480]:
        weight_names = [f"weights-{x}-s{s}" for s in range(3) if f"weights-{x}-s{s}" in evaluations]
        context_name = f"context-{x}"
        if not weight_names or context_name not in evaluations:
            continue
        wr = list(itertools.chain.from_iterable(evaluations[n] for n in weight_names))
        cr = evaluations[context_name]
        wm, cm = prompt_means(wr), prompt_means(cr)
        manifest = read(run / "training" / weight_names[0] / "checkpoint.json")
        curve.append({"x": x, "weights": interval(list(wm.values())), "context": interval(list(cm.values())),
                      "difference": difference(wm, cm), "rows": manifest["rows"], "seeds": len(weight_names),
                      "weight_U": statistics.mean(r["U"] for r in wr), "context_U": statistics.mean(r["U"] for r in cr),
                      "weight_conditional_S": statistics.mean(r["scores"]["A"]["S"] for r in wr if r["U"]) if any(r["U"] for r in wr) else None,
                      "context_conditional_S": statistics.mean(r["scores"]["A"]["S"] for r in cr if r["U"]) if any(r["U"] for r in cr) else None,
                      "seed_means": [statistics.mean(prompt_means(evaluations[n]).values()) for n in weight_names]})
    for p in (run / "collections").glob("*-round-*.json"):
        rows = read(p)
        counts[p.stem] = {"sessions": len(rows), "valid": sum(r["U"] for r in rows),
                           "targets": sum(r.get("editor_valid", False) for r in rows)}
    controls = {}
    for kind in ("lora-A", "lora-B", "self"):
        names = [f"{kind}-480-s{s}" for s in range(3) if f"{kind}-480-s{s}" in evaluations]
        if names:
            rows = list(itertools.chain.from_iterable(evaluations[n] for n in names))
            controls[kind] = {"seeds": len(names), "A": prompt_means(rows), "B": prompt_means(rows, "B"),
                              "flipped_A": prompt_means(rows, "A", True), "flipped_B": prompt_means(rows, "B", True),
                              "U": statistics.mean(r["U"] for r in rows)}
    comparisons = {}
    if {"lora-A", "lora-B"} <= set(controls):
        comparisons["A_specificity"] = difference(controls["lora-A"]["flipped_A"], controls["lora-B"]["flipped_A"])
        comparisons["B_specificity"] = difference(controls["lora-B"]["flipped_B"], controls["lora-A"]["flipped_B"])
        comparisons["A_gain_over_base"] = difference(controls["lora-A"]["flipped_A"], prompt_means(evaluations["base"], "A", True))
        comparisons["B_gain_over_base"] = difference(controls["lora-B"]["flipped_B"], prompt_means(evaluations["base"], "B", True))
    if {"lora-A", "self"} <= set(controls):
        comparisons["edited_vs_self"] = difference(controls["lora-A"]["A"], controls["self"]["A"])
    if "context-shared-480" in evaluations and "lora-A" in controls:
        comparisons["shared_weights_vs_context"] = difference(controls["lora-A"]["A"], prompt_means(evaluations["context-shared-480"]))
    costs = [json.loads(l) for l in (run / "costs.jsonl").read_text().splitlines()]
    diagnostics = {}
    for name, rows in evaluations.items():
        diagnostics[name] = {"samples": len(rows), "valid": sum(r["U"] for r in rows),
            "validity": statistics.mean(r["U"] for r in rows),
            "format_failures": {"too_short": sum(not r["U"] and r["format"]["words"] < 120 for r in rows),
                                "too_long": sum(not r["U"] and r["format"]["words"] > 350 for r in rows),
                                "empty_story": sum(not r["story"] for r in rows),
                                "missing_anchor": sum(not all(r["format"]["required_words"].values()) for r in rows)},
            "mean_words": statistics.mean(r["format"]["words"] for r in rows),
            "conditional_style": {g: statistics.mean(r["scores"][g]["S"] for r in rows if r["U"])
                                  if any(r["U"] for r in rows) else None for g in ("A", "B")},
            "genre_US": {genre: statistics.mean(r["U"] * r["scores"]["A"]["S"]
                        for r in rows if r["prompt"]["genre"] == genre)
                        for genre in sorted({r["prompt"]["genre"] for r in rows})},
            "rules": {g: [{"applicable": sum(r["scores"][g]["rules"][i] is not None for r in rows),
                            "passed": sum(r["scores"][g]["rules"][i] is True for r in rows)}
                           for i in range(8)] for g in ("A", "B")}}
    progress = [json.loads(l) for l in (run / "progress.jsonl").read_text().splitlines()]
    finished = next((r["time"] for r in reversed(progress) if r["event"] == "experiment_complete"), None)
    main_minutes = (datetime.fromisoformat(finished) - datetime.fromisoformat(read(run / "freeze.json")["time"])).total_seconds()/60 if finished else None
    result = {"run": run.name, "editor": read(run / "freeze.json")["editor"], "base": interval(list(base.values())), "curve": curve, "counts": counts,
              "comparisons": comparisons, "controls": controls,
              "diagnostics": diagnostics, "main_minutes": main_minutes,
              "estimated_usd": sum(r.get("estimated_usd", 0) for r in costs),
              "reserved_usd": sum(r.get("reserved_usd", 0) for r in costs),
              "complete": (read(run/"status.json").get("phase") == "complete") if (run/"status.json").exists() else False,
              "evaluation_files": {p.name: sha(p.read_text()) for p in (run/"evaluations").glob("*.json")}}
    if (run / "best_of_n.json").exists():
        result["best_of_n"] = best_of_n(read(run / "best_of_n.json"))
    if "context-shared-480" in evaluations and "lora-A" in controls:
        result["shared_archive"] = {
            "weights": interval(list(controls["lora-A"]["A"].values())),
            "context": interval(list(prompt_means(evaluations["context-shared-480"]).values())),
            "rows": read(run / "training" / "lora-A-480-s0" / "checkpoint.json")["rows"]}
    if (run / "calibration.json").exists():
        calibration = read(run / "calibration.json")
        result["calibration"] = {g: {"mean_before": statistics.mean(r["before"][g]["S"] for r in calibration),
                                      "mean_after": statistics.mean(r["after"][g]["S"] for r in calibration if g in r["after"]),
                                      "valid": sum(r["edits"].get(g, {}).get("valid", False) for r in calibration),
                                      "total": len(calibration)} for g in ("A", "B")}
    (run / "analysis.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def percent(x):
    return f"{100*x:.1f}"


def effect(metric):
    return f"{100*metric['mean']:+.1f} [{100*metric['ci95'][0]:+.1f}, {100*metric['ci95'][1]:+.1f}]"


def report(result):
    if not result["complete"]:
        raise ValueError("The final report requires a complete run; do not relabel partial results")
    curve = result["curve"]
    final = next(p for p in curve if p["x"] == 480)
    lower, upper = final["difference"]["ci95"]
    headline = "Weights outperform example context at the endpoint in the live arms." if lower > 0 else (
        "Example context outperforms weights at the endpoint in the live arms." if upper < 0 else "The endpoint comparison between the live arms is inconclusive.")
    first_lead = next((p["x"] for p in curve if p["difference"]["ci95"][0] > 0), None)
    cross = f"A pointwise advantage is already present at {first_lead} edits." if first_lead else "No tested budget resolves an advantage for weights."
    if first_lead and lower <= 0:
        cross += " No lasting crossover is established."
    unresolved = [p["x"] for p in curve[:-1] if p["difference"]["ci95"][0] <= 0 <= p["difference"]["ci95"][1]]
    if unresolved:
        cross += " The comparison at " + ", ".join(map(str, unresolved)) + " edits is inconclusive." if len(unresolved) == 1 else " Comparisons at budgets " + ", ".join(map(str, unresolved)) + " are inconclusive."
    table = "\n".join(f"{p['x']} & {p['rows']} & {percent(p['context']['mean'])} & {percent(p['weights']['mean'])} \\\\" for p in curve)
    coords = lambda arm: " ".join(f"({p['x']},{100*p[arm]['mean']:.3f})" for p in curve)
    controls = result["comparisons"]
    bon = result["best_of_n"]
    sessions = sum(v["sessions"] for v in result["counts"].values())
    targets = sum(v["targets"] for v in result["counts"].values())
    qa = result["calibration"]
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    with plt.rc_context({"font.size": 9, "axes.spines.top": False, "axes.spines.right": False,
                         "pdf.fonttype": 42}):
        fig, ax = plt.subplots(figsize=(4.45, 2.22), layout="constrained")
        for arm, color, marker, label in [("weights", "#1b5490", "o", "Weights"),
                                           ("context", "#be6716", "s", "Context")]:
            x = [p["x"] for p in curve]
            y = [100*p[arm]["mean"] for p in curve]
            ax.plot(x, y, color=color, marker=marker, markersize=3.5, label=label)
            ax.fill_between(x, [100*p[arm]["ci95"][0] for p in curve],
                            [100*p[arm]["ci95"][1] for p in curve], color=color, alpha=.1, linewidth=0)
        ax.axhline(100*result["base"]["mean"], color=".5", linestyle="--", label="Base")
        ax.set(xlim=(0, 490), ylim=(0, 100), xticks=[0, 120, 240, 360, 480],
               xlabel="Cumulative review budget", ylabel="Valid-format style score (%)")
        ax.grid(alpha=.15)
        ax.legend(loc="lower right", frameon=False, fontsize=8)
        fig.savefig(ROOT / "learning_curve.pdf")
        plt.close(fig)
    text = r'''\documentclass[10pt,letterpaper]{article}
\usepackage[margin=0.62in]{geometry}
\usepackage[T1]{fontenc}
\usepackage{lmodern,booktabs,microtype,xcolor,graphicx}
\usepackage[hidelinks]{hyperref}
\pagestyle{empty}
\setlength{\parindent}{0pt}
\setlength{\parskip}{4pt}
\begin{document}
{\LARGE\bfseries Exp 2: Ten Writers}\hfill{\small 26 September 2026 (UTC)}\\[3pt]
{\large Hidden editorial style: context versus weights}\\[4pt]
\textbf{@@HEADLINE@@} After 480 review opportunities, the paired weights-minus-context
gap is \textbf{@@GAP@@ percentage points} (95\% prompt bootstrap interval).
Valid submissions follow @@WS@@ of rules for weights versus @@CS@@ for context,
but submission validity is @@WU@@ versus @@CU@@. @@CROSS@@
This compares complete learning workflows with separate evolving data pools.

\textbf{Experiment.} Ten concurrent Qwen3-8B tool-using writers per arm draft, check,
revise and submit 120--350 word stories. The fixed Inkling editor applies eight
private rules. Four rounds produce @@SESSIONS@@ live sessions and @@TARGETS@@ valid edited
targets across three arms: no feedback, retrieved examples in an 8k-token context,
and rank-16 LoRA retrained from base. Learning targets are replay-validated edited
tool trajectories. Writer and editor versions are separate attributed Sun commits.

\begin{minipage}[c]{0.64\linewidth}
\includegraphics[width=\linewidth]{learning_curve.pdf}
\end{minipage}\hfill
\begin{minipage}[c]{0.33\linewidth}
\centering\small
\begin{tabular}{rrrr}\toprule
Reviews & Rows & Ctx. & Wts.\\\midrule
@@TABLE@@
\bottomrule\end{tabular}\\[4pt]
\footnotesize Scores are percentages; base is @@BASE@@\%. Bands show 95\% intervals.
Rows are usable LoRA targets. Budgets 15--60
count valid edits. Endpoint weights average three training seeds; earlier points use one.
Endpoint seed means span @@SEEDRANGE@@.
\end{minipage}

\textbf{Which editor?} Using @@CONTROLROWS@@ matched base drafts and three seeds per editor,
opposite-editor adapters yield an A-style advantage of @@ASPEC@@ pp for LoRA-A over LoRA-B, and a
B-style advantage of @@BSPEC@@ pp for LoRA-B over LoRA-A, scored on the three flipped
rules. Edited versus unedited-target SFT differs by @@SELF@@ pp on guide A.
On the shared A-edited archive, weights score @@SHAREDW@@ versus @@SHAREDC@@ for context,
an endpoint gap of @@SHARED@@ pp.

\textbf{Can edits rank drafts?} Best-of-4 selection by words kept changes hidden-rule
compliance for A by @@BON@@ pp versus a uniform choice on the same candidate pools
(@@BONN@@ held-out prompts; valid unique drafts, subset-averaged, uniform ties). An oracle selecting by
the secret score gains @@ORACLE@@ pp. Selection uses the original drafts' scores.
Mean story length changes by @@WORDS@@ words.
Kept ignores pure insertions; insertion-aware edit distance is retained in the data.

\textbf{Measurement and limits.} Evaluation uses 96 held-out prompts, four samples
each, with 48 prompts from unseen genres. Score is format validity times the share
of applicable rules passed, computed by fixed regex/token checks and a pinned
spaCy tagger. Intervals resample paired prompt means 10,000 times and are conditional
on the collected training data; intervals across budgets are pointwise, without
multiple-comparison correction. Calibration edited scores average @@QA@@ (A) and @@QB@@ (B).
There is no completed human smoke test or blind prose-quality evaluation;
this tests recovery of planted rules, not literary taste. Raw-example context, one
live trajectory per arm, heuristic checks, and imperfect edits limit generalization.
Best-of-4 is a selection test, not reward-based training.

\vfill
{\footnotesize\color{gray}Run: \texttt{@@RUN@@}. Estimated token charges: \$@@COST@@
(not a settled invoice). Reproduce with \texttt{analyze.py}; raw samples, training
manifests, costs and Sun provenance are retained under \texttt{runs/}.
Main-run wall time: @@HOURS@@ hours.}
\end{document}
'''
    values = {"HEADLINE": headline, "GAP": effect(final["difference"]), "CROSS": cross,
              "SESSIONS": str(sessions), "TARGETS": str(targets), "WEIGHTS": coords("weights"),
              "CONTEXT": coords("context"), "BASE": percent(result["base"]["mean"]), "TABLE": table,
              "ASPEC": effect(controls["A_specificity"]), "BSPEC": effect(controls["B_specificity"]),
              "SELF": effect(controls["edited_vs_self"]), "SHARED": effect(controls["shared_weights_vs_context"]),
              "SHAREDW": percent(result["shared_archive"]["weights"]["mean"]) + r"\%",
              "SHAREDC": percent(result["shared_archive"]["context"]["mean"]) + r"\%",
              "CONTROLROWS": str(result["shared_archive"]["rows"]),
              "BON": effect(bon["gain"]), "BONN": str(bon["gain"]["n"]), "ORACLE": effect(bon["oracle_gain"]),
              "WORDS": f"{bon['words_change']['mean']:+.1f}",
              "QA": percent(qa["A"]["mean_after"]) + r"\%", "QB": percent(qa["B"]["mean_after"]) + r"\%",
              "WU": percent(final["weight_U"]) + r"\%", "CU": percent(final["context_U"]) + r"\%",
              "WS": percent(final["weight_conditional_S"]) + r"\%" if final["weight_conditional_S"] is not None else "undefined",
              "CS": percent(final["context_conditional_S"]) + r"\%" if final["context_conditional_S"] is not None else "undefined",
              "SEEDRANGE": percent(min(final["seed_means"])) + "--" + percent(max(final["seed_means"])) + r"\%",
              "RUN": result["run"], "COST": f"{result['estimated_usd']:.2f}",
              "HOURS": f"{result['main_minutes']/60:.1f}"}
    for key, value in values.items():
        text = text.replace("@@"+key+"@@", value)
    if "@@" in text:
        raise ValueError("Unfilled report placeholder")
    (ROOT / "results.tex").write_text(text)
    latex = shutil.which("pdflatex") or "/Library/TeX/texbin/pdflatex"
    subprocess.run([latex, "-interaction=nonstopmode", "-halt-on-error", "results.tex"],
                   cwd=ROOT, check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("run", nargs="?", default="ten-writers-20260926-inkling")
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args()
    run = ROOT / "runs" / args.run
    result = analyze(run)
    if args.report:
        report(result)
    print(canonical({"complete": result["complete"], "points": len(result["curve"]),
                     "estimated_usd": result["estimated_usd"]}))
