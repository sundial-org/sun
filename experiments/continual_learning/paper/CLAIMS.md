# Claim-by-claim justification

Every substantive assertion in the paper and appended submission notes has a stable ID. Measured claims are checked against saved responses and independently recomputed summaries; method claims are checked against the frozen code and manifests; literature claims are checked in primary sources. Inferences and limitations are identified separately. Hashes detect changes to reviewed text; they do not prove a claim true. No human quality review is implied.

## C01: study question and design

We study whether a writer can learn a hidden writing rubric from editorial revisions through context or weight adaptation. An inferred playbook and corrected-target LoRA receive a shared archive of synthetic reviews, and Qwen3-8B is evaluated on fresh tool-based writing assignments.

**Evidence:** evidence/frozen-code/run.py: main, compile_playbook, train; evidence/prompts.json; evidence/reviews.jsonl.gz

**Check and justification:** The shared archive supplies the same public-valid review pairs to both learned recipes. SFT additionally conditions on actual trajectory prefixes, as stated explicitly in the methods. The question concerns the eight operational rubric checks, not a general natural-writing rubric.

## C02: measured primary result

At 480 review opportunities, averaging three method seeds, SFT achieves 89.1% validity-adjusted rubric compliance versus 71.7% for the inferred playbook, a 17.4-point difference with paired 95% interval $[15.4,19.5]$.

**Evidence:** evidence/analysis.json: methods.sft-480, methods.playbook-480, primary.US.prompt; evidence/verification.json

**Check and justification:** The endpoint score means are .8912863756613758 and .7169518849206349. Their paired prompt difference is .17433449074074076 with interval [.15352130869708996,.19473379629629628]. Three method seeds and two samples per prompt are averaged inside each prompt cluster.

## C03: measured outcome and scope

Mean valid submission is 96.2%, within three points of the 97.9% unadapted base, although one training seed falls below that safeguard. Only 46.1% of SFT episodes produce a valid submission satisfying every applicable rule.

**Evidence:** evidence/analysis.json: methods.sft-480, evaluations.test-base and seed evaluations; evidence/verification.json

**Check and justification:** SFT validity is831/864 (96.1806%) versus282/288 (97.9167%) for base, a1.7361-point loss. Seed31 has270/288 valid (93.75%), below the base-minus-three-point criterion. All-rule success is398/864=.46064814814814814.

## C04: bounded interpretation

These results establish substantial rubric adaptation for the tested recipes, while separating rule compliance from public-task validity and leaving prose quality unmeasured.

**Evidence:** evidence/analysis.json: primary; evidence/frozen-code/vendor/style.py: score; evidence/frozen-code/vendor/data.py: format_check

**Check and justification:** A positive primary interval supports the within-setting score contrast. The public checker and private rule scorer do not assess plot adherence, coherence, or human preference. This sentence deliberately claims only the tested recipes and their operational rubric.

## F01: design diagram and caption

The two learned adaptation routes share public-valid review pairs. Private rubric labels are withheld from both learners; SFT also conditions on original trajectory prefixes. Each budget starts with a fresh playbook or adapter, and evaluation uses fresh assignments.

**Evidence:** evidence/frozen-code/run.py; evidence/reviews.jsonl.gz; evidence/prompts.json; render_workflow.py; evidence/workflow.pdf

**Check and justification:** The diagram describes the primary comparison: 14, 55 and 460 usable public-valid pairs from 15, 60 and 480 opportunities; context through inferred instructions, weights through corrected-turn LoRA; SFT-only trajectory prefixes; 144 fresh prompts with two samples per policy and three method seeds. Private rubric labels are absent from both learners. The final vector graphic and its caption are inspected together.

**Reviewed artifact hashes:** {"evidence/workflow.pdf": "3a8a4f3eaef75028936fc9be099a4f463800982d5c64f14f6f99ba717b582174", "evidence/workflow.png": "7dc51c02a81ca9c877c782989722c3144ca0bf64b7510a2efc1451bd045fb11e", "render_workflow.py": "d3e77d32553b05a2414f15c9b0e9e22e6d19931f2b9cc8890409e4240bc11da2"}

## C10: research question

We study a writer that must learn an eight-rule writing rubric from editorial revisions while satisfying public assignment constraints. The question is whether to retain what the edits teach in context or in model weights.

**Evidence:** ../PROTOCOL.md: Cycle 1

**Check and justification:** The fixed task has eight private Guide A rule checks and public length, required-word and submission constraints. This states the question without claiming a result.

## C11: design rationale

When adaptation methods collect their own reviews, their comparison mixes differences in the learner with differences in the available examples. A shared review archive lets us compare the two recipes on the same corrections.

**Evidence:** ../PROTOCOL.md: common archive and scope amendments

**Check and justification:** Holding the archive fixed eliminates variation in which before/after pairs are available. It does not equalize computation, prefixes, or the transformations that the learners apply to that archive.

## C12: implementation

We compare an inferred instruction playbook with corrected-target supervised fine-tuning (SFT), using a common synthetic archive and fresh assignments. SFT also sees trajectory prefixes, so the comparison shares review pairs without equalizing conditioning information or computation.

**Evidence:** evidence/frozen-code/run.py: archive_rows, good, make_new_prompts, main; evidence/reviews.jsonl.gz; evidence/prompts.json

**Check and justification:** The playbook compiler and corrected-turn SFT receive the same public-valid pairs from a prefix of the no-feedback archive. Only SFT includes the actual original assistant trajectory prefix, checked against each source row. The claim explicitly bounds the comparison to recipes.

## C13: outcome definitions

We distinguish compliance with the private rubric, valid submission under public constraints, and performance on a separate instruction-following probe.

**Evidence:** evidence/frozen-code/vendor/data.py: format_check; evidence/frozen-code/vendor/style.py: score; evidence/frozen-code/followups.py: retention

**Check and justification:** These are three distinct recorded outcomes: planted-rule scores, public-valid submission, and strict public instruction checks. The statement does not equate any of them with prose quality.

## C18: measured contribution and bounded interpretation

Our central finding is a 17.4-point endpoint advantage for SFT in validity-adjusted rubric compliance. Lower-budget validity failures and training-seed variation qualify that gain, making task completion a separate part of the comparison rather than an assumed consequence of learning the rubric.

**Evidence:** evidence/analysis.json: primary and contrasts; evidence/evaluations.jsonl.gz

**Check and justification:** The endpoint SFT-minus-playbook gap is .17433449074074076, rounded to 17.4 percentage points. The 15- and 60-opportunity adapters fail the descriptive mean validity threshold, while the endpoint passes on average with one seed below threshold. Reporting task validity separately is a design and interpretation choice supported by these observed differences.

## C20: primary-source literature and design comparison

Inferring preferences from edits and retrieving them later, as in CIPHER [cipher], lets corrections influence future contexts without fine-tuning. Our fixed-archive comparison adds weight adaptation and measures public-format failures.

**Evidence:** https://arxiv.org/html/2404.15269v3: Sections2,3,4.2; ../PROTOCOL.md

**Check and justification:** CIPHER's Algorithm 1 retrieves and aggregates inferred preferences. Section 4.2 explicitly freezes the base model in all compared methods. Our fixed-archive weight comparison changes that assumption, without reproducing CIPHER.

## C21: primary-source literature and design comparison

Maintained playbooks provide another contextual representation: Agentic Context Engineering incrementally updates itemized instructions [ace]. We adopt delta updates, without reproducing its full reflection and curation pipeline.

**Evidence:** https://arxiv.org/html/2510.04618v3: Section3; evidence/frozen-code/run.py: compile_playbook

**Check and justification:** ACE's incremental playbook updates motivate local deltas. Our compiler lacks ACE's full Generator/Reflector/Curator roles and counters. The paper explicitly limits the connection to inspiration.

## C22: primary-source literature and motivation

Comparisons of contextual demonstrations and fine-tuning find that their relative performance depends on data scale and task [bertsch], motivating measurements at several budgets rather than a universal crossover claim.

**Evidence:** https://arxiv.org/html/2405.00200v2: fine-tuning and retrieval comparisons; ../PROTOCOL.md: three-budget scope

**Check and justification:** The source compares contextual demonstrations, retrieval, and fine-tuning with differing outcomes by setting. We borrow the budget-specific comparison structure; no source performance number or universal threshold is asserted.

## C23: primary-source literature and motivation

LoRA supplies low-rank weight updates [lora]; OPPU combines personal adapters with nonparametric context [oppu]. These support testing a weight-only recipe and its combination with a playbook.

**Evidence:** https://arxiv.org/abs/2106.09685; https://arxiv.org/abs/2402.04401v3

**Check and justification:** LoRA supplies the low-rank update mechanism. OPPU's abstract explicitly combines personal PEFT parameters with retrieval/profile information. These establish the methodological motivation, not an expected performance ordering here.

## C24: primary-source literature and evaluation motivation

Mechanically checkable instructions in IFEval [ifeval] provide a separate spillover probe. Work on language-model evaluation motivates paired comparisons and attention to clustered questions [miller].

**Evidence:** https://arxiv.org/abs/2311.07911; https://arxiv.org/abs/2411.00640

**Check and justification:** IFEval uses verifiable instructions. Miller discusses paired differences and dependence among evaluation questions. The actual bootstrap and its limits are separately specified; no coverage theorem is attributed to these sources for our design.

## C32: public task definition

The writer uses JSON file operations, a format check, and submission actions to produce a 120--350-word story containing two required words; at most eight assistant tool turns are allowed.

**Evidence:** evidence/frozen-code/vendor/data.py: SYSTEM and format_check; evidence/frozen-code/vendor/run_experiment.py: writer and apply_actions

**Check and justification:** The interface restricts paths and tools, checks inclusive120-to350 whitespace words plus both whole-word anchors, and permits at most8 assistant turns. Successful submission requires a check on the current story hash.

## C33: measurement boundary

The public checker verifies word count and anchors, and submission requires a successful check of the current story; it does not judge plot adherence, coherence, literary quality, or the private rubric.

**Evidence:** evidence/frozen-code/vendor/data.py: format_check; evidence/frozen-code/vendor/run_experiment.py: apply_actions

**Check and justification:** Inspection of the full public checker finds only word-count and anchor tests. Submission checks the current-story hash. There is no plot, coherence, genre, literary-quality, or private-style test in public feedback.

## C34: private rubric definition

Eight private checks ban "suddenly", "very", semicolons, and em dashes; require at least 90% present finite narration verbs, an opening of at most 12 words, say-only detected dialogue tags, and restricted capitalization, using fixed regex and spaCy rules.

**Evidence:** evidence/frozen-code/vendor/style.py: RULES['A'] and score; evidence/environment.json

**Check and justification:** The eight entries prohibit suddenly, very, semicolons, and U+2014; require at least 90% present finite verbs outside quotes, opener at most 12 words, say-only detected dialogue tags, and no disallowed capitalization. Regex plus the pinned spaCy tagger implement these proxies.

## C35: outcome definition

Let $U$ indicate a valid submitted story and $S$ be the fraction of applicable private rules passed; the primary score is $Y=US$, assigning invalid or unsubmitted episodes zero and omitting the dialogue-tag rule when no qualifying tags occur.

**Evidence:** evidence/frozen-code/vendor/style.py: score; evidence/frozen-code/analyze.py: measures; verify_evidence.py: outcomes

**Check and justification:** S averages non-null rule booleans. The tag rule alone can be null when there are no detected tags. U is submitted AND public-format-pass. Independent arithmetic reconstructs US using exact rational rule fractions, so every invalid episode contributes zero.

## C36: secondary outcome definition and failed calibration

We also report $S$ conditional on validity, all-rule success $U\mathbf{1}[S=1]$, and the harder-rule score $U(r_{\mathrm{tense}}+r_{\mathrm{opening}}+r_{\mathrm{capitalization}})/3$, because several rubric rules have high baseline pass rates.

**Evidence:** ../PROTOCOL.md: rubric amendment; evidence/frozen-code/analyze.py: measures and summarize; evidence/evaluations.jsonl.gz: dev-base

**Check and justification:** The frozen analysis defines all-rule success as public validity and all non-null rules passed, equivalent to U times the indicator that S=1. Conditional S includes only valid submissions. The harder-rule score averages tense, opener and capitalization flags and multiplies by U. Several base rubric rules already have high pass rates, so these secondary metrics expose limits of the composite score.

## C30: data provenance and counts

We reuse 480 earlier no-feedback Qwen3-8B review opportunities, of which 460 contain both a publicly valid writer submission and a publicly valid Inkling revision; budgets of 15, 60, and 480 opportunities yield 14, 55, and 460 usable pairs.

**Evidence:** evidence/reviews.jsonl.gz; evidence/local-check.json; evidence/payload-provenance.json

**Check and justification:** Count all 480 sorted opportunities, then retain U and editor_valid. Prefix counts are 14/15, 55/60, 460/480. The provenance audit matches synthetic assignments, writer receipts, and editor receipts. Budget counts include unusable opportunities.

## C55: archive construction and inclusion criteria

The archived editor configuration supplies all eight private rules and requests minimal revisions. It asks for sentence replacements preserving meaning and required words; semantic preservation is not checked. Pair selection requires a valid draft and an archived revision recorded as successfully applied and publicly valid, without filtering for rubric-score improvement.

**Evidence:** evidence/frozen-code/vendor/run_experiment.py: Experiment.edit and collect; evidence/frozen-code/run.py: good and archive_rows; evidence/reviews.jsonl.gz; evidence/editor-receipt-audit.json

**Check and justification:** The editor system prompt includes RULES[A] and requests minimal sentence replacements preserving plot, meaning and required words. This is an instruction, not a verified semantic-preservation result. Two editing passes apply sentence references and then check public format; editor_valid records successful application and format. The new good() filter requires writer U and editor_valid only, without any style-improvement threshold. Private editor audit labels remain excluded from learner inputs. An additional offline attempt exactly matched 873 of 913 reconstructed call hashes and 444 of 460 final edit records. It did not reproduce 16 edit records under current segmentation, so this claim describes the archived configuration, not a complete reconstruction of archive creation. The original saved revisions are shared unchanged across learners. One investigated call differs only in surrounding sentence whitespace; the remaining discrepancy causes are unresolved.

## C31: data provenance and implementation

The archive contains existing synthetic reviews, not human edits; the two primary learned arms use the same usable pairs at each budget.

**Evidence:** evidence/reviews.jsonl.gz; evidence/training-targets.jsonl.gz; evidence/compiler-inputs.jsonl.gz; ../research_log.md

**Check and justification:** The input archive predates this run and contains machine-generated stories and revisions. Newly saved compiler/training/evaluation artifacts establish the new work. Exact ID and input-pair checks establish common data availability, not equal computation.

## C41: baseline implementation

The no-feedback policy is unadapted Qwen3-8B; raw context uses BM25-ranked assignment matches and their before/after stories, greedily packed within 8,000 tokens.

**Evidence:** evidence/frozen-code/run.py: Study.__init__ and context

**Check and justification:** The base sampling client uses Qwen/Qwen3-8B. Context ranks assignment token matches with BM25 k1=1.5,b=.75, packs canonical before/after pairs with a conservative token margin, and checks the final context is at most 8000 tokens. Highest-ranked pairs appear last.

## C42: compiler implementation

The playbook compiler is Inkling with temperature 0.3 and effort 0.6; it sees public assignments and before/after stories in batches of at most 15 valid pairs, proposing evidence-linked additions, replacements, or deletions to numbered instructions.

**Evidence:** evidence/frozen-code/run.py: compile_playbook and sample; evidence/compiler-inputs.jsonl.gz; evidence/playbooks.json

**Check and justification:** Compiler requests use Inkling, tml_v0 effort 0.6, temperature 0.3, and at most4000 output tokens. Inputs contain public assignments and before/after pairs in batches 15. Accepted deltas carry review evidence and mutate numbered rules locally.

## C43: compiler safeguards and documented amendment

Each budget and construction seed starts with an empty playbook; local code applies the deltas and enforces a 2,000-Qwen-token cap, with at most two validation-only repairs for malformed updates; the compiler never receives private rules, scores, or editor audit labels.

**Evidence:** evidence/frozen-code/run.py: compile_playbook; evidence/frozen-code/compiler_validation.py; evidence/frozen-code/protocol-amendments.md; evidence/amendment-1.json; evidence/compiler-inputs.jsonl.gz

**Check and justification:** Each budget/seed begins with an empty rule map, apart from exact completed-cache reuse. The accepted text is capped at 2000 Qwen tokens. The bounded repair amendment followed two absent-ID failures and preceded any learned-policy test. Repairs expose only schema/reference/cap errors. Exact compiler payload checks exclude rule labels, scores, and editor audits.

## C44: supervision implementation

SFT replaces the final story-modifying action with the edited story and replays the trajectory; loss covers that assistant turn only, under its actual generation prefix, averaging over supervised tokens per example.

**Evidence:** evidence/frozen-code/run.py: export_corrected and train; evidence/frozen-code/vendor/run_experiment.py: edited_trajectory; evidence/mask-check.json; evidence/training-targets.jsonl.gz

**Check and justification:** The final modifying assistant action is replaced with the target, and replay regenerates tool messages. Export stops at that assistant turn. Original preceding messages are checked for exact equality. The renderer masks the prefix, gives positive completion weights summing to one, and supervises one assistant turn.

## C45: training recipe

Adapters have rank 16 on attention, MLP, and output layers, minibatches of at most 16 examples, and at least three epochs and 30 optimizer steps; the development-selected learning rate is $4.7\times10^{-4}$ for all three review budgets.

**Evidence:** evidence/frozen-code/run.py: train; evidence/training.json; evidence/freeze-v1.json

**Check and justification:** Training manifests record rank 16, nominal minibatch limit 16 (partial batches are retained), attention/MLP/unembedding updates, and LR 0.00047 for confirmatory runs. The schedule uses max(3,ceil(30/ceil(N/16))) epochs. Complete step logs must match each manifest; small budgets therefore receive more epochs.

## F02: data figure and caption

Validity-adjusted rubric score and public validity across review budgets. Large markers show means; faint points show the three method seeds, not confidence bounds. The validity axis begins at 80%. Budgets are categorical checkpoints and connecting lines only guide the eye.

**Evidence:** evidence/analysis.json; evidence/budget-visual-data.json; render_results.py; evidence/budget-comparison.pdf

**Check and justification:** Both panels plot all three tested budgets from saved evaluation summaries. Learned-method means average three equally sized seed policies; raw retrieval has one policy. Faint points display seed variability, not statistical intervals. The right panel starts at 80 percent, explicitly disclosed. The horizontal coordinates are categorical, so connecting lines do not estimate a continuous learning curve. Final plotted values are checked against the analysis and the rendered graphic.

**Reviewed artifact hashes:** {"evidence/budget-comparison.pdf": "2bfb24568ffe99c0abdf46895f029ba27c27e667a05304c4fa284b8226cc152b", "evidence/budget-comparison.png": "9b194e6f8fdf130c6d6d22e8d5eba2cf23fa9a6cfcfb878334122c8e158e94ae", "evidence/budget-visual-data.json": "2c1cbe1cdaed59329ef4d9553f5034f6aa4d1af0224882b6a87018dc9a5a4c06", "render_results.py": "b2736770497824cff2619d20fa1bd1caf645e6839272c6296f347040d9ab653f"}

## C37: assignment counts

Development uses 24 new assignments, while the sealed test set contains 144 assignments from 24 distinct places, with six assignments per place and equal numbers in familiar genres and fable/gothic.

**Evidence:** evidence/prompts.json; evidence/design.json; verify_evidence.py: prompt checks

**Check and justification:** Count 24 dev and 144 test prompts; test has24 places with 6 prompts each and 72 familiar versus72 unseen-genre prompts. The unseen category contains fable and gothic. Location and genre are not separately randomized causal factors.

## C38: split and sampling implementation

The generator separates development and test places, goals, and complications, rejects repeated anchor pairs and cross-split eight-word premise overlaps with the earlier prompts, and uses two stochastic samples per assignment.

**Evidence:** evidence/frozen-code/run.py: make_new_prompts and evaluate; evidence/old-prompts.json; evidence/prompts.json; verify_evidence.py: n-gram and pairing checks

**Check and justification:** Development/test places, goal lists, and complication lists are disjoint. The generator and independent checker reject cross-split premise8-grams and repeated anchor pairs, including the600 old prompts. Evaluation uses exactly 2 matched seeds per new assignment. Templates and some role classes remain shared, so this is not broad semantic decontamination.

## C15: measured development result

On 48 development episodes, the most valid adapter submitted 45 valid stories versus 47 for the base; none of three learning rates passed the declared base-minus-three-percentage-point validity safeguard.

**Evidence:** evidence/freeze-v1.json: candidates, base_U, guardrail_pass; evidence/evaluations.jsonl.gz: five dev evaluations

**Check and justification:** The candidate valid counts are 34, 45, 22 of 48 for learning rates 0.00015, 0.00047, 0.0007. Base has 47/48 valid. Even 45/48 falls 4.1667 percentage points below base, exceeding the 3-point allowance. These observations do not imply the chosen candidate satisfies the validity safeguard.

## C16: selection procedure

The prespecified fallback selected the highest-validity candidate, fixing its learning rate before test evaluation while retaining the failed safeguard.

**Evidence:** evidence/frozen-code/run.py: freeze_development_local; evidence/freeze-v1.json: selection and time; evidence/amendment-1.json

**Check and justification:** With no eligible candidate, the frozen fallback maximizes validity, then US, then favors smaller learning rate. It selects 0.00047. The subsequent compiler-reference amendment did not change selection or test settings.

## C17: scope limitation

Each review budget initializes a fresh adapter from the base model; this evaluates cumulative adaptation, not sequential updates.

**Evidence:** evidence/frozen-code/run.py: train and main; ../PROTOCOL.md: scope amendments

**Check and justification:** Every named budget/seed adapter is created with create_lora_training_client(base_model=WRITER), not from the preceding budget's adapter. This measures cumulative fresh-base adaptation, not sequential updates or forgetting prevention.

## C46: seed and decoding configuration

We use training and compiler seeds 31, 73, and 127; generation uses the non-thinking renderer, temperature 0.7, top-p 0.8, top-k 20, and matched sampling seeds across arms.

**Evidence:** evidence/frozen-code/run.py: SEEDS, Study.__init__, sample, evaluate; evidence/training.json; evidence/evaluations.jsonl.gz

**Check and justification:** Method seeds are 31, 73, 127. Writer sampling uses qwen3_disable_thinking, temperature 0.7, top_p 0.8, top_k 20. Assignment/sample seeds are deterministic and matched across arms; turn index increments within each episode. Repair/compiler seeds are separate from writer seeds.

## C53: documented implementation amendment

Schema-only compiler repairs were added after base and 15-review retrieval evaluation, before learned-policy test responses or confirmatory training; the audit preserves this amendment.

**Evidence:** evidence/amendment-1.json; evidence/freeze-v1.json; evidence/frozen-code/protocol-amendments.md; ../research_log.md

**Check and justification:** The first run ended after base and raw15 completed. The amendment manifest and local precondition checks record zero learned-policy test episodes and zero confirmatory training starts. Repairs changed schema handling only, and existing successful books were reused.

## C47: prespecified estimand and scope

The primary contrast is mean SFT minus playbook at 480 opportunities; other budgets and contrasts are exploratory, and these three checkpoints do not locate a precise review-count crossover.

**Evidence:** ../PROTOCOL.md: Confirmatory evaluation; evidence/frozen-code/analyze.py: main

**Check and justification:** The endpoint is480 opportunities and the direction is SFT minus playbook. Three sparse budgets cannot identify an unmeasured crossing point or establish a persistent threshold across intermediate budgets. Other comparisons are exploratory.

## C48: statistical procedure

We average samples and method seeds within each assignment, then use 10,000 paired prompt-cluster bootstrap draws within familiar and fable/gothic strata for a percentile 95% interval, with a place-cluster sensitivity interval accounting for shared locations.

**Evidence:** evidence/frozen-code/analyze.py: paired; verify_evidence.py: independent_interval

**Check and justification:** Rows are averaged within prompt or place before paired resampling. Strata are familiar/unseen;10000 draws sample each stratum with replacement and preserve its weight. The2.5th/97.5th percentiles define intervals. Independent reconstruction checks both units and all reported paired metrics.

## C49: inference limitation

Intervals condition on the three method seeds, archive, and premise generator. We also report seed variation and flag mean validity more than three points below the base; this descriptive safeguard is not a noninferiority test.

**Evidence:** ../PROTOCOL.md: inference and safeguard; evidence/frozen-code/analyze.py: paired and summarize

**Check and justification:** The bootstrap resamples prompts/places, not training seeds or review corpora. Thus it cannot quantify population variance across arbitrary training seeds or archives. The3-point safeguard compares point estimates without a prespecified noninferiority test. The test reference for the safeguard is the unadapted base, not the playbook.

## C50: control implementation

Follow-up controls combine SFT with its corresponding playbook, train on unedited drafts, shuffle edited targets while remapping required anchors, and supply the explicit planted rules to an unadapted privileged reference.

**Evidence:** evidence/frozen-code/followups.py: controls; evidence/shuffle-maps.json; evidence/training.json

**Check and justification:** The code pairs each adapter with its own playbook, substitutes original drafts for self-target training, and uses a seeded donor derangement with anchor remapping for shuffled targets. All share the endpoint schedule. Explicit rules are supplied only to the separately labeled privileged reference. These controls do not themselves score plot adherence.

## C54: exploratory control design

After observing the verbatim-rule reference, we fixed one compact, imperative rendering that prioritizes difficult requirements and omits detector detail. This additional privileged control probes instruction presentation on the reused test set; it is exploratory and does not measure learned rubric inference.

**Evidence:** evidence/compact-rubric-plan.json; evidence/exploratory-code/COMPACT_RUBRIC.md; evidence/exploratory-code/compact_rubric.py

**Check and justification:** The plan was frozen at 2026-09-29T02:51:56.296212Z after the verbatim reference result, before any compact-reference responses. It permits one version only. The rendering changes ordering, imperative wording, and level of detector detail, so it is not a pure length-only ablation and cannot assess preference inference from edits. The same test set is reused.

## C51: independent probe implementation

A separate probe uses 128 public IFEval examples selected by a fixed hash of example IDs before responses, with one response per example/policy and a 4,096-token cap; we report official strict prompt-level and instruction-level accuracy for the base, endpoint adapters, and active playbooks.

**Evidence:** evidence/retention-plan.json; evidence/frozen-code/followups.py: prepare_retention and retention; evidence/retention.jsonl.gz; ../vendor/instruction_following_eval/SOURCE.json

**Check and justification:** The plan selects 128 public IDs by a fixed SHA256 order before responses and fixes generic system prompt, decoding, and 4096 output-token cap. The official pinned strict checker scores base, 3 endpoint adapters, and 3 active playbooks, one response per example/policy.

## C56: instruction-probe uncertainty procedure

For prompt-accuracy contrasts, we average the three method seeds within each IFEval example before contrasting with the base, then form percentile 95% intervals from 10,000 paired example-bootstrap draws.

**Evidence:** evidence/frozen-code/analyze.py: main retention analysis; verify_evidence.py: retention interval recomputation; evidence/verification.json

**Check and justification:** The retention analysis groups the three seed-specific binary strict-prompt outcomes by example ID, subtracts the single base outcome from the within-example mean, and resamples all 128 paired example differences with replacement for 10000 draws using seed 260928. The 2.5th and 97.5th percentiles form the interval. No writing-genre strata are used for this separate public benchmark. Independent recomputation matched both intervals.

## C52: interpretation and scope limitation

Either adaptation can be disabled to restore the base policy. The public instruction subset measures active-policy spillover, with possible pretraining contamination and conflicts between the active playbook and benchmark instructions.

**Evidence:** evidence/frozen-code/run.py: independent base and adapter clients; evidence/frozen-code/followups.py: retention; evidence/retention-plan.json

**Check and justification:** Adapters leave pretrained parameters unchanged and are optional at sampling time; books are optional system context. The probe tests the active adapted policies. Its public128-item subset cannot establish general retention, and writing instructions can conflict with arbitrary IFEval requests.

## C60: measured result and bounded interpretation

At 480 review opportunities, SFT scores 89.1% versus 71.7% for the playbook and 52.0% for the unadapted base (Table 1). The primary difference is $+17.4$ percentage points, with paired prompt interval $[15.4,19.5]$ and place-cluster interval $[15.2,19.6]$.

**Evidence:** evidence/analysis.json: primary, methods and evaluations; evidence/evaluations.jsonl.gz: completed test episodes

**Check and justification:** The frozen analysis gives SFT .8912863756613758 and playbook .7169518849206349. The paired mean gap is .17433449074074076; prompt interval [.15352130869708996,.19473379629629628], place interval [.15207454943783066,.19574652777777773]. Percentages and points are rounded to one decimal. The unadapted base US is .5200892857142857, rounded to52.0%.

## C61: measured result and bounded interpretation

Mean validity is 96.2% for SFT, 94.6% for the playbook, and 97.9% for the base. SFT passes the descriptive three-point safeguard; its validity difference from the playbook is $+1.6$ points, interval $[-0.5,3.7]$, which does not establish a validity advantage.

**Evidence:** evidence/analysis.json: primary, methods and evaluations; evidence/evaluations.jsonl.gz: completed test episodes

**Check and justification:** Validity is831/864 SFT,817/864 book,282/288 base. SFT is1.7361 points below base, passing the descriptive3-point threshold. Its paired difference from book is.016203703703703703, interval[-.004629629629629629,.037037037037037035], including zero. Passing this point-estimate safeguard is not a noninferiority finding.

## C62: measured result and bounded interpretation

Endpoint SFT seeds score 86.3, 89.4, and 91.7%, with 270, 279, and 282 valid submissions out of 288. Thus the mean safeguard passes despite one seed falling below it; the prompt interval does not remove this training-seed variation.

**Evidence:** evidence/analysis.json: primary, methods and evaluations; evidence/evaluations.jsonl.gz: completed test episodes

**Check and justification:** Seeds31,73,127 have US .8626612103174602,.8937872023809523,.9174107142857143 and270,279,282 valid episodes. Seed31 validity93.75% is below base97.9167%-3%. The bootstrap averages the three seeds inside each prompt rather than resampling a seed population.

## C63: measured result and bounded interpretation

The harder-rule score is 79.4% versus 54.2%, and all-rule success is 46.1% versus 5.6%. The advantage therefore extends beyond the easy banned-word checks, but fewer than half of SFT episodes produce a valid submission satisfying every applicable rule.

**Evidence:** evidence/analysis.json: primary, methods and evaluations; evidence/evaluations.jsonl.gz: completed test episodes

**Check and justification:** Frozen hard3 means are .7935956790123456 and .5416666666666666; all-rule success .46064814814814814 and .05555555555555555. Both zero invalid episodes. Improvement on hard3 supports a gain beyond easy lexical prohibitions, while .46065<.5 directly bounds mastery.

## C64: measured result and bounded interpretation

Among valid stories, SFT passes the short-opening check in 51.4% versus 17.1% for the playbook; the playbook instead leads on capitalization, 100.0% versus 96.8%. Rubric learning remains uneven across rules.

**Evidence:** evidence/analysis.json: primary, methods and evaluations; evidence/evaluations.jsonl.gz: completed test episodes

**Check and justification:** Conditional rule pass rates use831 valid SFT and817 valid book episodes. Opening rates are .5138387484957883/.17135862913096694, capitalization .9675090252707581/1.0. The sentence does not infer unconditional superiority from conditional rates.

## C65: measured result and bounded interpretation

At 15 and 60 opportunities, the exploratory SFT-minus-playbook gaps are 18.5 and 18.6 points, but SFT validity is only 94.2% and 92.6%, failing the safeguard at both budgets (Figure 2). The observed score advantage starts at the smallest tested budget; these measurements do not locate a threshold for reliable adaptation.

**Evidence:** evidence/analysis.json: primary, methods and evaluations; evidence/evaluations.jsonl.gz: completed test episodes

**Check and justification:** 15/60 US gaps are .1848131613756614/.18619791666666666; SFT valid counts814/864 and800/864, both below base-.03. The first observed positive gap at15 is not evidence for the behavior of unmeasured budgets or a monotonic crossover.

## C66: measured result and bounded interpretation

The three endpoint playbooks occupy only 63--147 tokens despite a 2,000-token allowance. None explicitly states the 12-word opener limit. This incomplete inferred rubric motivates checking the explicit-rule reference, rather than treating the learned book as the best possible contextual policy.

**Evidence:** evidence/playbooks.json: n480-s31, n480-s73, n480-s127; evidence/frozen-code/run.py: compile_playbook

**Check and justification:** Final token counts are84,147,63. Read all three final playbooks: they mention present tense, lowercase names, and anchors, with various concise-prose/dialogue/premise instructions, but none gives the twelve-word opener limit. The inference is about this compiler output, not a universal context limitation.

## C68: measured exploratory result and bounded interpretation

Training on unedited drafts scores 52.9%, versus 89.1% for corrected targets, a difference of $-36.3$ points, interval $[-38.0,-34.5]$. Extra training on drafts therefore does not reproduce the rubric gain; the content of the corrections matters for this recipe.

**Evidence:** evidence/analysis.json: followups.self; evidence/evaluations.jsonl.gz: self and endpoint SFT policies; evidence/training.json

**Check and justification:** Unedited-target US is .5287491732804233, versus .8912863756613758 for corrected targets. The paired difference is -.36253720238095233, interval [-.37991898148148145,-.3449487433862434]. Both conditions use the same 460 selected source rows, rank, learning rate, three epochs and 87-step schedule, but target content and resulting token counts differ. This supports the importance of corrected targets for this recipe, not an isolated semantic mechanism or a general claim about all self-training.

## C69: measured exploratory result and bounded interpretation

Shuffled targets score 80.1%, $9.0$ points below SFT, interval $[-11.9,-6.3]$. Yet conditional compliance (94.6%) and all-rule success (52.4%) exceed SFT's 92.7% and 46.1%, while validity falls to 84.7%. These mixed outcomes reinforce the distinction between compliance and completion; none establishes that stories fit their assignments.

**Evidence:** evidence/analysis.json: followups.shuffled; evidence/evaluations.jsonl.gz: shuffled and endpoint SFT policies; evidence/shuffle-maps.json

**Check and justification:** Shuffled US is .8014012896825398, U is 732/864 = .8472222222222222, conditional S is .9459162763466042, and all-rule success is 453/864 = .5243055555555556. The US difference from SFT is -.08988508597883597 with interval [-.11861462466931218,-.06262349123677248]. SFT conditional S is .926680419460203 and all-rule success is .46064814814814814. Conditional comparisons select different valid subsets; the claim is descriptive and does not infer a causal style advantage. Neither private rubric checks nor public validity checks evaluate premise adherence.

## C67: measured exploratory result and bounded interpretation

Combining each adapter with its corresponding playbook scores 88.1%, a $-1.0$-point difference from SFT alone, interval $[-2.6,0.6]$. Validity falls from 96.2% to 93.9%, difference $-2.3$ points, interval $[-4.1,-0.6]$, although all-rule success rises to 53.8%. Thus this exploratory combination trades better all-rule success for lower public validity without a demonstrated primary-score advantage.

**Evidence:** evidence/analysis.json: followups.combined; evidence/evaluations.jsonl.gz: combined and endpoint SFT policies

**Check and justification:** Combined US is .8811383928571429 and U is 811/864 = .9386574074074074. The paired US difference is -.0101479828042328, percentile interval [-.02643435846560846,.005994233630952382]. Validity difference is -.023148148148148147, interval [-.04050925925925926,-.0057870370370370385]. These were independently calculated from all 864 saved combined episodes and the paired SFT episodes. The score interval includes zero; the validity interval is negative. These exploratory intervals are not adjusted for multiple comparisons. Combined all-rule success is 465/864 = .5381944444444444, versus 398/864 = .46064814814814814 for SFT. This is a descriptive secondary-metric increase, not an adjusted hypothesis test.

## C70: measured exploratory presentation result and scope

Supplying the verbatim rubric yields 62.4% $US$, with none of 274 valid stories passing the tense check. The compact reference raises $US$ to 73.2% and valid-story tense compliance to 73.1%, but validity falls from 95.1% to 85.1%; 36 of 43 invalid stories are too short. This single exploratory prompt change alters wording, order, and detector detail together. It illustrates presentation sensitivity without establishing an optimal context policy or learning from edits.

**Evidence:** evidence/analysis.json: test-explicit-rules and test-compact-rubric; evidence/evaluations.jsonl.gz; evidence/compact-rubric-plan.json; evidence/exploratory-code/COMPACT_RUBRIC.md

**Check and justification:** Verbatim US is .6236359126984127 and U is 274/288; zero of those 274 valid stories pass the tense check. Compact US is .7323288690476191 and U is 245/288; tense pass is 179/245 = .7306122448979592. Its 43 invalid episodes include 36 below the 120-word minimum. Invalid-feature counts overlap and are not exclusive causal assignments. This was one fixed exploratory rendering, designed after observing the verbatim result, with reused test prompts and matched seeds. It changes several prompt properties together, is privileged rather than inferred, and supplies no optimized contextual upper bound.

## C71: measured exploratory instruction-probe result and scope

On the unrelated IFEval subset (Table 2), strict prompt accuracy is 83.3% for active SFT, 79.2% for the active playbook, and 82.8% for the base. Paired differences from the base are $+0.5$ points, interval $[-3.6,4.7]$, and $-3.6$ points, interval $[-8.1,0.8]$, respectively. Both intervals include zero. This small public probe supplies neither a noninferiority result nor evidence of erased capabilities; the observations concern the active policies.

**Evidence:** evidence/analysis.json: retention; evidence/retention.jsonl.gz; evidence/rescore-retention.json; evidence/retention-plan.json

**Check and justification:** Strict prompt counts are base 106/128, SFT 320/384, and active playbook 304/384. Averaging the three seed responses within each example and bootstrapping 128 paired examples for 10000 draws gives SFT-minus-base .005208333333333328 with interval [-.036458333333333336,.046875], and playbook-minus-base -.036458333333333336 with interval [-.08072916666666667,.0078124999999999905]. Both include zero. No noninferiority margin or power guarantee is inferred, and public benchmark performance with an active policy does not establish knowledge erasure. Official strict checks were independently rerun for all 896 responses.

## T01: endpoint data table and caption

Endpoint scores (percent). Playbook, SFT, and SFT-control rows pool three seeds; other rows use one policy. Each policy has 288 episodes. $S\mid U$ conditions on validity; all-rule success requires validity. The last two rows supply privileged rubric instructions, with the compact rendering added as an exploratory follow-up.

**Evidence:** evidence/analysis.json; evidence/visual-data.json; evidence/endpoint-table.tex; render_results.py

**Check and justification:** The nine endpoint rows are generated from the full saved summaries, rounded to one decimal percentage point. Playbook, SFT and SFT-control rows pool three seed policies of 288 episodes each; base, retrieval and the two privileged rubric references each use 288 episodes. US and U include all episodes; S conditional on U pools only valid episodes; all-rule success requires validity. The privileged references are separated and the compact version is explicitly exploratory. Every table cell is checked against its unrounded source value.

**Reviewed artifact hashes:** {"evidence/endpoint-table.tex": "0b1c2fe1dbe169f99c9c711a1326b96f560e2f467c74b4c207bfc7985ba629ba", "evidence/visual-data.json": "69d7439f7f9c1ce4bbb63221130d0dde5533e285eca164ffb4f63699f020c5d0", "render_results.py": "b2736770497824cff2619d20fa1bd1caf645e6839272c6296f347040d9ab653f"}

## T02: instruction-probe data table and caption

Active-policy instruction probe (percent). Every policy answers the same 128 IFEval prompts, containing 206 instruction checks, once. Adapter and playbook rows pool three seeds. Strict prompt accuracy requires all instructions in a prompt; instruction accuracy pools individual checks.

**Evidence:** evidence/analysis.json: retention; evidence/retention.jsonl.gz; evidence/retention-table.tex; evidence/retention-visual-data.json; evidence/rescore-retention.json

**Check and justification:** Each of seven policies answers exactly the same 128 frozen public prompts once, giving 896 responses. The base row has one policy; endpoint SFT and active-playbook rows each pool three seed policies. Official strict prompt accuracy averages all-instructions-pass indicators, while instruction accuracy pools the individual constraint booleans. Values are rounded to one decimal percentage point and checked against unrounded summaries and the full official rescore. The selected examples contain 206 individual instructions per policy, or 618 for each pooled three-seed row.

**Reviewed artifact hashes:** {"evidence/retention-table.tex": "7212011e51fb4fb2da5e23c7a6d9a0a0bb2fd113f286a4eed06be7977b2939a7", "evidence/retention-visual-data.json": "8ee4acd3b5f6450b34993b9754a18b63e326a9870f306ca69ee32378aa2762dc", "render_results.py": "b2736770497824cff2619d20fa1bd1caf645e6839272c6296f347040d9ab653f"}

## C80: measurement limitation

This comparison concerns learning a fixed, planted writing rubric from synthetic revisions. The public checker establishes a valid submission, and the private scorer establishes compliance with its proxies; neither establishes that a story follows its plot, is coherent, or is preferable to a human reader. The shuffled-target control is especially limited by that missing semantic endpoint.

**Evidence:** evidence/frozen-code/vendor/data.py: format_check; evidence/frozen-code/vendor/style.py: score; evidence/frozen-code/followups.py: controls

**Check and justification:** The endpoint checks only public word/anchor/submission constraints and planted stylistic proxies. There is no semantic plot checker or human preference annotation. Shuffling targets therefore challenges pairing while leaving unmeasured whether a generated story actually fits its assigned plot.

## C81: implementation and identification limitation

The recipes are not compute-matched: the 15-, 60-, and 480-opportunity adapters receive 30, eight, and three epochs, respectively, corresponding to 30, 32, and 87 steps. Together with the SFT-only trajectory prefixes and development selection at one budget and seed, this prevents attributing every difference solely to where information is stored.

**Evidence:** evidence/training.json; evidence/frozen-code/run.py: train, export_corrected; evidence/freeze-v1.json

**Check and justification:** The schedule is max(3, ceil(30/ceil(N/16))) epochs with N equal to 14, 55, or 460. This gives 30/8/3 epochs and 30/32/87 optimizer steps. SFT additionally conditions on the original trajectory prefix. Learning-rate selection used only seed 31 at 60 opportunities. Hence the recipe contrast is not an isolated causal manipulation of storage representation.

## C82: generalization limitation

The shared archive removes variation in which review pairs are available, but leaves only one editor, writer model, planted rule set, and review corpus. Three method seeds and paired evaluation strengthen this within-setting comparison without supplying evidence about human personalization, other model families, or naturally evolving preferences.

**Evidence:** evidence/reviews.jsonl.gz; evidence/freeze.json; evidence/frozen-code/run.py: WRITER, EDITOR, SEEDS; evidence/frozen-code/vendor/style.py

**Check and justification:** The actual design has one Qwen3-8B writer, one Inkling editor, one guide A rule set, and one synthetic archive. Three method seeds repeat construction/training within that setting, not across models, human reviewers, or changing preferences.

## C83: future research and scope boundary

A subsequent study could independently test semantic adherence, compare optimization exposure, and update adapters sequentially under changing preferences. Those are distinct experiments: the present cumulative adapters and active-policy instruction probe do not demonstrate a continual learner or prevention of catastrophic forgetting.

**Evidence:** ../PROTOCOL.md; evidence/frozen-code/run.py: train, main; evidence/frozen-code/followups.py: retention

**Check and justification:** The proposed studies are future work and assert no unobserved result. Current adapters each start from the base; no optimization state is carried across budgets. IFEval measures the active policy on public instructions and cannot by itself demonstrate sequential adaptation or prevention of forgetting.

## R01: bibliographic metadata

G. Gao et al. [Aligning LLM Agents by Learning Latent Preference from User Edits](https://arxiv.org/abs/2404.15269v3). arXiv:2404.15269v3, 2024.

**Evidence:** https://arxiv.org/abs/2404.15269v3

**Check and justification:** Author attribution, title, version identifier and year are checked against the linked primary paper. Venue is included only where the checked version identifies it; arXiv entries are labeled as such. The shortened et al. author list is intentional.

## R02: bibliographic metadata

Q. Zhang et al. [Agentic Context Engineering: Evolving Contexts for Self-Improving Language Models](https://arxiv.org/abs/2510.04618v3). ICLR, 2026.

**Evidence:** https://arxiv.org/abs/2510.04618v3

**Check and justification:** Author attribution, title, version identifier and year are checked against the linked primary paper. Venue is included only where the checked version identifies it; arXiv entries are labeled as such. The shortened et al. author list is intentional.

## R03: bibliographic metadata

A. Bertsch et al. [In-Context Learning with Long-Context Models: An In-Depth Exploration](https://arxiv.org/abs/2405.00200v2). NAACL, 2025.

**Evidence:** https://arxiv.org/abs/2405.00200v2

**Check and justification:** Author attribution, title, version identifier and year are checked against the linked primary paper. Venue is included only where the checked version identifies it; arXiv entries are labeled as such. The shortened et al. author list is intentional.

## R04: bibliographic metadata

E. J. Hu et al. [LoRA: Low-Rank Adaptation of Large Language Models](https://arxiv.org/abs/2106.09685v2). arXiv:2106.09685v2, 2021.

**Evidence:** https://arxiv.org/abs/2106.09685v2

**Check and justification:** Author attribution, title, version identifier and year are checked against the linked primary paper. Venue is included only where the checked version identifies it; arXiv entries are labeled as such. The shortened et al. author list is intentional.

## R05: bibliographic metadata

Z. Tan et al. [Democratizing Large Language Models via Personalized Parameter-Efficient Fine-tuning](https://arxiv.org/abs/2402.04401v3). EMNLP, 2024.

**Evidence:** https://arxiv.org/abs/2402.04401v3

**Check and justification:** Author attribution, title, version identifier and year are checked against the linked primary paper. Venue is included only where the checked version identifies it; arXiv entries are labeled as such. The shortened et al. author list is intentional.

## R06: bibliographic metadata

J. Zhou et al. [Instruction-Following Evaluation for Large Language Models](https://arxiv.org/abs/2311.07911v1). arXiv:2311.07911v1, 2023.

**Evidence:** https://arxiv.org/abs/2311.07911v1

**Check and justification:** Author attribution, title, version identifier and year are checked against the linked primary paper. Venue is included only where the checked version identifies it; arXiv entries are labeled as such. The shortened et al. author list is intentional.

## R07: bibliographic metadata

E. Miller. [Adding Error Bars to Evals: A Statistical Approach to Language Model Evaluations](https://arxiv.org/abs/2411.00640v1). arXiv:2411.00640v1, 2024.

**Evidence:** https://arxiv.org/abs/2411.00640v1

**Check and justification:** Author attribution, title, version identifier and year are checked against the linked primary paper. Venue is included only where the checked version identifies it; arXiv entries are labeled as such. The shortened et al. author list is intentional.

## N01: model-paper choice and scoped comparison

Amanda Bertsch et al., In-Context Learning with Long-Context Models: An In-Depth Exploration,
[arXiv:2405.00200v2](https://arxiv.org/html/2405.00200v2) (2025).
We adapt its empirical comparison of contextual demonstrations and fine-tuning
over data budgets, retaining setup, comparative results, diagnostic analysis,
and a bounded conclusion. Our narrower question concerns editor corrections,
an inferred playbook, and validity in a tool-based writing task.

**Evidence:** https://arxiv.org/html/2405.00200v2; paper.tex: Introduction, Method, Experiments

**Check and justification:** The cited paper compares in-context demonstrations and fine-tuning across data sizes. These notes explicitly describe an adaptation of its empirical structure, not reproduction of its tasks or findings. Our paper concerns synthetic editor corrections and tool-based writing.

## N02: outline description

Abstract and introduction: establish the feedback-storage question,
the common-review design, and the distinction between private rubric compliance
and public task validity. State the measured result with its scope.

**Evidence:** paper.tex: Abstract and Introduction

**Check and justification:** The stated question, shared archive, two representations, and distinction between rubric score and public validity appear in the corresponding sections. The abstract gives the measured endpoint and its scope.

## N03: outline and editorial choice

Related work: place inferred preferences, maintained playbooks,
low-rank adaptation, and combined representations in one compact comparison.
Move this discussion before the experimental design so readers understand why
the learned playbook is the primary comparator. The broader literature map is
kept outside the half-length paper.

**Evidence:** paper.tex: Related work; ../RELATED_WORK.md

**Check and justification:** The compact related-work section covers CIPHER, ACE, LoRA and OPPU before Method and Experiments. The broader literature map remains outside the paper. Its position is an editorial decision, not an empirical claim.

## N04: outline and figure description

Method: describe the writing task, private rubric, shared reviews,
and context and weight adaptation. A workflow diagram shows the common archive
branching into a playbook and a LoRA adapter, then evaluation on fresh assignments.

**Evidence:** paper.tex: Method; evidence/workflow.pdf

**Check and justification:** The method covers the task, rubric, common reviews, inferred instructions and adapters. The diagram branches from the same review pairs into context and weights and ends at fresh evaluation.

## N05: outline and editorial rationale

Experiments: describe fresh assignment splits, development
selection, explanatory controls, and paired inference. Expand validity and scope relative
to the model paper because the composite endpoint needs explicit denominators.

**Evidence:** paper.tex: Experiments; https://arxiv.org/html/2405.00200v2

**Check and justification:** The experimental section specifies splits, development selection, controls and paired uncertainty. The composite endpoint and validity requirements motivate additional denominator explanations; this is an editorial rationale.

## N06: results and visualization description

Results: present all three review budgets and the prespecified
endpoint contrast. The central visual compares validity-adjusted rubric scores
and valid submission across budgets; showing both makes the tradeoff visible.
A compact endpoint table places explanatory controls beside the learned methods.
Text reports intervals and seed variation. A second table summarizes the separate
instruction probe.

**Evidence:** paper.tex: Results; evidence/budget-comparison.pdf; evidence/endpoint-table.tex; evidence/retention-table.tex

**Check and justification:** The final results show the three budgets, primary contrast, uncertainty and seed variation. The figure has separate panels for US and validity. The table contains all endpoint controls; the prose includes the public instruction probe. A second table reports strict prompt and instruction accuracy on the independent public probe.

## N07: diagnostic scope

Results, diagnostic comparisons: use unedited and shuffled targets, a combined
adapter/playbook policy, and an explicit-rule privileged reference to challenge
the interpretation. These are exploratory follow-ups on the same test set,
not independent confirmations of a selected mechanism.

**Evidence:** paper.tex: Experiments and Results; evidence/frozen-code/followups.py; evidence/compact-rubric-plan.json

**Check and justification:** The listed controls were actually run. They reuse the test prompts and are explanatory or exploratory comparisons, not fresh confirmatory tests of a mechanism selected from their results.

## N08: discussion scope and editorial choice

Discussion: bound the conclusion by the synthetic review archive,
planted scorer, single model, three method seeds, and absence of human prose
ratings. Distinguish cumulative fresh-base adaptation from sequential learning.
Omit the model paper's attention and ordering studies because this experiment
does not measure those mechanisms; omit broad multi-model and multi-dataset
figures because our evidence is intentionally narrower.

**Evidence:** paper.tex: Discussion; https://arxiv.org/html/2405.00200v2

**Check and justification:** The discussion identifies the single synthetic setting, three seeds, absence of human quality ratings and fresh-base training. Attention, ordering and broad multi-model investigations are outside this study; no findings about those mechanisms are borrowed.

## N09: artifact organization

References and audit: cite the primary research sources in the
paper. Keep the detailed evidence, source locators, frozen implementation,
response transcripts, and claim-by-claim justifications in the companion files.

**Evidence:** paper.tex: References; CLAIMS.md; evidence/package.json

**Check and justification:** The bibliography contains the cited primary sources. The separate evidence package and claim ledger contain records and checks, rather than adding them to the word-limited manuscript.

## N10: revision history and scope

The starting proposal at commit db853b1 covered writing and Lean.
The study narrows the empirical question to learning a writing rubric, implements a
learned-playbook comparator, holds review availability fixed, selects
hyperparameters on development prompts, and separates the primary comparison
from diagnostic controls. A workflow diagram makes the two adaptation routes
explicit, and the results figure separates rubric scores from public validity.
The failed development validity safeguard remains explicit. The original
per-rule calibration goal was not met; harder-rule and all-rule outcomes
therefore supplement the composite score.
Lean transfer and optimizer-continuous learning are outside this draft's claims.
No instructor or classmate feedback was supplied, so none is represented as addressed.

**Evidence:** git commit db853b1323dd009cbcc190ff23329c3233390be6; ../research_log.md; ../PROTOCOL.md; paper.tex

**Check and justification:** The repository proposal covered writing and Lean. The recorded research cycle narrows to writing, implements the planned shared archive and inferred playbook, freezes development selection, and separates the endpoint from diagnostics. The paper retains the failed development safeguard. No instructor or classmate feedback was provided in this task, and no response to such feedback is claimed. The original proposal required each rubric rule to pass at most 70% of base stories; the protocol records that several rules exceed this calibration goal and adds harder-rule/all-rule reporting before testing.

## N11: delivery specification and status

The user's half-length requirement overrides the ordinary full-paper length.
The measured body-word and page counts appear in evidence/build-check.json.
This combined PDF appends the model-paper analysis, outline, and revision notes
to the draft, following the
[CS197 draft-paper requirements](https://web.stanford.edu/class/cs197/assignments/project.html\#draft-paper).
The separate CLAIMS.md audit distinguishes measurements, implementation
facts, literature, inferences, and scope limits. The files are prepared for review;
they have not been uploaded to Overleaf or submitted to a class or venue.

**Evidence:** https://web.stanford.edu/class/cs197/assignments/project.html#draft-paper; build.py; evidence/build-check.json; CLAIMS.md

**Check and justification:** The user explicitly requested half length and a separate justification file. Build checks enforce 2000–2500 manuscript words and append one notes page. The notes supply a model-paper analysis, adapted outline and revisions. The task produced local review artifacts; no class, venue or Overleaf upload was performed.
