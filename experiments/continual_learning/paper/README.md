# Learning a Writing Rubric from Edits: Context or Weights?

- [Draft paper](output/pdf/draft-paper.pdf): four pages, 2,384 body words.
- [CS197 submission](output/pdf/submission.pdf): draft plus one notes page.
- [Claim justifications](CLAIMS.md): all 80 assertion blocks, including figures,
  tables, references and notes, with source locators and scope limits.
- [Editable source ZIP](output/rubric-paper-source.zip): LaTeX, vector figures,
  tables and claim records. Full raw evidence remains in this directory.
- [Sources and limits](SOURCES.md) and [reader review](reader-review-primary.md).

The paper follows normal research sections. The requested half-length target
is 2,000-2,500 body words, half the CS197 final-paper recommendation. References
and appended notes are excluded; captions and table entries are included. See
`evidence/word-count.json` for the counting procedure.

The new experiment includes 9,744 writing episodes, 896 public instruction
responses and 18 trained adapters. `evidence/verification.json` records the full
offline replay and statistical checks; `evidence/build-check.json` records the
final PDF and visual review. The older editor-creation replay has unresolved
discrepancies, retained separately and explained in C55 and SOURCES.md.

## Reproduce without model calls

With Python containing NumPy and pypdf, plus pdfLaTeX and the CVPR dependencies:

```sh
python build.py
python package_source.py
```

The build checks the evidence, claim coverage, reviewed hashes, word count,
pages and LaTeX diagnostics. After editing, render and inspect every final page
again; a successful build alone is not a new visual review. Claim wording or
figure changes require renewed factual review before updating hashes.

The source uses `\claim{ID}{text}` to connect invisible IDs to `CLAIMS.md`.
`claim-checks.json` is the authoritative reviewed ledger. The separate
`*-justifications.json` files are drafting worksheets, not approved final ledgers.
The first four submission pages match the standalone draft. No external class,
venue or Overleaf submission has been made.
