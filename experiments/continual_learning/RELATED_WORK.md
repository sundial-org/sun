# Literature map and changed assumption

Sources checked on 28 September 2026. These are methodological connections,
not performance numbers transferred to our experiment. The compact paper will
cite its direct comparators; this map records the broader research cycle.

## Nearest neighbor

[CIPHER / PRELUDE, Gao et al.](https://arxiv.org/pdf/2404.15269), Sections 2–4,
is the closest problem formulation. It infers preferences from edits, retrieves
preferences from nearby contexts, and aggregates them for generation. Its
interactive objective is cumulative edit cost; evaluation uses simulated users
in summarization and email. Our changed assumption is that the review archive
is held fixed across representations and that weight updates are available.
We measure hidden-rule compliance jointly with tool-task validity on fresh
prompts. Our global delta playbook is neither the CIPHER retrieval algorithm
nor a claim to replicate its reported performance.

## Thematic map

| Work | Checked primary source | Relevance and boundary |
|---|---|---|
| CIPHER / PRELUDE | [Gao et al., 2024](https://arxiv.org/abs/2404.15269) | Direct edit-feedback comparator; use inferred preferences, not only raw examples. |
| Agentic Context Engineering | [Zhang et al., 2026 version](https://arxiv.org/html/2510.04618v3) | Itemized delta updates motivate our compiler. We omit its generator/reflector/curator pipeline and helpfulness counters, so this is ACE-inspired only. |
| Long-context ICL exploration | [Bertsch et al., 2025 version](https://arxiv.org/abs/2405.00200v2) | Compares retrieval, many demonstrations, and fine-tuning. Motivates a data-budget curve without assuming a universal crossover. |
| LoRA | [Hu et al., 2021](https://arxiv.org/abs/2106.09685) | Low-rank adaptation supplies our weight representation; its parameter efficiency does not establish retention in this task. |
| Self-Distillation Enables Continual Learning | [Shenfeld et al., 2026](https://arxiv.org/html/2601.19897v2) | Derives reverse KL, but v2 reports forward KL in practice on student trajectories with a demonstration-conditioned teacher. This differs from our corrected-target SFT. |
| IFEval | [Zhou et al., 2023](https://arxiv.org/abs/2311.07911) | Verifiable instruction checks provide an independent retention probe. Our 128-example subset is not the full benchmark. |
| Reflexion | [Shinn et al., 2023](https://arxiv.org/abs/2303.11366) | Stores verbal reflections for subsequent trials. Our evidence consists of frozen edits, not each arm's own trial feedback. |
| Self-Refine | [Madaan et al., 2023](https://arxiv.org/abs/2303.17651) | Iterative feedback and revision within a task differs from transferring previous reviews to a fresh task. |
| OPPU | [Tan et al., 2024](https://arxiv.org/abs/2402.04401) | Combines personal PEFT parameters with retrieved/profile information. Motivates testing SFT plus playbook rather than assuming mutual exclusivity. |
| GEPA | [Agrawal et al., 2025](https://arxiv.org/abs/2507.19457) | Evolves prompts using reflection and evaluated candidates. Our compiler does not search prompts against hidden development style scores. |
| Many-Shot ICL | [Agarwal et al., 2024](https://arxiv.org/abs/2404.11018) | Demonstrations can remain useful at large counts. The 8,000-token retrieval arm here is a bounded-context comparison. |
| Lost in the Middle | [Liu et al., 2023](https://arxiv.org/abs/2307.03172) | Position sensitivity motivates recording retrieval order. It does not predict our writing result. |
| Direct Preference Optimization | [Rafailov et al., 2023](https://arxiv.org/abs/2305.18290) | Pairwise preference learning differs from imitating the edited target. We do not call the before/after pairs explicit human preference labels. |
| LLM Critics Help Catch LLM Bugs | [McAleese et al., 2024](https://arxiv.org/abs/2407.00215) | Critic errors motivate preserving reviewer receipts and reporting rubric limitations. Coding-critic accuracy is not editorial accuracy. |
| Adding Error Bars to Evals | [Miller, 2024](https://arxiv.org/abs/2411.00640) | Paired comparisons and clustering motivate our bootstrap and shared-place sensitivity analysis. |
| Overcoming catastrophic forgetting | [Kirkpatrick et al., 2016](https://arxiv.org/abs/1612.00796) | Sequential-task retention is a separate question. Fresh-base cumulative adapters alone do not demonstrate continual learning. |

## Synthesis

These works distinguish three decisions: which experience to collect, how to
represent it, and how to measure the resulting behavior. The pilots entangled
collection and representation in writing and lacked event diversity in Lean.
The new experiment compares representations on a common synthetic review pool,
then challenges the interpretation with unedited/shuffled targets, combined
context and weights, and independent instruction checks. Its contribution is a
controlled empirical result with an auditable boundary, not a new learning
algorithm or evidence that one representation universally wins.
