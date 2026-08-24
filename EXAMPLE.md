# A five-minute tour of sun

Everything below is real output from a repo where one Claude session (`9f2b41aa-...`) wrote
`src/auth.ts` and `src/auth.test.ts` in one turn, and a human edited `src/app.ts` around it.

## The log: every commit has an actor

```
$ sun log
156c86f 2026-08-23 sun: belinda/local edits  [belinda/local]
ab49563 2026-08-23 sun: belinda/agent:claude/9f2b41aa turn 1 (2 tool calls)  [belinda/agent:claude/9f2b41aa turn1]
81bb700 2026-08-23 sun: initial state  [belinda/local]
```

The agent's turn is one commit on the branch (two tool calls squashed at `Stop`). Human
edits are detected jj-style whenever any sun command or hook runs, and committed as
`<user>/local`. `[untracked]` marks commits sun knows nothing about.

## A commit's events: `sun show`

Events live in the operation log and point at commits; several events can share one commit
(for example an agent edit plus a concurrent human edit).

```
$ sun show ab49563
commit ab49563  2026-08-23
sun: belinda/agent:claude/9f2b41aa turn 1 (2 tool calls)

 src/auth.test.ts | 1 +
 src/auth.ts      | 1 +
 2 files changed, 2 insertions(+)

{
  "id": "98e465bf",
  "timestamp": "2026-08-23T19:50:41-0700",
  "type": "edit",
  "actor": "belinda/agent:claude/9f2b41aa",
  "turn": "turn1",
  "commit": "ab49563cea9a5d0930748b534530d4b4724b9d83",
  "patch_id": "d620b5a4ec9f5efcc4a76d1143463065899b7fed",
  "squashes": [
    "ea22a7ed",
    "a22b9b9f"
  ],
  "tool_calls": [
    {
      "id": "toolu_01auth.ts",
      "tool": "Write",
      "input": {
        "file": "src/auth.ts"
      }
    },
    {
      "id": "toolu_01auth.test.ts",
      "tool": "Write",
      "input": {
        "file": "src/auth.test.ts"
      }
    }
  ],
  "edits": [
    {
      "file": "src/auth.test.ts",
      "patch": "diff --git a/src/auth.test.ts b/src/auth.test.ts\nnew file mode 100644\nindex 0000000..96f56ed\n--- /dev/null\n+++ b/src/auth.test.ts\n@@ -0,0 +1 @@\n+export const login = (u: string) => sign(u);\n",
      "attribution": {
        "method": "squash"
      }
    },
    {
      "file": "src/auth.ts",
      "patch": "diff --git a/src/auth.ts b/src/auth.ts\nnew file mode 100644\nindex 0000000..96f56ed\n--- /dev/null\n+++ b/src/auth.ts\n@@ -0,0 +1 @@\n+export const login = (u: string) => sign(u);\n",
      "attribution": {
        "method": "squash"
      }
    }
  ]
}
```

`squashes` names the per-tool-call operations folded into this turn commit; each of those
still has its own commit, kept reachable under `refs/sun/ops`, so `sun show`/`sun undo`
work at tool-call granularity. `patch_id` lets `sun show` find these events again after a
squash-merge or rebase moves the sha.

## The refs: how all of this travels

Everything sun stores is plain git objects under `refs/sun/*`: never in your worktree,
invisible to `git status` and PR diffs, mirrored by a fail-soft `pre-push` hook:

```
$ git for-each-ref refs/sun
d1b39989dd3065b361a2e58bc9156a61ae86621c blob	refs/sun/log/belinda
7e97628f17992637bf41f8a5f19eb35b2a6b3cb7 commit	refs/sun/ops/7e97628f17992637bf41f8a5f19eb35b2a6b3cb7
8fff77e1f4edf7b4ea533347c6fd398b388f8e33 commit	refs/sun/ops/8fff77e1f4edf7b4ea533347c6fd398b388f8e33
c037c811aa54bbe302929355aed2ca3614c94db9 commit	refs/sun/sessions/belinda/9f2b41aa-7c33-4e08-b1d4-2a9c55e0f817

$ git ls-tree refs/sun/sessions/belinda/9f2b41aa-7c33-4e08-b1d4-2a9c55e0f817
100644 blob 542b32a6fea75991ff893d99fe5c3607c00bf952	turn-0001.jsonl
```

- `refs/sun/log/<user>`: that user's events.jsonl (one writer each; merged at read time)
- `refs/sun/ops/<sha>`: per-tool-call commits that survived the turn squash
- `refs/sun/sessions/<user>/<id>`: the raw transcript, one small blob appended per turn

## Sessions: stored, searchable, shared

```
$ sun sessions
9f2b41aa-7c33-4e08-b1d4-2a9c55e0f817  belinda  1 turns
```

`sun sessions export` (run automatically at `SessionStart`) mirrors these to
`.git/sun/sessions/` in the exact `~/.claude/projects` layout, including your teammates'
sessions after a `git pull`, so whatever your agent already does to find past sessions
works unchanged on the whole team's history.

## The visualization

`sun viz` writes a single self-contained HTML file: the attributed log on the left, a
commit's operations and patches on the right, and a replay slider across the top.

![sun viz](example/viz.png)
