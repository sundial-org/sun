# Sun Review 2

An experimental review of your own agent's work, separate from `sun review` and
`sun review --inbox`. One repository, threads, turns, then exact operation diffs.

```sh
sun review2 --prepare /tmp/my-review
sun review2 --open /tmp/my-review
```

The capture uses `sun data` and its resolved native session paths. Missing prompts
stay explicitly unavailable. Every recorded operation edit stays reachable,
including intermediate edits subsequently undone. This first version uses
operation-level text diffs. Rich binary document previews are not yet integrated.
The captured history is fixed; capture again to see subsequent work.

For a design demo without personal transcripts:

```sh
python3 examples/review2/make_demo.py /tmp/review2-example
python3 -m sun review2 --open /tmp/review2-example --no-browser
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

## Agent highlights and review progress

Preparing a workspace also writes `prompt.md`. Ask the current agent to read that
and `snapshot.json`, then write `selection.json`. No additional model service is
required. Apply its output with:

```sh
sun review2 --open /tmp/my-review --select /tmp/my-review/selection.json --json
sun review2 --open /tmp/my-review
```

Selections must classify every turn and change exactly once, reference the exact
snapshot, and supply explanations for highlights. Invalid or incomplete selections
are rejected. Without one, the pane shows all changes. Agent explanations are
judgments, not recorded check results.

`Mark highlights reviewed` acknowledges only the highlighted change IDs. Expand
other changes to use `Mark turn reviewed`. Undo reverses that scope. Neither action
changes source files or submits a GitHub review. Review state persists in the
workspace's `review.sqlite`, independently of browser storage or the random URL.
A new workspace starts a separate review. Cross-capture progress and live refresh
are deliberately deferred in this prototype. Captured content never silently moves.

## Local Codex plugin

Install this checkout with Python 3.10+ and the optional official MCP SDK:

```sh
uv pip install -e '.[review2-plugin]'
python -m sun.review2_mcp /tmp/my-review --package /tmp/sun-review2-plugin
```

The generated package contains a compatible `.codex-plugin/plugin.json`, the
review skill, and `.mcp.json` with the current Python interpreter and a single
absolute workspace path. Keep that interpreter, package, and workspace available.
Packaging does not install or enable anything or modify personal Codex settings.
Add the generated folder to a local Codex marketplace to install it. See the
[official local plugin instructions](https://developers.openai.com/plugins/build/plugins#install-a-local-plugin-manually).

The MCP tools read this snapshot, save validated highlights, and return the same
local browser pane. There is intentionally no tool to claim human review. The
browser server lives until the MCP connection closes. The current adapter does
not embed an MCP Apps widget; its returned URL can open in the host browser or a
normal browser. No second model/API key or external hosting is required.

Run `python -m unittest test_review2 test_review2_mcp` in the SDK environment. The
integration test initializes a real stdio session, lists tools, reads the snapshot,
rejects an invalid selection, saves a valid one, and fetches the browser pane.
