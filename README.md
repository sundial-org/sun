# sun

An operation log for humans + agents on top of git. Every change becomes a
commit attributed to whoever made it — humans are detected jj-style (a diff
check whenever any `sun` command or agent hook runs), agents are captured per
tool call via harness hooks: `PreToolUse` commits everything dirty as human,
`PostToolUse` commits the pre→post diff as the agent's, and `Stop` squashes the
turn's tool-call commits into one commit per turn. The per-call commits stay in
the operation log (events in `.git/sun/events.jsonl` + `refs/sun/ops/*`), so
`sun show` / `sun undo --op` still work at tool-call granularity. One commit can
carry several events (e.g. an agent edit + a concurrent human edit).

## Install

```sh
./install.sh          # copies sun.py to ~/.local/bin/sun
cd your-repo && sun init
```

`sun init` creates the git repo if needed, snapshots the initial state, and
installs Claude Code hooks (`.claude/settings.json`). For other harnesses, ask
the agent to call `sun hook` from its SessionStart / UserPromptSubmit /
PreToolUse / PostToolUse / Stop hooks with the harness's JSON payload on stdin.

## Commands

| command | what it does |
| --- | --- |
| `sun init` | git repo + `.git/sun` state + agent hooks |
| `sun log [-n N]` | git log annotated with actors, sessions and turn numbers |
| `sun show <commit>` | the operations (events, patches, tool calls) behind a commit |
| `sun undo [--op ID] [--commit HASH]` | reverse one operation (default: latest) or revert a commit |
| `sun sync` | detect + commit pending human edits now |
| `sun viz [-o out.html] [-n N]` | self-contained HTML: branches, commits, per-actor stats, replay |
| `sun hook` | hook entrypoint called by the agent harness |

## Demos & tests

```sh
python3 example/demo_fresh.py        # fresh from-scratch demo -> example/demo(.html)
python3 example/demo_sundial.py      # real data: example/sundial-md clone + every
                                     #   ~/.claude session (incl. subagents) that ran
                                     #   in ~/sundial-md, + GitHub PRs/issues
python3 -m unittest test_sun -v
```

## Design notes

- **Concurrency**: like git's `index.lock`, every `sun` command/hook takes
  `.git/sun/lock` (flock) and `events.jsonl` is append-only, so parallel
  sessions/subagents serialize instead of tearing the log. A file named in
  `PreToolUse` is claimed before the write exists, so another session's sync
  can't attribute it to the human.
- **Attribution inside a tool-call diff**: for `Edit`/`Write`-style tools only
  the named file is the agent's; any other dirty file is a concurrent human
  edit (overlay) and gets its own event on the same commit. For other tools
  (`Bash`, ...) the whole diff is the agent's (`method: hook_diff`).
- **Squash is skipped** when a foreign commit (a human sync, another agent's
  tool call, a manual `git commit`) landed between the turn's first tool call
  and `Stop` — squashing would fold it into the agent's turn, so the per-call
  commits simply stay on the branch. A human overlay *inside* one of the
  agent's commits doesn't block it; its event is re-pointed at the turn commit.
- Suggestions (branching off a state) are deliberately not implemented yet.

Planned next (see proposals): `env <commit>` to export a repo state as an RL
environment, `sft` to export SFT data from accept/reject and issues/PRs, and
review-granularity stats in the visualization.
