# Sun repository review

Review agent edits across every locally recorded Sun branch and session. The
monospace UI shows checked/unchecked edit counts, repository rules, a square for
each turn, and an unreviewed session queue with failures first. Open a session,
turn, or file to inspect the full recorded diffs.

```sh
sun review2 --prepare /tmp/my-review
sun review2 --open /tmp/my-review
sun review2 --open /tmp/my-review --tui
sun review2 --open /tmp/my-review --print
```

Preparation uses the same capture path as `sun data --all -n 0`, including its
resolved native transcript paths. It never guesses session directories or copies
native sessions into a collaborator cache. The capture is fixed, not a live feed.
Choose a new workspace to capture later work; an existing workspace is preserved.

## Checks and human review

- **Checked:** a current recorded check references the file change's operation or
  final turn revision. This includes failures and does not imply complete passing
  coverage of every intermediate line.
- **Unchecked:** no matching current result is recorded for that file change.
- **Unreviewed:** the person has not explicitly marked every change in the turn
  reviewed. Opening or explaining a diff does not mark it reviewed.

Rules come from the repository's `RULES.md`. Superseded results and results for an
outdated rule definition are excluded from current coverage counts. Any failed
check makes a turn red; additional failures deepen the red. Pass-only turns are
green, with deeper shades for more passes. Turns without results are gray.

Review clicks persist in the workspace's SQLite database and do not change check
verdicts. The terminal shows recorded evidence only. Use arrows or j/k to move,
Enter to open, Esc to go back, g to select a turn square, r to mark reviewed, and q
to quit. Arrow keys scroll long diffs horizontally; Page Up/Down scroll vertically.

The UI displays saved **AI assessments** beneath failed session/turn titles and
above a turn's diffs. The current chat agent writes these explanations after
reading the evidence. They are distinct from deterministic results. A missing
assessment is explicitly labeled. The agent should inspect later work before
claiming a failure remains relevant; this prototype does not automatically
suppress failures based on prose or an unrelated later pass.

## Inline chat plugin

Install the optional SDK with Python 3.10+:

```sh
python -m pip install -e '.[review2-plugin]'
python -m sun.review2_mcp /tmp/my-review --package /tmp/sun-review2-plugin
```

The generated package binds the current interpreter and checkout to one captured
workspace. It contains the skill and machine-specific configuration; none of
those local paths or captured data are shipped in the repository. Packaging does
not install or enable the plugin or change personal Codex settings.

The repository adapter provides `read_repository`, `read_turn`, paginated
`read_patch`, `save_explanation`, and `open_review`. The latter declares an MCP Apps
resource with inline display metadata. `review_turn` is app-only and reserved for
the person's explicit click. The skill tells agents never to invoke it.

Protocol handling is tested through a real stdio connection. Native inline
rendering still requires a compatible host and has not been verified in Codex.
The browser command above is the working fallback. No second model API key or
external hosting is required. The loopback URL is a local capability; keep it
private. Full patches stay in the workspace and load on demand.

## Illustrative demo

Run from a Sun repository so the rule definitions come from that repository:

```sh
python examples/review2/make_repository_demo.py /tmp/repository-example
sun review2 --open /tmp/repository-example
sun review2 --open /tmp/repository-example --tui
```

The history, verdicts, and saved example assessments are synthetic and clearly
labeled in the UI. With configured rules, it illustrates 395 edits, 151 checked,
and 244 unchecked. It contains no captured personal transcripts.

## Existing PR review

The earlier PR-specific workflow remains available:

```sh
sun review2 --prepare /tmp/pr-review --base main --pr 'Release review'
sun review2 --open /tmp/pr-review
```

This uses named Sun ancestry for turns and ordinary Git ancestry for net PR file
and commit diffs. The base requires local or remote Sun history. Existing captures,
`--select` plans, and their browser plugin continue to work. That older UI records
human-viewed state through explicit file navigation; repository captures use the
separate mark-reviewed action described above.

Run `python -m unittest test_repository_review test_review2 test_review2_mcp
 test_branches.RepositoryDataTest` and `node --check sun/repository_review_assets/app.js`.
