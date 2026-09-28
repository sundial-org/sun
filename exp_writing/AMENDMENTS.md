# Execution amendments

## 26 September 2026: Qwen training-prefix correction

The initial code hash in `freeze.json` is retained. During round-one collection,
before any optimizer step, an offline SDK validation identified that Qwen's
non-thinking renderer does not preserve generation prefixes when an entire
multi-turn transcript is rendered as one training example. The baseline
evaluation had already completed at this point.

The training converter now creates one masked datum per assistant action, using
that action's exact conversation prefix and supervising only its final assistant
message. A batch still contains the specified number of source trajectories;
their action datums are flattened into the same optimizer step. This preserves
the intended assistant-only trajectory supervision while making its conditioning
match inference. No rules, prompts, sampling settings, learning rates, data
selection, or stopping criteria were selected from held-out outcomes.

An offline check verified exact token-prefix equality for all 26 assistant actions
in the 24 final development trajectories. No development data were trained on.
The machine-readable receipt is `runs/ten-writers-20260926-inkling/prefix-validation.json`.
The original process was stopped after all three round-one collections completed,
before importing the training code. There were zero training-start events and no
training files or optimizer steps. No paid training was abandoned or replayed.
The boundary receipt and revised hashes are recorded in the run directory.

Reporting changes add format validity, per-rule and genre diagnostics, and a
standard Matplotlib figure. These do not change generation or training.

## 26 September 2026: interrupted context requests

The first context evaluation finished 380 sessions before the batch surfaced an
`APIConnectionError` during request submission. Four requests had no returned
result. Their original request files and reservations are preserved in
`failed_requests/`; their maximum unresolved charge is USD 0.01085679. Only those
four requests are explicitly resubmitted with the same prompts and seeds.
Completed requests and the first trained adapter are reused.

The initial harness disabled the SDK's lower-level retry function. That override
is removed: Tinker's submission retries retain the same request identity and are
idempotent. Whole-sample automatic retries remain disabled. The extra 900-second
application timeout is removed, leaving SDK progress detection in place. Failed
requests now get an error receipt, and batch failures are reported individually
while remaining submitted work finishes. These are transport and recording
changes, with no changes to the experimental policies or data-selection rules.

References: [Tinker changelog](https://tinker-docs.thinkingmachines.ai/changelog/)
and [timeout guidance](https://tinker-docs.thinkingmachines.ai/tinker/under-the-hood/).

## 26 September 2026: overlap independent offline work

The 15/30/60-edit checkpoints use immutable snapshots of round-one collections,
which already contain more than 60 valid edits per learning arm. The best-of-n
test uses only the fixed base policy and held-out prompts. Both can therefore
run alongside rounds two through four without changing any live writer's inputs.
Two auxiliary threads schedule these independent stages, with the existing ten
workers per batch. Round barriers and all sample counts, seeds, model settings,
training settings, and comparison datasets remain unchanged.

One process owns all stages, so token rendering and the USD 800 reservation ledger
share their existing locks. Training datum rendering now also takes the tokenizer
lock. The update is loaded at a completed round-two collection boundary; a boundary
receipt and revised source hashes accompany the run. This is a scheduling change
to reduce elapsed time, not a change selected to improve measured outcomes.

## 26 September 2026: matched-control scheduling and local archives

After all four live rounds, all early checkpoints, and the ranking test completed,
the process paused before the first optimizer step for endpoint seed 1. No
inference requests were unresolved. The LoRA-A, LoRA-B, and unedited-target
control families now run concurrently after their common archive is ready. Each
family still trains and evaluates the same three preselected seeds, and all
settings and dataset intersections remain unchanged. The boundary and source
hashes are retained in `controls-amendment.json`.

`archive_checkpoints.py` independently downloads each completed sampler adapter,
checks that its archive is readable, and records its SHA-256 digest. This preserves
the learned weights after the hosted seven-day lifetime. It does not sample or
train a model, and never stores credentials or signed download URLs.

Reporting now also retains per-evaluation format-failure counts and endpoint seed
spread, so improved style cannot conceal a loss of public-task reliability.
