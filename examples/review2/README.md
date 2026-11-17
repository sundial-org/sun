# Sun Review 2

An experimental review of your own agent's work, separate from `sun review` and
`sun review --inbox`. One repository, threads, turns, then exact operation diffs.

```sh
sun review2 --prepare /tmp/my-review
sun review2 --open /tmp/my-review
```

For a PR on the current checkout, scope the capture to its named base branch:

```sh
sun review2 --prepare /tmp/pr-review --base main --pr 'PR #42: Prepare the next release'
sun review2 --open /tmp/pr-review
```

This includes every recorded turn on the current Sun branch after the base's Sun
history, including intermediate edits later undone. The base needs a local or
remote Sun ref; missing attribution is never inferred from file similarity.
Git commit diffs and the net PR file diffs are captured separately from ordinary
Git HEAD relative to its merge base. Commit diffs use the first parent. Uncommitted
Sun turns remain accessible but are not represented as committed Git changes.
The PR title is a display label; this does not fetch a GitHub PR automatically.

The capture uses `sun data` and its resolved native session paths. Missing prompts
stay explicitly unavailable. Every recorded operation edit stays reachable,
including intermediate edits subsequently undone. This first version uses
operation-level text diffs. Rich binary document previews are not yet integrated.
The captured history is fixed; capture again to see subsequent work.

For a design demo without personal transcripts:

```sh
python3 examples/review2/make_demo.py /tmp/review2-example
python3 -m sun review2 --open /tmp/review2-example --select /tmp/review2-example/selection.json --no-browser
```

The example is entirely synthetic and marked `example` in the UI. It includes
multiple turns and both code and prose. `--open WORKSPACE --json` emits its data.
The random loopback URL is a local capability; keep it private.

Design: plain thread rows, one reading column, neutral surfaces, system type,
monospace only for code and paths. Relevant content should be visible without
opening a tab. Native disclosures reveal full evidence. No decorative cards,
badges, metrics, icon toolbar, or redundant headings. Keyboard focus is visible;
the sidebar stacks above the reader on a narrow screen.

Run `python3 -m unittest test_review2` and `node --check sun/review2_assets/app.js`.

## Summaries, checks, and human views

Preparing a workspace also writes `prompt.md`. Ask the current agent to read that
and `snapshot.json`, then write `selection.json`. No additional model service is
required. Apply its output with:

```sh
sun review2 --open /tmp/my-review --select /tmp/my-review/selection.json --json
sun review2 --open /tmp/my-review
```

Selections must classify every turn and change exactly once and reference the
exact snapshot. They supply summaries, inline highlights, and an ordered list of
priority check IDs with explanations. The agent chooses which checks deserve
attention; all recorded check results remain accessible and unchanged.
All files in pending turns remain visible regardless of the agent's selection.

The PR overview leads with agent-prioritized checks, then lists every contributing
turn grouped by thread. A turn opens its summary, relevant diffs, and explanations.
Turn diff, PR files, and commit links open full-page diffs with a file sidebar.
Opening
a file replaces the thread sidebar with a file sidebar. That deliberate navigation
automatically records its exact changes as `human-viewed`. Merely opening the
thread overview does not mark unseen files viewed. Once every file in a turn has
been viewed, the turn is marked human-viewed with its summary and highlights still
visible. Merely opening the combined turn or commit diff does not mark individual
files viewed. Select a file within a turn to record its exact operation diffs.

Checks come from Sun's recorded coverage, not generated explanations. Only exact,
whole-file passing coverage of every change and applicable rule can automatically
collapse a turn as checked. Missing rules, partial coverage, stale revisions,
failing results, and conflicts never qualify. Failures and conflicts remain
available even after human viewing, and disclosures show the original verdicts,
notes, actors, and citations. A view is exposure, not a test pass or GitHub approval.

Views persist in the workspace's `review.sqlite`, independently of browser storage
or the random URL. A new capture starts a separate workspace. Cross-capture
progress, live refresh, and rich document previews are deferred in this prototype.
