# sun

An operation log for humans + agents on top of git. Every change becomes a commit attributed
as `<user>/<source>` — `<user>/local` for changes on `<user>`'s machine not made by a tracked
agent, `<user>/agent:<harness>/<session>` for agent tool calls. Live attribution runs from
harness hooks: `PreToolUse` commits dirty state as local, `PostToolUse` commits the pre→post
diff as the agent's (one commit per tool call), `Stop` squashes the turn into one commit —
per-call commits stay in the op log under `refs/sun/ops`. Events (`.git/sun/events.jsonl`,
mirrored to `refs/sun/log/<user>`, one writer each) point at commits; a commit can carry
several events. Sessions are tracked in git too: transcripts live as objects under
`refs/sun/sessions/<user>/<id>` (chunked per turn, never in the worktree) and travel with the
repo via the fetch refspec + fail-soft `pre-push` hook that `sun init` installs. Agents find
them through `.git/sun/sessions/` (exported in the `~/.claude/projects` layout, with a
`sessions-index.json`) via a `SessionStart` context line and an optional `CLAUDE.md` line.

## Install

```sh
./install.sh                    # copies sun.py to ~/.local/bin/sun
cd your-repo && sun init        # git repo + hooks + session import + backfill + viz link
```

`sun init` also imports the folder's existing Claude Code sessions (root, worktrees) and
backfills attribution over existing commits by matching transcripts within a time window
(`method: transcript_backfill`; unmatched commits become `<author>/local`, `method: import`).
Benchmark (sundial-md clone: 6,489 commits, 25 sessions + 53 subagent transcripts, 33 MB):
cold `sun init` 6.4s, warm rerun 0.7s (idempotent by file size+mtime and per-commit events).

## Commands

| command | what it does |
| --- | --- |
| `sun init [--claude-md]` | git repo + `.git/sun` + hooks + import; writes `.git/sun/viz.html` |
| `sun import` | re-run just the session import + attribution backfill |
| `sun log` / `sun show <c>` | git log with actors + turns / the events behind one commit (patch-id fallback) |
| `sun undo [--op ID] [--commit H]` | reverse one operation (default: latest) or revert a commit |
| `sun sessions [id] [--grep re] [--file p]` / `sessions export` | list/read team sessions / mirror to `.git/sun/sessions/` |
| `sun sync` / `sun gc --older-than N` / `sun viz` / `sun hook` | commit local edits / drop old session refs / HTML replay / hook entrypoint |

## Demos & tests

```sh
python3 example/demo_init.py    # pick any local repo with Claude sessions -> timed sun init
python3 example/demo_fresh.py   # synthetic end-to-end story -> example/demo.html
python3 -m unittest test_sun    # 33 tests
```

Not yet implemented (see proposals): `env`, `sft`, suggestions, `sun doctor`, `--redact`,
review-granularity stats, LFS transcript backend. Assumes sha1 repos (loose-object writer).
