# Learning a Writing Rubric from Edits: Context or Weights?

Status: completed experiments, verified evidence, and final draft. The study compares an inferred playbook and corrected-target LoRA on
a common synthetic review archive, measuring rubric compliance, public validity,
and active-policy instruction spillover.

- [Draft paper](paper/output/pdf/draft-paper.pdf): 2,384 body words, four pages,
  normal research sections, a workflow diagram, a results figure, and two tables.
- [CS197 submission PDF](paper/output/pdf/submission.pdf): draft plus one page
  of model-paper analysis, adapted outline, and revision notes.
- [Claim justifications](paper/CLAIMS.md): 80 reviewed assertion blocks,
  including captions, references, and submission notes.
- [Editable source bundle](paper/output/rubric-paper-source.zip).

Completed 9,744 writing episodes, 896 instruction-probe responses, and 18
adapter runs. Estimated new token charges are **$17.42253885**, including
conservative full-plan charges for two interrupted training attempts. This
excludes storage and invoice adjustments. All 18 adapter archives are saved
locally. No paid processes remain active.

The primary endpoint is 89.1% validity-adjusted rubric compliance for SFT
versus 71.7% for the inferred playbook: +17.4 percentage points, paired 95%
interval [15.4, 19.5]. The paper reports validity failures and seed variation,
and does not equate this result with prose quality or sequential learning.

The user authorized up to $1,000 for new API/training work. `run.py` reserves
uncached maximum token charges before requests, stops at $950 reserved, and
retains $50 for storage. Cost estimates are not invoices. An interrupted training
attempt is conservatively charged its full planned token cost.

- [Protocol](PROTOCOL.md): question, scope amendments, development selection,
  confirmatory endpoint, and controls.
- [Research log](research_log.md): experiments, failures, and decisions.
- [Literature map](RELATED_WORK.md): nearest neighbor and 16 relevant papers.
- [Payload provenance](payload-provenance.json): synthetic source verification.
- [Local checks](local-check.json) and [mask checks](mask-check.json): data and
  corrected-turn supervision validation.
- [Environment](environment.json): dependency versions and tokenizer hash.

## Running

Use the existing workspace `exp_writing/.venv/bin/python`, which has Tinker,
the Cookbook, spaCy's pinned transformer tagger, and IFEval dependencies. Set
`TINKER_API_KEY` in the process environment. Never put credentials in files or
command arguments. Run from the repository root:

```sh
exp_writing/.venv/bin/python experiments/continual_learning/run.py check
exp_writing/.venv/bin/python experiments/continual_learning/audit_payload.py
exp_writing/.venv/bin/python experiments/continual_learning/run.py dev
exp_writing/.venv/bin/python experiments/continual_learning/followups.py prepare
exp_writing/.venv/bin/python experiments/continual_learning/run.py freeze
exp_writing/.venv/bin/python experiments/continual_learning/run.py main
exp_writing/.venv/bin/python experiments/continual_learning/followups.py controls
exp_writing/.venv/bin/python experiments/continual_learning/followups.py retention
exp_writing/.venv/bin/python experiments/continual_learning/compact_rubric.py
exp_writing/.venv/bin/python experiments/continual_learning/analyze.py
exp_writing/.venv/bin/python experiments/continual_learning/archive_adapters.py
exp_writing/.venv/bin/python experiments/continual_learning/rescore_audit.py style
exp_writing/.venv/bin/python experiments/continual_learning/rescore_audit.py retention
```

Paid commands require network access. Local checks, freezing, analysis, and
paper verification do not call a model. The freeze refuses to overwrite itself
after test episodes exist. The main run checks the frozen code and input hashes.
Run paid stages sequentially: their shared cost ledger has a process-local lock.
The compact-rubric condition is a separately frozen exploratory follow-up, not
part of the original primary comparison; see `COMPACT_RUBRIC.md`.

Raw receipts, transcripts, playbooks, training exports, checkpoints, and costs
are stored in `runs/shared-reviews-20260928/`. Completed results are cached.
An unresolved provider request or unfinished training job stops automatic
replay. Inspect it and record recovery explicitly. Do not erase receipts to
force a rerun. Optimizer recovery states are saved every 16 completed steps;
the completed sampler and final training state have seven-day provider TTLs.
All 18 sampler archives have been downloaded and verified. They are intentionally
excluded from Git; retain the local copies after provider expiry.

The four `vendor/*.py` files are snapshots of this repository's writing pilot
harness, used for its public tool environment and private mechanical scorer.
`vendor/instruction_following_eval/` is official Google Research code/data;
its commit, file hashes, and Apache license are stored alongside it. NLTK
sentence data are downloaded separately into `vendor/nltk_data/` for local
scoring. See the pinned versions in `environment.json`.

## Paper and claim audit

The manuscript lives in `paper/paper.tex`, with normal research-paper sections,
a workflow diagram, a budget-results figure, and two results tables. Its target
is 2,000–2,500 body words. Submission notes separately supply the model-paper
analysis, adapted outline, and revision record requested by CS197.

The full evidence packet is assembled with `paper/collect_evidence.py`.
`paper/verify_evidence.py` successfully replayed all 9,744 new tool transcripts,
recomputed all 38 evaluation summaries and 38 paired intervals, and checked
training, compiler inputs, provider receipts, and saved adapter hashes. The
linguistic scorer was rerun on 152 deterministic sampled episodes, and all 896
public instruction responses were rescored with the official checker.
The older editor-creation replay has recorded discrepancies; see
`editor-receipt-audit.json` and `paper/SOURCES.md`. It is not claimed as a full
reproduction of the review archive's creation.

`paper/claim-checks.json` binds reviewed wording to evidence and justification;
`paper/claims.py` checks coverage, hashes, and length and renders `paper/CLAIMS.md`.
Paper claims, figure/table captions, and appended notes are included. A wording
or artifact change requires renewed review, not merely regeneration of hashes.

`paper/build.py` requires Python with NumPy and pypdf, pdfLaTeX, and the CVPR
style dependencies. It reruns the offline checks and writes `paper/output/pdf/`.
Render and inspect all final pages after changes. `paper/package_source.py`
creates a compact editable typesetting ZIP; full audit data remain in the repo.
