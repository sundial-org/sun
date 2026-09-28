# Exp 2: Ten Writers

Execution workspace for the four-round hidden-style learning experiment.
The writer is Qwen/Qwen3-8B; the selected editor is Inkling. Both were verified
against the live Tinker API. Credentials are held in process memory and are never
written to this directory.

The selected run is `runs/ten-writers-20260926-inkling/`. Preliminary DeepSeek
calibration is retained separately in `runs/ten-writers-20260926/`.
The selected run is complete: four live rounds, 18 trained adapters, 27 held-out
evaluation sets and the best-of-four ranking test. The one-page report is
[`results.tex`](results.tex), with a visually checked [`results.pdf`](results.pdf).
All 18 adapters are archived locally. Nine implementation checks and the final
data/archive audit passed; 3,440 Sun edit pairs were independently verified.
The human editor smoke test and blind prose-quality evaluation remain incomplete.
See `PROTOCOL.md` for the exact design and differences from the attachment.
`AMENDMENTS.md` records the rendering correction, transport recovery and scheduling
changes after the initial freeze. Model settings were not tuned on held-out results.

## What this branch contains

This Git export includes the harness, protocol, one-page report, and final result
and audit summaries under `runs/ten-writers-20260926-inkling/`. The complete local
run additionally contains raw model traces, evaluation stories, training rows,
Sun object databases, and 3.3 GB of adapter archives. Those local artifacts are
not included in this branch. The analysis and full-audit commands below require
that complete run directory.

## Run and reproduce

The local `.venv` contains pinned spaCy models and references the existing Tinker
environment through a `.pth` file. For another machine, create a fresh environment
and install `requirements.txt`.

```sh
.venv/bin/python -m unittest -v test_experiment
.venv/bin/python -u supervisor.py
```

The supervisor prompts for the key with terminal echo disabled. Once ready, its
JSON-line command is:

```json
{"op":"run","run":"ten-writers-20260926-inkling"}
```

Completed inference and training outputs are reused on resumption. Unresolved
paid requests and incomplete training jobs require inspection instead of blind
replay. All paid work reserves worst-case token costs before submission.

After completion:

```sh
.venv/bin/python analyze.py ten-writers-20260926-inkling --report
.venv/bin/python audit.py ten-writers-20260926-inkling
.venv/bin/python verify_run.py ten-writers-20260926-inkling
```

`results.tex` and its compiled `results.pdf` are the one-page measured-results
report. The final-report generator refuses to label an incomplete run complete.
Statistical analysis can be rerun from saved samples without model access.
The last command verifies complete evaluation coverage, matching control drafts,
training-data separation, API receipts and local adapter SHA-256 hashes. It requires
the archive downloader to have finished.

## Evidence

- `progress.jsonl`, `status.json`: durable execution progress.
- `freeze.json`, `PROTOCOL.md`: frozen code/data hashes and protocol.
- `provider/`, `episodes/`: raw sampled tokens, log probabilities and agent traces.
- `collections/`, `edits/`: original drafts and private editor actions.
- `training/`: replay-validated supervised rows, optimizer metrics and checkpoint manifests.
- `evaluations/`, `best_of_n.json`, `analysis.json`: held-out drafts and computed results.
- `costs.jsonl`: reservations and token-price estimates, not provider invoices.
- `arms/*/.git`: independent Sun histories with writer/editor attribution.
- `provenance/`: exact two-commit identities used to calculate text retention.

Sun was initialized for the parent task, this experiment repository, and each run
and arm repository. The harness records commits through Sun's Python API under
an explicit lock. It does not depend on desktop hook trust, and raw Codex session
sharing is disabled. Hosted adapter checkpoints expire after seven days.
`archive_checkpoints.py` preserves completed sampler adapters as local archives,
with SHA-256 receipts, while a run is active. Its key prompt also disables echo:

```sh
.venv/bin/python -u archive_checkpoints.py ten-writers-20260926-inkling
```

Local copies and their file lists are in `checkpoint_archives/` under the run;
`archive_manifest.json` records final coverage. Signed download URLs are never saved.
