# Boundaries on interpretation

These notes were written during the frozen run and do not change its hypotheses,
training, context selection, test inputs, or primary outcome.

- The two noisy pools have identical whole-example accuracy (80%) and use the
  same corruption operation (ignore recall). Their wrong output labels are not
  matched: at seed 31, scattered errors produce 40 EXPRESS and 40 STANDARD routes,
  while all 80 systematic errors produce STANDARD because west shipments use
  that route. Therefore a difference establishes that these equally accurate
  correction sources behave differently, not that error predictability alone
  causes the difference. A future isolation experiment should match this marginal.
- Every example has exactly three orders and exactly one recalled order. New
  random input records test this distribution, not arbitrary batch sizes or
  arbitrary recall counts. The region counterfactual does not remove this limit.
- Correctness is completely specified and mechanically checkable here. This is
  a causal test environment, not evidence that an LLM should replace a simple
  policy implementation in a real fulfillment system.
- All decisions correct and full output correct are distinct endpoints. The
  latter additionally requires the specified sorting. Their separate metrics
  must accompany claims about learning the policy.
- `recall_correct` requires a valid response schema and complete IDs, as well as
  the correct recalled-order decision. An invalid overall response is zero even
  if some text in it describes the recall correctly. Inspect valid-response
  recall errors before describing a result as a learned recall-rule violation.
- The primary comparison uses non-thinking inference. A matched secondary
  reasoning-mode test has 50 tasks and a larger output budget. Its results must
  not be substituted into the 250-task primary confidence intervals.
- Training supervises final answers in the non-thinking mode. It does not teach
  reasoning traces or explicitly preserve reasoning behavior. The reasoning
  control gives both models the same allowance, but their actual output lengths
  differ. A reversal there applies to this training recipe and decoding mode;
  it does not show that all fine-tuning harms reasoning or identify an equal-cost
  crossover. Truncation and final-answer formatting are reported separately.
- One example count, one error rate, one model, and one fixed rule set do not
  locate a general data threshold or establish a universal context/weight rule.
- Scattered-label masks change with training seeds; the clean and systematic
  pools do not. Seed variation includes both mask and training variability in
  that condition. Bootstrap intervals condition on the three observed seeds.
- No learned verifier is evaluated or used for training. The 80% figure refers
  to the exactness of synthetic corrected targets, not judge confidence,
  criterion-level judge accuracy, or stochastic self-consistency.
