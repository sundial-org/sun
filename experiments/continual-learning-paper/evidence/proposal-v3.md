# Reviews in context or in weights? (v3)

A strong reviewer corrects a small agent after each session. After how many reviews do corrections in weights beat corrections in context, and what does learning break? "Never" is a finding ([evidence](continual-learning-evidence.md)).

## Lessons from the pushed runs (`exp/lean`, `exp/writing`)

- **Lean collapsed.** None of the 120 held-out traces were proved (113 were E4 only), so an exit-code rule matched every LoRA report. In the live loop the whole-episode LoRA arm proved 7% vs 19% for the no-feedback arm (one seed, unconfirmed).
- **Writing worked.** Weights learned the style from 15 edits (90% vs 74% of rules in context), but validity dropped (83-97% vs 98% for base) from short stories and missing anchors. Final gap: -1.2 pp [-4.0, +1.5] on live pools, +13.7 on a shared pool.

## Both experiments

- **Policy:** Qwen3-8B on Tinker (LoRA only), `qwen3_disable_thinking`. Sampling: T 0.7, top-p 0.8, top-k 20 ([Qwen](https://github.com/QwenLM/Qwen3/blob/main/docs/source/getting_started/quickstart.md); Tinker defaults differ), with a unique seed per session. Prompts stay within 32,768 tokens. Qwen3.5-9B if Qwen3-8B leaves Tinker.
- **Reviewer:** a frozen strong model from another family, read-only. It is a `RULES.md` rule with `feedback: false`. It must pass dev gates or be swapped ([critics catch bugs but also invent them](https://arxiv.org/abs/2407.00215)). A human checks 30 cases.
- **Scorer:** a deterministic program that only grades held-out data.
- **Pools:** in the primary, all arms learn from one frozen pool of reviews of the no-feedback arm, with checkpoints at 15, 30, 60, 120, 240, 360 and 480. The live loop (4 rounds of 120 sessions, 10 workers, each arm reviewed on its own sessions) is secondary.
- **Arms:**
  1. none;
  2. raw context: BM25 review records within 8k tokens;
  3. **playbook:** a SKILL.md of at most 2k tokens, updated by deltas ([ACE](https://github.com/ace-agent/ace)). It is written from the reviews only, by a model that never sees the secret rules. A self-written playbook is an ablation ([SkillsBench](https://arxiv.org/abs/2602.12670));
  4. **SFT:** LoRA retrained from base on all corrections (the joint-training upper bound);
  5. **distill:** the model with the playbook in context teaches itself without it, on pool prompts, step-matched ([SDFT](https://github.com/idanshen/Self-Distillation), forward KL);
  6. SFT plus playbook.
- **Primary gap:** SFT minus playbook. **Controls:** step-matched SFT at every checkpoint. At 480, also sequential LoRA, self-target and shuffled-target SFT.
- **Recipe:**
  - Rank 16 on all layers, batch 16.
  - LR picked on dev from {1.5e-4, 4.7e-4, 7e-4} ([get_lr](https://github.com/thinking-machines-lab/tinker-cookbook/blob/main/tinker_cookbook/hyperparam_utils.py); [LoRA Without Regret](https://thinkingmachines.ai/blog/lora/)).
  - At least 3 epochs and 30 steps. Loss on the corrected turn only.
  - 3 seeds; adapters downloaded.
- **Forgetting:** track public-task validity, an IFEval subset and KL to base ([RL's Razor](https://arxiv.org/abs/2509.04259)).
- **Stats:** clustered paired analysis ([Miller](https://arxiv.org/abs/2411.00640)) via cluster bootstrap, with power simulated on dev. One primary test at 480. x0 is the first checkpoint whose simultaneous lower band stays above 0.

## Exp 1: Ten Provers (core Lean 4, events as in `exp/lean`)

- **Tools:**
  - `read_file`;
  - `write_file` (assigned file only);
  - `compile` (up to 3; output, axioms, read-only receipt);
  - `submit_report` (proved, partial or unproved; E1-E6; explanation).
- **Gates:**
  - On dev, base proves 20-70%, and the exit-code rule scores at most 0.85.
  - Tool errors at most 2%.
  - Reviewer at least 95% exact.
  - Our choice: about 20% of lemmas are unprovable ([ImpossibleBench](https://arxiv.org/abs/2510.20270)).
  - Rare events come from a compiler-checked set with 20 positives and 20 negatives per event.
  - At least 60 sealed dependency groups.
- **Row:** trajectory, then the corrected report (about 5k tokens). Context retrieves reports only.
- **Score:** exact header match on 5 samples per frozen trace.
- **Adapter:** applied at the report turn only. The whole-episode adapter's proof rate measures spillover.
- **Sun question:** at least 30 E3, 30 E6 and 60 clean groups. Compare recall for Sun vs transcripts plus git, with a false-positive guard.

## Exp 2: Ten Writers

- **Tools:** `read_file`, `write_file`/`edit_file`, `check_format` (length and anchors), `submit`. Stories are 120-350 words.
- **Editor A:** 8 secret checkable rules, each passed by at most 70% of base stories ([IFBench](https://github.com/allenai/IFBench)).
  - Rewrites flagged sentences only, preserving length.
  - Gates: recall of at least 0.9 per rule, and at most 20% of changed words in clean sentences.
- **Editor B:** the opposite rules. LoRA-B, trained on B's edits of the same stories, tests whether the writer learned A specifically.
- **Row:** the trajectory with the final story replaced by the edited one. Targets failing the public format check are dropped.
- **Scores:** S (rules followed) on valid stories. Validity guard: no more than 3 pp below base. Kept: the share of writer tokens surviving, from two Sun commits.
- **Kept as a reward:**
  - Best-of-n, n from 1 to 16, against KL ([Gao 2023](https://arxiv.org/abs/2210.10760)).
  - GRPO on fresh samples scored by frozen editor A: LR 1e-5, group 4, KL 0.05 ([Tinker](https://github.com/thinking-machines-lab/tinker-cookbook/blob/main/tutorials/402_rl_hyperparams.py)).
  - S stays held-out gold ([rubric hacking](https://arxiv.org/abs/2605.12474)).
