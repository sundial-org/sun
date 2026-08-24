#### `sun init` will initialize everything a user's folder will need

- A git repository
- Initial .git/sun state
- Import of the folder's existing agent sessions, so a repo with history + chats is connected from day one:
  - Find transcripts for this folder. One repo maps to many `~/.claude/projects/` dirs: the root (`-Users-bmo-sundial-md`), every Claude worktree (`-Users-bmo-sundial-md--claude-worktrees-<name>`), every `git worktree list` path, and symlink/realpath variants. Take every project dir whose encoded name is the encoded repo root, starts with `<encoded root>--claude-worktrees-`, or is the encoded form of a git worktree path. Include nested subagent transcripts. Store them under `refs/sun/sessions/<user>/<session-id>` (owned by the importing git user, chunked per turn; see *Sessions*).
  - Backfill attribution over existing commits by matching each commit's files against Edit/Write tool calls in the transcripts within a time window (`attribution.method: "transcript_backfill"`). History is never rewritten; commits with no matching transcript are `<author>/local`.
  - Idempotent: rerunning `sun init` / `sun import` only picks up new sessions and commits.
  - Fast: must feel instant even with hundreds of transcripts (GBs). Skip already-imported files by (size, mtime), stream-parse only tool_use lines, hash blobs once. Benchmark on `sundial-md` (~100 project dirs) and keep the number in the README.
  - Prints a summary (`imported 7 sessions, 3 subagents; attributed 42/60 commits`) and, on first run, the CLAUDE.md prompt described in *Sessions*.
  - Ends by writing `sun viz` to `.git/sun/viz.html` and printing a clickable link (`open file:///.../.git/sun/viz.html` to see your history), so the first thing a user sees after init is their repo's history with sessions attached. Under `.git/` so it never shows in `git status`.

Actors are `<user>/<source>`. `<user>` is the git user (`user.name`) on whose machine the change happened: it owns every event, agent or not. `<source>` is what we actually observed; `attribution.method` says how.

| actor | method | meaning |
| --- | --- | --- |
| `<user>/local` | `hook` | a change on `<user>`'s machine not made by a tracked agent (editor, script, untracked agent; we don't claim it was the human) |
| `<user>/local` | `import` | pre-existing commit, no transcript matched |
| `<user>/agent:<harness>/<session>` | `hook` | PreToolUse→PostToolUse diff of a tracked agent run by `<user>` |
| `<user>/agent:<harness>/<session>` | `transcript_backfill` | pre-existing commit matched to a transcript at import |

#### Sessions

Sessions that run locally are tracked in git and travel with the repo, pushed and fetched with it and shared with teammates, without appearing in `git status` and without the user thinking about them.

**Storage.** Raw transcripts (tool results included, nothing stripped) and the op log are plain git objects under custom refs, written with git plumbing and never checked out into the worktree (the same trick as `git notes` and GitHub's `refs/pull/*`). No LFS, no external store.

```
refs/sun/ops/<sha>                       per-tool-call commits
refs/sun/log/<user>                      events.jsonl, append-only, one writer
refs/sun/sessions/<user>/<session-id>    tree = turn-0001.jsonl, turn-0002.jsonl, ... (+ subagents/<id>/turn-*.jsonl)
```

- One ref per user per session, one writer each, so nothing ever needs merging. `sun log` merges the per-user logs by timestamp at read time.
- Transcripts are chunked per turn: the `Stop` hook appends one small blob for the new turn instead of rewriting the whole file, so pushes are cheap and no single object grows unbounded.
- Nothing in the worktree, so `git status`, `git log`, blame and PR diffs never see them. No `.gitignore` entry needed.
- `.git/sun/` is **not** tracked or pushed; nothing under `.git/` ever is. It is a per-machine cache (`events.jsonl`, `active.json`, the exported `sessions/` mirror) that `sun` can rebuild at any time from `refs/sun/*`, which are the source of truth. On a fresh clone, `sun init` fetches `refs/sun/*` and rebuilds `.git/sun` from them.
- Travel: `sun init` adds `+refs/sun/*:refs/sun/*` to the remote's fetch refspec, and installs a `pre-push` hook that pushes `refs/sun/*` as a separate, fail-soft push (so the user's normal `git push` semantics are untouched and a rejected sun push never blocks code).
- Squash-merge / rebase resilience: each edit event also stores its `patch-id`, so `sun show <squash-commit>` can match events by content when the original shas are no longer on the branch.
- Privacy: transcripts can contain pasted secrets, so `sun init` asks once (`track sessions in git? [Y/n]`) and `sun sessions --redact` / a `sun.sessions.exclude` glob are available.
- Retention: `sun gc --older-than <days>` drops old session refs so `git gc` can prune the objects.

**How agents use sessions.** `sun sessions export` (run automatically by the `SessionStart` hook and after fetch) joins each session's turn chunks back into one file at `.git/sun/sessions/<encoded-project-dir>/<session-id>.jsonl` (plus `<session-id>/subagents/` and `tool-results/`) and writes a merged `sessions-index.json` in the native schema with two extra fields, `user` and `origin: local|team`. The layout is byte-for-byte what `~/.claude/projects/` looks like, so whatever the harness currently does to find sessions (grep, index lookup, a search subagent) works unchanged on a superset that includes teammates' sessions. We never tell the agent *how* to search, only *where*; the method is the harness's business and changes between releases. `sun sessions [--file <path>] [--grep <re>] [<id>]` is a convenience over the same files. Agents are told about it in two places, both needed: the hook is Claude-only and its context is ephemeral; the file is durable and cross-harness:

1. The `SessionStart` hook injects one line: `sun: past sessions for this repo (yours + teammates') are in .git/sun/sessions/, not ~/.claude/projects; 12 sessions, 3 touching src/auth.`
2. A line in `CLAUDE.md`: `Past sessions for this repo, yours and other team members', are in .git/sun/sessions/ (same layout as ~/.claude/projects/, with a sessions-index.json). Look there instead of ~/.claude/projects/.`

Neither forbids the agent from using its own memory or `~/.claude`; they redirect the search. A skill is only added later if the one-liner proves insufficient.

**Where the line goes.** `CLAUDE.md` at the repo root, created if missing, appended to otherwise. No other files, no symlinks.

**When the user is prompted.** Once, at the end of `sun init` after the import summary: `sun requires one line in CLAUDE.md so agents find team sessions. Without it, sessions are tracked but agents will not use them. Add it? [Y/n]`. Enter or `y` writes it; an explicit `n` skips and prints `run sun init --claude-md later to enable team session sharing`. It is a normal worktree edit, committed as `<user>/local` and reviewable in the PR that introduces sun. `sun init --claude-md` / `--no-claude-md` for scripts. Never on hook runs, never silently; if the line is later removed, `sun doctor` mentions it but does not re-add it.





Out of scope

- LFS backend for very long transcripts. Transcripts compress only ~2x (sundial-md: 99 sessions, 485 MB raw, 209 MB compressed, largest 31 MB compressed), so a busy team will eventually want the bytes out of the object store. Same ref layout, the turn blobs become LFS pointers, fetched lazily on `sun sessions <id>`.