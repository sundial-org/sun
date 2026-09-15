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
Existing commits stay untracked because sun did not observe them. From then on, hooks keep an
independent Sun history current: one commit per agent tool call, squashed per turn, with local
edits detected in between. Sun commits share Git's object database but never move normal `HEAD`
or the real index, and they do not appear in GitHub's branch history. Codex asks you to review
and trust new project hooks through `/hooks` before it runs them.

Sun stores the shared history under `refs/sun/heads/main`. Normal `git pull` fetches it into
`refs/sun/remotes/origin/main`, and the pre-push hook publishes the local Sun tip without force.
`sun log`, `sun show`, `sun blame`, and `sun viz` read this history. A repository must be
initialized with Sun on each machine because Git does not clone local hook or refspec settings.

## 1 · Analyze your past sessions

| command | what you learn |
| --- | --- |
| `sun log` | git log annotated with the actor and turn behind each commit |
| `sun show <commit>` | a commit's events and patches, even after a squash-merge (patch-id) |
| `sun merge` | join divergent Sun histories after resolving the normal worktree |
| `sun viz` | interactive terminal history with commit and operation attribution |
| `sun viz --html [-o path]` | optional self-contained HTML export |
| `sun sessions [id] [--grep re] [--file p]` | search every session that ran here |
| `sun undo [--op ID] [--commit H]` | reverse any single operation or commit |

`sun viz` stays in the terminal. Use `j`/`k` to move through commits, `J`/`K` to scroll
details, left/right to move the replay boundary, `r` to replay from the beginning, and `q` to
quit. Each commit shows its native git author alongside Sun's observed actors. Operation
details identify the human or agent that generated them, including harness, session, turn,
tool call, attribution method, files, and patches. Squashed turns retain their individual
generated operations.

## 2 · Optional raw session sharing

Pass `--share-sessions` to store raw transcripts under `refs/sun/sessions/*` and share them
with everyone who can read the git remote. This is off by default because transcripts may
contain prompts, tool output, file contents, environment data, and secrets. Shared sessions
stay outside normal branches and PR diffs, but collaborators can inspect them with git.

## Demos & tests

```sh
python3 examples/demo_init.py   # pick any repo you've used Claude Code on -> timed sun init
python3 examples/demo_fresh.py  # synthetic end-to-end story -> examples/demo.html
python3 -m unittest test_sun    # full test suite
```
