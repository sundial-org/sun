# Exploratory compact-rubric reference

This follow-up was specified after the verbatim explicit-rule reference scored
0.6236359126984127 on validity-adjusted rubric compliance, with 274/288 valid
submissions and no valid story passing the present-tense check. Its instruction
payload was checked against the intended eight rules. Hash-selected examples
were written in past tense; the low score was not an absent-prompt bug.

The unresolved question is whether a compact, imperative instruction rendering
can produce stronger contextual performance when the rubric is supplied. One
version is frozen in `compact-rubric-plan.json` before any responses from that
policy. `compact_rubric.py` contains its exact text and uses the unchanged
evaluation settings, sampling seeds, assignments, and cost ledger.

The instruction leads with the difficult requirements, uses direct imperatives,
and removes the linguistic detector's detailed tag-verb enumeration. It is a
privileged reference, not a learned method and not a pure length-only ablation.
The comparison probes sensitivity to instruction representation, without
identifying which wording or ordering choice causes a difference.

Run exactly one compact version on the existing 144 test prompts with two
samples each. Report its score, validity, conditional score and all-rule success
alongside the verbatim reference, even if it performs poorly. No prompt search,
selection of a best variant, retuning of learned arms, or replacement of the
original primary endpoint is allowed. Because this control was motivated by
test observations, its interpretation is exploratory on the reused test set.
No private rubric text enters the learned playbooks or training targets.
