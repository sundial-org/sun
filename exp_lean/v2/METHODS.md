# Ten Provers, revised methods

**Status: revised protocol, not a new result.** Run `20260926-01` is a failed
calibration study. Its original evidence remains immutable. No v2 model calls,
training, reviewer qualification, or human validation have been performed.
`design.json` fixes proposed thresholds; `readiness.py` demonstrates that the old
run fails them. These files do not make the old runner v2 compliant.

The user's simplified experiment is the objective. The attached design is
background, not an instruction to execute every proposed extension. This
revision retains ten Qwen3-8B workers per arm, four rounds of 120 sessions per
arm, three compiles per session, a separate frozen strong reviewer, cumulative
reviews, report-only LoRA training, a deterministic scorer, and Sun provenance.
It changes the evaluation, controls, failure gates, and permissible claims.

## 1. Questions and units of inference

**A. Report learning.** On a fixed population of previously unseen natural
base-prover trajectories, does training on corrected reports improve the exact
status-and-event report relative to an 8,000-token retrieval prompt? The primary
endpoint is the paired difference at 480 reviews. A review-count crossover is a
secondary, discrete-checkpoint result, available only if the final comparison
and the coverage checks are informative.

This is a practical comparison under a context limit. It is not an equal-token,
equal-compute, or equal-example-exposure comparison. A separate fixed-subset
control addresses the last of those distinctions.

**B. Sun-assisted review.** Given identical underlying evidence and fixed access
budgets, does a fresh strong-model analyst detect more cross-session reporting
errors with Sun than with ordinary Git? Transcripts alone are secondary. This
comparison does not depend on A succeeding.

The live three-arm prover loop remains useful: report actual proving rates,
`sorry` use, invalid tool calls, and dependency poisoning per round. With one
live corpus per arm these are descriptive. Ten copies and hundreds of sessions
are not independent experimental replicates. The main inference unit is a
connected dependency component, merged with any component sharing a task
template. Repeated traces, report samples, and workers stay within that group.

## 2. Repair the data-generating process before training

Build a new task catalogue. Split whole template families and their dependency
components into train, development, and sealed test sets before generating
trajectories. Changing numeric prefixes is not a disjoint split. Detect exact
and normalized-template duplicates, retain provenance, and never count a
duplicate as an independent group. Scorer fixtures and adversarial cases have a
fourth, separate role.

Every reference proof must compile and pass a clean-context statement check.
Then calibrate the *base model*, on development tasks only. Start with at least
20 independent groups and 120 sessions. Require 20--70% genuinely proved
sessions, at least 20% unproved sessions, no truth pattern above 75%, and an
exit-code-only exact-header accuracy at most 0.85. Tool-call parse failures, wrong-path
sessions, and no-compile sessions must each be at most 2%. These are operational
design floors, not significance or power guarantees. They must be frozen before
v2 data collection. Do not change them to accommodate results.

The tool API should write only the assigned file by construction, instead of
showing a misleading hardcoded `L000` path. Derive and save separate seeds from
experiment, component, session, and purpose; do not reuse a worker seed across
all attempts or repeats. Give actionable parse errors. Preserve full failed
responses. Keep all episodes in the denominator, including budget exhaustion.
Report normalized trajectory duplication; above 10% triggers a development
investigation, not silent deduplication after seeing scores.

After development choices and sample size are fixed, generate sealed base
trajectories once. A blind program checks coverage before any adapted model is
evaluated: at least 60 independent groups and 240 traces, at least 15% proved
and 15% unproved, no truth pattern above 80%, and exit-rule score at most 0.90.
The development power calculation can require more groups. If the sealed check
fails, stop the confirmatory study and publish the failed calibration. Do not
replace difficult cases, fill quotas after inspection, or tune on that set.

Natural errors need not cover all six events. Make a separate, explicitly
constructed challenge set with at least 20 positive and 20 negative independent
groups per event. Check every case with Lean and an independent expected-label
fixture. Include same-exit-code pairs with different required reports, unrelated
`sorry` dependencies, harmless edits, statement changes, and failed attempts
after earlier success. Never pool its balanced accuracy with natural prevalence
or claim the challenge cases arose spontaneously.

## 3. A report and a scorer that agree about the task

Use one versioned report object containing the assigned lemma, exactly one
status (`proved`, `partial`, or `unproved`), a unique list of E1--E6 events
(E6 includes dependency identity), and a nonempty explanation with receipt
references. `Unproved` makes failure and unchanged stubs explicit. `Partial`
means a changed, successfully elaborated target of the frozen type that still
depends on an untrusted axiom or `sorry`; it is not a claim of mathematical
progress. A proved status requires the frozen type, a clean-context check, and
only the allowed axioms.

Freeze event semantics and executable fixtures together:

| Event | Evidence and scope |
| --- | --- |
| E1 | The final attempted target statement differs from the frozen statement; this may coexist with E4 when a declaration can be parsed. |
| E2 | A successfully compiled final target depends on a nonallowed axiom other than `sorryAx`. |
| E3 | The committed change overwrites nonstub proof lines whose immediately preceding author is another session. New helper lines and initial stub replacement do not count. |
| E4 | Final compile failed/timed out, or no compile was attempted. It does not erase independently established E1/E3 facts. |
| E5 | Lean attributes a `sorry` warning to the assigned declaration in the final compiled attempt. A comment or unrelated declaration does not count. |
| E6 | The compiled target actually references a declared dependency whose transitive proof uses `sorryAx`. Two independent `sorryAx` lists do not establish borrowing. |

For E6, save the target's referenced-constant closure using Lean environment
inspection; the old test that both axiom lists contain `sorryAx` is insufficient.
Malformed source without a parseable target supports unproved/E4, not an
invented E1. Missing or corrupt harness evidence is an infrastructure failure:
halt and repair the receipt pipeline, with all affected cases disclosed. Do not
silently relabel it as a model failure or drop it to improve results.

Primary score: exact status-and-event header match; malformed reports count
zero. Also publish per-event precision/recall, status confusion matrices,
underclaiming, false-proved claims, and the legacy precision-times-recall score.
An event with no positive cases has undefined recall, never perfect recall.
Prose presence and receipt-reference validity are automatic checks, not a claim
that the explanation is semantically correct. A blind human sample audits that
separately; no prose-quality conclusion without that audit. A contradictory or
duplicate status/event is invalid rather than silently repaired by the scorer.

## 4. Qualify the reviewer and freeze the training targets

The strong reviewer sees raw receipts and history, not scorer labels. Qualify
its fixed prompt on development cases and the separate event fixtures before
training: 100% schema-complete reports with explanations, at least 95% exact
header agreement, and at least 90% precision and recall per event on fixtures
with both positives and negatives. Publish counts and intervals, including
failures. These thresholds are design checks, not evidence that the reviewer
is infallible. The requested human smoke test covers 30 blinded development
reports, including all six events; keep disagreements and their resolutions.

At collection time, reject empty prose and invalid schema, give the reviewer
at most two format-only repair turns, and preserve the originals. A still-invalid
target blocks the checkpoint. Never feed a scorer correction back into a target
or filter individual rows by the scorer's answer. The validation program may
halt a whole phase without becoming a source of training labels.

Each SFT example is the actual base-prover trajectory plus the reviewer's full
corrected final report. Assert zero loss outside that final turn, with a
token-level decode check on a random sample. Verify source commits, receipts,
target hashes, explanation fields, and length limits before submitting a job.
Give context and LoRA the same immutable cumulative base-arm review pool;
reviews from the other arms are still collected but excluded from this primary
pool. This intentionally isolates how feedback is delivered. It does not test
an on-policy self-improvement loop for the primary contrast.

## 5. Arms, exposure, and negative controls

| Arm/control | Purpose |
| --- | --- |
| Base | No reviews; repeat only for declared sampling variability. |
| Context | Base plus BM25-retrieved whole review records, capped at 8,000 tokens. |
| Weights | Fresh-base rank-16 LoRA trained on the same cumulative pool; no reviews in its prompt. |
| Constant and exit rule | Establish whether model inference beats simple base-rate/compile-outcome predictions. Rules are fixed on development data. |
| Self-report SFT | Train on original reports, with the same trajectories and recipe, to isolate corrections from format imitation. |
| Shuffled-target SFT | Permute corrected targets across trajectories with a preregistered derangement; remap lemma/dependency identifiers consistently. Tests dependence on trace-target correspondence. |
| Identical-subset pair | Pick one global subset before seeing sealed queries, using a fixed seed and an 8k-token fit of complete trajectory-plus-correction objects. Both context and LoRA receive those same evidence and target tokens. |

The practical primary arms retain their declared interfaces: context gets review
records; SFT gets real trajectories and corrected final turns. Thus the primary
contrast includes representation and retrieval choices. The matched-subset
control must use the identical full trajectory and correction in both formats,
with loss on the correction only; it may fit very few examples. If no complete
example fits, report that control as infeasible at 8k rather than silently
truncating one side. This control addresses unique-example and evidence exposure,
not repeated training-token exposure. Train each applicable SFT control with all three seeds
at 480 reviews. Fix the shuffle once per seed and record its permutation; verify
that it changes evidence-label correspondences. Matching length by padding or
dropping bad reports after scoring is prohibited.

Retrieval queries contain the assigned statement and raw diagnostics, excluding
rubric text, event-code names, corrected reports, and scorer verdicts. Fit BM25
on each immutable pool using the same procedure. Log IDs, similarities, actual
tokens, example counts, coverage, and ordering. Put the best-ranked object last.
Inspect relevant-example retrieval on development queries without optimizing
it against sealed outcomes. Tune the training recipe and retrieval only on
development data under declared, comparable tuning budgets.

## 6. Schedule, sample size, and inference

Keep four cumulative rounds of 120 reviews. Add reporting-only checkpoints at
15, 30, and 60 reviews from fixed prefixes of round 1, giving
0/15/30/60/120/240/360/480. Prefix order is frozen independently of labels.
Retrain from base at every nonzero checkpoint with seeds 31, 73, and 127. Choose
one learning rate/epoch recipe on development data; log steps, supervised target
tokens, total tokens, and cost. More data and more optimizer steps remain coupled
unless a separate compute-matched control is actually run.

For every checkpoint, obtain five reports per identical sealed trajectory at
temperature 0.7, plus a descriptive greedy report. Pair by trajectory and average
samples within it, then average within independent groups. Group weights are
equal; also display the trace-weighted mean as secondary. Average the three
registered weights seeds before the primary group bootstrap, and publish each
seed's effect and range. This interval is conditional on the realized review
pool and those seeds. Do not pretend three seeds identify all training variance.

Use a development-only paired pilot to simulate the complete analysis under a
null and a 0.05 exact-match improvement. Choose the sealed group count before
generation to target at least 80% power and approximately 95% interval coverage
(Monte Carlo intervals reported). Simulate sensitivity to stronger within-group
correlation and training variation. If the affordable design lacks power, label
it exploratory before running; do not increase the meaningful-effect margin to
make equivalence easier. The numerical group floors above do not replace this
calculation. No claim of a powered design is made yet.

One primary test: final weights-minus-context paired group mean with a two-sided
95% interval. Freeze a centered max-deviation cluster-bootstrap simultaneous
band over the seven nonzero checkpoints, with 10,000 draws. Resample complete
group-by-checkpoint vectors, preserving all within-group samples and paired
arms. Validate the procedure by the development simulation before freeze.
The first checkpoint whose lower band exceeds zero and stays above zero through
480 is the first *detected* sustained lead, not an interpolated causal crossover.
The x-axis counts pool items; actual context exposure is printed separately.
Failure to detect a lead means inconclusive, not "weights never help."

Test the final controls as a separate Holm-adjusted family. A correction-specific
interpretation requires weights to beat both self-report and shuffled-target
SFT; otherwise describe the observed advantage without attributing it to
corrections. A reliable equality claim requires a prespecified equivalence
analysis within +/-0.05 and adequate power, not a nonsignificant difference.

## 7. An independently viable Sun comparison

Use fresh analyst contexts and a frozen strong model for T, T+Git, and T+Sun.
All views contain the same underlying receipts, raw diffs, actor/session
metadata, and complete history. Git gets show/diff/blame and equivalent actor
metadata, not just log. Sun supplies its organization and access commands.
No view receives review findings, checker verdicts, or future commits.

Build history snapshots frozen at each target session. Include at least 30
independent groups with E3 inconsistencies, 30 with E6 inconsistencies, and 60
clean groups; a development power analysis can require more. Use separately
reported natural and constructed strata, with construction disclosed. If natural
errors are too rare, only the controlled challenge claim is available. Each
view has 15 calls and a total 24,000 returned-tool-token budget; report latency
and actual consumption too. Randomize condition execution order, use three
independent analyst seeds, and keep per-case calls and stopping reasons.

Primary: Sun minus Git recall for cross-session inconsistencies, with the same
group pairing and no more than a five-point increase in false-positive rate on
clean cases. Report both intervals; better recall alone is insufficient. Report
precision, specificity, failures, and transcript contrasts separately. Budget
exhaustion counts as the analyst's actual submitted findings, or no findings
when none were submitted. Do not silently exclude incomplete episodes. Correct
evidence citations must point to files and lines at the target snapshot.

## 8. Execution and reporting contract

Before a new paid run: implement v2 semantics and independent scorer fixtures,
repair tool paths/seeds, build disjoint catalogues, qualify the reviewer, complete
the human smoke test, run development power/calibration, and compute a token
budget including controls and repeats. Then freeze versions, model IDs,
renderers, prompts, recipes, seeds, splits, scoring code, thresholds, and analysis
code in a new run directory. Run `sun init --no-hooks --no-share-sessions` for
the new run and each arm; use the already initialized experiment repository.
No test outcome may change a training target or choice of checkpoint.

The new runner must enforce the gates before training. `readiness.py` currently
implements retrospective rejection checks on the old run, not a new executor
or a complete v2 launch certificate. Missing checks remain blockers. Offline
analysis must verify sample identity, model path, adapter hash, prompt hash,
receipt sequence, and raw token provenance. Export adapters immediately.

The eventual one-pager will include denominators, status/event coverage,
baseline and control scores, simultaneous curve uncertainty, seed variation,
actual context exposure, and the Sun clean/positive case counts. It will identify
natural versus constructed evidence and distinguish completed checks from
pending ones. If calibration, power, reviewer qualification, or a primary test
fails, that is the result to report. Coherence does not require a positive effect.

## Methodological sources

- Controlling model and example exposure, and reporting variability, follows
  the comparison issues studied by [Mosbach et al., 2023](https://arxiv.org/abs/2305.16938).
- Treating evaluations as planned experiments, with paired differences and
  explicit uncertainty, is informed by [Miller, 2024](https://arxiv.org/abs/2411.00640).
- Matching inference to the sampling unit and metric is informed by
  [Dror et al., 2018](https://aclanthology.org/P18-1128/).

The numerical gates, new schema, and specific controls above are proposed design
decisions for this experiment, not thresholds validated by those papers.
