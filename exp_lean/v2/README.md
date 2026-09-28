# Methods revision, v2

Read [METHODS.md](METHODS.md) for the full protocol and `methods.tex` for the
one-page summary. `design.json` contains the proposed numeric gates. The
original experiment and its measurements are preserved under `../runs/`.

This revision implements the design and a retrospective rejection diagnostic.
It does not implement the v2 scorer, catalogue, reviewer qualification, power
simulation, or paid runner. Those are explicit prerequisites, not completed
checks. No new experiment results are claimed.

From `exp_lean/`, reproduce the diagnostic with:

```sh
python3 v2/readiness.py --legacy-run runs/20260926-01 --output v2/readiness-legacy.json
python3 -m unittest discover -s v2 -p 'test_*.py' -v
```

The first command intentionally exits 2 because the old run fails the proposed
checks. Missing evidence is a failure, not an implied pass. A passing diagnostic
would still not certify a v2 launch; it is a subset of the required checks.
These retrospective thresholds must not be described as preregistered for v1.
Freeze them before new v2 data collection.

The next scientific step is development calibration after the v2 fixtures and
interfaces are implemented, not another four-round run through the old code.
Preserve each failed pilot and do not reuse an inspected test set as sealed data.
