# Verification records

Sun records checks and reviews submitted by Desktop, a person, or an external
experiment runner. It does not start agents, run tests, schedule work, or train
models. A recorded finding is evidence of a caller's judgment, not proof that
the finding is correct.

## Safe setup

```sh
cd your-experiment
python3 /path/to/sun.py init --record-only
```

This creates local record storage and, if needed, a Git repository. It does not
import sessions, fetch anything, install hooks, change Git configuration,
create commits, stage files, or update instructions. Existing hooks and settings
are left intact, not disabled. Ordinary `sun init` retains its original behavior,
including session imports and hooks. Use record-only setup for integrations.

Project-scoped integrations must pass the global guard before the subcommand:
`sun --expected-root /absolute/project/path init --record-only`, and likewise
`sun --expected-root /absolute/project/path verify list --json`. If a project
is nested inside an ancestor Git repository, the command refuses before any
writes and asks the caller to open the repository root. Without this flag,
ordinary CLI invocation from a subdirectory retains Git's root discovery.
Adapters should also remove inherited `GIT_DIR`, `GIT_WORK_TREE`, and related
Git environment overrides so the caller's shell cannot redirect the operation.

All verification commands output JSON. `--json` is accepted explicitly. Requests
are read from stdin. Invalid requests exit with status 2 and a JSON error on
stderr. Paths are relative to the repository root, even when invoked below it.

## Freeze the evidence

```sh
sun verify snapshot paper.md results.json --json
# {"schema_version":1,"type":"snapshot","id":"<64 hex>","files":[...]}
```

Snapshots preserve exact UTF-8 content, including line endings. Each file has
`path`, `sha256`, and `bytes`. The snapshot ID is content-addressed and reusable.
Files must be regular files, not symlinks. Absolute paths, traversal, `.git`,
binary files, and duplicate paths are rejected. Limits: 128 files, 1 MiB per
file, 8 MiB total. Concurrent modification during a read causes an error; retry.
A multi-file snapshot is a collection of independently read file versions, not
an atomic filesystem transaction. To freeze a coherent experiment, the runner
must stop writes or supply an immutable run-artifact directory first.

```sh
sun verify evidence <snapshot-id> paper.md --json
# {"schema_version":1,"snapshot_id":"...","path":"paper.md",
#  "content":"...","sha256":"...","bytes":123}
```

Evidence remains available after the working file changes or is deleted.

## Record a check

Pass this JSON to `sun verify record --json`, replacing the snapshot IDs:

```json
{
  "request_id": "experiment-1/check-1",
  "actor": {"id": "writer-reviewer", "kind": "agent"},
  "module": {"id": "claim-verification", "version": "1.0.0"},
  "run_id": "experiment-1",
  "synthetic": true,
  "targets": [{"snapshot_id": "<snapshot-id>", "path": "paper.md"}],
  "findings": [{
    "id": "accuracy",
    "criterion": "Reported accuracy matches recorded experiment results",
    "tier": "numeric-consistency",
    "verdict": "contradicted",
    "rationale": "The paper reports 81%, but the experiment records 78%.",
    "citations": [
      {"snapshot_id": "<snapshot-id>", "path": "paper.md", "start_line": 1, "end_line": 1},
      {"snapshot_id": "<snapshot-id>", "path": "results.json"}
    ]
  }]
}
```

`tier`, `criterion`, and `verdict` are task-specific, not pass/fail enums. A
finding must cite at least one recorded source. For insufficient-evidence
findings, cite the materials examined and explain the missing evidence; that
does not establish an exhaustive search. Optional line ranges are inclusive,
1-based, and validated against the recorded content.

Each citation has exactly one of two shapes:

- `{"snapshot_id":"<id>","path":"file", ...optional line range}` cites a frozen file.
- `{"record_id":"<id>"}` cites a whole immutable [external record](records.md).

External-record citations cannot contain paths, line ranges, or field selectors.
Retrieve their complete payload with `sun records show <record-id> --json`.
For example, a runner can retain compiler stdout, stderr, exit status, toolchain
identification, and axiom-check output through `sun record`, then cite those
receipts in a verification. Sun validates that the external record exists and
has a valid envelope; it does not authenticate the process, interpret the
payload, or conclude that a proof is valid. Checks citing any synthetic record
must explicitly set `synthetic: true`; they cannot claim to be non-synthetic.

Targets remain snapshot/path references. Include the source files and build
inputs whose versions determine whether process evidence still applies.
References nested inside an external record's opaque payload are not traversed
or validated. The runner must capture the right inputs, bind receipts to its
invocation, and describe missing dependencies or concurrent changes honestly.
No temporary output file is necessary to retain or cite a process receipt.

`module.digest` optionally holds the module content's SHA-256 as 64 lowercase
hexadecimal characters. `run_id`, `parent_run_id`, and a JSON `metadata` object
are optional. IDs for runs and modules describe external objects; Sun does not
claim they exist or that the module was actually executed. Snapshot, external
record, and finding references are checked. Unknown schema fields are rejected.

The result preserves the request and adds `schema_version`, `id`, `type`,
`recorded_at`, `recorded_by`, and `attribution: "caller-declared"`. Actor identity
is declared by the caller, not authenticated. `recorded_by` identifies the local
Git user/account, not a witness to the work. Use a run-unique `request_id`:
repeating an identical request returns the original record; reusing the same
ID with a different payload fails. No edit or replacement operation is exposed.
Both record and review requests are limited to 1 MiB.

## Record a human review

Pass this JSON to `sun verify review --json`:

```json
{
  "request_id": "experiment-1/review-1",
  "actor": {"id": "fixture-human", "kind": "simulated_human"},
  "verification_id": "<verification-id>",
  "finding_ids": ["accuracy"],
  "decision": "accept-correction",
  "rationale": "Keep the numeric correction, not the unsupported significance claim.",
  "synthetic": true
}
```

An empty `finding_ids` list means a review of the check as a whole. The decision
is free text: agreement, disagreement, deferral, partial acceptance, and other
task-specific judgments are retained without reducing them to a reward.
A review does not edit the paper or overwrite a finding. Later reviews append
alongside earlier ones, including disagreement. Reviews of synthetic checks
must remain marked synthetic. Non-synthetic does not mean training-approved;
data permissions and curation are responsibilities of the external exporter.

## Inspect coverage honestly

```sh
sun verify list --json
sun verify show <verification-or-review-id> --json
sun verify list --limit 20 --json
sun verify list --limit 20 --before <next_cursor> --json
```

List returns `{ "schema_version": 1, "records": [...] }`, ordered by recorded
time and ID. Verification views add `reviews` and `freshness: {status, files}`.
Every target and cited file is compared against its recorded SHA-256, yielding
`current`, `stale`, `missing`, or `unavailable`. A changed result artifact stales
a finding even if the paper itself is unchanged. Freshness is recomputed at
read time, not stored as an eternal verdict. "Current" means matching file
content, not scientific validity, complete review coverage, or approval.
External-record citations are revalidated on list/show; missing or corrupt
records produce an error rather than apparently current coverage. They do not
add filesystem paths to freshness checks. Their applicability depends on the
captured source targets, not whether an obsolete log file still exists.

With `--limit` (1 to 100), list pages **checks**, newest pages first, with reviews
attached rather than counted as separate rows. Within a page records remain in
chronological order. The response adds `total`, `offset` and `next_cursor`; pass
the cursor as `--before` to read older checks. Unknown and review cursors are
rejected. Only selected checks have freshness evaluated. Without `--limit`, the
complete-list format is unchanged. Refresh the first page to see concurrent new
work. Metadata is batch-read from Git, but still scanned across the complete
record; this is not a million-record indexed query engine.

Records are stored under `refs/sun/verification/<id>` and snapshots under
`refs/sun/evidence/<id>`. Atomic Git ref creation and a shared worktree lock
serialize appends; Git garbage collection retains the referenced content.
Record-only setup does not configure transport. Explicitly transferring Sun
refs transfers their evidence content too; an already-installed Sun push hook
also transfers these refs. Review privacy before sharing them.

These refs are append-only through this API, not tamper-proof or signed. A Git
owner can rewrite refs outside Sun. The original `sun export` remains the
legacy operation/session export; external improvement exporters should consume
these verification records explicitly. This API does not claim Tinker/Harbor
compatibility, authenticate a human, or turn a fixture into training data.

Run the focused tests with `python3 -m unittest test_verification` and the
existing behavior tests with `python3 -m unittest test_sun`.
