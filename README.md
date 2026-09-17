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

Sun stores the shared history under `refs/sun/heads/main`. Normal `git pull` fetches it into
`refs/sun/remotes/origin/main`, and the pre-push hook publishes the local Sun tip without force.
`sun log`, `sun show`, `sun blame`, and `sun viz` read this history. A repository must be
initialized with Sun on each machine because Git does not clone local hook or refspec settings.

## Use the history

| command | what it does |
| --- | --- |
| `sun sync` | record currently uncommitted files as a human edit |
| `sun log [-n COUNT]` | list Sun commits with actors and turns |
| `sun show <commit>` | show a commit's operations and patches, including hidden operation snapshots |
| `sun viz` | interactive terminal history with commit and operation attribution |
| `sun viz --html [-o path]` | optional self-contained HTML export |
| `sun blame <file> <line>` | show the operation and stored conversation behind a line |
| `sun undo [--op ID \| --commit HASH]` | cleanly reverse an operation or commit as a new operation |
| `sun undo --dry-run` | check whether the latest reversal can apply without changing anything |
| `sun restore <commit>` | restore an older Sun state as a new commit without rewriting history |
| `sun merge` | join divergent Sun histories after resolving the normal worktree |
| `sun export [-o path]` | export prompts, tool calls, and edits as JSONL |
| `sun update` | update a Sun installation made from this repository with uv |

`sun viz` stays in the terminal. Use `j`/`k` to move through commits, `J`/`K` to scroll
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
| `sun sessions export` | materialize stored transcript refs under `.git/sun/sessions/` for local tools |
| `sun sessions prune --older-than DAYS` | delete your old local transcript refs and materialized copies |
| `sun sessions prune --older-than DAYS --remote` | also delete those refs from `origin` |

Import does not reconstruct edit attribution or modify the operation history. It only stores
transcript copies for later search, blame, and export. Prune only selects refs owned by the current
Git user. Teammates' refs are left alone. Git may remove the now-unreferenced transcript objects
during a later internal garbage collection.

## Demos & tests

```sh
python3 examples/demo_init.py   # pick any repo you've used Claude Code on -> timed sun init
python3 examples/demo_fresh.py  # synthetic end-to-end story -> examples/demo.html
python3 -m unittest test_sun    # full test suite
```
