# Completed work state

The requested research cycles and half-length draft are complete on
`exp/continual-learning`. No paid processes remain active. Do not restart the
experiments or reinterpret the historical instructions below as pending work.

- Draft: `paper/output/pdf/draft-paper.pdf`, four illustrated pages, 2,384 words.
- Submission: `paper/output/pdf/submission.pdf`, adds one CS197 notes page.
- Justifications: `paper/CLAIMS.md`, 80 reviewed claim blocks.
- Editable source: `paper/output/rubric-paper-source.zip`.
- Final audit: `paper/evidence/verification.json` and `build-check.json`.
- Full run: `runs/shared-reviews-20260928/`.

All 9,744 new writing transcripts replayed, 38 summaries and 38 intervals
recomputed, 896 instruction-probe responses checked, and 18 training runs and
local adapter archives verified. Independent rescores cover 152 writing episodes
and every probe response. Estimated new token cost: $17.42253885, excluding
storage/invoice adjustments; authorized cap $1,000. Two interrupted attempts
are preserved and conservatively charged their full plans.

The primary SFT-minus-playbook gap is 17.4 points, paired 95% interval
[15.4, 19.5]. All controls, the compact privileged rubric, and the separate
instruction probe are complete and reported with limits. The older archive's
editor-creation replay still has 16/460 final-record mismatches; see the audit,
SOURCES.md and C55 justification. Shared input identity and new evaluation
replay are verified separately. Do not claim complete old-archive recreation.

Final reader review and five-page visual inspection passed. Standard sections,
rubric title, workflow diagram, results figure, and two tables satisfy the user's
latest steering. Frozen source, original freeze and amended freeze remain intact.
Research log records the chronology; all earlier progress notes below are historical.

# Historical progress notes

Do not stop with a protocol or pilot-only draft. User requires actual research
cycles, experiments, then a half-length draft with every assertion justified
in a separate file. Budget approved: $1,000. Branch: exp/continual-learning.

At 00:17 UTC 2026-09-29, MAIN RESUMED in exec session80156. Log:
`runs/shared-reviews-20260928/main-resumed-console.log`. Initial main4451 exited1
at compiler n15: seeds73/127 cited nonexistent review ID none-train-0005.
No learned-policy test responses or confirmatory training existed. All requests
were complete. Original freeze/code preserved as freeze-v1.json/frozen-code-v1.
Added transactional compiler_validation.py and maximum2 schema-only repair calls
in run.py; each failed compiler succeeded on repair1, with no private feedback.
Amendment frozen 00:17:04 UTC, details protocol-amendments.md and amendment-1.json.
Current freeze includes new files; do not modify frozen code. Original scorer is
unchanged. A batch scoring trial on48 dev stories matched all saved A/B scores
but was not much faster, so it was not adopted. Main base US=.520089 U282/288;
raw15 US=.514819 U258/288. Estimated new spend$2.3995 before resume.

Paper infrastructure added: collect_evidence.py (requires37 evaluations,18
adapters,7 retention policies); verify_evidence.py (all transcript replays,
independent arithmetic/bootstrap, targets and compiler inputs); render_results.py
(two-panel figure+endpoint table); build.py; submission-notes.tex (1page, visually
checked in /private/tmp/continual-new-notes.png). No final paper.tex/claim ledger
yet. Methods-draft.tex updated C43 for bounded repairs and C52 to clarify either
adapter or playbook can be disabled, and active playbook can conflict with IFEval.
Collector now requires freeze-v1.json/amendment-1.json, packages full old480reviews,
full new evaluations and targets compressed, and frozen current source. Do not
run collector until all main/control/retention/archive work has completed.
Original adapter archive tool works after all18 trainings. No outstanding calls.

Update at00:30UTC: same main session80156 continues. All3 n15 playbooks
scored (US .654204 seed31, .679315 seed73, .673673 seed127; U272,274,278/288).
All3 n15 adapters trained and saved; evaluation running. Development3sampler
archives downloaded (184647680bytes each), archive session88158 exited0. Run
archive_adapters.py again after all18complete. main original15compilerfailure
is resolved by first-repair success for both invalid-ID outputs.

Paper reader /root/draft_reader_review reviewed methods and found qualifications;
all addressed: shared pairs but different conditioning/computation, explicit
secondary-score denominators, C53 amendment timing, base-relative descriptive
safeguard, IFEval prompt/instruction metrics and one response each. Methods now37
claim blocks with prepared method-justifications.json, all marked reviewedfalse
pending complete data. About1175words before abstract/results/discussion.
New rescore_audit.py must run `style` after37 evaluations and `retention` after7
retention files; produces rescore-style.json (148deterministic sampled A/B score
rechecks) and rescore-retention.json (all896official strict rechecks). Collector
requires both reports. Verifier now checks38 paired intervals, alltranscript
replays, alltraining prefixes/target IDs, compiler inputs and pair hashes,
providertext/prompt hash/seed receipts, and estimated per-request token costs.
Completed-baseline independent bootstrap check matched all8 tested intervals.
Provider-metadata.jsonl.gz will retain text/params/token counts without big token
and logprob arrays. collect_evidence includes old480reviews, oldprompts, main
compressedfullrows, targets, metadata, and current+originalfreeze/amendment.
No finalpaper.tex/results/claim-checks.json yet. Do not present pending as complete.

Update at 00:49 UTC: main session 80156 is healthy, now training/evaluating
60-opportunity SFT. All 15-opportunity arms complete. Pooled SFT US=.853877,
U814/864; book US=.669064,U824/864. Exploratory gap=.184813, prompt CI
[.163235,.206474], place CI [.165902,.205525]. n15 fails descriptive validity
guardrail by 3.7037 points below base. n60 raw US=.566902,U265/288. n60 books:
seed31 US=.641803,U280; seed73 .605593,U279; seed127 .691282,U280 (all/288).
n60 seed127 SFT completed32steps at00:48:52; other2 near completion.
Archive session45718 exited0, now6 adapters downloaded (dev3+n15main3).

Unfrozen audit improvements: collector streams hashes of actual local binary
archives and binds only collected payloads (safe to rerun after rendering).
claims.py checks reviewed artifact hashes when provided and rejects a pending
verification_status. Add figure/table artifact hashes to their final ledger
entries. New paper/diagnostics.py computes descriptive length/tool/token counts
from final evidence, no provider calls. Run after collecting evidence.
New discussion-draft.tex and discussion-justifications.json contain4 prepared
limitation claims C80-C83 (~220words), all pending final review. Methods C38 now
names places/goals/complications, C48 specifies familiar versus fable/gothic
strata. Existing method-justifications still compatible. Final paper.tex and
claim-checks.json remain uncreated; no final draft yet. Current estimated spend
about$6.11. Followups, retention, final audit/build/review still required.

Update at01:08UTC: main80156 (PID50165) has completed all60-budget arms and
is starting raw480. Local scoring slowed temporarily (CPU active, not stuck),
but all evaluations finished. SFT60seed31 US=.878844,U280;seed73 .866877,U278;
seed127 .751550,U242. Pooled US=.832424,U800/864, fails safeguard. Book60
pooled .646226,U839/864. Gap .186198 CI [.167244,.205130], place
[.171896,.200562]. Archive session23530 exited0, now9 adapters saved locally.
controls-preflight.json checks all3 donor derangements,460 valid remapped
targets each, no unchanged recipient target. Verifier now reconstructs donor
substitutions and checks package's actual-binary-hash-check count. Estimated
new token spend$6.9089 before480. Main/controls/retention/audits/paper remain.

Historical state, superseded by the paragraphs above:
At 23:15 UTC 2026-09-28, development is running in exec session 92820. Logs:
`runs/shared-reviews-20260928/dev-console.log`. Base dev U*S=.565476, U=47/48;
60-review playbook seed31 U*S=.634673, U=46/48; SFT lr.00015=.663318,U=34/48;
lr.00047=.850074,U=45/48. The .0007 candidate is still running. Its first attempt
stalled at step29/32 because the original SDK connection stopped responding.
Fresh SDK reads worked. Interrupted with SIGINT, exit130; preserved under
aborted-training and conservatively charged $0.10865536. Retry now has a
step16 optimizer checkpoint and is using the same data/seed/hyperparameters.
No test responses have been generated. The Python process loaded an earlier
run.py; recent edits add parallel independent seed work, global sampling cap10,
serialized scoring, and a more complete local freeze. After dev completes,
run `run.py freeze` locally to snapshot the final current code before `main`.

Next: finish development, inspect selected-candidate variance and record a
dev-only 5pp power simulation before freezing. Current design is 96 test prompts,
48 familiar/48 fable-gothic, 16 places. Preliminary lr.00047 dev variance implies
about73% normal-approx power at96 prompts for5pp; could increase sealed sample
size before any test calls if the chosen candidate's variance warrants it.
Then run main (15/60/480, three seeds), controls, retention, analysis, archive.
Main compiler and seed jobs now run independently in threads, with max10 sampling
requests and serialized spaCy scoring. Controls currently run seeds sequentially.

Follow-up controls already coded: explicit-rule privileged reference, SFT plus
playbook, self-target SFT, shuffled targets with remapped anchors. Retention:
128 public IFEval prompts frozen by key hash, official strict checks, base plus
three endpoint SFT and three active playbooks. No rule labels reach the learned
compiler or training inputs. No human-quality claims are permitted.

After actual results, create a NEW paper under this directory, preserving the
old pilot report in ../continual-learning-paper. Reuse its CVPR template/build
assets if useful. Need 2000–2500 body words, about3 pages, model-paper outline
and revision notes separately, generated scientific figure, claim ledger,
independent arithmetic/hash verification, PDF visual QA, and fresh reader review.
Doc-coauthoring skill authorizes reader-review agents only. Existing agent
/root/draft_reader_review already reviewed the protocol; its concerns were fixed.
No general agent delegation is authorized.

Important source correction: SDFT v2 derives reverse KL but explicitly reports
forward KL in its practical implementation. Do not repeat the earlier mistaken
claim that the proposal's forward-KL direction was wrong. PROTOCOL and literature
map now state this correctly.

Paper runtime already available: bundled Python with numpy/pypdf/matplotlib,
pdflatex; TEXMFHOME=/private/tmp/continual-texmf and
TEXINPUTS=/private/tmp/continual-tex-deps//:. PDF skill requires artifact-operation
marker before new PDF authoring, then render and visually inspect. Primary PDF
skill was read this turn; document coauthoring, Tinker, curation skills also read.
Preserve existing .claude/settings.json and untracked .codex/.sundial/exp_*.

Latest user steering: normal research-paper sections, no pilot/revised framing
in the paper, title "Learning a Writing Rubric from Edits: Context or Weights?",
and an actual workflow diagram alongside results figures. At02:33UTC, prior
session80156/PID50165 no longer exists. Preserved incomplete sft480seed127
at27 logged steps under aborted-training, charged full plan$0.34631388, and
will resume main with identical frozen configuration. All requests complete.

Update at02:42UTC: resumed main session19387 is healthy. All480 endpoint
adapters trained87steps, evaluation ongoing. All480 playbooks scored:
seed31 US.7353670634920635 U280/288; seed73 .683407738095238 U254/288;
seed127 .7320808531746033 U283/288. Archive session27799 downloads final3,
with9 prior archives retained. New workflow vector diagram rendered and visually
checked atpaper/evidence/workflow.pdf/png. User saw it in commentary. Methods
now standard Introduction, Related work, Method, Experiments; Discussion
prepared separately. No finalpaper.tex orclaim-checks.json yet.

Length interpretation clarified in commentary: maintain2000–2500words, half
CS197's4000–5000word final requirement; readable figures may make4pages.
This supersedes earlier self-imposed3-page target, never explicitly requested
byuser. build.py nowaccepts3–4paperpages andoneappendednotespage, dynamically
numbersnotes. Notes renderedcleanlyaftertitle/outlinechanges. BasicTeXworks
withTEXMFHOME=/private/tmp/continual-texmf;tlmgrinstalledofficial2025deps there.
BundledPythonhasnumpy+pypdfbutNOmatplotlib; useexp_writing/.venv/bin/python
forfigureswithMPLCONFIGDIR=/private/tmp/continual-matplotlib. Do not repeatPDF
artifactmarker. NewSOURCES.md prepares provenance. Collector/verifier now
includeinterruptedtrainingmetadataandthepinnedofficialIFEvalsource/dataset;
verifierrederiveshashsubsetandcheckscompletepromptidentity. Allunfrozen.

Update at02:52UTC: main19387 exited0 at02:46:35, primary US89.1286%vs
book71.6952%, gap17.4334pp CI[15.3521,19.4734], place[15.2075,19.5747].
SFTU831/864passesmean safeguard,seed31U270/288failsalone,others279/282.
All12archivesdone, archive27799exited0. Controls now session62684, log
controls-console.log, combinedpoliciesongoing. ExplicitverbatimUS.623636
U274/288,0of274validstoriespasstenserequirement. Actualsystempromptchecked
correct,hashselectedstoriespasttense. Announcedandfroze ONE exploratory
compact privileged rubric rendering, afterthisfinding,beforeitsresponses.
RUNTHIS AFTERcontrolsandretentionexit: compact_rubric.py, sharedledger.
Its sourceandCOMPACT_RUBRIC.md arehash-boundbycompact-rubric-plan.json.
Do notedit those3files orcreatepromptvariants. Originalfreezeunchanged.
New collector expects38evaluations,9744storyepisodes,18adapters,896IFEval.
rescore_audit.py style nowrequires38policiesand152selectedepisodes,verifier
updatedaccordingly. This supersedesold37/9456/148counts. Frozenanalyze.py
naturallysummarizesextracompactreferencebutdoesnotchangeprimarycontrasts.
Newresults-draft.tex has7checked-against-current-analysisprimaryclaims;
result-justifications.json remainsreviewedfalseuntilfullfinalaudit.
Eightprimaryintervalsindependentlyrecomputedpassedprimary-independent-check.
Budgetgraphgeneratedfromcompletedmainanalysisandvisuallychecked;rightaxis
80–100.5%, left0–102, seedpointsvisible. Finalcaptionsmustdiscloseaxes/scatter.
No finalpaper.tex/claim-checks.jsonyet. Paidremainingcontrols->retention->compact,
thenanalysis/rescores/archives/packet/fullverification/paperbuild+readerreview.

Update at03:17UTC: controls session62684 still running shuffled evaluations.
All18 adapters are now trained and archived; archive session31927 exited0.
Combined complete: US.8811383928571429,U811/864,allrules465/864.
Paired combined-SFT US-.0101479828042328 CI[-.02643435846560846,.005994233630952382];
U-.023148148148148147 CI[-.04050925925925926,-.0057870370370370385].
Self-target complete: US.5287491732804233,U838/864,allrules0; self-SFT gap
-.36253720238095233 CI[-.37991898148148145,-.3449487433862434].
C67/C68 added to results fragments and prepared ledger, not yet marked reviewed.
Paid remaining after controls EXIT0: followups.py retention, then compact_rubric.py.

New audit_editor_receipts.py attempted offline replay of old editor creation:
873/913 reconstructed prompt hashes and444/460 final revisions match exactly;
40 prompt mismatches,16 final mismatches,7 first-pass failures prevent pass2.
All920 original receipts exist, as prior provenance audit verified. One inspected
prompt differs only in sentence whitespace; other causes unresolved. Preserve
editor-receipt-audit.json with status discrepancies, do not call full replay passed.
Old shared pairs remain unchanged. C55 now describes archived editor configuration
and explicitly says semantic preservation is not checked. The limitation is in
C55 justification, research_log, SOURCES and README. Collector includes report;
verifier carries its limited status separately from new transcript verification.
No paid calls were made by this diagnostic.

Paper working layout preview (in build/, NOT final delivery) rendered4pages.
Workflow and budget figure are legible. Add raggedbottom to suppress excessive
vertical stretch on page2 (already in assemble_draft.py, not yet reassembled).
Full final paper still needs shuffled/retention/compact results and final table.
Current body prose about2000words before remaining results/table, so likely2250.
Normal title/sections retained. C31 narrowed to TWO PRIMARY arms sharing pairs
because shuffled control changes pairings. C45 says all three review budgets.
C67 now reports combined all-rule success53.8% alongside validity decrease.

Claim coverage extended: submission-notes.tex now has N01-N11 claim wrappers;
notes-justifications.json prepared. notes_coverage() verifies no untracked prose.
references.tex now has R01-R07 wrappers with reference-justifications.json.
claims.py excludes bibliography and notes from word count, includes them in audit,
and resolves actual figure/table numbers (old plain() hardcoded1, now fixed).
extra-justifications.json prepared for C18,F01,F02,T01. All remain reviewedfalse.
Final merge only IDs actually present in final paper plus notes; omit C39/C40.
N10 fixed inaccurate 'adds' playbook relative proposal to 'implements'; original
proposal already planned it. Notes also disclose failed originalper-rulecalibration.
Notes rendered clean1page at/private/tmp/rubric-notes-review.png.

Collector now also packages all14 original frozen-code-v1 files, verified against
freeze-v1.json, and verifier checks those hashes. package_source.py added to build
an editable minimal typesetting ZIP after finalbuild; excludesfullrawauditdata.
README updated commands and audit instructions but status still inprogress.
No finalclaim-checks.json or newfinalPDF yet. Need finish paid stages, analyze,
rescore152+896, collect, verify, diagnostics, finalrender/table, assemble, semantic
review+final ledger, complete fresh-reader review, build and inspect all finalpages,
package source, update docs, open finalPDF, deliver only after allauthorizedworkdone.

Update at03:27UTC: controls62684 exited0 at03:23:41. Retention now running
session41603, logretention-console.log. Base strictprompt106/128=.828125;
SFT31 104/128=.8125; activebook31 100/128=.78125. Otherpoliciespending.
After RETENTION EXIT0 launch compact_rubric.py (samegloballedger, no concurrentStudy).
Shuffledall3 complete: US.8014012896825398,U732/864,conditionalS.9459162763466042,
allrules453/864. Shuffled-SFTUS-.08988508597883597 CI[-.11861462466931218,-.06262349123677248].
C69 added to results and preparedjustifications. Controls estimatednewspend
16.826266455,reserved58.831484495. Researchlog records completecontrols.

Layoutpreview rendered4pages: figuresclear. raggedbottom nowinassembledpaper
andvisualcheckedpage2, fixeslargeverticalgaps. Preview isINCOMPLETE, onlyinbuild/.
Final source includes nofakecontrolresults. Newrender_results.py willalsocreate
retention-table.tex andretention-visual-data.json, three rows/two strictmetrics.
assemble_draft.py addsT02caption/probetable afterendpointtable. T02preparedinextra
justifications. package_source.py includesboth tables. NotesN06updatedforprobe
figure role; finalnotesneedrenderafterthissmalladdition. BibliographyR01-R07
andnotesN01-N11nowauditedasclaims, excludedfrombodywordcount. claims.pychecks
local evidencefilelocators too, allowingCLAIMS.md/build-check.jsongeneratedlater.
C55 freshreaderrecommendation applied: revisions 'recorded as successfully applied
and publicly valid', not anassertionthatalloldrevisionsreplayedindependently.
Reader saidC30/C31remainvalid; clarificationrecordedinreader-review-primary.md.
Original14frozen-code-v1files nowpackageandverify, allhashespassedread-onlycheck.
No finalclaim-checks.json yet. Needremainingresultsthencompletefinalaudits/build.
