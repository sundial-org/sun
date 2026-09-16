# Twelve agents, and a teammate with none

alice needs twelve handbook pages written. She opens twelve Claude Code sessions in the same
checkout, one per page, and lets them run at once. bob does not use agents. He fixes one page
in his editor and pushes. Each ran `sun init --share-sessions` once.

1. alice runs `sun init --share-sessions` in a repo with twelve stub pages under `docs/`.
2. She starts twelve Claude Code sessions at the same time. Each writes its one page. Their
  hooks arrive interleaved. sun serializes them with a lock, and each session claims its
  file before writing, so every commit carries exactly one session's edit.
3. alice commits and pushes. The pre-push hook sends sun's history and her twelve sessions along.
4. bob clones, runs `sun init --share-sessions`, and adds a note to `docs/03-cli.md` by hand.
  `sun sync` records it as `bob/local`. He commits and pushes.
5. alice pulls:

```
$ sun log
8fc023a 2026-09-15 sun: bob/local edits docs/03-cli.md  [bob/local]
f2e1e18 2026-09-15 sun: alice/agent:claude/pg08cf1b Write  [alice/agent:claude/pg08cf1b turn1]
391cf50 2026-09-15 sun: alice/agent:claude/pg127097 Write  [alice/agent:claude/pg127097 turn1]
a526f99 2026-09-15 sun: alice/agent:claude/pg106ac5 Write  [alice/agent:claude/pg106ac5 turn1]
ae49e8b 2026-09-15 sun: alice/agent:claude/pg1177e5 Write  [alice/agent:claude/pg1177e5 turn1]
4733644 2026-09-15 sun: alice/agent:claude/pg05b9ce Write  [alice/agent:claude/pg05b9ce turn1]
cf8e099 2026-09-15 sun: alice/agent:claude/pg09e9c2 Write  [alice/agent:claude/pg09e9c2 turn1]
6138b45 2026-09-15 sun: alice/agent:claude/pg063fd1 Write  [alice/agent:claude/pg063fd1 turn1]
7eecc67 2026-09-15 sun: alice/agent:claude/pg03fac4 Write  [alice/agent:claude/pg03fac4 turn1]
250257f 2026-09-15 sun: alice/agent:claude/pg074757 Write  [alice/agent:claude/pg074757 turn1]
95531b1 2026-09-15 sun: alice/agent:claude/pg025c47 Write  [alice/agent:claude/pg025c47 turn1]
9e0e8e0 2026-09-15 sun: alice/agent:claude/pg04d653 Write  [alice/agent:claude/pg04d653 turn1]
39d559e 2026-09-15 sun: alice/agent:claude/pg011cb1 Write  [alice/agent:claude/pg011cb1 turn1]
d813497 2026-09-15 sun: initial state  [alice/local]
```

Fourteen commits, thirteen actors. Twelve are alice's sessions, each named by its session id,
in whatever order they finished. One is bob, who never touched an agent. A turn is squashed
into one commit at Stop only when no other session committed during it, which is why these
subjects say `Write` rather than `turn 1 (1 tool calls)`. The tag is the same either way.
Had bob skipped `sun init`, his note would still arrive with alice's pull, but sun would only
notice it at her next command, as an `alice/local` edit with attribution method `sync`. That
is why each machine runs `sun init` once.

## What the thirteenth agent sees

alice later asks a fresh session to expand the CLI page. Its `SessionStart` line says there are
twelve sessions to draw on:

```
sun: past sessions for this repo (yours + teammates') are in .git/sun/sessions/, not ~/.claude/projects; 12 sessions
```

It asks which of the twelve wrote this page, and gets that session's conversation:

```
$ sun blame docs/03-cli.md 3
docs/03-cli.md:3  7eecc677  alice/agent:claude/pg03fac4 turn1  op d04b4a89
> How cli works in sun.
session pg03fac4b598b1e74366b8df187b3c5ebd59 (turn-0001.jsonl):
user: Write the handbook page docs/03-cli.md.
agent: One short page. Keeping docs/03-cli.md to what a new user needs first.
[Write toolu_pg03fac4]
```

Then it hits the note at the bottom of the page and asks where that came from:

```
$ sun blame docs/03-cli.md 5
docs/03-cli.md:5  8fc023a5  bob/local  op 350ada61
> Note: the flag is `--claude`, not `--claude-only`.
human edit (bob/local): no conversation
{
  "id": "350ada61",
  "actor": "bob/local",
  "commit": "8fc023a50a62099ad9089ad2c9e9f986cd4b9708",
  "edits": [{"file": "docs/03-cli.md", "patch": "...+Note: the flag is `--claude`, not `--claude-only`.\n",
             "attribution": {"method": "sync"}}]
}
```

Agent lines come with the conversation behind them. Human lines come with who and the exact
patch. The agent now knows the note is bob's deliberate correction, not a leftover to clean up.

`python3 examples/demo_twelve.py` replays this with real threads, so the order varies per run.
