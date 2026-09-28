"""Create the requested one-page LaTeX report from recomputed measurements."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from analyze import analyze


TEMPLATE = r'''\documentclass[10pt,letterpaper]{article}
\usepackage[margin=0.65in]{geometry}
\usepackage[T1]{fontenc}
\usepackage{lmodern,booktabs,amsmath,microtype,xcolor,graphicx}
\usepackage[hidelinks]{hyperref}
\pagestyle{empty}
\setlength{\parindent}{0pt}
\setlength{\parskip}{5pt}
\begin{document}
{\Large\bfseries Exp 1: Ten Provers (Lean)}\hfill {\small @@DATE@@}
\vspace{2pt}\hrule
\textbf{Result.} @@RESULT@@

\textbf{Design.} Ten Qwen3-8B workers per arm attempted small Lean list lemmas
with at most three compiler calls. The no-feedback, context, and LoRA arms each
ran @@SESSIONS@@ sessions over @@ROUNDS@@ rounds. DeepSeek-V3.1 reviewed
@@REVIEWS@@ reports. Context and weights received the same cumulative
no-feedback-arm reviews: context retrieved whole examples within 8,000 tokens;
rank-16 LoRA was retrained from base, with loss only on corrected final reports.
The scorer never supplied training targets or reward.

\textbf{Reporting accuracy.} Frozen base-agent trajectories were generated once
for 40 held-out lemmas (120 traces). Each checkpoint produced five reports per
trace at temperature 0.7. Score $F=P\times R$ measures precision and recall of
the structured status/event header; prose is unscored. Malformed reports score zero. The paired 95\%
interval resamples 20 lemma families (10,000 draws).

\begin{minipage}[t]{0.58\linewidth}
\vspace{0pt}
\includegraphics[width=\linewidth]{results-curve.pdf}
\end{minipage}\hfill
\begin{minipage}[t]{0.39\linewidth}
\vspace{3pt}\centering\small
\begin{tabular}{rccc}
\toprule
Reviews & Base & Context & Weights\\
\midrule
@@CURVEROWS@@
\bottomrule
\end{tabular}
\par\raggedright\footnotesize
@@TRAINING@@
@@CONSTANT@@
\end{minipage}

\textbf{Does Sun help the analyst?} A fresh DeepSeek-V3.1 analyst inspected
the same @@AUDITN@@ sessions through transcripts (T), transcripts plus ordinary
Git history (T+), or transcripts plus Sun log/show/blame (S), with 15 calls per
episode and no access to earlier reviews or scorer verdicts. @@HISTORYRESULT@@
\begin{center}\small
\begin{tabular}{lrrrr}
\toprule
View & Precision & Recall & Specificity & E3/E6 recall\\
\midrule
@@AUDITROWS@@
\bottomrule
\end{tabular}
\end{center}
{\footnotesize @@COMPLETION@@}

\textbf{Checks and limits.} @@QUALITY@@
All 160 reference proofs passed Lean and the clean-context check; six automated
scorer tests cover failures, statement changes, custom axioms, direct/transitive
\texttt{sorry}, omissions, and overwrite attribution. @@HUMAN@@
This is one live run with one LoRA seed per checkpoint. Parameterized lemma
families overlap across splits, and no self-label or shuffled-label training
controls were run. Logged operational amendments repaired pagination, context
overflow, transport retries, and run snapshots. These results measure reporting on base-agent traces, not
general theorem-proving ability or deliberate deception.

{\footnotesize\textbf{Reproducibility.} Sun was initialized for the experiment,
run, pilot, held-out and arm repositories. Saved compiler receipts, Sun commits,
review checks, samples, source hashes, and exported adapters support offline
recomputation. @@COST@@\quad Run: \texttt{@@RUN@@}.}
\end{document}
'''


def fmt(x, digits=3):
    return "--" if x is None else f"{x:.{digits}f}"


def render(run, output):
    run, output = Path(run), Path(output)
    result = analyze(run)
    curve = result["curve"]
    if len(curve) != 5:
        raise RuntimeError("The four-round result is incomplete; do not publish a completed-run report")
    last = curve[-1]
    d, lo, hi = last["delta"], *last["ci95"]
    if lo > 0:
        headline = f"At 480 reviews, weights exceeded context by {d:.3f} score units (95\\% CI [{lo:.3f}, {hi:.3f}])."
    elif hi < 0:
        headline = f"At 480 reviews, context exceeded weights by {-d:.3f} score units (weights minus context: 95\\% CI [{lo:.3f}, {hi:.3f}])."
    else:
        headline = f"The final weights--context difference was inconclusive: {d:+.3f} (95\\% CI [{lo:.3f}, {hi:.3f}])."
    crossing = result["first_sustained_point_lead_reviews"]
    headline += (f" The first observed lead that persisted through the remaining checkpoints was at {crossing} reviews."
                 if crossing else " No sustained point-estimate crossover was observed within 480 reviews.")
    constant = result["best_constant_header"]
    if constant and last["weights"] <= constant["heldout_F"]:
        headline += " Weights did not exceed the best constant-header baseline."
    h = result["history_primary_difference"]
    if not h or h["instances"] < 20:
        n = h["instances"] if h else 0
        history = (f"Sun recall was {result['history_audit']['S']['all']['recall']:.3f} versus "
                   f"{result['history_audit']['T']['all']['recall']:.3f} for transcripts, with similarly low precision. "
                   f"The primary E3/E6 comparison (overwrites or borrowed \\texttt{{sorry}}) had only {n} "
                   f"{'inconsistency' if n == 1 else 'inconsistencies'} and is underpowered.")
    else:
        history = (f"For cross-session inconsistencies (E3/E6, $n={h['instances']}$), "
                   f"S minus T+ recall was {h['delta']:+.3f} (95\\% CI [{h['ci95'][0]:.3f}, {h['ci95'][1]:.3f}]).")
    training = result["training"]
    human = result["human_smoke_test"].get("status")
    values = {
        "DATE": "26 September 2026",
        "RESULT": headline,
        "SESSIONS": str(result["live"]["a0"]["sessions"]), "ROUNDS": "4",
        "REVIEWS": str(result["reviewed_sessions"]),
        "CURVEROWS": "\n".join(f"{r['reviews']} & {r['base']:.3f} & {r['context']:.3f} & {r['weights']:.3f} \\\\" for r in curve),
        "TRAINING": "Optimizer steps: " + ", ".join(str(x["completed_steps"]) for x in training) + ".",
        "CONSTANT": (("Always reporting compile failure" if constant["mode"] == "neither" and constant["events"] == ["E4"] else "Best constant header") + f": $F={constant['heldout_F']:.3f}$ (selected on corrected training reports).") if constant else "",
        "AUDITN": str(result["history_audit"]["T"]["all"]["episodes"]),
        "HISTORYRESULT": history,
        "COMPLETION": "Budget-exhausted analyst episodes (T/T+/S): " + "/".join(str(result['history_audit'][c]['all']['unfinished']) for c in ("T", "Tplus", "S")) + "; scored as no flags.",
        "AUDITROWS": "\n".join(f"{label} & {fmt(result['history_audit'][c]['all']['precision'])} & {fmt(result['history_audit'][c]['all']['recall'])} & {fmt(result['history_audit'][c]['all']['specificity'])} & {fmt(result['history_audit'][c]['cross']['recall'])} \\\\" for c, label in (("T", "Transcripts"), ("Tplus", "Transcripts + Git"), ("S", "Transcripts + Sun"))),
        "QUALITY": f"Reviewer-corrected reports exactly matched the scorer in {100*result['corrected_report_strict_accuracy']:.1f}\\% of sessions; {result['review_failures']} reviews failed.",
        "HUMAN": "The user confirmed the two rubric smoke-test decisions; this was not a full human audit." if human == "rubric_confirmed" else "The planned human smoke test has not been completed.",
        "COST": f"Including pilots, saved successful calls imply an uncached token cost of \\${result['uncached_token_estimate_usd']:.2f}; reservations total \\${result['reserved_ceiling_usd']:.2f}, excluding storage. Neither is a provider invoice.",
        "RUN": run.name.replace("_", r"\_"),
    }
    for arm in ("base", "context", "weights"):
        values[arm.upper() + "COORD"] = " ".join(f"({r['reviews']},{r[arm]:.6f})" for r in curve)
    text = TEMPLATE
    for key, value in values.items():
        text = text.replace("@@" + key + "@@", value)
    if "@@" in text:
        raise RuntimeError("Unfilled report template")
    subprocess.run([os.environ.get("EXP_LEAN_REPORT_PYTHON", sys.executable),
                    str(Path(__file__).parent / "postprocess" / "plot_curve.py"),
                    str(run / "analysis.json"), str(output.with_name("results-curve.pdf"))], check=True)
    output.write_text(text)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("run")
    parser.add_argument("--output", default="results.tex")
    args = parser.parse_args()
    render(args.run, args.output)
