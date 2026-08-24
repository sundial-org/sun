#### Getting started with `sun`

Install the CLI via a curl command

- Will install the `sun` CLI and modify agent hooks
  - detect Claude → edit .claude/settings.json, detect Cursor → edit .cursor/hooks.json, etc.

`sun init` will initialize everything a user's folder will need

- A git repository
- Initial .git/sun state
- Import of existing sessions (see *3_init and storage.md*)

It can work with various editors. The curl command installation route will work with supported harnesses. For non-supported harnesses, users can probably get the agent to edit its own hooks to use `sun`.

#### Human edits

To detect human edits, we run file diff checks during agent hooks.

These are some examples of hooks that Claude Code has

- SessionStart
- UserPromptSubmit
- PreToolUse
- PostToolUse
- Stop

And many more!

The more hooks we run these file diff checks on, the more granular user edits we'll get. However, I don't believe we need user edits to be that granular.

- Very granular edits (such as character, or even word level edits) are not that high signal
- Since `sun` is a CLI and harness hook tool, and doesn't control a user's editor, we cannot generate CRDT operations or state to prevent merge conflicts anyways.
- Running a filesystem watcher is not very practical because it's not clear when to start/stop watching for human edits.

This is inspired by Jujutsu (https://github.com/jj-vcs/jj) and Entire (https://entire.io). Jujutsu detects file edits whenever a `jj` command is run, and Entire checks the git state before and after an agent turn (one user prompt + one agent response).

Since we plan to run `sun` commands in agent hooks, we'll get the same effect. Whenever a human or an agent hook triggers a `sun` command, we'll detect changes in files and commit the human edits. In between an agent tool call end and an agent tool call start, we can commit the human changes.

Whenever a human edit has been detected by a `sun` command, we'll create a commit on the branch the human edit was made on.
Typically, this will be main. However, a human can checkout an agent branch or go on a collaborator's branch and make edits on top of it.

#### Agent edits

The same thing can be said for detecting agent edits.

1. At the start of an agent tool call, in PreToolUse, we can record the `git` state before.
2. Then, an agent, let's call it `Agent A`, works.
3. At the end of the tool call, in PostToolUse, the hook payload already tells us the tool, its input file and its tool_use_id; we compare the `git` state before vs after. (Transcripts are still read, but for session storage and import-time backfill — see *3_init and storage.md* — not for live attribution.)
4. We create a commit, and record `Agent A` changes as an "event".

We want a commit per tool call, that gets squashed into a commit per turn. This is kind of like the commits that get edited in jujutsu, but get saved in the operation log. These commits should still be stored, but in git, it should be squashed into commits per turn.

The reason why an agent edit is a commit and not a branch (contrary to what Belinda suggested) is for simplicity in the case of many agents running at once. A local git repo can only be on one branch at a time, unless there are multiple worktrees. To support `Agent A` and `Agent B` running at the same time in separate branches, they would need to be in separate worktrees, or we would have to switch between branches at the right time. The problem with these approaches is that in an agent like Claude, if `Agent A` and `Agent B` are running at once, they can actually detect each others edits, as well as human edits, causing the agent sessions to update on their own. Users should have the option to create worktrees for isolation, but I view isolation and attribution as separate problems. We should not force isolation to be able to properly attribute agent and human edits.

If another agent `B` starts making edits during `Agent A`'s tool call, a few things can happen

1. `Agent B` tool call finished before `Agent A` : `Agent B` creates a commit and an event for itself pointing to the commit, then `Agent A` finishes, creates another commit and a event for itself. The system works fine.
2. `Agent B` tool call finished after `Agent A` : reverse of ^

If another human `H` starts making edits during `Agent A`'s tool call:

1. `H` finished before `A`: nothing happens when `H` is done because the hook is run after `A` is done. We'll log `A`'s edits and everything not changed by `A` is attributed to `H`. Create events for both A and H.
2. H finishes after A: We'll only log an event for A, and we'll log for H when the next sun command is run.

These types of conflicts will be rare. If we decided to make the commits happen per turn, then there would be more opportunity for conflicts since turns can take minutes to hours.

One thing to make sure of: concurrent agent work can edit our operation log in .git/sun while working concurrently. You might want to think about how git makes it possible to have many terminal sessions or agent session run git commands at the same time.

This also conflicts a bit with the blog post's idea of having a separate commit per human and agent. Again, since we don't control when we log human commits, and we commit during agent hooks, the state change from one agent hook to another agent hook run can include changes from humans and agents.

We can maybe explore running a diff check before the agent's edit tool. Maybe if we commit everything before an agent's edit tool and after its edit tool, we can always capture human edits in their own commits, not mixed with agents. But again, if the edits happen at the exact same time, I'm not sure what will happen.

#### Suggestions

We create a `git` branch when we want to branch off from a state to edit it. This means the branch can get stale.
Avoid implementing suggestions for now.

#### Logging changes

These are the previously mentioned "events" in .git/sun/.

To support a commit possibly attributing to multiple users and agents, we need to store observed "events".

These events point to commits. Multiple events can point to the same commit.
Actors and attribution methods follow *3_init and storage.md*, which is authoritative: `<user>/<source>` actors and methods `hook`, `import`, `transcript_backfill`. The examples below use that scheme.

```
{
  "id": "a125",
  "type": "edit",
  "actor": "emma/local",

  "commit": commit-hash

  "edits": [
	{
	  "file": "foo.ts",
	  "patch": "@@ -10,2 +10,2 @@\n-const name = \"Alice\";\n+const name = \"Emma\";\n console.log(name);",
	  "attribution": { "method": "hook" },
	  "char_edits": [
	    {
	      "old_line": 10,
	      "new_line": 10,
	      "old_range": [14, 19],
	      "new_range": [14, 18],
	      "old_text": "Alice",
	      "new_text": "Emma"
	    }
	  ]
	}
  ]
}

{
  "id": "a124",
  "type": "edit",
  "actor": "emma/agent:claude/session123",
  "timestamp": "...",
  "turn": "turn7",

  "commit": commit-hash

  "edits": [
    {
      "file": "foo.ts",
      "patch": "...",
      "tool_call_id": "tool42",
      "attribution": {
        "method": "hook",
      }
    }
  ],

  "tool_calls": [
    {
      "id": "tool42",
      "tool": "Edit",
      "input": {
        "file": "foo.ts"
      }
    }
  ]
}


This makes sense
```

```
human edits
human edits
human edits

PreToolUse(Edit)
    ↓
Sun snapshots/commits all current dirty state
    ↓
everything before this point = human
    ↓
agent Edit runs
    ↓
PostToolUse(Edit)
    ↓
Sun records pre-tool → post-tool diff
    ↓
everything in this diff = agent

Also, I think if there is some conflict between agent tool call and human edit, it's fine, we can still record the agent tool call changes and overlay those diffs and realize that the human made it instead. 

Entire actually just stores
- **Checkpointed file state**
    - During a session, Entire creates ephemeral checkpoints containing the **full worktree state** on a shadow branch.
    - After the user makes a Git commit, that gets condensed into a permanent checkpoint linked to the Git commit.
- **The raw agent transcript**
    - `full.jsonl` stores the agent session, including prompts, responses, tool calls, etc.
    - Entire can parse that transcript to learn things like which files the agent touched

It's actually kinda expensive for entire 
checkpoint C1
├── repo state
└── transcript: messages 1–10

checkpoint C2
├── repo state
└── transcript: messages 1–11

checkpoint C3
├── repo state
└── transcript: messages 1–12

```