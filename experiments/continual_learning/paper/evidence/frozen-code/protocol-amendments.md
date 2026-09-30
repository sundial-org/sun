# Implementation amendment 1: compiler reference repair

Declared 28 September 2026 after the first main process stopped, before any
learned-policy test responses or confirmatory training jobs. The base and
15-opportunity raw-retrieval evaluations had completed. Their observations do
not select the amendment, which responds to a compiler schema failure.

Two of three 15-opportunity compilers cited `none-train-0005`, which was absent
from their 14 supplied valid review pairs. The original validator correctly
rejected these outputs. All provider responses were received and cached; no
ambiguous request or unfinished paid training job remained.

For every compiler batch, allow the original response plus at most two repair
responses. A repair receives the same review input, the rejected model output,
and only the local schema/reference/token-cap error. It never receives private
rules, style scores, or editorial audit labels. Use the same compiler settings,
with deterministic repair seeds equal to the original seed plus10,000 per
repair. Preserve each input, rejected output, validation error, and accepted
operation. Apply operations transactionally so a rejected list cannot partially
change the playbook. Exhaustion still stops the run; there is no silent skip.

The already successful 60-opportunity development playbook and 15-opportunity
seed31 playbook are preserved unchanged. No tuning of playbook content against
test outcomes is permitted. Budgets, model recipes, writer prompts, sampling,
scorer, sample size, primary contrast, controls, and analysis remain unchanged.
The original freeze and code are preserved as `freeze-v1.json` and
`frozen-code-v1/`. An amendment manifest records changed hashes before resuming.

A separate local throughput trial batched48 development-base stories through
the same tagger and reproduced every saved A/B score exactly. It took47.53seconds
after45.70seconds of model loading while the main process was also active.
This was not a controlled speed benchmark and did not justify changing the
frozen scorer. Single-story scoring remains unchanged.
