# sun

Your repo has two histories: the code, and the conversations that produced it. git keeps the
first and loses the second. sun keeps both. It is an operation log on top of git that records
who made every change, whether that was you or a specific agent session, and it stores the
sessions themselves in the repo so your whole team's agents can use them.

![the sun operation log: attributed commits on the left, one commit's events on the right](example/viz.png)

## One command

```sh
uv tool install git+https://github.com/sundial-org/sun
cd your-repo && sun init           # Claude Code, the default
cd your-repo && sun init --codex   # Codex
```

`sun init` imports every Claude Code session that ever touched this repo. `sun init --codex`
does the same for Codex sessions. Worktrees and subagents are included, and attribution is
backfilled across existing commits. From then on, hooks keep the log current: one commit per
agent tool call (squashed per turn), with local edits detected in between. Codex asks you to
review and trust new project hooks through `/hooks` before it runs them.

## 1 · Analyze your past sessions

| command | what you learn |
| --- | --- |
| `sun log` | git log annotated with the actor and turn behind each commit |
| `sun show <commit>` | a commit's events and patches, even after a squash-merge (patch-id) |
| `sun viz` | self-contained HTML visualization, with replay from the beginning |
| `sun sessions [id] [--grep re] [--file p]` | search every session that ran here |
| `sun undo [--op ID] [--commit H]` | reverse any single operation or commit |

Real output for all of these, plus the refs layout, is in [EXAMPLE.md](EXAMPLE.md).

## 2 · Share sessions with your team's agents

Sessions live as git objects under `refs/sun/*`, never in your worktree and invisible to
`git status` and PR diffs. They travel with plain `git push` and `git pull`. On a
teammate's clone, `sun init` surfaces them, and their agents are pointed at
`.git/sun/sessions/` (the exact `~/.claude/projects` layout, now including teammates'
sessions) via a `SessionStart` context line and one line in `CLAUDE.md` or `AGENTS.md`. An agent
debugging auth can read the session where auth was built, whoever's machine it ran on. No
server needed.

## Demos & tests

```sh
python3 example/demo_init.py   # pick any repo you've used Claude Code on -> timed sun init
python3 example/demo_fresh.py  # synthetic end-to-end story -> example/demo.html
python3 -m unittest test_sun   # 33 tests
```
