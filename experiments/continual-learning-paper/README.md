# Reviews in context or in weights: draft paper

**Superseded:** the completed new research cycles and illustrated rubric paper
are in [continual_learning](../continual_learning/README.md). This directory
preserves the earlier pilot-only report and its original evidence.

- [Draft paper](output/pdf/draft-paper.pdf): three pages, including references.
- [Submission PDF](output/pdf/submission.pdf): draft plus one page with model paper, adapted outline, and revision notes.
- [Claim audit](CLAIMS.md): 65 individually checked assertion blocks, including every table value.
- [Sources](SOURCES.md): primary literature, pinned experiment commits, exact source locations, and evidence limits.
- [Editable LaTeX](paper.tex) and [submission notes](submission-notes.tex).

The draft reports completed pilots and labels the v3 follow-up as unexecuted.
Its 2,042 body words meet the requested half-length target of 2,000-2,500.
The word-count method is recorded in `evidence/word-count.json`; the separate
claim audit and submission notes do not count toward paper length.

## Reproduce without provider calls

From this directory, with Python packages `numpy` and `pypdf` and a complete
LaTeX distribution:

```sh
python verify_evidence.py
python build.py
```

The build uses the assignment-linked official CVPR style, with standard paper
fonts and no margin or font-size compression. It needs `silence`, `enumitem`,
`cleveref`, Times, Helvetica, and Courier in addition to the usual LaTeX packages.
The unmodified `cvpr.sty` is in `vendor/`; `build.py` adds it to `TEXINPUTS`.
Overleaf can compile `paper.tex` if the style is placed next to it, or if
`vendor/` is added to its TeX input path. Include `evidence/curve-table.tex`.

The bundled runtime used here was:

```sh
TEXMFHOME=/private/tmp/continual-texmf \
TEXINPUTS=/private/tmp/continual-tex-deps//: \
/Users/bmo/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 build.py
```

Those temporary package directories are local build dependencies, not necessary
on a machine with the required LaTeX packages installed. The PDF build checks
page count, unresolved references and overfull boxes. Render the final PDFs with
`pdftoppm` and visually inspect them after editing.

## Evidence and maintenance

`verify_evidence.py` reproduces every displayed numerical comparison from compact
sample-level records, checks training-manifest and split counts, and reconciles
the results with the committed writing analysis. It covers 10,368 writing samples,
1,536 selection candidates and 6,480 Lean reports. It also verifies snapshot and
claim-text hashes. `render_audit.py` renders the separately reviewed records into
`CLAIMS.md`; it refuses stale claim hashes and does not reapprove claims.

When changing prose, revisit the corresponding justification in
`claim-checks.json` and update its text hash only after checking the revised claim.
New assertions need new claim IDs. All table cells are generated from verified
data under T01. The source macro `\claim{ID}{text}` keeps audit IDs out of the PDF.

To recreate compact records from the original local archives:

```sh
python collect_evidence.py
python verify_evidence.py --check-archives
```

Collection reads the untracked `exp_lean/` and `exp_writing/` archives, and checks
their sources against pinned Git commits. It does not edit those directories.
The raw archives and adapters are not embedded in this draft bundle. Portable
verification needs only the compact records and snapshots in `evidence/`.

The audit recomputes arithmetic from the original writing scorer's rule flags;
it does not substitute for a human check of linguistic judgments. Lean truth was
rederived from saved compiler receipts, not newly compiled. No new inference,
training, human review, or revised-protocol result is claimed.

## Review record

A fresh-reader review checked the distinction between completed and proposed
work, metric denominators, unsupported conclusions, and missing methods. The
draft was revised to identify the two guides as belonging to one editor, describe
the planted rules and applicability denominator, add the actual pilot training
recipe, explain the 16-sample selection pools, and label the shared-archive result
as held-out evaluation. The claim audit was updated after those edits.
