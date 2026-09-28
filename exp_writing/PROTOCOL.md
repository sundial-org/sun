# Frozen execution protocol

This implementation follows the user's four-round agent experiment. The supplied
long design is background. Its planned results and timing are not observations.

- Writer: Qwen/Qwen3-8B, thinking disabled, temperature 0.7.
- Editor A/B: Inkling, reasoning effort 0.6, temperature 0, same persona.
  Numbered sentence edits followed by one independent reread, without scorer feedback.
- Ten concurrent workers per arm share a policy. Workers are throughput, not replicates.
  Independent early checkpoints and the base-policy ranking test may overlap live
  rounds, using separate ten-worker batches and the same locked budget ledger.
- Three live arms: no feedback; retrieved edited stories in an 8,000-token system
  block; rank-16 LoRA retrained from base on cumulative edited trajectories.
- Four rounds, 120 prompts per arm per round. Early offline checkpoints at
  15, 30, and 60 accepted edits. Actual accepted rows are reported at every point.
- The editor sees eight private rules. Writers see no rule list, labels, scores,
  rule explanations, or access to the private scorer. Only edited stories enter
  context or supervised targets. Held-out and dev prompts never enter training.
- Agent tools: read_file, write_file, edit_file, check_format, submit. File tools
  operate on a two-file in-memory sandbox. Every transcript is saved. SFT replaces
  the final story-producing action with a full write_file of the edited story,
  regenerates subsequent tool results, and trains assistant messages only.
- Length/anchors are checked publicly; style is checked privately. An invalid or
  unsubmitted evaluation scores zero in U*S. Failed sessions are counted.
- 480 training, 24 development, 96 held-out prompts. Half of held-out prompts use
  two genres absent from training. Prompts use a fixed seed and reject shared
  premise 8-grams and repeated anchor pairs.
- Score raw held-out drafts before editing, at baseline and after each update.
  Four stochastic samples per prompt. Bootstrap paired prompt means, 10,000 draws.
- Offline controls at 480: LoRA-A and LoRA-B on A/B edits of the same base drafts;
  LoRA-self on those unedited drafts. Evaluate each under both guides. Flipped
  rules, not the aggregate off-diagonal score, test editor specificity.
- Three training seeds for the final primary and control comparisons. Early
  checkpoints use seed 0. Training uses lr=4e-4, batch 4 up to 60 rows, otherwise
  16, at least 3 epochs and 30 steps. No held-out tuning.
- Best-of-n: base policy, 16 samples per held-out prompt; compare uniform selection
  with Kept selection at n=4, and an oracle S selector on the same eligible pool.
  Ties average uniformly. All selected scores come from unedited stories.
- Kept is case-sensitive whitespace-token survival with punctuation attached,
  computed from two Sun commits. Token Levenshtein similarity is also recorded
  because Kept ignores insertion-only changes. No policy-gradient RL is claimed.
- All requests reserve their maximum token cost before submission, using current
  official rates. The execution ceiling is USD 800. Failed/uncertain calls retain
  reservations; no automatic replay of failed paid submissions. The SDK's
  idempotent submission retries retain a stable request identity (see amendments).

## Explicit differences from the attachment

1. The editor is Inkling, accessible through the supplied Tinker account,
   rather than the attachment's unspecified proprietary model.
   DeepSeek-V3.1 was rejected on development calibration before any held-out
   evaluation: mean edited-rule scores were 83.2% for A and 94.9% for B.
2. This is a real tool-using writer trajectory, not a one-shot story action.
3. The pinned grammar tagger is spaCy 3.8.11 / en_core_web_trf 3.8.0. The smaller
   en_core_web_sm tagger was used only in preliminary calibration, then replaced
   before held-out evaluation. Fixtures and spot checks are retained. A human
   smoke test is reported only if actually done.
4. Context contains edited stories without margin notes. There is one fixed 8k
   budget; results do not establish superiority over a learned rule-summary memory.
   Retrieval uses normalized prompt-token overlap with deterministic recency ties.
5. Current Sun main records attributed commits and operation events. Private
   editor rule annotations are ordinary private JSON artifacts, not Layer-2 checks.
6. Separate live data pools compare complete learning workflows. The shared-base
   offline controls isolate edits on identical source stories at the endpoint.
7. Timing is measured, not forced to one hour per round. No external timestamped
   preregistration, human review, or independent live-trajectory replication is claimed.
8. Development calibration is 24 prompts with one sample each. The attachment's
   full rule-reselection, minimal-pair editor recall, test-retest and attack gates
   are not reproduced. Editor errors are retained and reported; targets are never
   filtered by the hidden style score. The runtime requires at least 80% valid
   writer sessions on this calibration set.

The report must state missing controls, failed gates, and incomplete runs. It must
never replace missing experimental measurements with predictions or simulated data.
