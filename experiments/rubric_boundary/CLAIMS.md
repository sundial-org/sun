# Claim justifications

These are evidence explanations, not merely artifact hashes. Intervals are conditional on the observed training seeds.

## M1

The experiment compares clean corrections with two archives that are each 80% correct: scattered mistakes and a consistent west-region blind spot. Every mistake ignores the recall override on one order.

Check all nine correction pools against both exact oracles. Noisy pools each have 80 incorrect whole examples out of 400; the other orders retain their correct decisions.

Sources: `runs/20260929-policy-v2/pools/`, `task.py`, `test_task.py`

## M2

Nine Qwen3-8B LoRA adapters use 400 shared training inputs, three epochs, and three seeds per correction condition. Evaluation uses 250 held-out three-order tasks. Frozen and trained models receive the same complete rules, checklist, and four retrieved examples.

The frozen protocol, training manifests, complete 75-step logs, saved supervised examples, and evaluation receipts establish these settings. Retrieval was selected on 50 development tasks from 0, 4, 8, and 16 example alternatives.

Sources: `PROTOCOL.md`, `runs/20260929-policy-v2/freeze.json`, `runs/20260929-policy-v2/training/`, `runs/20260929-policy-v2/selection.json`

## M4

All 95% intervals resample test tasks within region while holding the three training seeds fixed. They do not estimate uncertainty over new training runs.

The primary and reasoning analyses average the three seeds within each task before the stratified bootstrap. The paired region control resamples its 50 west-origin pairs. Per-seed values are retained to expose between-run variation.

Sources: `analyze.py`, `controls.py: analyze`, `results.json: comparisons[].seeds`

## R1

| Clean (100% correct) | 22.0% | 62.5% | +40.5 [34.1, 46.7] |

Completely correct output, averaged over method seeds within each task. Paired 10,000-draw task bootstrap stratified by focus region; intervals condition on the three seeds. All raw responses were rescored.

Sources: `results.json: comparisons[clean, retrieval].metrics.exact`, `analyze.py`

## R2

| Scattered errors (80% correct) | 21.9% | 54.9% | +33.1 [27.1, 38.8] |

Completely correct output, averaged over method seeds within each task. Paired 10,000-draw task bootstrap stratified by focus region; intervals condition on the three seeds. All raw responses were rescored.

Sources: `results.json: comparisons[scattered, retrieval].metrics.exact`, `analyze.py`

## R3

| Regional blind spot (80% correct) | 20.8% | 48.1% | +27.3 [21.5, 33.1] |

Completely correct output, averaged over method seeds within each task. Paired 10,000-draw task bootstrap stratified by focus region; intervals condition on the three seeds. All raw responses were rescored.

Sources: `results.json: comparisons[systematic, retrieval].metrics.exact`, `analyze.py`

## R4

The difference between the training gains under scattered and systematic errors is +5.7 [0.7, 10.9] percentage points. The prespecified practical-reversal criterion was not met.

Difference-in-differences is paired by task. The reversal rule requires one gain interval entirely above +3 points and the other entirely below -3 points. A source difference without opposite signs is not a strategy reversal.

Sources: `results.json: noise_interaction, practical_reversal`, `PROTOCOL.md`

## R5

The decision-only measure ignores output ordering while retaining exact IDs, allocations, and routes; the primary measure additionally requires the requested order.

The scorer independently compares the per-ID dictionaries and the ordered output. Table values are the decisions_exact fields of the same verified responses.

Sources: `task.py: score`, `results.json: comparisons[].metrics.decisions_exact`

## R8

The example-context effects compare the same models with four retrieved examples versus the complete policy/checklist alone, in percentage points of complete-task success.

The diagnostic was included in the frozen protocol. Effects are paired within the same 250 tasks; both sides retain the full correct policy. These are additional contrasts rather than the primary noise-interaction test.

Sources: `results.json: context_example_effects`, `analyze.py`

## R9

The regional-error adapters correctly handle 1 of 150 west recall evaluations (0.7%), versus 80.0% for the frozen model. Of the failures, 143 are valid complete responses with the wrong recall decision and 6 are invalid responses. These are the same 50 tasks evaluated across three adapters, not 150 independent tasks.

Sum the west-region diagnostic counts across the three systematic adapters. The correct action is HOLD with zero units. Separating valid rule violations from malformed output shows that the collapse is not simply a JSON-format effect. This subgroup outcome was specified before test collection.

Sources: `runs/20260929-policy-v2/diagnostics.json`, `results.json: systematic regions`

## M3

The following controls were specified after the frozen baseline was observed and before any trained test result was inspected. They do not replace the primary endpoint.

The original control freeze is dated 19:28:08 UTC, before the first trained model completed at 19:28:24 UTC. An operational amendment increased concurrency before collecting any control responses; it changed no scientific settings.

Sources: `runs/20260929-policy-v2/control-original/control-freeze.json`, `runs/20260929-policy-v2/control-freeze.json`, `runs/20260929-policy-v2/main.log`

## R6

The reasoning control gives both policies a 4,096-token output allowance and uses the same 50 tasks and retrieved examples within each paired comparison.

CONTROL_PROTOCOL and control-freeze precede trained test inspection. The separately cached Qwen3 thinking receipts and control analysis establish settings, exact success, and intervals.

Sources: `CONTROL_PROTOCOL.md`, `runs/20260929-policy-v2/control-freeze.json`, `runs/20260929-policy-v2/control-analysis.json: reasoning`

## R10

With clean corrections on those same 50 tasks, the training gain is +39.3 [24.0, 54.0] points in non-thinking mode and -23.3 [-32.7, -14.7] points with reasoning enabled. Mean output length in reasoning mode is 1649 tokens for the frozen model and 574 for the trained models. This secondary comparison identifies a mode-dependent reversal, not an equal-cost threshold.

Use only the common 50-task subset for both mode-specific differences. The independently scored reasoning control stores the corresponding non-thinking difference. Output length counts every sampled token, including reasoning. The same maximum allowance is not the same realized token consumption.

Sources: `runs/20260929-policy-v2/control-analysis.json: reasoning.clean`, `runs/20260929-policy-v2/control-visual-data.json`

## R11

A post hoc wrapper check changes trained reasoning-mode success to clean: 74.7%, scattered: 56.7%, systematic: 50.0%. It removes only a whole code fence or a lone unclosed `<think>` tag followed entirely by JSON. The clean result is unchanged: among its 38 failures across three runs, 29 have correct decisions in the wrong order, 6 have invalid outputs, and 3 have valid outputs with wrong decisions.

diagnostics.py scores both the untouched final response and a strictly delimited wrapper-normalized response. It never searches prose for a favorable JSON object. The clean error partition is disjoint and asserted to sum to all evaluated outputs. This robustness analysis was added after inspecting control responses and is not a replacement endpoint.

Sources: `diagnostics.py`, `runs/20260929-policy-v2/diagnostics.json`

## R7

The region control changes only the recalled order’s region; its correct answer stays identical. It uses the complete policy and checklist without retrieved examples.

control-inputs stores all 50 pairs; both oracle implementations assert unchanged gold answers. Raw originals are reused from the main checklist condition and counterfactual responses are independently rescored.

Sources: `controls.py`, `runs/20260929-policy-v2/control-inputs.json`, `runs/20260929-policy-v2/control-analysis.json: counterfactual`

## R12

For the regional-error adapters, north-region recall success varies sharply by run (seed 31: 98.0%, seed 73: 0.0%, seed 127: 98.0%). Seed 73 produces 50 malformed responses; its zero score cannot be interpreted as 50 valid wrong recall decisions. The other two adapters recover correct recall handling on 49 of 50 pairs each.

Read the per-region diagnostic partition for the three region-sft-systematic control groups. Every original west checklist recall score is zero. The per-seed numbers qualify the average and its task-only interval; format failure prevents a clean semantic interpretation for seed 73.

Sources: `runs/20260929-policy-v2/diagnostics.json`, `runs/20260929-policy-v2/controls/region-sft-systematic-73.json`

## I1

The primary test did not find opposite preferred strategies for the two equally accurate correction sources. It did find improved overall execution alongside a learned regional rule failure. The secondary reasoning control challenges the premise that this task needs weight updates: the frozen model already reaches 98% with clean examples on its 50 tasks.

The two primary noisy-source gain intervals are positive. R9 verifies valid recalled-order action errors in the systematic subgroup. R6 verifies the frozen clean reasoning baseline; its smaller test set and different mode are stated explicitly. This interpretation is restricted to the observed model, task, and recipe.

Sources: `results.json`, `runs/20260929-policy-v2/control-analysis.json`, `runs/20260929-policy-v2/diagnostics.json`

## L1

This study tests one synthetic task family, one fixed policy, one model, one training-data size, and one nonzero error rate. It does not locate a general data threshold, test generated rubrics, or establish cross-domain transfer.

The complete protocol grid has no other task family, dynamic policy, data-size condition, or error-rate condition.

Sources: `PROTOCOL.md`, `INTERPRETATION_LIMITS.md`

## L2

The noisy archives match accuracy and corruption operation, but not the distribution of incorrect route labels. Consequently, any difference cannot be attributed solely to error predictability.

For seed 31, the scattered corrupted targets contain 40 EXPRESS and 40 STANDARD decisions; systematic corrupted targets contain 80 STANDARD decisions. West-region shipping explains this difference.

Sources: `INTERPRETATION_LIMITS.md`, `runs/20260929-policy-v2/pools/scattered-31.json`, `runs/20260929-policy-v2/pools/systematic-31.json`

## L3

Fine-tuning supervises final answers in non-thinking mode. It does not teach reasoning traces or explicitly preserve reasoning behavior. The reasoning result therefore applies to this training recipe; it does not establish that fine-tuning generally harms reasoning.

Training exports contain the correct policy, task, and final JSON target, rendered with qwen3_disable_thinking. The supervised-token checks confirm that only the final answer and termination are targets. There is no reasoning-preservation training arm.

Sources: `run.py: Study.train`, `runs/20260929-policy-v2/training/`, `INTERPRETATION_LIMITS.md`

## L4

The rule system has an ordinary executable solution. Recall-success measurements require a valid complete response, so malformed outputs count as failures.

Both deterministic oracle implementations compute the complete answer from the input records. The scorer builds its per-ID prediction dictionary only after validating the entire response schema and ID set.

Sources: `task.py: oracle, independent_oracle, score`

## V1

The analysis replays 5,489 unique primary test responses and checks frozen source/data hashes, both task oracles, all completed training steps, and the additional control responses. Estimated token charges for this cycle, including development and controls, are $3.69; estimated cumulative charges including the earlier writing study are $21.12.

analysis.json verification records primary replay and training checks; controls.analyze replays its raw receipts. Cost sums the current and initial-development ledgers, including conservative interrupted-attempt charges, then adds the prior study estimate. Estimates exclude storage and invoice adjustments.

Sources: `runs/20260929-policy-v2/analysis.json`, `runs/20260929-policy-v2/control-analysis.json`, `runs/20260929-policy-v2/costs.jsonl`, `runs/20260929/costs.jsonl`
