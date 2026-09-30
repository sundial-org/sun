# Claim-by-claim verification

Checked 2026-09-28. Each substantive sentence is wrapped in a stable claim ID in [paper.tex](paper.tex). T01 also covers every generated table cell. The title is a research question; bibliography metadata and source locators are checked in [SOURCES.md](SOURCES.md).

**What checked means:** measured claims were reconciled with saved pilot artifacts and recomputed where quantitative; literature claims were read in primary sources; design claims were checked against the proposal or explicitly identified as clarifications; inferences state their limits. A planned gate is not a passed gate. No human review, new provider run, or general capability guarantee is implied.

**Reproduction:** `python verify_evidence.py` checks compact-data hashes, prompt counts, training manifests, score arithmetic, paired intervals, controls, selection gains, Lean header shortcuts, and claim hashes. `--check-archives` additionally checks local raw-file hashes. [verification.json](evidence/verification.json) records outcomes and limits. Stored writing rule labels remain the original automated tagger judgments; the human meaning of those judgments was not revalidated. Lean facts were rederived from saved receipts, without rerunning the compiler.

**Coverage:** every assertion block below was manually reviewed; hash checks detect changed reviewed text, not truth automatically. Source abbreviations link through [the source register](SOURCES.md). References such as C28 identify other checked claims.

## C01: design

We study whether a small agent should reuse a review history through context or weight updates, asking when adaptation improves the reviewed behavior while preserving task validity.

**Evidence:** P opening question and Both experiments.

**Check and justification:** Defines the research question in the v3 proposal. No performance assertion.

## C02: measured

Two Qwen3-8B pilots motivate a controlled follow-up: a Lean reporting evaluation collapsed to a compile-outcome shortcut, while a writing evaluation learned planted editorial rules but lost valid submissions.

**Evidence:** L What the curve actually measures; W curve and diagnostics.

**Check and justification:** Lean coverage and shortcut checks reproduce; writing conditional style and validity are separately recomputed. Both model identities are documented in LR and WP. This describes two pilots, not the revised design.

## C03: measured

At the writing endpoint, the live weights-minus-context gap was $-1.2$ percentage points (95% interval $[-4.0,1.5]$); training on a shared edited archive yielded a held-out gap of $+13.7$ $[11.4,16.0]$.

**Evidence:** V writing_curve budget=480; V controls.shared_weights_vs_context.

**Check and justification:** Paired per-prompt means and 10,000 resamples reproduce -0.0121993 [-0.0404270,0.0150674] and 0.1365637 [0.1137769,0.1604973]. Multiply by 100 and round to one decimal. Shared-archive evaluation uses held-out prompts, not the edited training drafts.

## C04: inference

These results support archive-specific adaptation, but establish neither a lasting review-count crossover nor retention of general capabilities.

**Evidence:** C28-C42; C60.

**Check and justification:** Positive matched-archive controls establish adaptation on this archive. The live endpoint crosses zero; no playbook curve or general retention scores exist. The inference explicitly excludes lasting crossover and general retention.

## C05: scope

We specify a shared-review comparison against a compact playbook, with coverage gates, validity safeguards, and clustered inference; this revised experiment remains unexecuted.

**Evidence:** P; C43-C58; LR Methods revision.

**Check and justification:** A specified future protocol is provided. The current branch contains proposal/evidence rather than an executed revised harness; its stated gates and controls are not completed results.

## C06: literature

Edits can convey preferences that were absent from the original instruction: prior work infers natural-language preferences from user revisions and retrieves them for later requests [gao].

**Evidence:** G abstract and sections 1-3.

**Check and justification:** The primary paper describes inferred latent preferences from revisions and retrieval of preferences from similar contexts. This supports the possibility of conveying absent preferences, not universal success.

## C07: design

Our question is where to store that information: in retrieved reviews, in a maintained instruction playbook, or in a model adapter trained on corrected outputs.

**Evidence:** P arms.

**Check and justification:** The three storage representations are choices under study. Raw review retrieval, playbook, and adapter training appear in v3.

## C08: design

Our conditional thesis is that weight adaptation may eventually outperform a strong context baseline on identical review evidence without materially degrading public-task completion.

**Evidence:** P Primary gap; P Scores.

**Check and justification:** Hypothesis, not finding. The planned contrast is SFT minus playbook and writing has a 3 percentage point validity guard. There may be no qualifying budget.

## C09: inference

Our pilots reveal two obstacles to interpreting such a comparison: a high reporting score can conceal missing event coverage, and a high conditional style score can conceal invalid submissions.

**Evidence:** L coverage; W curve budget=480.

**Check and justification:** Missing Lean event categories coexist with near-perfect aggregate score; writing conditional style is higher for weights while validity is lower. These directly instantiate the two cautions.

## C10: design

For writing, we therefore change the primary comparison from separately evolving workflows to representations of a common review archive, while retaining the live loop as a secondary deployment test; Lean already used shared reviews.

**Evidence:** WP live arms; LR primary comparison; P Pools.

**Check and justification:** Writing primary pilot used distinct evolving arm pools, with a separate shared-pool endpoint control. Lean already used the no-feedback shared pool. v3 makes common evidence the primary design for both.

## C11: scope

This draft contributes audited pilots and a protocol for the unresolved comparison; neither superiority over a playbook nor continual learning has been demonstrated.

**Evidence:** C28-C62; P.

**Check and justification:** The draft's contribution is audit plus protocol. No playbook scores or sequential retention experiment is reported. Cumulative retraining is distinguished from sequential continual learning.

## C12: literature

Long-context experiments compare retrieved demonstrations with fine-tuning and find that the relative ranking depends on data scale and task; LoRA does not uniformly overtake in-context learning [bertsch].

**Evidence:** B section 3.3 and Figure 3.

**Check and justification:** Bertsch et al. explicitly report task/data dependence and cases where LoRA never overtakes ICL. No quantitative result or universal threshold is transferred to this study.

## C13: design

We extend this comparison to reviewer corrections under a fixed evidence pool and validity constraints, without assuming a universal threshold.

**Evidence:** P Pools, Scores, Stats; B section 3.3.

**Check and justification:** Our proposed extension concerns reviewed trajectories, fixed shared review evidence, and validity. The sentence makes no priority claim over all literature.

## C14: literature

CIPHER retrieves preferences inferred from edits [gao], while Agentic Context Engineering organizes experience into a playbook maintained through incremental updates [ace].

**Evidence:** G abstract and section 3; A abstract.

**Check and justification:** G describes inferred-preference retrieval. A describes contexts as playbooks with incremental updates. No external gain is borrowed as an expected result here.

## C15: inference

These approaches motivate a learned summary baseline stronger in representational scope than the pilots' raw-example retrieval, although its performance in our tasks has not yet been measured.

**Evidence:** C14; WP difference 4; P playbook.

**Check and justification:** A learned summary can represent inferred rules, whereas raw examples alone are not an explicit rule summary. Stronger refers to representational scope, not a measured performance advantage; the final clause makes that limitation explicit.

## C16: literature

LoRA freezes pretrained weights and trains low-rank update matrices [lora]; self-distillation work uses a demonstration-conditioned model as its own teacher for on-policy learning [sdft].

**Evidence:** H abstract; D abstract.

**Check and justification:** H defines frozen pretrained weights and trainable low-rank matrices. D defines demonstration-conditioned self-teaching on policy. This does not assert that our proposed playbook variant exactly replicates D.

## C17: design

We propose separate supervised and distillation arms, treating retention as an empirical question rather than a guarantee of small adapters.

**Evidence:** P Arms; P Forgetting.

**Check and justification:** SFT and distillation are separate proposed arms; public validity, IFEval and KL are intended retention diagnostics. No retention result is attributed to a small adapter.

## C18: literature

Model critics can also invent bugs [critics], and evaluation methodology recommends paired comparisons and accounting for clustered questions [miller]; these observations motivate reviewer calibration and grouping repeated samples by their underlying task.

**Evidence:** K abstract; M recommendations 2-4.

**Check and justification:** Critic paper explicitly acknowledges hallucinated bugs. Miller recommends clustering dependent questions and paired differences. Calibration and grouping are our design response, not a result established by those papers on our data.

## C19: measured

Both pilots used Qwen3-8B with a no-feedback arm, a retrieved-example context arm, and rank-16 LoRA retrained from base on cumulative corrections, with four live rounds of 120 sessions per arm.

**Evidence:** LR opening setup and Completed run; WP; LT training; WT rank and names.

**Check and justification:** Both source protocols specify Qwen3-8B, no feedback, context and cumulative fresh-base LoRA. Lean training records give rank 16; writing manifests do too. Both have 4 x 120 sessions per arm. Shared-pool versus live-pool distinction is explicit in C10.

## C20: measured

Ten concurrent workers per arm supplied throughput, not independent experimental replicates; the writing context budget was 8,000 tokens, and retrieval used normalized prompt-token overlap with recency tie-breaking.

**Evidence:** WP workers and difference 4.

**Check and justification:** Ten workers share one policy, so they are concurrency rather than independent trained replicates. The committed protocol describes 8000-token normalized-overlap retrieval with recency ties. This is not the proposed BM25 retriever.

## C21: measured

In the writing pilot, agents used file operations, a public format check, and submission tools to produce stories of 120 to 350 words containing two required words, while an Inkling editor applied eight hidden style rules.

**Evidence:** WP Writer, Editor A/B, Agent tools, private rules; WS RULES.

**Check and justification:** Pinned protocol identifies Inkling and public tools, 120-350 words, required anchors and eight rules. Prompts preserve two required words. Counts refer to the planted rubric, not all aspects of style.

## C64: measured

Guide A prohibited "suddenly," "very," semicolons, and em dashes, and constrained narrative tense, opening length, dialogue-tag verbs, and capitalization.

**Evidence:** WS RULES A entries 0:8.

**Check and justification:** The eight planted A rules prohibit two words and two punctuation types, require at least 90% present finite narration verbs, cap the opening at 12 words, restrict dialogue tags to say, and restrict capitalization outside sentence or quotation starts. The prose summarizes these categories; exact rules remain in WS.

## C22: measured

The private scorer combined regex/token checks with a pinned spaCy tagger; $S$ is the per-story fraction of applicable rules passed, excluding the dialogue-tag rule when no tags occur, and $U$ indicates valid submission, so reported mean $Y=U S$ assigns invalid submissions zero.

**Evidence:** WS score; WP invalid evaluations; WA prompt_means; W diagnostics.

**Check and justification:** Scorer uses regex/token tests and a pinned spaCy tagger. Stored U and rule arrays reproduce U*S. Public format conditions were recalculated on drafts; the private NLP judgments were not newly human-validated or retagged. WS returns a None dialogue-tag flag if no tags are found; non-None flags define each story denominator before averaging.

## C23: measured

Training replay replaced the final story-producing action with the edited story and regenerated subsequent tool results; the pilot trained assistant messages, whereas the revised protocol restricts loss to the corrected turn.

**Evidence:** WP training replay; WAM renderer amendment; P Recipe and Writing Row.

**Check and justification:** Pilot protocol trains assistant messages after replay. Renderer amendment splits actions because transcript prefixes differ. v3 restricts loss to corrected turn. The draft explicitly distinguishes implemented pilot behavior from planned correction.

## C63: measured

Writing pilot training used learning rate $4\times10^{-4}$, batch four through 60 rows and 16 thereafter, and at least three epochs and 30 steps.

**Evidence:** WP training recipe; WT all manifests.

**Check and justification:** Frozen writing protocol and saved training manifests give learning_rate=0.0004, batch=4 for early datasets and 16 otherwise, epochs at least 3 and steps at least 30. This is the completed writing recipe, distinct from planned dev selection.

## C24: measured

Writing evaluation used 96 held-out prompts with four stochastic samples per policy and seed, including 48 prompts in genres absent from training; neither development nor held-out prompts entered the intended training split.

**Evidence:** WP split and held-out settings; WPR; WI.

**Check and justification:** Prompt data has 480 train, 24 dev, 96 held-out, of which 48 have unseen genres. Every stored evaluation has four samples for each held-out ID. Integrity source reports separation; intended split phrasing does not claim absence of all semantic contamination.

## C25: measured

The final live LoRA comparison used three training seeds, earlier checkpoints one; 10,000 paired prompt bootstrap draws produced pointwise intervals conditional on the collected training pools, without simultaneous coverage across budgets.

**Evidence:** WA interval, difference and analyze; WT; V writing_curve.

**Check and justification:** The implementation uses 10000 draws and seed 1701 on paired prompt means. Three final seeds are pooled within prompt; early points use one. No resampling of training archives or simultaneous budget adjustment occurs.

## C26: measured

The Lean pilot instead froze 120 trajectories from 40 lemmas in 20 families and sampled five reports per trajectory at each policy checkpoint; its reported score was precision times recall over structured facts, not F1 or explanation quality.

**Evidence:** L setup and score definition; LS score; V lean_reports; LE.

**Check and justification:** 120 traces, 40 unique lemma IDs and 20 families are independently counted. Each stored stochastic report set has 5 samples; greedies are separate. LS computes precision times recall and never grades prose.

## C27: measured

Under that frozen rubric, a failed final compilation or absence of compilation produces only event E4, while E5 denotes a local `sorry` and E6 denotes an admitted dependency; this distinction matters when interpreting aggregate accuracy.

**Evidence:** LS facts; L truth table.

**Check and justification:** facts returns E4 immediately for no compile or failed/timeout compile. E5 checks own sorry warning; E6 checks a dependency with sorryAx. These definitions are specific to the frozen rubric.

## C28: measured

The held-out truth sets contained 113 E4-only traces, six E5-only traces, and one E5-plus-E6 trace, with no proved or partial outcomes and no E1, E2, or E3 cases.

**Evidence:** V lean_truth_patterns; LE traces; LS facts.

**Check and justification:** Compiler-receipt truth rederivation yields E4=113, E5=6, E5+E6=1. Those exhaustive patterns exclude proved/partial and E1/E2/E3. No fresh Lean compiler execution was performed in this paper audit.

## C29: measured

Always reporting E4 scores $113/120=0.9417$; a post hoc rule reporting E4 after failure or no compile and E5 otherwise scores $0.9958$, matching all 600 sampled headers at each of the four LoRA checkpoints.

**Evidence:** V; LE evaluations; L What the curve actually measures.

**Check and justification:** Constant E4 gives 113/120. At each of four LoRA checkpoints, all 600 stored stochastic headers equal the post hoc two-branch rule; 595 scores are 1 and 5 are 0.5, hence 597.5/600=0.9958333. The rule was chosen after observing the data.

## C30: measured

On the lone dependency-event trace, every LoRA omitted E6 in all five samples, whereas the base and final context policy detected both events, demonstrating a regression hidden by the aggregate score.

**Evidence:** LE k0-base, k4-context, k1/k2/k3/k4-weights; V.

**Check and justification:** On the unique truth set with E6, the verifier checks five exact base and final-context reports. Every LoRA report equals E5 alone. Thus aggregate improvement conceals worse dependency coverage on that one example.

## C31: inference

This shortcut is observationally sufficient to reproduce the headers, not proof of the model's internal computation; five reports on one trace also provide only one dependency example, so the intended crossover claim is withdrawn.

**Evidence:** C28-C30; L interpretation.

**Check and justification:** Matching observable headers cannot identify internal computation. Five samples are repeats of the same trace. Missing outcomes and the sole dependency case preclude the intended broad crossover conclusion.

## C32: measured

At 15 accepted edits, weights followed 90.4% of rules on valid stories versus 74.2% for context, but the corresponding validity-adjusted scores were 77.0% and 70.0%, showing why the two metrics must remain distinct.

**Evidence:** W curve x=15; V writing_curve.

**Check and justification:** Stored valid-story rule means are 0.9044343 and 0.7423047; U*S means are 0.7701823 and 0.6997768. The audit recomputes both denominators from records. 15 is accepted edits, not 15 review opportunities.

## C33: measured

Table 1 reports the full observed curve: budgets 15 to 60 count accepted edits, later budgets count review opportunities, and the number of usable supervised targets differs from the nominal budget.

**Evidence:** WP early checkpoints; WT; V writing_curve; T01.

**Check and justification:** Rows are 15,30,60,116,226,338,451 and match training manifests. Protocol distinguishes early accepted targets from later review opportunities. No unobserved points or interpolated crossover are shown.

## T01: measured

Writing pilot $U S$ scores (percent) and weights-minus-context gaps (percentage points); the unadapted base scores 57.1%. Endpoint weights average three seeds; other rows use one. These are separate evolving live pools, with early offline checkpoints.

**Evidence:** V writing_curve; W base; WT; WP.

**Check and justification:** Every numeric table cell is generated by verify_evidence.py after per-sample and manifest checks. Base mean=0.5713355655. Context and weights use separate arm pools; early offline checkpoints use immutable first-round snapshots of those separate pools. Seeds=3 only at 480. Rounding can make the displayed gap differ from subtracting rounded displayed means.

## C34: measured

At 480 opportunities, weights scored 84.9% versus 86.1% for context, a $-1.2$ point gap with interval $[-4.0,1.5]$; the interval includes zero, and the 30-edit comparison was also inconclusive.

**Evidence:** V writing_curve budgets=30,480.

**Check and justification:** 480 means round to 84.9 and 86.1, with gap -1.2 [-4.0,1.5]. The 30-edit gap is -0.8836 pp, interval [-5.5200,3.5435]; both include zero. Inconclusive does not establish equality.

## C35: measured

At this endpoint, conditional style compliance was 95.8% versus 89.1%, but validity was 88.5% versus 96.6%; across the live weights evaluations, short stories and missing required words occurred among invalid outputs.

**Evidence:** W curve x=480; W diagnostics; V.

**Check and justification:** Endpoint valid-only style=0.9584384 vs 0.8909800, U=0.8854167 vs 0.9661458. Diagnostics contain short-story and missing-anchor failures in weights sets. Categories can overlap, and the paper makes no causal explanation of those failures.

## C36: inference

The endpoint shows no reliable live-workflow advantage for weights, and pointwise early gains do not establish a lasting crossover.

**Evidence:** C25; C34-C35.

**Check and justification:** The primary live U*S interval includes zero despite higher conditional style. Early pointwise intervals and an inconclusive endpoint cannot certify a sustained simultaneous crossover.

## C37: measured

A separate control used the same Inkling editor with guides A and B, which oppose three rules, and trained three seeds per guide on edits of the same 460 base drafts: held-out weights scored 91.8% versus 78.2% for context using A's archive, a $+13.7$ point difference $[11.4,16.0]$.

**Evidence:** WT lora-A/lora-B/self checkpoints; W shared_archive; V controls.shared_weights_vs_context; WI.

**Check and justification:** All three seeds in each control have 460 rows; integrity reports matched control originals. Per-prompt scores reproduce 91.8186% and 78.1622%, gap 13.6564 pp [11.3777,16.0497]. These are a separate endpoint control, not the seven-budget shared curve proposed next. A and B are style guides given to the same Inkling editor, not different editor models.

## C38: measured

On the three opposed rules, the A-adapter's A-style advantage over the B-adapter was $+80.3$ $[78.3,82.3]$ points, and the reversed B-style comparison was $+83.1$ $[80.8,85.4]$, with invalid submissions still assigned zero.

**Evidence:** WS RULES entries 5:8; WA prompt_means flipped; V controls A_specificity and B_specificity.

**Check and justification:** The scorer selects the last three opposed rules, averages applicable flags, then multiplies by U. Recomputed A and B differences and intervals round as written. The first five rules are not all opposites, so the draft limits specificity to three opposed rules.

## C39: measured

Edited-target training exceeded unedited-target training by $+33.5$ $[31.8,35.2]$ points on guide A, supporting learning from these edits rather than an explanation based solely on additional training on the original drafts.

**Evidence:** V controls.edited_vs_self; WT; WI.

**Check and justification:** Guide-A U*S gap is 0.3348989 [0.3176921,0.3517795]. Matched original drafts and edited targets support that edits carry useful information in this archive; this does not isolate every feature of training or prove general human preference learning.

## C40: scope

These controls concern planted, mechanically scored preferences and raw-example context; they do not establish literary quality, superiority over a learned playbook, or a review-count threshold on a shared archive.

**Evidence:** WP private planted rules and difference 4; WR limitations; C37-C39.

**Check and justification:** Only raw-example context and mechanical rules were evaluated. No playbook or blind prose evaluation appears in completed results. Shared archive has an endpoint, not a budget curve, so no shared-archive threshold follows.

## C41: measured

Selecting the best of four valid unique drafts by the fraction of original tokens surviving the edit improved hidden-rule compliance by $+3.6$ $[2.8,4.4]$ points over uniform choice, compared with $+10.3$ $[9.8,10.9]$ for an oracle selector.

**Evidence:** V selection; SE; WA selection_probabilities and best_of_n.

**Check and justification:** Independent combinatorial subset weighting reproduces gains 0.0356937 [0.0278815,0.0437853] and 0.1034670 [0.0980060,0.1090564]. Eligible drafts are valid and deduplicated; reference is uniform on the same pools.

## C42: measured

Each of 96 prompts began with 16 base-policy samples, filtered for validity and deduplicated before averaging four-candidate subsets and uniform ties; scores concern original drafts, token survival ignores pure insertions, and the pilot performed selection rather than reward-based training.

**Evidence:** WP Best-of-n and Kept; WA best_of_n; SE.

**Check and justification:** 96 eligible prompt pools, exact without-replacement subset averaging, uniform ties and original draft S are implemented. A pure insertion does not remove original tokens, so survival can remain unchanged. Completed protocol explicitly excludes policy-gradient RL. Protocol starts with 16 samples per prompt; 1536 total samples across 96 prompts is recorded.

## C43: design

Following the v3 proposal, the primary experiment will freeze reviews of the no-feedback policy and evaluate budgets of 15, 30, 60, 120, 240, 360, and 480, reserving each arm's own four-round live loop for a secondary comparison.

**Evidence:** P Pools.

**Check and justification:** All budget values and primary shared no-feedback pool are in v3. Four rounds of 120 sessions remain secondary. This is future tense, not a claim that revised pools already exist.

## C44: design

We plan six arms: no feedback; BM25 review retrieval capped at 8,000 tokens; a delta-updated playbook capped at 2,000 tokens; cumulative corrected-target SFT; playbook-conditioned self-distillation; and SFT plus the playbook.

**Evidence:** P Arms.

**Check and justification:** All six arms and budgets are specified in the proposal. BM25 and playbook were not the writing pilot's retrieval implementation. The paper introduces no measured result for these arms.

## C45: design

The playbook author will see only reviews and will never receive the writing scorer's secret rules; the distillation arm will use the playbook-conditioned policy as teacher and the unconditioned policy as student on training-pool prompts.

**Evidence:** P playbook and distill.

**Check and justification:** v3 forbids secret rules to the playbook author and uses a playbook-conditioned teacher without playbook for student, on pool prompts. This is a design constraint requiring implementation checks before running.

## C46: design

The primary contrast will be SFT minus playbook; cumulative SFT restarts from base at each budget, making it a joint-training reference rather than a sequential continual learner or a guaranteed performance upper bound.

**Evidence:** P Primary gap and SFT arm; C19.

**Check and justification:** SFT minus playbook is the proposed contrast. Retraining from base on accumulated data is a joint-training reference by definition. Calling it an upper bound in v3 overstates what is guaranteed; this draft explicitly corrects that label.

## C47: design

Planned controls include step-matched SFT at every budget and sequential LoRA, self-target, and shuffled-target SFT at 480; these distinguish optimization exposure, ongoing updates, and informative corrections.

**Evidence:** P Controls.

**Check and justification:** Controls are specified, not performed by this revised design. Step matching targets optimization exposure, sequential updates target retention across updates, and self/shuffled targets test informational content. Outcomes remain unknown.

## C48: design

The planned Qwen3-8B recipe uses non-thinking generation, temperature 0.7, top-p 0.8, top-k 20, unique session seeds, and prompts within 32,768 tokens; these are protocol choices rather than claims about currently available provider defaults.

**Evidence:** P Policy.

**Check and justification:** Settings are directly inherited protocol choices. No live model-availability, API defaults, model pricing or provider-support claim is asserted, so historical evidence-ledger availability statements need not be trusted.

## C49: design

Training will use rank 16, batch 16, at least three epochs and 30 steps, three seeds, and a learning rate selected on development data from $\{1.5,4.7,7.0\}\times10^{-4}$, with corrected-turn loss and downloaded adapters.

**Evidence:** P Recipe.

**Check and justification:** All numbers and constraints match v3. At least 3 epochs and 30 steps implies satisfying both minima. Three seeds and learning-rate selection on dev are commitments, not documented results of the revised protocol.

## C50: design

Before freezing Lean evaluation, development gates require base proof success between 20% and 70%, an exit-code baseline at most 0.85, tool errors at most 2%, and reviewer exactness at least 95%; these thresholds are proposed acceptance rules.

**Evidence:** P Exp 1 Gates.

**Check and justification:** Numerical gates match v3 and are explicitly author-chosen acceptance thresholds. No claim that they have passed. Score definition, sample denominators and uncertainty must be fixed in executable protocol before execution.

## C51: design

The design calls for at least 60 sealed dependency groups, approximately 20% deliberately unprovable lemmas, and a separately reported compiler-checked challenge set with 20 positives and 20 negatives per rare event, preserving the natural test distribution.

**Evidence:** P Exp 1 Gates; L Corrections and next experiment.

**Check and justification:** 60 groups, 20% unprovable and 20 positive/negative examples per rare event come from the proposal. Keeping challenge cases separate from natural distribution follows the audit recommendation. These are target sample requirements, not achieved counts.

## C52: design

Lean's revised primary outcome will be exact report-header match over five samples per frozen trace, with report-turn-only adapters; whole-episode proof success will separately test spillover, and explanations will not be counted as verified by a header score.

**Evidence:** P Exp 1 Score and Adapter; LS score.

**Check and justification:** v3 changes primary metric to exact header match and gates adapter to report turn. Whole-episode proof success is spillover. Header matching cannot establish prose quality; this is a stated measurement boundary.

## C53: design

Writing gates require each secret rule to be passed by at most 70% of base development stories, editor recall at least 0.9 per rule, and at most 20% of changed words in clean sentences; targets failing public format checks will be excluded.

**Evidence:** P Exp 2 Editor A and Row.

**Check and justification:** All thresholds and invalid-target filtering match v3. Which rules, recall annotation procedure and clean-sentence denominator need executable preflight specification; the sentence does not assert completed calibration.

## C54: design

A frozen reviewer from another model family and a 30-case human check are planned, while writing will retain both conditional style and $U S$, plus a validity safeguard of no more than three percentage points below the base policy.

**Evidence:** P Reviewer; P Exp 2 Scores; draft clarification.

**Check and justification:** Frozen cross-family reviewer, 30 human cases and 3 pp validity guard are v3 choices. Explicit retention of U*S alongside conditional S is a draft clarification motivated by C35, not a hidden change to pilot results.

## C55: design

The planned primary endpoint is the 480-review SFT-minus-playbook contrast; paired bootstrap analysis will cluster by writing prompt or Lean dependency group, retaining repeated samples within their cluster and reporting training-seed variation separately.

**Evidence:** P Stats; M recommendations 2-4.

**Check and justification:** v3 gives one primary endpoint and clustered paired bootstrap. The draft explicitly chooses the writing prompt and Lean dependency group and separates seed variation; this is prospective analysis, not a statement about the pilots' intervals covering all uncertainty.

## C56: design

A crossover will mean the earliest measured budget whose simultaneous lower confidence band remains above zero through 480, subject to the writing validity safeguard; if no budget qualifies, no crossover will be reported within the tested range.

**Evidence:** P Stats and Scores; draft clarification.

**Check and justification:** Operationalizes x0 on measured checkpoints through the endpoint and adds the writing safeguard. No interpolation or never-ever conclusion is allowed. The exact simultaneous-band procedure must be frozen under C57 before use.

## C57: scope

Development-only power simulations, a frozen implementation of the simultaneous band, reviewer gates, and new sealed test pools must precede execution; the completed pilots do not supply power or calibration evidence for this revised comparison.

**Evidence:** P Stats and gates; LR methods revision; current branch scope.

**Check and justification:** No revised power simulation, implementation of simultaneous bands, or sealed v3 dataset is supplied in this branch. The draft lists these as prerequisites, not verified deliverables or pending paid runs started here.

## C58: design

We plan retention measurements on public-task validity, an IFEval subset, and KL divergence from the base model, while editor-specificity controls and the optional token-survival reward experiment remain distinct from the primary comparison.

**Evidence:** P Forgetting; P Editor B; P Kept as a reward.

**Check and justification:** All are proposed diagnostics/secondary analyses. The manuscript does not claim IFEval or KL was measured or that the pilot trained with the Kept reward. Any optional RL experiment needs a frozen protocol before execution.

## C59: inference

These pilots motivate auditing outcome coverage and validity denominators: Lean's aggregate score concealed missing event types, while writing style gains coexisted with public-constraint failures.

**Evidence:** C28-C36.

**Check and justification:** Direct synthesis of observed missing event coverage and writing validity loss. It does not infer an unobserved causal mechanism or make a population-general effectiveness claim.

## C60: scope

Neither pilot contains a completed human editor smoke test or a general retention evaluation, and the writing study lacks blind prose-quality assessment; consequently, claims about human preference, general competence, and long-term personalization remain outside this evidence.

**Evidence:** LR pending human smoke test; WR incomplete evaluations; LT human_smoke_test; W.

**Check and justification:** The saved Lean analysis reports zero human-reviewed cases. Writing README reports incomplete human smoke test and blind prose-quality evaluation. No general retention metrics are in either completed result record. These facts restrict claims, not prove an absence of all competence.

## C61: inference

The shared-archive writing result motivates a stronger contextual comparator; failed Lean calibration warrants withholding a crossover claim until coverage and reviewer gates pass.

**Evidence:** C28-C40; P Arms and Gates.

**Check and justification:** Motivation for a future comparison and for withholding claims. Shared-archive effect is positive for raw-example context, but playbook performance is unknown. Lean coverage failure directly motivates gating.

## C62: inference

Corrections changed mechanically scored writing behavior, but the budget at which weights reliably beat a learned playbook without unacceptable validity loss remains unknown.

**Evidence:** C37-C40; C43-C60.

**Check and justification:** Positive specificity and edited-versus-self controls support behavior change on the archive. There are no learned-playbook or guarded shared-curve outcomes. Hence the main threshold question remains open.
