# Research log

## Before new paid calls

The user's correction requires actual research cycles, not a retrospective draft.
The previous draft remains an audited pilot report until replaced by new results.
Budget authorization: $1,000 total new API/training spend.

Vector: the missing learned-playbook comparator is the most direct threat to the
pilot interpretation. Reusing a common frozen review pool isolates its effect
without confounding the learner with which reviews it happened to collect.
New test prompts and corrected-turn training address evaluation reuse and the
pilot's broader supervision mask. See PROTOCOL.md for prespecified scope changes.

Read-only provider preflight passed: Qwen3-8B and Inkling are available. No paid
work was submitted during preflight. Current official token prices were checked.

## Development checks

Synthetic-payload provenance was verified after automatic approval review asked
for evidence of origin: 480 deterministic assignments, 665 matching Tinker
writer receipts, and 920 Inkling editor receipts. The approved retry sends only
synthetic task/story/transcript content. No unrelated repository documents are
included. An initial pricing download returned HTTP 403 before paid work;
official machine-readable prices were checked through the web tool instead.

Two local implementation checks caught issues before confirmatory evaluation:
the Cookbook normalizes supervised token weights to one per example, so the
mask check must test positive completion weights rather than literal ones;
and concurrent tokenizer encoding needs the same lock used for sampling.
Completed responses were cached, and failed local work was resumed without
reissuing ambiguous paid calls.

The first dev measurements are baseline U*S 0.565476 (47/48 valid) and inferred
playbook U*S 0.634673 (46/48 valid). These are development results only. The
initial playbook recovered naming and tense preferences but leaves substantial
rule errors. Learning-rate selection is still running.

A closer source check also corrected an initial reading of SDFT: its formal
derivation is reverse KL, while v2 explicitly reports forward KL in practice.
The original proposal's forward-KL direction was therefore not itself an error.
The revised scope omits distillation to isolate corrected-target supervision.

## Development conclusion and final freeze

The 60-opportunity SFT grid (55 valid pairs, seed31, 32 steps) produced:

| Learning rate | U*S | Valid submissions |
|---|---:|---:|
| 0.00015 | 0.663318 | 34/48 |
| 0.00047 | 0.850074 | 45/48 |
| 0.0007 | 0.431920 | 22/48 |

None passed the base-minus-three-percentage-point validity selection guard.
The declared fallback selects 0.00047 by highest validity. This failed gate must
remain visible in the draft; it is not evidence of safe adaptation. The first
candidate had thirteen nonempty final stories below 120 words and one empty
output, despite eight available tool turns.

The first 0.0007 attempt stalled after 29 logged steps. A fresh official SDK
session could read the model, which had no checkpoint; the original process
was interrupted with SIGINT and exited130. Its complete provenance remains in
aborted-training. The budget conservatively charges its full planned $0.10865536
token cost. The same candidate was then retrained from base, with an intermediate
optimizer checkpoint, and completed. Generic urllib requests returned Cloudflare
1010, while the supported SDK worked; no access-control workaround was used.

Before any test response, a centered development-prompt simulation estimated
5-point-effect power .729 at96 prompts and .877 at144. The sealed test set was
therefore expanded to144, with72 familiar-genre and72 fable/gothic prompts from24
places. Its assumptions and limited development sample are recorded in
development-power.json. This is planning evidence, not guaranteed test power.

Final local freeze: 2026-09-28 23:19:45 UTC. The earlier development process's
automatic freeze was superseded before test generation by a complete snapshot
of current code, protocol, environment, data design, analysis, and retention plan.
The new main run verifies these hashes. Independent seeds run concurrently,
sampling is capped at10 in flight, and private spaCy scoring is serialized.

## Offline audit preparation during the sealed run

Replayed all 528 completed development and base-test transcripts through the
frozen tool interpreter, matching every returned tool result, final story, and
submission outcome. This is an execution-consistency check, not validation of
literary quality or the linguistic tagger. The final paper audit will extend
replay to all episodes, independently recompute paired statistics, and package
the evaluated stories and training targets alongside source hashes.

The unadapted sealed-test policy scored U*S=.520089 with282/288 valid submissions.
This partial observation does not alter the frozen methods, sample size, endpoint,
or stopping rule. All planned budgets and controls remain required.

## Compiler validation cycle and amendment

The first main process stopped after base and raw15 scoring, before any learned
policy was tested or confirmatory adapter trained. Two compilers cited absent
review ID none-train-0005. All paid responses were complete and retained.
A transactional validator now allows at most two schema/reference-only repairs,
without private rules, scores, or editorial labels. Replaying the initial
responses accepted seed31 unchanged and rejected seeds73/127 without mutation.
Each failed compiler then succeeded on its first paid repair. The amended source
was frozen before learned-policy evaluation; see protocol-amendments.md and the
original and amended freeze manifests. No scientific endpoint or scorer changed.

## First completed budget (exploratory)

The 15-opportunity comparison completed at 2026-09-29 00:36 UTC. Averaged across
three seeds, SFT U*S is 0.853877 versus playbook 0.669064. The paired prompt
interval for the difference is [0.163235, 0.206474]; the place sensitivity
interval is [0.165902, 0.205525]. SFT validity is 814/864 (0.942130), below
base 282/288 by 3.7037 percentage points, so it fails the descriptive safeguard.
Playbook validity is 824/864. These exploratory observations do not change the
primary 480-opportunity endpoint, remaining budgets, or declared controls.

Hash-selected invalid examples show whole-word anchor substitutions (such as
lemonade instead of lemon), unsuccessful repair attempts, and a check followed
by a write that invalidates submission state. These examples motivate retaining
separate format and submission diagnostics; they do not establish a causal
mechanism or a population frequency beyond the saved counts.

The six completed development and 15-opportunity adapters are archived locally.
The evidence collector now also verifies actual binary archive hashes before
packaging. A separate descriptive diagnostic script reports token use, story
length, and tool-turn counts without changing the frozen inferential analysis.

## Second completed budget (exploratory)

The 60-opportunity comparison completed at 2026-09-29 01:07 UTC. Mean SFT
U*S is 0.832424 versus playbook 0.646226, with paired prompt difference
0.186198, interval [0.167244, 0.205130], and place sensitivity interval
[0.171896, 0.200562]. SFT validity is 800/864 (0.925926), versus playbook
839/864 and base282/288, so the SFT mean again fails the declared safeguard.
SFT seeds31/73/127 have280/278/242 valid submissions, showing substantial
training-seed variation. The seed-averaged confidence interval does not model
variation over a population of training seeds. Nothing is retuned on these
exploratory observations; the480 endpoint and declared controls remain fixed.

The shuffled-target preflight checks all460 remapped targets per seed: every
target retains public validity, no donor is its recipient, and no remapped
target equals the recipient's original correction. The final independent
evidence audit also reconstructs these donor substitutions from the archive.

## Endpoint process interruption

At 2026-09-29 02:33 UTC the original local exec session was unavailable and
PID50165 was absent. The run had completed all endpoint playbook generation
and seed127 scoring; its adapter had27 logged optimizer steps, an intermediate
step16 state, and no final checkpoint or evaluation. The cause of process exit
is unestablished. Preserve the complete attempt under aborted-training and
restart that adapter from base with the identical frozen seed, data and schedule.
Conservatively charge its entire planned token cost, $0.34631388, in addition
to the new attempt. No scored result is discarded. Completed API responses are
reused, and all request receipts were complete before restarting.

## Primary endpoint

Main completed at2026-09-29 02:46:35UTC. SFT US=.8912863756613758,
playbook=.7169518849206349; gap=.17433449074074076, prompt interval
[.15352130869708996,.19473379629629628], place interval
[.15207454943783066,.19574652777777773]. SFT validity831/864 versus
playbook817/864 andbase282/288 passes the descriptive mean safeguard,
although seed31 is270/288 andfails individually. OtherSFTseeds279/282valid.
The harder-rule score is.793596 versus.541667, all-rule success.460648
versus.055556. These support within-recipe rubric learning, not full mastery.

Final playbooks contain84,147,63tokens andnone explicitly encodes the12-word
opener criterion. They are not maximal contextual policies. The declared
explicit-rule, combined, self-target andshuffled-target controls are nowrunning,
followedbytheindependentIFEvalprobe. No method orendpoint isretuned.
Newestimatedtokencostaftermainis$13.010420685,includingconservativechargesfor
both interrupted attempts; reserved$44.341280525. All12 completedadapters
havebeenarchived locally. Paperusesnormalresearchsections andrubric title.

## Instruction-presentation follow-up

The verbatim explicit-rule reference scored US=.623636 with274/288 valid;
none of its274 valid stories passed present tense. The saved system prompt
contains all intended rules, and hash-selected examples are in past tense.
Before any new responses, froze one compact, imperative privileged rubric
reference in compact-rubric-plan.json. It reorders the difficult requirements
and removes detector detail, so it probes instruction representation rather
than a pure length-only effect. This is an exploratory, reused-test follow-up,
not a new confirmatory result or a replacement for the learned comparator.
Run after all other paid processes exit. See COMPACT_RUBRIC.md.

## Archive-construction replay diagnostic

An additional offline editor replay exactly matched 873 of 913 reconstructed
request hashes and 444 of 460 final revision records. Seven replay failures
prevented reconstruction of the second call. All 920 original editor receipts
remain present, as checked by the original provenance audit. One inspected
prompt mismatch is explained by surrounding whitespace in numbered sentences;
the remaining discrepancy causes have not been established. The report retains
every mismatch ID in `editor-receipt-audit.json`. This limits claims about exact
reproduction of the older archive's creation. No archived pair was changed or
excluded: both learned recipes still use the same saved revisions, and their
new training inputs and evaluations are checked separately. The paper describes
the archived editor configuration and explicitly avoids asserting verified
semantic preservation. This diagnostic does not call a provider.

## Completed writing controls

Controls finished at 2026-09-29 03:23:41 UTC. Unedited-target training scores
52.8749% US versus 89.1286% for corrected targets: paired difference -36.2537
points, interval [-37.9919, -34.4949]. Its validity is 838/864, showing that
additional draft training alone does not reproduce the rubric gain.

Shuffled targets score 80.1401% US with 732/864 valid episodes. The difference
from SFT is -8.9885 points, interval [-11.8615, -6.2623]. Conditional compliance
is 94.5916% and all-rule success is 453/864, both descriptively above SFT, despite
lower public validity. These are different valid subsets, not a causal estimate
of improved style. Semantic premise adherence remains unmeasured.

SFT plus playbook scores 88.1138% US with 811/864 valid episodes. Its score
difference from SFT is -1.0148 points, interval [-2.6434, 0.5994]; validity
difference is -2.3148 points, interval [-4.0509, -0.5787]. All-rule success rises
from 398/864 to 465/864. Report this tradeoff rather than selecting one metric.
All control comparisons are exploratory, without multiplicity adjustment.

All 18 adapters were downloaded and hash/tar checked, totaling 3,323,658,240
bytes. Estimated new token spend after controls is $16.826266455, including
conservative full-plan charges for the two interrupted training attempts.
Reserved token spend is $58.831484495. These are estimates, not invoices.
The independent public instruction probe began after controls exited, followed
by the single frozen compact-rubric presentation control.

## Public instruction probe

The 896-response probe finished at 2026-09-29 03:30:33 UTC. The 128 examples
contain 206 verifiable instructions per policy. Base strict prompt/instruction
counts are 106/128 and 184/206. Across three seeds, SFT gives 320/384 and
554/618; active playbooks give 304/384 and 536/618. Paired prompt-level
differences from base are SFT +0.5208 points (95% interval [-3.6458, 4.6875])
and playbook -3.6458 points ([-8.0729, 0.78125]). Both intervals include zero;
this is not a noninferiority or broad capability-retention result. All 896
responses passed an independent repeat of the official strict checks.
The compact-rubric run began only after this paid stage exited successfully.

## Compact rubric and completed evidence

The single frozen compact-rubric control completed at 2026-09-29 03:37:08 UTC,
with all 1,099 request receipts complete and 288 episodes saved. Its process
exited successfully; the SDK's session-poller shutdown warning did not leave an
unresolved request. US is .7323288690476191, validity 245/288, conditional
compliance .8608600583090379, and all-rule success 66/288. Among valid stories,
179/245 pass the tense check. Of 43 invalid episodes, 36 are below 120 words
and 16 omit an anchor; these counts overlap. Relative to the verbatim rubric,
the change improves rubric outcomes while reducing public validity. It changes
wording, ordering and detector detail together and is exploratory on reused
prompts. No further prompt variants or paid evaluations were run.

Final estimated new token charges are $17.42253885; reserved maximum token
charges total $62.49627689. Estimates include full-plan charges for both
interrupted training attempts and exclude storage/invoice adjustments. All paid
stages have exited, and all 18 adapters are archived locally (3,323,658,240 bytes).

The full offline verifier passed: 9,744 new story transcript replays, 38 summary
recomputations, 38 paired interval recomputations, 896 instruction responses,
18 completed training runs and adapter archives, 119 compiler inputs, 480 shared
review opportunities, and 23,112 provider receipts. Independent rescores passed
for 152 deterministic selected writing episodes and all 896 IFEval responses.
The older editor-creation replay retains its separate discrepancy status; the
passed new evaluation audit does not imply that old archive creation was fully
reproduced. Both interrupted attempts remain in the evidence packet.

## Final draft and claim review

The complete-paper reader found no numerical contradictions and correctly
identified the recipe comparison, conditional inference, validity safeguard,
exploratory controls, and limits. Added the IFEval-specific bootstrap procedure
and made the valid-submission conjunction explicit in all-rule result wording.
The paper uses Introduction, Related work, Method, Experiments, Results, and
Discussion, titled “Learning a Writing Rubric from Edits: Context or Weights?”
A workflow diagram, a budget comparison figure, and two result tables accompany
2,384 body words. The manuscript has four pages; one appended submission-notes
page supplies the CS197 model-paper analysis, adapted outline and revisions.

All 80 claim blocks have separately reviewed justifications and source locators;
the ledger binds final text and visual artifacts by hash. Final PDF checks found
no overfull boxes or unresolved references. Every page of the final five-page
submission was rendered and visually inspected. The standalone draft's four
pages match the submission, all source links survive merging, and all named
link destinations resolve. An editable source ZIP is provided. No Overleaf,
class, or venue submission was performed.
