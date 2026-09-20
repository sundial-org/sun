# Collaboration experiments

These scenarios invoke the actual Sun CLI, agent hook payloads, separate working clones,
and a local bare remote. No mocks, GitHub credentials, VMs, or new dependencies.
They do not call a live model: agent tool boundaries are supplied as harness JSON.

The scenarios now exercise independent Sun publication, without Git commit checkpoints.

## Run later

From the Sun source checkout, choose a new output path:

```sh
python3 experiments/collaboration.py --output /tmp/sun-experiment-01
python3 experiments/collaboration.py --output /tmp/sun-experiment-10-users --scenario many-users --users 10 --seed 41
```

The output must not exist. The runner never reuses or deletes an existing repo.
Each scenario keeps a bare remote, every user's working clone, an isolated CLI
launcher, and an `actions.jsonl` recording commands, edits, results, and hook payloads.
`report.json` distinguishes PASS, FAIL, and SKIP. Failures keep the repositories too.
Open any clone to inspect `git log --graph --all` and `sun viz`.

For disposable unittest runs instead:

```sh
python3 -m unittest test_sun test_reliability test_collaboration -v
```

The unittest adapter removes only its own temporary fixtures. It includes 3, 5,
and 10 collaborators with two deterministic schedules. The standalone runner
defaults to five users, seed 17, and all scenarios. Neither runner runs on import.
Do not use Python's `-O`: the experiment checks use assertions.

## Coverage

| Case | Assertions |
| --- | --- |
| Two users on main | Alternating human and agent work; both edit before fetching; same-line conflict; rejected normal Git push; merge abort and retry; one Git resolution; independent Sun history joins preserve operations |
| One user, nested branches | Main, siblings, child and grandchild; inherited IDs; checkout isolation; observe fast-forward/non-fast-forward results; source operations retained on source branches, not automatically imported to target |
| Two users, nested branches | Parent advances while collaborator edits child; genuine parent/child conflict; integrate child to parent to main through Git; original operations remain in their source Sun histories |
| Multiple users | Everyone starts stale; shuffled publication; automatic nonconflicting merges; each forks a child; shuffled integration; all users also conflict on the same line and resolve through Git |
| Same Git identity on two computers | Separate clones using the same identity, divergent edits, conflict resolution, immutable operation IDs without duplicates |
| Partial commits | Recorded uncommitted work can be published; staged/unstaged hunks do not gate Sun; unrecorded files stay local; normal Git remote branch stays unchanged |
| Later and in-flight edits | Already recorded work publishes during an active call; receiver barrier lets a real edit happen during push; that unfinished edit stays out of publication; worktree and index survive |
| Atomic rejection | Normal Git divergence does not gate Sun; rejection of an operation rejects the Sun head as well; normal branches never change; lack of atomic support refuses without fallback |
| Selected branch and remote | Publish feature while checked out on private branch; unrelated main has advanced; explicit named remote; private operations stay local |
| Parallel agents | Separate hook processes edit distinct files; attribution retained; overlapping same-file writes are explicitly uncertain |
| Git independence and hook delivery | No Sun Git hooks installed; normal and empty commits leave all Sun refs unchanged, including during an active agent call; duplicate agent completion remains idempotent |
| Turn grouping | Human before turn remains separate; tool calls and intervening human edits squash with distinct original operations and snapshots; branch inheritance prevents rewriting shared operations |
| Normal Git state | Empty commits do not invent Sun edits; resetting a fixture is observed as a new state, not a rewrite or guessed human attribution |
| Session opt-in | No raw copies by default; explicit sharing publishes the latest recorded session independently of Git commits; unrelated branch sessions stay local |
| Checks/reviews from PR #26 | Two collaborators independently review the same check; both records remain unchanged; disagreement remains mixed |

Every collaboration convergence check verifies unique operation IDs, original
operation contents and actors, parent-before-child replay, and matching log/data
ordering. Clock-skewed commits deliberately oppose wall-clock order. Sibling
operations do not need a universal timestamp order; their causes must precede
them and both sides must precede the merge. Fetch/log alone must not integrate
remote history or change files. Sync must leave normal Git HEAD and index intact.

Existing regression tests retain failure/retry recovery, interrupted calls and
squashes, multiple identities in one checkout, linked worktrees, binary/unusual
paths, multi-file patches, Codex attribution, undo/restore, and transcript lookup.
Obsolete tests for a second Sun conflict-resolution workflow are replaced by
these real Git conflict scenarios.

## Explicit limits

- PR #26 is not in this stack's base. Checks/reviews are marked SKIP until those
  commands are present, not reported as passing coverage.
- Passing assertions cover only the stated cases, not a general proof of reliability.
- Local subprocesses exercise concurrency and Git receive hooks, not actual
  Codex/Claude hook approval, remote hosting policies, process-kill durability,
  arbitrary force-push recovery, or network partitions.
- Sun publication includes recorded attempts and undone edits, including uncommitted work.
  Opted-in raw sessions may include later conversation and cross-branch context.
- Git feature merges do not automatically combine source Sun ancestry into the target.
  Tests verify retained source records and observed target state separately, not inferred provenance.
