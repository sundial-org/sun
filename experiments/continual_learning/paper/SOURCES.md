# Sources and evidence boundaries

The paper asks whether a writer can learn a fixed writing rubric from edits
through context or weight adaptation. It reports the completed comparison on
that operational task. It does not treat rubric scores as literary quality,
human preference, or proof of a continual learner.

## Paper structure

[CS197 project and draft-paper instructions](https://web.stanford.edu/class/cs197/assignments/project.html#draft-paper)
were checked on September 28, 2026. The draft combines a research question,
related work, approach, evaluation and results, with references. The model-paper
analysis, adapted outline, and revision notes are in a separate appended page.
The user's half-length instruction sets the target to 2,000 to 2,500 body words,
half the course's 4,000 to 5,000-word final-paper range. Readable figures may make
the illustrated draft four pages. The separate audit does not count toward
that length.

## Primary research sources

| Source | Version and relevant evidence | Use in this paper |
|---|---|---|
| [Gao et al., CIPHER](https://arxiv.org/html/2404.15269v3) | Sections 2, 3, and 4.2; preference inference, retrieval and aggregation; frozen base models | Contextual preference inference from edits; not a replication claim |
| [Zhang et al., ACE](https://arxiv.org/html/2510.04618v3) | Section 3; incremental itemized playbook updates | Inspiration for local deltas; our compiler omits the full multi-role pipeline |
| [Bertsch et al., long-context learning](https://arxiv.org/html/2405.00200v2) | Comparisons of demonstration scale and fine-tuning; NAACL 2025 version | Model-paper organization and motivation for budget-specific comparisons |
| [Hu et al., LoRA](https://arxiv.org/abs/2106.09685v2) | Low-rank trainable updates with pretrained weights frozen | Adaptation mechanism |
| [Tan et al., OPPU](https://arxiv.org/html/2402.04401v3) | Personalized parameter-efficient tuning plus nonparametric context | Motivation for the combined adapter and playbook condition |
| [Zhou et al., IFEval](https://arxiv.org/abs/2311.07911v1) | Verifiable instruction checks and strict metrics | Separate active-policy instruction probe |
| [Miller, evaluation error bars](https://arxiv.org/html/2411.00640v1) | Paired comparisons and clustered evaluation units | Statistical motivation, not a guarantee of bootstrap coverage |

The broader neighborhood and methodological distinctions are recorded in
[RELATED_WORK.md](../RELATED_WORK.md). Literature statements are checked against
the cited primary sources. Source version identifiers are deliberate, including
when later versions exist.

## Experimental records

The source archive is the September 26 synthetic writing run under
`exp_writing/runs/ten-writers-20260926-inkling`. Only the 480 no-feedback review
opportunities enter this comparison. Public-valid draft/revision pairs number
14, 55 and 460 at the three opportunity budgets. No user-authored documents or
human edits are used as training data.

The new run is `../runs/shared-reviews-20260928`. The evidence collector packages
complete evaluated stories and tool transcripts, training targets and masks,
playbook updates, compiler inputs, compact provider receipts, cost records,
the data split, frozen implementation, and amendment records. Large token arrays
and binary adapters stay in the local run archive. Their hashes are retained.

`package.json` binds the packaged input files. `verify_evidence.py` replays the
tool transcripts, checks input provenance and target construction, and
independently recomputes scores and paired intervals. It does not call a model.
The sampled linguistic recheck and full IFEval recheck are recorded separately.
These checks establish consistency with the frozen scorer; they are not human
validation of its linguistic judgments.

An additional reconstruction of the older editor process matched 873 of 913
attempted prompt hashes and 444 of 460 final edit records. It did not fully
reproduce archive creation under the current sentence segmentation pipeline.
The exact discrepancies are retained in `evidence/editor-receipt-audit.json`;
the experiment uses the original shared before/after pairs without alteration.
The method claim about editor instructions describes the archived configuration,
and does not claim verified semantic preservation or complete editor replay.

## Interpretation

- Statistical intervals resample prompts or places while conditioning on the
  observed archive and three method seeds. They do not estimate variation over
  arbitrary new model families, editors, or training corpora.
- The public validity checker measures length, required words, and submission
  state. It does not measure premise adherence, coherence, or prose quality.
- The private rubric uses fixed regex rules and a pinned spaCy pipeline. Its
  easy rules and operational linguistic approximations limit score interpretation.
- The active IFEval comparison uses a small public subset. Either adaptation
  can be disabled to restore the base policy. Active instruction interference
  does not by itself establish erased capabilities or catastrophic forgetting.
- Every claim's exact wording, justification and evidence locators are retained
  in `claim-checks.json` and rendered into `CLAIMS.md`. Hashes detect stale review;
  semantic verification still requires examining the evidence and reasoning.
