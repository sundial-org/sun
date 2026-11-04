# Checks

Run manually with `sun check --run tests`, `sun check --run ponytail`, or
`sun check --run` for both. View recorded results with `sun coverage`.

## tests
---
run: python3 -m unittest test_sun test_reliability.ReliabilityTest
---
The existing test suite passes.

## ponytail
---
agent: codex exec -s read-only -
---
Review the changed code using the ponytail skill when available and these
criteria: reuse existing code, prefer the standard library and native platform
features, and avoid unnecessary dependencies, speculative abstractions, dead
code, and configuration without a current use. Prefer the smallest clear
solution that preserves behavior. Inspect surrounding code and callers before
recommending simplifications. Do not sacrifice validation, error handling,
security, accessibility, or necessary tests to reduce code size.

Judge complexity introduced by this diff, not unrelated existing code. Fail
only for concrete, actionable unnecessary complexity; cite its location and
the simpler replacement. Do not fail for subjective formatting preferences or
line count alone. Review only, without editing files. Follow Sun's requested
JSON verdict format.
