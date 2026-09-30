# Research cycles, 28 September 2026

Budget: up to **$1,000 for new API/training work**, authorized by the user. The
runner reserves maximum uncached token charges before submission. Prior runs are
sunk costs and are reported separately. Stop at $950 reserved, leaving $50 for
storage and reconciliation. Never retry an ambiguous paid request automatically.

## Cycle 1: repair the decisive comparison

The pilots compared weights with retrieved examples, not with a learned
playbook. Their writing rubric also contains easy rules. The immediate research
question is therefore: **does supervised adaptation beat an inferred playbook
when both consume the same frozen edits?** A negative answer is informative.

Reuse the 480 no-feedback review opportunities from the September 26 writing
archive, in chronological prompt order. Keep all opportunities in budget counts;
only public-valid writer/editor pairs enter either method. No private scores or
editor audit labels enter the playbook. This is new training and new evaluation
on an existing review corpus, not a new collection or a live continual-learning
experiment. The editor's original prompt is excluded from every learner input.

Amendments to the broad proposal, declared before new evaluation:

* Concentrate the confirmatory study on writing. The Lean pilot failed event
  coverage and cannot support transfer or crossover claims. Repairing that
  benchmark is a separate research direction, not evidence for this claim.
* Preserve the existing eight-rule rubric for comparability; explicitly report
  its easy-rule ceiling. Also report the three always-applicable, difficult
  rules (narrative tense, short opener, capitalization), all-rule success, public
  validity, length, and dialogue usage. Do not claim that the original
  every-rule-below-70% gate passed.
* Use review budgets 15, 60, and 480, with 480 the primary endpoint. These sparse
  checkpoints do not identify a precise crossover. Use three training and
  playbook construction seeds: 31, 73, 127.
* Train only the final story-modifying assistant turn, under its actual
  generation prefix. The pilot also supervised unrelated assistant turns.
* A playbook compiler sees before/after stories and the public assignment,
  updating numbered rules with add/replace/delete deltas. Apply changes locally;
  retain at most 2,000 Qwen tokens. This is inspired by ACE, not an ACE replication.
  Compiler: Inkling, effort 0.6, temperature 0.3, 4,000 output-token cap, batches
  of 15 valid reviews. Each budget/seed is constructed from an empty playbook in
  chronological order, with seed plus valid-review offset for each update.
* Omit distillation from the primary comparison to isolate supervised correction
  transfer. SDFT derives a reverse-KL objective but its v2 practical implementation
  reports using forward KL on student trajectories (Section 3, Practical
  Implementation). Teacher-sampled SFT is not equivalent to that method.

## Development and selection

Generate 24 new development prompts and 144 sealed test prompts. New places,
characters, anchor pairs, and premise templates are checked against all 600 old
prompts. Split by place; all samples for a prompt remain one statistical cluster.
Within test, 72 prompts use familiar genres and 72 use fable/gothic, which were
absent from review collection. This is template-controlled generalization, not
a broad natural-task benchmark.

The initial 96-test-prompt design was expanded before any test responses were
generated. The selected candidate's development differences gave estimated
5-point-effect power 0.729 at 96 prompts and 0.877 at 144 in the centered-resample
planning simulation recorded in development-power.json. This normal-interval,
single-method-seed approximation is a planning aid, not guaranteed power or
coverage for the final bootstrap; only four development places were available.

First measure the base and the 60-review playbook on development prompts.
Train 60-review adapters at learning rates 0.00015, 0.00047, and 0.0007, seed 31.
Batch 16, rank 16, attention/MLP/output adapters, at least 3 epochs and 30 steps.
The cross-entropy loss averages over the supervised tokens of each example.
Select highest mean U*S among candidates whose validity is no more than three
percentage points below development base. If none qualifies, retain the highest
validity candidate, breaking ties by U*S then smaller learning rate, and report
the failed guardrail. Use two samples per dev prompt. Do not tune on test.
Reuse the selected learning rate at every confirmatory budget and seed. The
validity safeguard also qualifies interpretation of the test result: a gain
with validity more than three points below base is not called an unqualified
improvement. This descriptive safeguard is not a noninferiority test.

Inspect compiler output for schema, token limit, and evidence references without
injecting known rules. Inspect training masks and replay all edited trajectories.
Record the selection and code/input hashes in a freeze file before test calls.
Failures trigger a documented new development cycle, not silent test reuse.

## Confirmatory evaluation

Arms: no feedback; BM25 retrieval of the same before/after pairs (8,000-token
cap); inferred playbook (2,000-token cap); fresh-base cumulative SFT. Three seeds
for playbook/SFT, one deterministic retrieval configuration. Use two stochastic
samples per test prompt and common sampling seeds across arms, temperature 0.7,
top-p 0.8, top-k 20, eight tool turns maximum. Public feedback only.

Primary outcome is U*S, zero for invalid/unsubmitted episodes. Primary contrast
is SFT minus playbook at 480 opportunities, averaged over construction/training
seeds. Report a paired prompt-cluster percentile 95% bootstrap interval with
10,000 draws, stratified by familiar versus unseen genre. Also report a
place-cluster sensitivity interval (24 places, twelve per stratum) because six
prompts share each place. The inference is conditional on this premise generator
and its shared templates. Intervals condition on three method seeds; show every
seed separately. Secondary contrasts and earlier budgets are
exploratory, with no claim of significance from multiple unadjusted intervals.

## Cycle 2: explain and challenge the result

After the frozen comparison, run declared endpoint controls: SFT plus the
corresponding playbook; self-target SFT using the original drafts and the same
training schedule; and a shuffled edit-target control with required anchors
remapped so public-format failure is not built in. Label follow-up tests as
exploratory on the same test set. Compare per-rule errors, public validity, and
generation/input tokens. Add an independent instruction-following retention
set before interpreting any adaptation gain as an overall improvement.
Also evaluate a base-policy reference supplied the explicit planted rules.
This privileged reference diagnoses inference versus application of rules; it
is not a learned comparator or a mathematical performance upper bound. The
private rules remain excluded from every learned playbook and SFT target input.
Retention uses 128 public IFEval examples selected by a fixed hash of example
IDs, frozen in retention-plan.json before responses. Use the official strict
checker, one sample each, 4,096 output tokens, and the same Qwen sampling
parameters. Compare base, each endpoint adapter, and each active playbook on a
generic assistant prompt. With the playbook removed, context adaptation is
identical to the base policy by construction. Do not describe this small,
possibly pretrained-on subset as a broad capability evaluation.

No claim of human editing quality, human review, cross-model generality, Lean
transfer, optimizer-continuous learning, or catastrophic-forgetting prevention
is supported by this study. Every final paper assertion receives a separate
evidence entry with raw-file hashes or a checked primary source.
