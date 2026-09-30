# Learning from imperfect corrections under a complete rubric

This follow-up tests whether the pattern of errors in a correction archive changes
the benefit of updating weights when the full correct policy remains in context.
It follows the CS197 vectoring and evaluation-design workflow. The earlier writing
paper and its evidence remain unchanged in `../continual_learning/paper/`.

- `PROTOCOL.md`: question, hypothesis, task, comparisons, uncertainty, limitations,
  development decisions, and budget.
- `task.py`: task generator, correction mechanisms, retrieval, exact target oracle,
  independently implemented scoring oracle, and prompts.
- `test_task.py`: oracle boundary, corruption, split, scorer, and invariance checks.
- `run.py`: native tokenization, development selection, frozen experiment,
  resumable raw-response cache, training, and conservative cost reservations.
- `analyze.py`: independent response replay, paired bootstrap, and result figure.
- `controls.py`: matched reasoning-mode and single-region counterfactual checks.
- `diagnostics.py`: schema, sorting, truncation, and valid-response rule errors.
- `REPORT.md` and `CLAIMS.md`: results and separate claim justifications.
- `archive.py`: durable local adapter copies without persisting signed URLs.

The selected experiment uses 400 shared training inputs, 50 development tasks,
250 test tasks, and three training seeds. Clean corrections are fully correct;
the scattered and systematic error conditions are both exactly 80% correct at
the whole-example level. All incorrect targets disregard the recall override on
one order. The systematic condition makes this mistake only for west-region
recalls; the scattered condition distributes it across all regions.

The selected context strategy uses four examples retrieved by input features,
plus the complete policy and execution checklist. Both frozen and trained models
receive identical context within each comparison. Rules with no examples are a
separate diagnostic. LoRA uses Qwen3-8B, rank 16, learning rate 0.00047, batch 16,
three epochs, and seeds 31, 73, 127. The task has an exact executable solution;
this is a controlled learning study, not a proposed replacement for ordinary
software implementing a fulfillment policy.

## Reproduction

From the repository root, use the existing Python environment. Paid stages need
`TINKER_API_KEY` in the environment and network access. Credentials are never saved.

```sh
cd experiments/rubric_boundary
../../exp_writing/.venv/bin/python -m unittest test_task -v
cd ../..
HF_HUB_OFFLINE=1 exp_writing/.venv/bin/python experiments/rubric_boundary/run.py main
HF_HUB_OFFLINE=1 exp_writing/.venv/bin/python experiments/rubric_boundary/controls.py main
exp_writing/.venv/bin/python experiments/rubric_boundary/analyze.py
exp_writing/.venv/bin/python experiments/rubric_boundary/controls.py analyze
exp_writing/.venv/bin/python experiments/rubric_boundary/diagnostics.py
exp_writing/.venv/bin/python experiments/rubric_boundary/plot_controls.py
exp_writing/.venv/bin/python experiments/rubric_boundary/report.py
exp_writing/.venv/bin/python experiments/rubric_boundary/archive.py
```

The `main` command resumes completed requests and adapters from saved receipts.
It refuses to replay unresolved requests or unfinished adapters automatically.
Run paid stages sequentially. Do not edit frozen code or inputs to force a rerun.
`prepare`, `dev`, and `freeze` are the original development commands and must not
be rerun over a frozen experiment.

`runs/20260929-policy-v2/freeze.json` binds the protocol, runner, task, checks,
selection, data and correction pools before test evaluation or training.
`runs/20260929` retains the initial development task, which failed the preset
difficulty check, together with a conservatively charged tokenizer-race recovery.
Its costs are included in the cycle total. No adapter was trained on that task.

This cycle reserves at most $75 against the user's $1,000 total authorization.
The prior study estimated $17.42253885 in token charges. Estimates use current
official rates and uncached input tokens; they are not invoices. Provider
checkpoints expire after seven days; local archives retain completed samplers.
