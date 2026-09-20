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

`sun sync` and agent hooks only record locally. Fetching brings in shared refs but does not join
histories or change files. Merge through normal Git and resolve conflicts once, in Git. Sun's
post-merge/post-commit hooks record a completed merge and link the available input checkpoints.
There is no separate `sun merge` command or Sun conflict-resolution workflow.

After a Git commit with a clean index and working tree (including untracked, non-ignored files),
Sun pins a checkpoint under `refs/sun/checkpoints/<git-commit>/<sun-commit>`. The checkpoint is
bookkeeping, not a copy of each Git commit in the operation log. Multiple histories can describe
the same Git state without overwriting one another. Checkpoints prevent later turn squashing
from rewriting their operations.

Use `sun push [remote] [branch]` instead of `git push` to publish both the selected Git branch
and its checkpoint in **one atomic push**, without force. The default is origin/current branch.
Only checkpoint-reachable operations and snapshots travel; later edits and unrelated branches
remain local. A failed Git or Sun ref update publishes neither. If you opt into raw session
sharing, only your session snapshots pinned at that checkpoint are sent, not later transcript
turns. Plain `git push` publishes Git only; no pre-push hook secretly publishes Sun first.

Partial commits have no publishable checkpoint. Finish committing the intended work, then push
that later clean commit. New edits after an established checkpoint do not prevent publishing it.
Checkpoint recording also refuses active agent calls: complete those calls before making the
clean Git commit. If hooks were missing, run `sun init`; it can checkpoint a currently clean
checkout. Existing non-Sun Git hooks are preserved and initialization explains how to chain Sun.

Published history includes preceding attempts and undone edits, not merely the final diff.
Sun is not a secret-redaction tool. Atomic pushes require server support; failures are reported,
never retried as non-atomic pushes. Fetch and merge a collaborator's Git changes before retrying
a divergent push. Squash/rebase integrations without input checkpoints are not reconstructed;
use ordinary merges/fast-forwards for full provenance. Published or checkpointed calls are never squashed;
interleaved turns may also remain separate commits.
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
| `sun push [remote] [branch]` | atomically publish a Git branch and its clean Sun checkpoint |
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

## Demos & tests

```sh
python3 examples/demo_init.py   # pick any repo you've used Claude Code on -> timed sun init
python3 examples/demo_fresh.py  # synthetic end-to-end story -> examples/demo.html
python3 -m unittest test_sun test_reliability.ReliabilityTest  # full test suite
```
