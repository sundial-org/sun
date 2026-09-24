# sun

Sun is an operation log on top of git. It records who made every change, whether that was you
or a specific agent session. Raw conversations stay local unless you explicitly share them.

![the sun operation log: attributed commits on the left, one commit's events on the right](examples/viz.png)

## One command

```sh
uv tool install git+https://github.com/sundial-org/sun
cd your-repo && sun init   # sets up every harness it detects (Claude Code, Codex)
```

`sun init` scans sessions that touched this repo for each harness it detects. Worktrees and
subagents are included. Raw transcripts remain in their existing local directories by default.
Existing commits stay untracked because sun did not observe them. From then on, hooks keep an
independent Sun history current: one visible commit per turn, containing one operation per
agent tool call. Each operation keeps a hidden Git snapshot for exact replay and undo. Human
edits observed during a turn remain separately attributed operations inside that turn commit.
Sun commits share Git's object database but never move normal `HEAD`
or the real index, and they do not appear in GitHub's branch history. Codex asks you to review
and trust new project hooks through `/hooks` before it runs them.

Each Git branch has a corresponding Sun branch under `refs/sun/heads/<branch>`.
Creating a branch at the current checkout inherits its Sun history; subsequent edits stay
on that branch. Git commits do not rewrite Sun history. Git checkout/reset changes are observed
as repository state, with unknown authorship rather than assigning imported edits to you.
Detached HEAD is unsupported. Do not switch branches during a tool call.

`sun sync` and agent hooks record locally. Normal Git commits and merges do not invoke Sun,
create checkpoints, or publish Sun history. There are no Sun post-commit, post-merge, or pre-push
hooks. A later sync observes the resulting files without changing the Git index or history.

`sun push [remote] [branch]` publishes **already recorded Sun history only**, independently of
Git commits. The default is origin/current branch. It does not run sync, require a clean worktree,
or push a normal Git branch. Use `git push` separately for normal Git history. Uncommitted edits
that Sun has recorded are publishable; edits not yet recorded are not included.

Fetching does not join histories. When publishing, Sun combines the selected branch's local
and fetched Sun ancestry, preserving original operation IDs and keeping the local snapshot.
This is a history join, not a file merge: it neither applies remote files nor resolves conflicts.
Resolve file conflicts through normal Git once, then run `sun sync` to observe the result.
A `merge` operation in Sun describes this history join, not a mirrored Git merge commit.
There is no separate `sun merge` conflict-resolution workflow.

Git feature-branch merges do not automatically link the feature's Sun ancestry into the target
branch. Each branch retains its own recorded history; Sun observes the target's resulting files.
Automatic cross-branch provenance is deliberately deferred rather than inferred from Git commits.

Only the selected Sun history's reachable operations and snapshots travel in one atomic push,
without force. Unrelated Sun branches stay local. If sharing raw sessions is enabled, your latest
stored versions of sessions referenced by that history also travel. Raw sessions are not redacted
or bounded by a Git commit: they may include later conversation or other branches.

Published operations and operations inherited by another local Sun branch are not squashed.
Interleaved turns may also remain separate commits. Atomic pushes require server support and
are never retried non-atomically. A concurrent push rejection can be retried: Sun fetches and
joins the additional history without changing your files. Recorded attempts and undone edits
remain part of published history; Sun is not a secret-redaction tool.
`sun log`, `sun show`, `sun blame`, and `sun viz` read this history. A repository must be
initialized with Sun on each machine because Git does not clone local hook or refspec settings.

Operations have full unique IDs and separate refs under `refs/sun/events/`, so two computers
using the same Git identity cannot overwrite each other's event logs. Operation metadata and
the local history tip are updated in one Git transaction. History is ordered by ancestry,
then operation order within a turn, not by wall-clock timestamps on different machines.
Concurrent branches have no implied total chronological order.

Hooks support concurrent writes to different files. Overlapping writes, failed partial writes,
and edits recovered after an interrupted call are marked uncertain instead of assigned to an
agent by guesswork. Stop, session end, or a new prompt releases abandoned claims. Re-running
a completion hook is safe. If a process disappears without any closing hook, stop the agents
and run `sun sync --recover` to release abandoned calls and record uncertain edits.
Sun cannot detect a human typing into the same file during an
agent write; use separate worktrees if precise ownership of overlapping edits is required.

## Use the history

| command | what it does |
| --- | --- |
| `sun sync` | record local changes since the last Sun snapshot; never fetch or publish |
| `sun log [-n COUNT]` | list Sun commits with actors and turns |
| `sun show <commit>` | show a commit's operations and patches, including hidden operation snapshots |
| `sun data [-n COUNT]` | JSON history, attribution, patches, and resolved session paths for agents |
| `sun viz [-n COUNT]` | interactive terminal history for humans |
| `sun viz --html [-o path]` | optional self-contained HTML export |
| `sun blame <file> <line>` | show the operation and stored conversation behind a line |
| `sun undo [--op ID \| --commit HASH]` | cleanly reverse an operation or commit as a new operation |
| `sun undo --dry-run` | check whether the latest reversal can apply without changing anything |
| `sun restore <commit>` | restore an older Sun state as a new commit without rewriting history |
| `sun push [remote] [branch]` | publish the selected Sun history, separately from normal Git |
| `sun export [-o path]` | export prompts, tool calls, and edits as JSONL |
| `sun update` | update a Sun installation made from this repository with uv |

`sun data` emits one JSON object, including `commits`, `events`, `actors`,
`sessions`, and `summary`. Each operation includes `session_path`; session entries include
`id`, `user`, `harness`, `origin`, `path`, `subagents`, and `ref`. Read `path` directly:
it points to your native transcript or a cached collaborator transcript. A missing native
transcript has a null path, even if you previously shared it. Shared Git refs remain available
through `sun sessions show`. No terminal is required, including with stdin from `/dev/null`.

`sun viz` opens the terminal view. Use `j`/`k` to move through commits, `J`/`K` to scroll
details, left/right to move the replay boundary, `r` to replay from the beginning, and `q` to
quit. Each commit shows its native git author alongside Sun's observed actors. Operation
details identify the human or agent that generated them, including harness, session, turn,
tool call, attribution method, files, and patches. A `sync` attribution means a Sun command
discovered an uncaptured dirty edit later. It does not mean an agent hook observed the edit
when it happened.

Undo can target any stored operation or ordinary single-parent Sun commit, not only the latest
one. It stops without changing files if the reverse patch no longer applies cleanly. Restore is
the safer way to return the whole worktree to an earlier point: it preserves the existing log and
adds a restoration commit. Neither command rewrites or deletes history.

## Optional raw session sharing

Pass `--share-sessions` to store raw transcripts under `refs/sun/sessions/*` and share them
with everyone who can read the git remote. This is off by default because transcripts may
contain prompts, tool output, file contents, environment data, and secrets. Shared sessions
stay outside normal branches and PR diffs, but collaborators can inspect them with git.

| command | what it does |
| --- | --- |
| `sun sessions list [--grep REGEX] [--contains TEXT]` | list or search transcripts already stored in Sun refs |
| `sun sessions show <id>` | print one transcript by full ID or unique prefix |
| `sun sessions import` | copy new or changed native harness transcripts into Sun refs when sharing is enabled |
| `sun sessions export` | index native paths and cache collaborators' shared transcripts under `.git/sun/sessions/` |
| `sun sessions prune --older-than DAYS` | delete your old local transcript refs and materialized copies |
| `sun sessions prune --older-than DAYS --remote` | also delete those refs from `origin` |

Your own transcripts are never materialized into the local session cache. Sun resolves their
native paths, including paths learned from hooks. Collaborator copies are separated by owner,
so identical session IDs do not overwrite each other. Export refreshes `sessions-index.json`
and removes legacy cached copies of your own shared sessions. Git transcript objects are still
stored when sharing is enabled so collaborators can fetch them.

Import does not reconstruct edit attribution or modify the operation history. It only stores
transcript copies for later search, blame, and export. Prune only selects refs owned by the current
Git user. Teammates' refs are left alone. Git may remove the now-unreferenced transcript objects
during a later internal garbage collection.

## Code map

The `sun/` package separates the main jobs:

| File | Responsibility |
| --- | --- |
| `cli.py` | Command arguments, initialization, hook installation, and updates |
| `git_store.py` | Git objects, refs, snapshots, and local state files |
| `history.py` | Branch history, events, turn squashing, publishing, undo, and restore |
| `hooks.py` | Agent hooks and before/after tracking for tool calls |
| `sessions.py` | Native transcripts and optional shared session storage |
| `output.py` | Log, show, blame, JSON, terminal, HTML, and training export |

Run source checkouts with `python -m sun` instead of `python sun.py`. The installed
`sun` command calls `sun.cli:main`. Modules use explicit imports so callers can
see which part of Sun owns a function.

Events are read from `refs/sun/events/`. The old `events.jsonl` and `refs/sun/log/`
formats are no longer imported or used to reconnect branch history. Existing old
data is left untouched; repositories that only have that data need an older Sun
version to migrate it before upgrading.

## Demos & tests

```sh
python3 examples/demo_init.py   # pick any repo you've used Claude Code on -> timed sun init
python3 examples/demo_fresh.py  # synthetic end-to-end story -> examples/demo.html
python3 -m unittest test_sun test_reliability.ReliabilityTest  # full test suite
```
