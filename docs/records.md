# Mirror an external ledger without changing files

`sun record` preserves an exact, attributed JSON payload supplied by a caller.
It does not reread current file contents, stage files, commit work, apply CRDT
updates, or replace Desktop's existing ledger. Producer identity is declared,
not authenticated by Sun. This interface complements [verification](verification.md):
operation records describe captured work; verification records contain judgments.

Initialize with `sun --expected-root /absolute/project init --record-only`.
An integration should use the same root guard for every command and clear
inherited Git directory/index/environment overrides.

## Append

Send this JSON to `sun --expected-root /absolute/project record --json`:

```json
{
  "request_id": "desktop-install/project/local_edits/42",
  "source": {
    "installation_id": "desktop-install",
    "project_id": "project",
    "stream": "local_edits",
    "row_id": 42
  },
  "actor": {"id": "alice", "kind": "user"},
  "synthetic": true,
  "payload": {
    "id": 42,
    "project_id": "project",
    "path": "paper.md",
    "actor": "user",
    "author_id": "alice",
    "content_text": "Recorded version: 78%.\n",
    "update_b64": "AAEC/w==",
    "chat_id": null,
    "message_id": null,
    "edit_mode": "edit",
    "created_at": "2026-09-06T10:01:00.123Z"
  }
}
```

This is synthetic protocol data, not a valid Yjs update or real human review.

The outer source identity must be stable across retries and restarts. Use a
persisted installation ID, project ID, stream name, and the original positive
integer row ID (at most 2^53 - 1). A row from another installation, project, or
stream is a different source even when its numeric ID matches.

The payload is opaque JSON, bounded with the entire request to 1 MiB. Unknown
outer fields are rejected; inner fields are preserved without interpretation.
JSON key order and transport whitespace are not meaningful, but text, CRDT
base64, nulls, and numeric/boolean distinctions are retained. Paths inside the
payload are data, not instructions to access or modify a file. The caller must
validate them before using them for later filesystem operations. Sun does not
claim that a payload's declared source actually produced it.

Optional `module: {id, version, digest?}`, `run_id`, and `parent_run_id` carry
external execution provenance. A digest is 64 lowercase SHA-256 hexadecimal
characters. Do not fabricate an individual author for an ambiguous mixed
persist window or replace a known agent producer with the machine owner.

The response preserves the request and adds:

```json
{
  "schema_version": 1,
  "id": "<64 lowercase hex>",
  "type": "external_record",
  "recorded_at": "2026-09-06T10:01:01.123456Z",
  "recorded_by": "local-recorder-account",
  "attribution": "caller-declared"
}
```

The ID hashes the source identity. An identical retry returns the same original
record, including its recorded time. Reusing either source identity or request
ID with changed content fails. Retrying a source with a different request ID
also fails: derive the request ID deterministically and persist it in the outbox.

Verification findings may cite this immutable record as `{"record_id":"<id>"}`.
The citation covers the whole record, without a field selector or line range.
A check citing synthetic evidence must also be marked synthetic. Use snapshot
targets for the source versions on which a process result depends; paths and
references inside the opaque payload are not freshness dependencies. See the
[verification contract](verification.md) for mixed file and record citations.

## Read and paginate

```sh
sun records show <record-id> --json
sun records list --limit 100 --json
sun records list --limit 100 --after <cursor> --stream local_edits --json
```

List returns `{schema_version: 1, records: [...], next_cursor: null | "<id>"}`.
The default page size is 100, maximum 1,000. Results are ordered by recorded
timestamp, then ID. Use the returned cursor unchanged with the same stream
filter. Unknown or wrong-stream cursors fail instead of restarting silently.
An immutable chronological index avoids reading every payload to serve one page.
The stream filter may still scan unrelated records; it is not an indexed query
engine. Pages are count-bounded, not a frozen snapshot of all future arrivals.
In particular, imported older records can appear before a previously used cursor.
This pagination cursor is not the Desktop mirror's durable delivery cursor.

## Reliability and ownership

The record, request-ID lookup, and chronological index are created in one atomic
Git reference transaction, under a lock shared across worktrees. A transaction
failure creates none of these refs. Append or list detects missing indexes;
it does not silently recreate potentially conflicting history. Refs live under
`refs/sun/records/`, `refs/sun/record-requests/`, and `refs/sun/record-order/`.
Transfer all three together. They survive Git garbage collection. As with
verification refs, local Git owners can rewrite them outside this API; this is
not signed or tamper-proof storage.

Desktop should write to its own ledger first and deliver through a durable
outbox. Acknowledgement follows a successful Sun response, and the original
outbox item must survive failures or a sidecar restart. Never let a failed Sun
delivery lose a Desktop edit. Pending items must be retained before Desktop's
normal ledger trimming can remove their payload. Sun owns none of that SQLite
retention policy, scheduling, or replay of edits. Existing Sun hook events and
Desktop undo/history behavior remain separate and unchanged.

Run `python3 -m unittest test_sun test_verification test_records`.
