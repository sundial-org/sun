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
