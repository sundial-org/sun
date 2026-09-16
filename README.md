# sun

`sun` is a simple git extension that lets you:

1. See who made every change in your repo: you, or a specific Claude Code or Codex session and turn
2. Share your Claude or Codex sessions with your teammates through the repo, so their future sessions can search across your team's work, using a lightweight hook

Local Claude and Codex already have built-in memory by searching past chats, but they can't see your teammate's chats, containing important decisions and actions. `sun` gives an additional level of versioning past git commits, built for both people and Claude Code / Codex. Raw conversations stay local unless you explicitly share them.

# Getting started

Install:

```
uv tool install git+https://github.com/sundial-org/sun
```

Set it up in your repo:

```
cd your-repo && sun init
```

`sun init` sets up every harness it detects (Claude Code, Codex; `--claude` or `--codex` restricts to one), installs their hooks, and asks you:

- Share raw agent transcripts with everyone who can read this remote? Default no, because transcripts may contain prompts, tool output, file contents, and secrets. We recommend yes for private repos or research experiments. `--share-sessions` and `--no-share-sessions` skip the question.
- If you share: add one line to `CLAUDE.md` / `AGENTS.md` so agents look in the team's sessions?

This works best if every member of the team runs `sun init` once on their machine: git does not clone hook or refspec settings. Codex asks you to review and trust the new project hooks through `/hooks` before it runs them.

# Example (to review)

[Try example here](examples/demo_plan.py): `python3 examples/demo_plan.py` replays everything below.

Alice uses Claude Code and Bob uses Codex. They share one repo and one file, `EXPERIMENT_PLAN.md`. Both ran `sun init --share-sessions`.

1. Alice's Claude writes the plan. alice commits and pushes.
2. Bob's Codex adds a "Not measuring" section, and leaves latency out. bob commits and pushes.
3. Alice pulls.

**Without sun:** Alice's next Claude session cannot see why latency was left out. That conversation is on Bob's laptop.

**With sun:** the log shows both agents, and the conversation behind Bob's line came along with the pull:

```
$ sun log
a7ca821 2026-09-15 sun: bob/agent:codex/d9b0f5e1 turn 1 (1 tool calls)  [bob/agent:codex/d9b0f5e1 turn1]
2f89e83 2026-09-15 sun: alice/agent:claude/7c1e42ab turn 1 (1 tool calls)  [alice/agent:claude/7c1e42ab turn1]
0152f22 2026-09-15 sun: initial state  [alice/local]
```

Alice's next Claude session starts with one line in its context, from the hook:

```
sun: past sessions for this repo (yours + teammates') are in .git/sun/sessions/, not ~/.claude/projects; 2 sessions
```

When Alice asks why latency is not measured, her Claude reads Bob's Codex conversation instead of guessing:

```
$ sun blame EXPERIMENT_PLAN.md 17
EXPERIMENT_PLAN.md:17  a7ca821e  bob/agent:codex/d9b0f5e1 turn1  op c1ed957f
> - Latency
session d9b0f5e1-0000-4000-8000-000000000002 (turn-0001.jsonl):
user: Add a Not measuring section to EXPERIMENT_PLAN.md.
agent: Leaving latency out: both models run in a nightly batch job, so speed per request does not matter for this decision.
[apply_patch call_d9b0f5e1]
```

In summary, these are the memory actions that `sun` enables:

| Action | What it gives you |
| --- | --- |
| `sun log` | git log with each commit's actor: a person, or an agent session and turn |
| `sun blame <file> <line>` | the conversation behind a line, not just the commit |
| `sun sessions [--grep]` | list, search, and read every session your team has shared |
| `sun show <commit>` | the operations recorded for one commit |
| `sun viz` | interactive terminal history; `--html` writes a self-contained page |
| `sun undo` | undo one operation, or a whole commit |

(`init`, `sync`, `merge`, `import`, `gc`, `export`, and `update` handle setup and maintenance; `hook` is the internal entrypoint the harnesses call.)

A second example, one person running twelve agents at once and a teammate running none, is in [examples/twelve-agents.md](examples/twelve-agents.md).

# How it works

sun keeps its own history under `refs/sun/heads/main`, next to your branches but never on them: one preserved commit per agent tool call and one aggregate commit per turn, with human edits observed during a turn attributed separately inside it. It never moves `HEAD` or the real index, and nothing shows up in `git status`, PR diffs, or GitHub's branch history. Existing commits stay untracked because sun did not observe them. The pre-push hook publishes sun's history with your normal `git push`, `git pull` fetches it into `refs/sun/remotes/origin/main`, and `sun merge` joins divergent histories after you resolve the normal worktree. Shared transcripts live under `refs/sun/sessions/*`, travel the same way, and can be inspected with plain git by anyone who can read the remote.

`sun viz` stays in the terminal. Use `j`/`k` to move through commits, `J`/`K` to scroll details, left/right to move the replay boundary, `r` to replay from the beginning, and `q` to quit. Each commit shows its native git author alongside sun's observed actors. A `sync` attribution means a sun command discovered an uncaptured dirty edit later, not that a hook observed the edit when it happened.

# Demos & tests

```sh
python3 examples/demo_plan.py    # the story above, two people and two agents -> examples/demo-plan/
python3 examples/demo_twelve.py  # twelve concurrent sessions, one teammate with none -> examples/demo-twelve/
python3 examples/demo_init.py    # pick any repo you've used Claude Code on -> timed sun init
python3 examples/demo_fresh.py   # synthetic end-to-end story -> examples/demo.html
python3 -m unittest test_sun     # full test suite
```
