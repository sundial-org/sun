# Additional controls specified during the frozen primary run

The primary protocol and its non-thinking comparison remain unchanged. These
secondary controls were specified after observing the frozen baseline but before
inspecting any trained model's test result. They require no additional training.
They address two interpretation risks that the primary comparison cannot resolve.

## Inference effort

Evaluate the first 50 already-held-out tasks, balanced across the five focus
regions, with Qwen3 thinking enabled and a 4,096-token output allowance. Evaluate
both frozen and trained models for every condition and seed, with the same four
retrieved examples as the primary comparison. This is a matched comparison of
adding weight updates within a higher-compute inference mode. It is a secondary
50-task test, not the 250-task primary endpoint, and must be reported separately.
Compare its paired effects with the corresponding 50-task non-thinking subset.
Report output tokens including reasoning; no wall-clock service latency claim is
made. Do not claim that the primary context baseline was globally optimal.

## Region counterfactual

For each of the 50 west-region focus tasks, change only the recalled order's
region to north. The complete correct answer must remain identical because the
recall override takes precedence over the regional shipping rule. Run every
adapter and the base model under the checklist with no examples. The original
west response is reused from the primary run; only the counterfactual is new.
Measure the paired change in correct recall handling. This tests sensitivity to
the feature defining the systematic training-error group while holding the
required answer and remaining task content fixed.

Both controls use frozen primary artifacts. Their own source, inputs, and this
protocol are hashed before any control response is collected. Costs enter the
same ledger and $75 cycle cap, and commands run only after the primary process
finishes. Bootstrap intervals are conditional on three training seeds; all seed
values are retained. These controls do not establish cross-domain transfer,
generalization to unseen rubrics, or a universal reliability threshold.

Operational amendment before any control response: use up to 40 concurrent
sampling requests rather than 10, within the SDK's own dispatch limit, to reduce
waiting for longer reasoning responses. Models, inputs, decoding, sample counts,
statistical comparisons, and cost cap are unchanged. The original source and
freeze are retained under `control-original/`; the amended freeze records both
the original specification time and the operational amendment time.
