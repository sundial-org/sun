# Learning from imperfect corrections under a complete rubric

## Research question and vector

The previous writing draft compared two adaptation recipes under a hidden fixed
rubric. Its controls separated rubric compliance from submission validity, but
did not measure semantic task success. Its inferred playbooks were incomplete.
The riskiest question is whether weight updates improve complete task success
when the model already has the complete rules, and whether the structure of
correction errors changes that answer.

CS197 asks us to choose the riskiest unanswered question, distinguish core from
periphery, execute a bounded experiment, and re-vector from the result:
https://web.stanford.edu/class/cs197/assignments/project.html

## Hypothesis, not an asserted discovery

Two correction sources with identical example-level accuracy can have different
value for weight adaptation because a repeatable blind spot can be learned.
The ambitious outcome would be opposite signs of the benefit of updating weights.
A difference between noise conditions alone does not establish such a reversal.
No literature-wide assumption that accuracy is sufficient is asserted. Relevant
neighbors include rubric reward hacking (https://arxiv.org/abs/2605.12474),
rubric-guided self-distillation (https://arxiv.org/abs/2606.12507), and structured
weak supervision (https://arxiv.org/abs/2405.16043). This controlled study is not
by itself a claim of a novel general theory.

## Task and independent variable

Synthetic batch fulfillment, three records per task. The complete seven-rule
policy covers a recall override, stock allocation, fragile shipments, shipping
eligibility, a regional override, and sorting. Every task contains
exactly one recalled order whose recall matters. Its region is balanced across
five values. All methods see the correct complete policy at inference.

400 fixed training inputs; three target conditions:

- Clean: exact oracle answers, 100% correct.
- Scattered: 20% wrong answers, selected independently within each region.
- Systematic: wrong on all west-region recall examples, exactly 20% overall.

Both wrong-answer mechanisms make the same local semantic mistake: ignore the
recall override on the recalled order, then consistently update sorting.
They change no other order's decision. The systematic mechanism creates
a stable conditional blind spot; scattered error masks vary with training seed.
This manipulates corrected-target accuracy, not the measured accuracy of a
learned reward model. No learned judge is used.

## Development and evaluation

50 development tasks and 250 untouched test tasks, generated using disjoint
fixed random seeds. Exact prompts cannot overlap. This measures new inputs under
the same rubric, not unseen-rubric or cross-domain generalization.

Development compares concise rules, rules with an execution checklist, and the
checklist plus 4, 8, or 16 training examples retrieved using input features only.
Choose one common context style by average exact accuracy across the clean,
scattered, and systematic pools at seed 31; ties favor fewer examples then fewer
tokens. Report every development condition. Stop and reconsider task difficulty
before training if all styles have <10% or the best has >95% development success.
Any such change is recorded before observing test performance.

Freeze task code, runner, training files, test inputs, context choice, and this
protocol before any test response is requested. Use Qwen3-8B with non-thinking
rendering, deterministic greedy decoding, max 1,024 output tokens. Train fresh
rank-16 LoRA adapters at learning rate 0.00047, batch 16, three epochs (75 steps),
seeds 31, 73, 127. Full correct rules/checklist are in each training prefix;
only the answer has loss. No learning-rate search or checkpoint selection on test.

Primary comparison: fine-tuned versus frozen model under the same selected
context style and same correction pool, separately for each target condition.
If retrieval is selected, both use the same retrieved examples. Also
evaluate all models with the checklist and no examples to isolate the adapter's
effect from inference demonstrations; identical conditions are cached.

Primary outcome: completely correct task output, including every decision,
sorting, units, and IDs. Secondary outcomes: per-order accuracy, recall
override success overall and by region, valid output schema/IDs, and agreement
with the flawed systematic oracle (explicitly a proxy, not task success).
Also report all decisions correct regardless of output order, and correct
sorting of the predicted entries, to distinguish policy learning from packaging.

Average training seeds within each test task, then calculate paired 95% bootstrap
intervals stratified by focus region (10,000 resamples). Intervals condition on
these three seeds; report all seed-level values. The primary noise interaction
is delta(scattered) minus delta(systematic). A positive interval is evidence of
an interaction, not proof of opposite preferred strategies. Call a practical
reversal only if one delta's interval is entirely above +3 points and the other's
entirely below -3 points. Otherwise report uncertainty or a smaller effect.

## Validity checks and scope

The target oracle and scorer use separately implemented decision procedures.
Exhaustively compare the procedures at numeric/Boolean boundaries; test input
permutation invariance, recall overrides, corruption rates, corruption locality,
unique examples, split separation, output scoring, and supervised token masks.
Manually inspect 50 generated tasks/targets spanning all regions and conditions.
Synthetic inputs contain no private user information. No external dataset is used.

One task family and one model can falsify or motivate the hypothesis in this
setting, not establish a universal training rule. Policy is deliberately fixed;
dynamic/generated rubrics, RL, broader retention, and other domains are periphery
until this uncertainty is reduced. An adapter can be disabled, so harmful active
behavior is not called irreversible forgetting.

## Costs and provenance

Total user authorization: USD 1,000. Prior completed study estimated USD
17.42253885 in token charges. This cycle has a separate hard reservation cap of
USD 75, conservatively charging full input/output maxima and full training plans
before requests. Checkpoint storage has additional room within the total cap.
Current official Qwen3-8B rates checked 2026-09-29: input $0.195/M, output $0.60/M,
training $0.44/M; https://tinker-docs.thinkingmachines.ai/tinker/models/ . Native
tokenization provides actual sequence counts. Estimates are not invoices.
Interrupted requests are not silently retried; receipts and pending markers are
retained. Save raw outputs, corrections, training masks, model paths, charges,
source hashes, and a separate claim-to-evidence file. Preserve the writing paper
and its frozen evidence unchanged.

## Development calibration record, before any test response or training

The initial six-order task included fee arithmetic and totals. All nine context
conditions scored zero exact success on 50 development tasks. The difficulty
gate therefore failed, and the task was simplified to three orders without
fees or totals before test evaluation or training. The initial data, responses,
selection and costs remain in `runs/20260929`; the selected task uses
`runs/20260929-policy-v2`. Those initial costs count against the same cycle cap.
No positive training result prompted this change. Development examples are reused
for calibration; test inputs are regenerated using the specified independent seed.
After seeing that four examples improved development performance, the context
search was expanded to 8 and 16 examples before freezing. This addresses the
prior draft's weak-context-comparator concern; all development candidates and
the common selection rule remain reported. No test response or training result
informed this expansion.
