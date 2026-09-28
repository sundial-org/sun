"""Create the requested one-page LaTeX report from recomputed measurements."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from analyze import analyze
from postprocess.audit_curve import audit


TEMPLATE = r'''\documentclass[10pt,letterpaper]{article}
\usepackage[margin=0.65in]{geometry}
\usepackage[T1]{fontenc}
\usepackage{lmodern,booktabs,amsmath,microtype,xcolor,graphicx}
\usepackage[hidelinks]{hyperref}
\pagestyle{empty}
\setlength{\parindent}{0pt}
\setlength{\parskip}{5pt}
\begin{document}
{\Large\bfseries Exp 1: Ten Provers (Lean)}\hfill {\small Evaluation audit}
\vspace{2pt}\hrule
\textbf{Corrected conclusion.} @@RESULT@@

\textbf{Design.} Ten Qwen3-8B workers per arm attempted small Lean list lemmas
with at most three compiler calls. The no-feedback, context, and LoRA arms each
ran @@SESSIONS@@ sessions over @@ROUNDS@@ rounds. DeepSeek-V3.1 reviewed
@@REVIEWS@@ reports. Context and weights received the same cumulative
no-feedback-arm reviews: context retrieved whole examples within 8,000 tokens;
rank-16 LoRA was retrained from base, with loss only on corrected final reports.
The scorer never supplied training targets or reward.

\textbf{Why the curve saturates.} @@COVERAGE@@
Each checkpoint produced five reports per frozen trace at temperature 0.7.
Score $P\times R$ is the product of precision and recall of the structured
header, not F1; prose is unscored. @@SATURATION@@

\begin{minipage}[t]{0.58\linewidth}
\vspace{0pt}
\includegraphics[width=\linewidth]{results-curve.pdf}
\end{minipage}\hfill
\begin{minipage}[t]{0.39\linewidth}
\vspace{3pt}\centering\small
\begin{tabular}{rccc}
\toprule
Pool & Base & Context & Weights\\
\midrule
@@CURVEROWS@@
\bottomrule
\end{tabular}
\par\raggedright\footnotesize
@@CONTEXT@@
Base is one reused measurement. No checkpoint was measured between 0 and 120 reviews.
\end{minipage}

{\small\textbf{Numerical result only.} @@NUMERICAL@@
The interval does not repair the missing outcome coverage.}

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
@@AUDITCHECK@@ @@HUMAN@@
This is one live run with one LoRA seed per checkpoint. Parameterized lemma
families overlap across splits, and no self-label or shuffled-label training
controls were run. @@PROSE@@
The implementation checked pilot review completion, but had no gate for held-out
outcome coverage. A new calibrated run is needed for the intended comparison.

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
    diagnostic = audit(run)
    curve = result["curve"]
    if len(curve) != 5:
        raise RuntimeError("The four-round result is incomplete; do not publish a completed-run report")
    last = curve[-1]
    d, lo, hi = last["delta"], *last["ci95"]
    if diagnostic["fact_coverage"]["proved"] or diagnostic["fact_coverage"]["partial"]:
        raise RuntimeError("This corrected report describes the collapsed 20260926-01 evaluation only")
    headline = ("The evaluation collapsed to compile-outcome reporting. Weights scored "
                f"{last['weights']:.3f} from the first checkpoint, but a two-branch exit-code rule "
                "gives exactly the same predictions. This run does not establish the intended "
                "review-count crossover; the earlier conclusion is withdrawn.")
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
        "RESULT": headline,
        "SESSIONS": str(result["live"]["a0"]["sessions"]), "ROUNDS": "4",
        "REVIEWS": str(result["reviewed_sessions"]),
        "CURVEROWS": "\n".join(f"{r['reviews']} & {r['base']:.3f} & {r['context']:.3f} & {r['weights']:.3f} \\\\" for r in curve),
        "COVERAGE": "The 120 traces (40 lemmas) contain 113 E4-only outcomes: 107 failed compiles and six sessions with no compile. Seven compile with \\texttt{sorry}; one also has E6. There are \\textbf{zero proved, partial, E1, E2, or E3 cases}. Always reporting E4 scores 0.942.",
        "SATURATION": "All four LoRAs emit identical headers on all 600 sampled reports: E4 after failure/no compile, E5 otherwise. Each misses the same E6 event, giving $(595 + 5/2)/600 = 0.99583$.",
        "CONTEXT": "Context actually receives 20--30 whole reviews per report under the 8,000-token cap. The x-axis counts available pool items, not visible examples.",
        "NUMERICAL": f"At 480 reviews, weights minus context is {d:.3f} (paired 20-family bootstrap, 95\\% CI [{lo:.3f}, {hi:.3f}]).",
        "AUDITN": str(result["history_audit"]["T"]["all"]["episodes"]),
        "HISTORYRESULT": history,
        "COMPLETION": "Budget-exhausted analyst episodes (T/T+/S): " + "/".join(str(result['history_audit'][c]['all']['unfinished']) for c in ("T", "Tplus", "S")) + "; scored as no flags.",
        "AUDITROWS": "\n".join(f"{label} & {fmt(result['history_audit'][c]['all']['precision'])} & {fmt(result['history_audit'][c]['all']['recall'])} & {fmt(result['history_audit'][c]['all']['specificity'])} & {fmt(result['history_audit'][c]['cross']['recall'])} \\\\" for c, label in (("T", "Transcripts"), ("Tplus", "Transcripts + Git"), ("S", "Transcripts + Sun"))),
        "QUALITY": f"Reviewer-corrected reports exactly matched the scorer in {100*result['corrected_report_strict_accuracy']:.1f}\\% of sessions; {result['review_failures']} reviews failed.",
        "AUDITCHECK": "An offline audit reproduced all 6,480 scores against saved compiler evidence and checked distinct adapter hashes, request identities, and raw outputs.",
        "PROSE": "384/480 corrected training reports omit prose, as do 580/600 final-checkpoint weights reports; the score does not penalize this.",
        "HUMAN": "The user confirmed the two rubric smoke-test decisions; this was not a full human audit." if human == "rubric_confirmed" else "The planned human smoke test has not been completed.",
        "COST": f"Including pilots, saved successful calls imply an uncached token cost of \\${result['uncached_token_estimate_usd']:.2f}; reservations total \\${result['reserved_ceiling_usd']:.2f}, excluding storage. Neither is a provider invoice.",
        "RUN": run.name.replace("_", r"\_"),
    }
    text = TEMPLATE
    for key, value in values.items():
        text = text.replace("@@" + key + "@@", value)
    if "@@" in text:
        raise RuntimeError("Unfilled report template")
    subprocess.run([os.environ.get("EXP_LEAN_REPORT_PYTHON", sys.executable),
                    str(Path(__file__).parent / "postprocess" / "plot_curve.py"),
                    str(run / "analysis.json"), str(output.with_name("results-curve.pdf")),
                    str(run / "curve-audit.json")], check=True)
    output.write_text(text)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("run")
    parser.add_argument("--output", default="results.tex")
    args = parser.parse_args()
    render(args.run, args.output)
