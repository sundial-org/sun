# Ten Provers (Lean)

**Methods revision:** [v2/METHODS.md](v2/METHODS.md) specifies the redesigned
study, controls, sample-size planning, and required stop conditions. The old run
is a failed calibration study. The v2 protocol has not been executed and the
legacy runner is not v2 compliant. Its retrospective readiness check fails on
the saved evidence; see [v2/readiness-legacy.json](v2/readiness-legacy.json).

Executable experiment: Qwen3-8B proves and reports, a frozen stronger model
corrects reports, and a deterministic scorer grades saved evidence.

The primary comparison uses identical cumulative reviews from the no-feedback
arm for context and LoRA. All three arms run and are reviewed. There are ten
workers per arm, 120 sessions per arm per round, and four rounds. Separate arm
repositories prevent cross-arm leakage. Each repository is initialized with Sun.

Only the corrected final report carries training loss. Held-out base trajectories
are frozen before training. The held-out lemmas never enter training repositories.
Evaluation runs at 0, 120, 240, 360, and 480 reviews. Context retrieval is bounded
to 8,000 tokens. LoRA is retrained from base after each round.

The run records actual counts, exceptions, source hashes, model versions, token
usage, receipts, reviews, and checkpoint paths. The one-page report distinguishes
completed measurements from unavailable or inconclusive results.

Sun is vendored without modifications from local commit
`2eb500744d6d8ba0d9734a6c2e2ce87a5f0d005c` because the current main branch lacks
the check API. Raw credentials are never written into experiment artifacts.

## Running and auditing

Use the existing Tinker virtual environment at
`/Users/bmo/sun-sundial-desktop/.tinker-venv/bin/python`. Start
`provider_session.py --run runs/20260926-01`; enter the key at its hidden prompt.
Commands on stdin are JSON: `{"op":"preflight"}`,
`{"op":"pilot","name":"new-dev-pilot","count":20}`, and `{"op":"execute"}`.
The supervisor keeps credentials only in memory. Existing completed samples are
reused after verifying prompt and policy identities; ambiguous submissions stop
rather than silently replaying a paid operation.

`analyze.py runs/20260926-01` recomputes scores and intervals entirely offline.
Install report plotting dependencies with
`uv pip install --target .cache/report-packages -r requirements-report.txt`.
`render_report.py runs/20260926-01 --output results.tex` writes the one-page
LaTeX source and its adjacent vector figure, `results-curve.pdf`, only when all
four rounds have completed. Keep both files together. Compile with
`pdflatex -interaction=nonstopmode -halt-on-error results.tex`.

Development pilots remain in the run for transparency and are excluded from
the frozen evaluation and training pool. The final protocol is written to
`frozen-config.json` before held-out generation. Budget accounting uses current
uncached token rates and a USD 450 reservation ceiling. Saved token estimates
are not provider invoices. No artifact contains the API key.

## Completed run: 20260926-01

All four rounds completed: 1,440 live sessions, 1,440 reviews, 480 shared review
targets, four fresh-base LoRAs, 6,480 evaluation reports, and 360 analyst episodes.
The requested report is `results.tex`; `results.pdf` is its one-page rendering.

**Corrected interpretation after the curve audit:** this evaluation collapsed to
compile-outcome reporting. It does not establish the intended review-count
crossover. The original numerical measurements below are unchanged; the earlier
crossover conclusion is withdrawn. See [the audit](audit/curve-audit.md).

| Reviews | Base | Context | Weights |
| ---: | ---: | ---: | ---: |
| 0 | 0.848 | 0.848 | 0.848 |
| 120 | 0.848 | 0.832 | 0.996 |
| 240 | 0.848 | 0.793 | 0.996 |
| 360 | 0.848 | 0.901 | 0.996 |
| 480 | 0.848 | 0.864 | 0.996 |

Final weights minus context: 0.132, paired family-bootstrap 95% interval
[0.053, 0.227]. This interval describes the sampled task mix and does not fix
its missing outcome coverage:

- 113/120 frozen traces have E4 alone; the remaining seven compile with `sorry`.
  No trace contains a proved or partial result, E1, E2, or E3. Only one has E6.
- Always reporting E4 scores 0.942. A **post hoc** two-branch rule that reports
  E4 on failure/no compile and E5 otherwise scores 0.996, exactly matching all
  600 sampled headers from each of the four LoRAs. Every LoRA misses the same E6.
- The x-axis is the available review pool size. Context actually receives
  20 to 30 retrieved examples under the 8,000-token cap. Base is measured once.
- The score is precision times recall, not F1, and grades only the header.
  384/480 corrected training targets have no prose; 580/600 final weights reports
  also have none. The human smoke test remains pending.

All 6,480 scores were independently recomputed from frozen compiler evidence and
saved reports. Checkpoint request identities, provider-output tokens/logprobs,
and four distinct exported adapter hashes were checked. The flat line is present
in the saved predictions, rather than introduced by the plot. The pilot gate
checked review completion but did not require an adequate outcome mix.
Reviewer-corrected headers exactly matched compiler-derived truth in 90.6% of
live sessions.

Sun audit recall was 0.583 versus 0.792 for transcripts and 0.667 for transcripts
plus Git. Precision was low in every view (0.211 to 0.230). Only one cross-session
inconsistency was sampled, so that primary comparison is underpowered. Two Sun
episodes exhausted their budget and were scored as no flags.

Operational repairs are recorded in `runs/20260926-01/protocol-amendments.json`.
The original freeze and every completed sample were preserved. Two unresolved
provider requests were explicitly archived before retry; their reservations
remain counted. Run-level Sun snapshots bind raw files through
`evidence-manifest.json`; each arm also has its own session commits and checks.

`analysis.json`, `integrity-check.json`, and `evaluation-validation.json` in the
run directory contain recomputable measurements and validation records. Local
adapters are in `runs/20260926-01/adapters/`, with SHA-256 receipts in
`downloaded-adapters.json`. The supervisor's `audit` command exports these after
completion. The API credential was held in memory, and the supervisor is stopped.

Run `postprocess/audit_curve.py runs/20260926-01` to reproduce the offline curve
diagnostic. It writes `runs/20260926-01/curve-audit.json`, including per-outcome
scores and input hashes; it never calls a model or changes original evidence.
The corrected report renderer runs this audit before publishing the figure.
`audit/pre-correction/` preserves the previous one-pager and rendering sources.
