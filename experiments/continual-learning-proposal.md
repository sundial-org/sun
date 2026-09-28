# Reviews in context or in weights? (v3)

A strong reviewer corrects a small agent after every session. After how many reviews do corrections in weights beat corrections in context, and what does learning break? "Never" is a finding. Sources and details: [evidence](continual-learning-evidence.md).

## Lessons from the pushed runs (`exp/lean`, `exp/writing`)

- **Lean collapsed.** 113/120 held-out traces were compile failures and none were proved, so an exit-code rule matched every LoRA report. The report-trained LoRA also cut live proofs from 19% to 7%.
- **Writing worked.** Weights learned the style from 15 edits (90% of rules vs 74% in context), but shortened stories, so validity fell to 86-92%. The final gap was -1.2 pp [-4.0, +1.5] on live pools but +13.7 pp on a shared pool.

## Both experiments

- **Policy:** Qwen3-8B on Tinker (LoRA only), `qwen3_disable_thinking`. Sampling: T 0.7, top-p 0.8, top-k 20 ([Qwen](https://github.com/QwenLM/Qwen3/blob/main/docs/source/getting_started/quickstart.md); Tinker defaults differ), with a unique seed per session. Prompts stay within 32,768 tokens. Fallback: Qwen3.5-9B.
- **Reviewer:** a frozen strong model from another family, read-only. It is a `RULES.md` rule with `feedback: false`. Before training it must reach 95% exact agreement with the scorer on dev ([critics hallucinate](https://arxiv.org/abs/2407.00215)). A human checks 30 cases.
- **Scorer:** a deterministic program. It grades held-out data only.
- **Pools:** in the primary, all arms learn from one frozen pool of reviews of the no-feedback arm, which isolates delivery. The live loop, where each arm is reviewed on its own sessions, is secondary.
- **Arms:**
  1. none;
  2. raw context: BM25 review records within 8k tokens;
  3. **playbook:** a SKILL.md of at most 2k tokens that the reviewer updates by deltas ([ACE](https://github.com/ace-agent/ace), [CIPHER](https://arxiv.org/abs/2404.15269)). A playbook written by the policy itself is an ablation ([SkillsBench](https://arxiv.org/abs/2602.12670));
  4. **SFT:** LoRA retrained from base on all corrections so far. This is the joint-training upper bound;
  5. **distill:** the model with the playbook in context teaches itself without it, on-policy ([SDFT](https://github.com/idanshen/Self-Distillation));
  6. SFT plus playbook.
- **Offline controls at 480:** sequential LoRA, self-target, shuffled-target and step-matched SFT.
- **Recipe:**
  - Rank 16 on all layers, batch 16.
  - LR picked on dev from {1.5e-4, 4.7e-4, 7e-4} ([get_lr](https://github.com/thinking-machines-lab/tinker-cookbook/blob/main/tinker_cookbook/hyperparam_utils.py); [LoRA Without Regret](https://thinkingmachines.ai/blog/lora/)).
  - At least 3 epochs and 30 steps. Loss on the final corrected message only.
  - 3 seeds per checkpoint. Adapters downloaded.
- **Checkpoints:** 15, 30, 60, 120, 240, 360 and 480 reviews. Four rounds of 120 sessions, 10 workers.
- **Forgetting:** at every checkpoint, track public-task validity, an IFEval subset and KL to base ([RL's Razor](https://arxiv.org/abs/2509.04259)).
- **Stats:** paired cluster bootstrap with a dev power simulation ([Miller](https://arxiv.org/abs/2411.00640)). One primary test at 480. x0 is the first checkpoint whose simultaneous lower band stays above 0.

## Exp 1: Ten Provers (core Lean 4)

- **Tools:**
  - `read_file`;
  - `write_file` (assigned file only);
  - `compile` (up to 3; output, axioms, read-only receipt);
  - `submit_report` (status proved, partial or unproved; E1-E6; explanation).
- **Gates before training:**
  - On dev, base proves 20-70%, and the exit-code rule scores at most 0.85.
  - Tool errors at most 2%.
  - About 20% of lemmas are unprovable ([ImpossibleBench](https://arxiv.org/abs/2510.20270)).
  - Rare events come from a compiler-checked challenge set with 20 positives and 20 negatives per event.
  - At least 60 sealed groups.
- **Row:** trajectory, then the corrected report (about 5k tokens).
- **Score:** exact header match on 5 samples per frozen trace.
- **Adapter:** applied at the report turn only. The whole-episode adapter's proof rate measures spillover.
- **Sun question:** at least 30 E3, 30 E6 and 60 clean groups. Compare Sun to transcripts plus git on recall, with a guard on false positives.

## Exp 2: Ten Writers

- **Tools:** `read_file`, `write_file`/`edit_file`, `check_format` (length and anchors), `submit`. Stories are 120-350 words.
- **Editors:** editor A holds 8 secret checkable rules, each passed by at most 70% of base stories ([IFBench](https://github.com/allenai/IFBench)). Editor B holds the opposite rules. Editors rewrite flagged sentences only, preserving length. Gates: recall of at least 0.9 per rule, and at most 20% of changed words in clean sentences ([LLMs over-edit](https://arxiv.org/abs/2409.14509)).
- **Row:** the trajectory with the final story replaced by the edited one. Loss on that write only. Targets that fail the public format check are dropped.
- **Scores:** S (rules followed) on valid stories. Validity guard: no more than 3 pp below base. Kept: the share of writer tokens that survive, from two Sun commits.
- **Kept as a reward:**
  - Best-of-n, n from 1 to 16, against KL ([Gao 2023](https://arxiv.org/abs/2210.10760)).
  - Offline GRPO on Kept: LR 1e-5 to 4e-5, group 8, KL 0.05 ([Tinker](https://github.com/thinking-machines-lab/tinker-cookbook/blob/main/tutorials/402_rl_hyperparams.py)).
  - S is the held-out gold score ([rubric hacking](https://arxiv.org/abs/2605.12474)).
