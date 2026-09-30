# Position of the experiment

This is a controlled next experiment, not evidence that the literature assumes
feedback accuracy is sufficient. The intended contribution is a measured
interaction between correction-error structure and the value of weight updates,
under a shared complete contextual policy and exact task evaluation.

1. [Reward Hacking in Rubric-Based Reinforcement Learning](https://arxiv.org/abs/2605.12474)
   separates verifier errors from incomplete rubric design. It reports proxy and
   reference-quality divergence in rubric-based RL. Our experiment holds the
   rubric complete, uses SFT targets with controlled equal error rates, and asks
   whether adding weights improves an otherwise identical contextual policy.
   A result that biased supervision can hurt, by itself, would repeat the broad
   lesson of this work rather than establish a new research contribution.

2. [Rubric-Guided Self-Distillation: Post-Training Without Rubric Verifiers](https://arxiv.org/abs/2606.12507)
   transfers behavior from a rubric-conditioned teacher into a student without
   that privileged context. It already studies the rubric-conditioning gap as
   a diagnostic of transferable signal. Here both frozen and trained policies
   retain the complete rubric, and correction reliability is manipulated. Our
   study therefore concerns incremental training value given the rules, not
   removal of rubric tokens or recovering an enrichment gap.

3. [Theoretical Analysis of Weak-to-Strong Generalization](https://arxiv.org/abs/2405.16043)
   analyzes conditions under which students can correct weak labels and expand
   coverage. Error structure is already central to this account. Our small
   experiment does not offer a new theory of noisy supervision. A stronger future
   contribution would validate a diagnostic that predicts context-versus-weight
   decisions on unseen task families, with these theories as relevant precedent.

The previous writing paper is our empirical starting point: it establishes a
recipe-level adaptation gain from synthetic edits, with limited contextual
inference and no semantic writing endpoint. This experiment removes hidden-rule
inference and replaces proxy writing checks with complete executable task
correctness. It retains the limitations of one model, one fixed rule set, and
synthetic data; those limitations should remain explicit in any paper claim.
