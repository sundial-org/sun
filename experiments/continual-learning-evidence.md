# Evidence behind the v3 proposal

Checked 2026-09-28. The container's network policy blocked arxiv.org, huggingface.co, thinkingmachines.ai, openreview and metr.org. GitHub and the Tinker/Qwen repos were opened directly. **S** marks a claim seen only in search snippets; open it before publishing.

## Measured in the pushed runs

| Claim | Source |
| --- | --- |
| Lean held-out traces: 113/120 E4 only, 0 proved; the exit-code rule gives 0.996, equal to every LoRA; crossover withdrawn | `exp/lean:exp_lean/audit/curve-audit.md` |
| Live Lean facts: A0 90/480 proved, 18 E5; A2 33 proved, 77 partial, 170 E5. A2 round 1 still ran the base model and the adapter was applied at every turn, so this is spillover, not a measured effect | `exp/lean:exp_lean/audit/pre-correction/analysis.json` (`live`) |
| Lean rows (first checkpoint; later 240-480 rows, 3 epochs, 45-90 steps, LR 4e-4): 120 rows, 2.31M tokens over 4 epochs (about 4.8k per row), max 14,708 tokens, 32 steps, `LAST_ASSISTANT_MESSAGE` | same file, `training` |
| Lean reviewer (DeepSeek-V3.1): corrected headers matched the scorer on 90.6% of 1,440 live sessions (all arms); 384/480 targets had no prose | `exp/lean:exp_lean/README.md` |
| Sun analyst: recall 0.583 vs 0.792 for transcripts; 1 cross-session case | `exp/lean:exp_lean/results.tex` |
| Writing: base 57.1; at 15 edits, weights 90.4% vs context 74.2% of rules on valid stories; final gap -1.2 [-4.0, +1.5]; shared pool +13.7; editor-specific +80.3/+83.1; best-of-4 by Kept +3.6 vs oracle +10.3 | `exp/writing:exp_writing/results.tex`, `runs/.../analysis.json` |
| Writing weights validity 0.83-0.97, with `too_short` the largest failure type overall (220/416), but `missing_anchor` dominant at 60, 240, 360 and in one endpoint seed; mean words 137-165 vs base 165 | `analysis.json` `diagnostics` |
| The Qwen non-thinking renderer does not preserve prefixes across a whole multi-turn transcript, so datums are split per action | `exp/writing:exp_writing/AMENDMENTS.md` |

## Model and platform

| Claim | Source |
| --- | --- |
| Non-thinking sampling: T 0.7, TopP 0.8, TopK 20, MinP 0; no greedy decoding | [Qwen3 quickstart](https://github.com/QwenLM/Qwen3/blob/main/docs/source/getting_started/quickstart.md) |
| 32,768 native context; YaRN is not advised when average length is under 32k | [concepts](https://github.com/QwenLM/Qwen3/blob/main/docs/source/getting_started/concepts.md), [vLLM](https://github.com/QwenLM/Qwen3/blob/main/docs/source/deployment/vllm.md) |
| Tinker SamplingParams defaults: temperature 1, top_k -1, top_p 1, seed optional | [tinker sampling_params.py](https://github.com/thinking-machines-lab/tinker/blob/main/src/tinker/types/_pydantic_types/sampling_params.py) |
| Qwen3-8B is still in the Tinker lineup (24 Sep 2026); Qwen3-8B-Base is gone; Qwen3.5-9B is listed | [models.md](https://github.com/thinking-machines-lab/tinker-cookbook/blob/main/skills/research/references/models.md) |
| `qwen3_disable_thinking` exists; Hermes tool calls; `TrainOnWhat.LAST_ASSISTANT_MESSAGE` | [qwen3.py](https://github.com/thinking-machines-lab/tinker-cookbook/blob/main/tinker_cookbook/renderers/qwen3.py), [base.py](https://github.com/thinking-machines-lab/tinker-cookbook/blob/main/tinker_cookbook/renderers/base.py) |
| get_lr(Qwen3-8B) = 5e-5 x 10 x (2000/4096)^0.0775 = 4.7e-4; the guide says LR scales with sqrt(batch) from 128 and to aim for at least 100 steps | [hyperparam_utils.py](https://github.com/thinking-machines-lab/tinker-cookbook/blob/main/tinker_cookbook/hyperparam_utils.py), [hyperparams.md](https://github.com/thinking-machines-lab/tinker-cookbook/blob/main/skills/research/references/hyperparams.md) |
| LoRA on all layers; effective batch under 32; the optimal LR is about 10x full fine-tuning (up to about 15x for short runs, **S**) | [TRL summary](https://github.com/huggingface/trl/blob/main/docs/source/lora_without_regret.md) |
| RL settings: start at LR 1e-5, group 4-16, KL 0.05; drop groups where every reward is equal | [402_rl_hyperparams.py](https://github.com/thinking-machines-lab/tinker-cookbook/blob/main/tutorials/402_rl_hyperparams.py) |
| Pricing: training $0.44/M after 17 Jul 2026 (**S**); prefill and sample rates unconfirmed, so check `effective_rate_usd_per_million_tokens` | Tinker docs (blocked) |
| Sun main has checks, `RULES.md` `## name` rules with `agent:` and `feedback` (default true); `--no-hooks` was removed | `sun/checks.py`, `sun/cli.py` on main |

## Continual learning, context vs weights, skills

| Claim | Source |
| --- | --- |
| Joint training on all data is the offline upper bound, not a continual-learning strategy | [Avalanche](https://raw.githubusercontent.com/ContinualAI/avalanche/master/avalanche/training/supervised/joint_training.py) |
| On-policy RL forgets less than SFT; KL to base predicts forgetting | [RL's Razor](https://arxiv.org/abs/2509.04259) (**S**), [replication](https://github.com/SakanaAI/rl-razor-mnist) |
| SDFT: a demonstration-conditioned self-teacher learns with little forgetting; the Tinker recipe shows SFT retention of 12% at LR 1e-3 vs 94-97% for SDFT | [SDFT](https://github.com/idanshen/Self-Distillation), [Tinker sdft](https://github.com/thinking-machines-lab/tinker-cookbook/blob/main/tinker_cookbook/recipes/sdft/README.md) |
| SDPO: textual feedback (runtime errors) as a self-teacher | [SDPO](https://github.com/lasgroup/SDPO) |
| Feedback Distillation for Lean, main model Qwen3.5-9B | [Narozniak 2026](https://arxiv.org/abs/2605.30861) (**S**) |
| LoRA learns less and forgets less | [Biderman 2024](https://github.com/danbider/lora-tradeoffs) |
| ICL keeps improving to thousands of examples; fine-tuning is more data-hungry but can overtake | [Bertsch 2025](https://arxiv.org/abs/2405.00200) (**S**) |
| With size and data matched, ICL and fine-tuning generalize alike, with high variance | [Mosbach 2023](https://github.com/uds-lsv/llmft) |
| ACE playbooks: delta updates avoid context collapse | [ACE](https://github.com/ace-agent/ace) |
| GEPA beats GRPO on Qwen3-8B with far fewer rollouts | [GEPA](https://github.com/gepa-ai/gepa) (numbers **S**) |
| Curated skills gave +16 pp; self-generated skills gave no benefit | [SkillsBench](https://arxiv.org/abs/2602.12670) (**S**) |
| CIPHER learns preferences from edits, retrieves inferred preferences and uses edit cost | [PRELUDE](https://github.com/gao-g/prelude) |
| PEFT plus retrieval beats either alone | [OPPU](https://github.com/TamSiuhin/OPPU) |

## Verifiers, rubrics, self-improvement

| Claim | Source |
| --- | --- |
| Weak rubric verifiers give proxy gains that do not transfer (NeurIPS 2026) | [Mahmoud 2026](https://arxiv.org/abs/2605.12474) (**S**) |
| Verifiable-constraint training overfits; IFBench has 58 unseen constraints | [IFBench](https://github.com/allenai/IFBench) |
| The best-of-n KL formula log n - (n-1)/n is an upper bound | [Beirami 2024](https://arxiv.org/abs/2401.01879) (**S**) |
| Model critics hallucinate bugs and nitpicks | [McAleese 2024](https://arxiv.org/abs/2407.00215) (**S**) |
| Self-correction without external feedback fails; self-improvement saturates in 2-3 rounds | [Huang 2024](https://arxiv.org/abs/2310.01798), [Song 2025](https://arxiv.org/abs/2412.02674) (**S**) |
| Impossible tasks surface cheating; an abort option cuts it | [ImpossibleBench](https://arxiv.org/abs/2510.20270) (**S**) |
| LLM text idiosyncrasies and professional edits (LAMP). The over-editing claim is not established by this paper; check Beemo (arXiv 2411.04032) | [LAMP](https://arxiv.org/abs/2409.14509) (**S**) |
| Lean comparator: same statement, permitted axioms, kernel replay | [comparator](https://github.com/leanprover/comparator) |
| Paired, clustered evaluation statistics | [Miller 2024](https://www.anthropic.com/research/statistical-approach-to-model-evals) |

## Citation corrections to the long designs

- Narozniak 2026 compares against GRPO, not SFT. Its main model is Qwen3.5-9B.
- Gröner & Chiou 2026 compares simulated *participants*, not editors.
- Misra et al.: NeurIPS 2025 with a Jan 2026 arXiv id is consistent (posted after the conference).
- LeanMarathon uses Mathlib and Codex agents, so it is not comparable to core-only Lean.

## Adversarial check applied (2026-09-28)

Fixed: the playbook writer never sees the secret rules; the primary gap is defined as SFT minus playbook; checkpoints below 120 exist in the pool only; Lean context retrieves reports only (a record is about 5k tokens, max 14.7k); loss is on the corrected turn; the GRPO defaults match the Tinker tutorial (LR 1e-5, group 4, KL 0.05); the 20% unprovable share is our own choice; the live Lean proof rate is labelled unconfirmed.
