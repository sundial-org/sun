# Review inbox prototype

A dependency-free, standalone UI experiment. Five ranked PRs stay visible while
search and pagination reach the rest. Review questions, diffs, dependencies, and
check evidence share one white workspace.

## Run

From this directory:

```sh
python3 -m http.server 54810 --bind 127.0.0.1
```

Open http://127.0.0.1:54810. Requires a browser with native dialog support.

```sh
node test.mjs
node --check app.mjs
```

## Review action

Open **Settings** to choose what happens when you finish:

- **Mark reviewed locally** removes the item from this local queue. Undo restores
  it. This never submits a GitHub review.
- **Review on GitHub** opens an explicitly linked GitHub PR's files in a new tab.
  Submit approval on GitHub. Opening the link does not mark the item reviewed or
  claim an approval succeeded. Add the URL for each selected review; sample PR
  numbers are never automatically mapped to a real repository.

The setting and explicit links persist in local browser storage for this origin.
If storage is unavailable, the choice works for the current tab. Clearing the URL
and saving removes a link. GitHub Enterprise URLs are not supported by this demo.
These are UI settings, independent of Skills and excluded from the agent prompt.
Direct authenticated approval is not implemented.

## Skills and evidence

Security and Reliability preferences reorder the fixture queue. Selected skills
add expected checks without creating passing results. Importing a SKILL.md reads
its text into the downloadable **Ask agent** prompt; it does not execute the skill.
[DESIGN_PROMPT.md](DESIGN_PROMPT.md) is a manual design brief, not an installed skill
or an automatically loaded generator.

All PRs, authors, revisions, check results, explanations, and diffs are synthetic.
The 100-record fixture exercises pagination; the initial view shows only five.
There are no model calls, live GitHub data, or Sun check execution. Skill selections
and local queue completion reset on reload. This example is not wired into
`sun review --inbox` or distributed as a plugin.

## Validation

`test.mjs` checks ranking, completion filtering, required checks, revision evidence,
GitHub URL validation, explicit linking, and settings recovery. Browser validation
covers navigation, search, skills, handoff, local undo, settings persistence and
validation, and a 390px layout.
