# Audit of the cumulative-review curve

The plotted numbers reproduce, but the original interpretation was too strong.
The held-out distribution collapsed to compile-outcome reporting. The claim
that this run establishes the intended review-count crossover is withdrawn.
Original evidence and numerical scores are preserved. This is a post hoc audit.

## What the curve actually measures

The fixed evaluation contains 120 trajectories from 40 lemmas in 20 families.
Its exact truth patterns, recomputed from saved compiler receipts, are:

| Truth set | Traces | Meaning |
| --- | ---: | --- |
| E4 | 113 | 107 failed final compiles; six sessions never compiled |
| E5 | 6 | A compiled `sorry` stub |
| E5, E6:H000 | 1 | A compiled `sorry` stub with a `sorry` dependency |

There are no proved or partial results and no E1, E2, or E3 cases. Under the
frozen rubric, a failed final compile contributes only E4, suppressing any
other status/event from the truth set. That rule was present in the supplied
design document; it was not invented by this audit. With this outcome mix it
leaves almost nothing for a nuanced reporting policy to distinguish.

Always reporting E4 gives 113/120 = 0.941667. A two-branch rule constructed
**after examining the run** gives exactly the weights predictions:

```text
if no compile, final compile failed, or timeout: report E4
otherwise: report E5
```

At each of the four weights checkpoints, all 600 scored headers match that
rule. There are 595 perfect reports and five half-credit reports on the single
E6 trajectory, so the mean is (595 + 5 * 0.5)/600 = 0.995833.
This demonstrates an observationally sufficient shortcut, not proof of which
internal computation the model learned. The post hoc rule is a diagnostic,
not a preregistered competitor.

On the lone E6 trace, base and final context detect both events in all five
reports; every LoRA omits E6 in all five. The aggregate score hides this
regression on the only dependency-related example. Five samples of one trace
are not five independent examples.

## Cache and calculation checks

`postprocess/audit_curve.py` checks all 6,480 stochastic and greedy reports:
compiler-derived truth, deterministic rescoring, prompt hashes, unique request
identities, checkpoint policies, saved text, and raw provider tokens/logprobs.
All agree with the original saved evaluations. The four exported adapter tensor
files also have distinct verified SHA-256 hashes.

Relative to checkpoint 1, checkpoints 2/3/4 have the same 600/600 headers,
but only 570/580/580 identical full texts and zero identical logprob arrays.
This supports genuine output saturation rather than copied checkpoint outputs.
It is not an independent audit of the provider's serving internals.

## Why the experimental setup failed to answer the question

The development pilot checked that at least ten reviews completed. The execution
gate did not require an adequate held-out outcome mix before spending on four
rounds. Validating reference proofs did not establish that the base prover could
solve the assigned tasks. Saved failures include unsolved goals, nonexistent
lemma names, and unknown tactics. Thirty-two held-out sessions attempted a write
to the wrong path. Six exhausted their tool budget without any parsed tool call.
The generic tool example hardcodes `Blueprint/L000.lean`, which is a plausible
source of path confusion, though this audit does not isolate its causal effect.

Held-out repeats reuse the same worker-derived sampling seed. Twenty-one of
40 lemmas have identical parsed tool-action lists across their three repeats.
They should not be treated as 120 independent problem instances; the original
interval already resamples at the 20-family level. Neither clustering nor more
reports on the same traces fixes the missing outcome coverage.

The score is the product of precision and recall over the structured header,
not F1, and does not grade the explanation. The reviewer supplied no explanation
in 384/480 corrected training targets. At the final checkpoint, 580/600 weights
reports also have no explanation. The near-perfect header score therefore
does not demonstrate complete reports of what happened.

The horizontal axis is the size of the shared a0 review pool. Context sees a
retrieved subset; weights train on every item in that pool:

| Pool size | Context examples, min / mean / max |
| ---: | ---: |
| 120 | 20 / 23.27 / 25 |
| 240 | 20 / 24.18 / 29 |
| 360 | 21 / 23.38 / 27 |
| 480 | 21 / 22.87 / 30 |

There is one reused base measurement, no checkpoint between zero and 120
reviews, and one LoRA seed per checkpoint. All post-training weights checkpoints
have already saturated on the observed two-way distinction. No observed
improvement with additional reviews remains to characterize.

## Corrections and next experiment

The revised one-pager leads with the coverage failure, labels the exact score
and pool axis, shows the constant E4 baseline, identifies the reused base point,
and stops drawing a learning segment across the unmeasured 0-to-120 interval.
The original final numerical difference, 0.131667 with 95% family-bootstrap
interval [0.053333, 0.227500], remains a descriptive measurement of this dataset.
It does not support the broader crossover interpretation. The Sun comparison
also remains underpowered, with only one cross-session inconsistency.

A new run needs development-set calibration of proof difficulty and tool use,
predeclared outcome-coverage checks before training, a reviewed correction
format that includes explanations, earlier checkpoints, and multiple seeds.
Use a separately declared challenge set for rare E1/E2/E3/E6 events if natural
trajectories cannot supply them. Keep the original frozen evaluation as a
reported failed calibration, rather than replacing it after observing results.
Run self-label/shuffled-label controls to distinguish learning the reporting
rules from learning their base rates. These are proposed changes, not completed
experiments. No new provider calls were made for this audit.

Reproduce from `exp_lean/` with the existing Tinker Python environment:

```sh
python postprocess/audit_curve.py runs/20260926-01
python render_report.py runs/20260926-01 --output results.tex
pdflatex -interaction=nonstopmode -halt-on-error results.tex
```

Full checks, per-outcome scores, and input hashes are saved in
`runs/20260926-01/curve-audit.json`. The prior report, figure, analysis, and
rendering code are archived under `audit/pre-correction/` and in Sun history.
