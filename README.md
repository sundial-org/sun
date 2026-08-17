# sun

An operation log for humans + agents on top of git. Every change becomes a
commit attributed to whoever made it — humans are detected jj-style (a diff
check whenever any `sun` command or agent hook runs), agents are captured per
turn via harness hooks that compare git state and read the transcript's edit
tool calls. Events live in `.git/sun/events.jsonl` and point at commits; one
commit can carry several events (e.g. an agent edit + a concurrent human edit).

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

Planned next (see proposals): `env <commit>` to export a repo state as an RL
environment, `sft` to export SFT data from accept/reject and issues/PRs, and
review-granularity stats in the visualization.
