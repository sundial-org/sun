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
From then on, hooks keep the log current: one commit per agent tool call (squashed per turn),
with local edits detected in between. Codex asks you to review and trust new project hooks
through `/hooks` before it runs them.

## 1 · Analyze your past sessions

| command | what you learn |
| --- | --- |
| `sun log` | git log annotated with the actor and turn behind each commit |
| `sun show <commit>` | a commit's events and patches, even after a squash-merge (patch-id) |
| `sun viz` | self-contained HTML visualization, with replay from the beginning |
| `sun sessions [id] [--grep re] [--file p]` | search every session that ran here |
| `sun undo [--op ID] [--commit H]` | reverse any single operation or commit |

## 2 · Optional raw session sharing

Pass `--share-sessions` to store raw transcripts under `refs/sun/sessions/*` and share them
with everyone who can read the git remote. This is off by default because transcripts may
contain prompts, tool output, file contents, environment data, and secrets. Shared sessions
stay outside normal branches and PR diffs, but collaborators can inspect them with git.

## Demos & tests

```sh
python3 examples/demo_init.py   # pick any repo you've used Claude Code on -> timed sun init
python3 examples/demo_fresh.py  # synthetic end-to-end story -> examples/demo.html
python3 -m unittest test_sun    # 49 tests
```
