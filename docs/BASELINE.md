# Baseline comparison (T-22)

What the standard tools report on the 20 `noise_only` corpus pairs, measured rather than
asserted. Every pair is a real before/after capture of a page whose content did not change
(admitted by independent human review, D-021), so **every change any tool reports here is a
false positive** — with the two exceptions noted at the end.

Reproduce it:

```
python -m tests.baseline.report            # the tables below
python -m tests.baseline.report --json     # machine-readable
python -m tests.baseline.report --repeat 5
```

Measured on Python 3.12.10, Windows 11, lxml 6.1.3, selectolax 0.4.11, best of 5 runs.
Timings are wall clock for a whole pair (both snapshots) on one unquiet laptop: compare the
tools against each other, not against another machine's numbers.

## What each column is

| Column | Tool | What it stands in for |
|---|---|---|
| `difflib_lines` | `difflib` over raw HTML, line granularity | urlwatch's default, and any `diff`- or body-hash-based check |
| `difflib_words` | `difflib` over raw HTML, whitespace-token granularity | the same byte-level comparison, without the line metric's coarseness |
| `difflib_text` | `difflib` over extracted visible text, `<script>`/`<style>` removed | changedetection.io's model |
| `lxml_htmldiff` | `<ins>`/`<del>` markers from `lxml.html.diff.htmldiff` | the only HTML-aware differ in the Python standard ecosystem |
| `semdiff` | `normalize(old) == normalize(new)` | this project, at layer 1 |

Each number is "how many changes would this tool show a user". `0` means it reports nothing.

## Results

| pair | family | KiB | difflib_lines | difflib_words | difflib_text | lxml_htmldiff | semdiff |
|---|---|---:|---:|---:|---:|---:|---:|
| babeljs-io-001 | asset_hash | 55 | 1 | 2 | 0 | 0 | 0 |
| babeljs-io-002 | asset_hash | 55 | 1 | 2 | 0 | 0 | 0 |
| docs-python-org-001 | timestamp | 110 | 1 | 2 | 2 | 2 | 0 |
| docs-python-org-002 | timestamp | 58 | 1 | 2 | 2 | 2 | 0 |
| docs-python-org-004 | timestamp | 52 | 1 | 2 | 2 | 2 | 0 |
| docs-python-org-005 | timestamp | 58 | 1 | 2 | 2 | 2 | 0 |
| docs-python-org-006 | timestamp | 22 | 1 | 2 | 2 | 2 | 0 |
| docs-python-org-007 | timestamp | 79 | 1 | 2 | 2 | 2 | 0 |
| docusaurus-io-001 | asset_hash | 50 | 1 | 2 | 0 | 0 | 0 |
| docusaurus-io-002 | asset_hash | 65 | 1 | 3 | 0 | 0 | 0 |
| docusaurus-io-003 | asset_hash | 92 | 1 | 3 | 0 | 0 | 0 |
| docusaurus-io-004 | asset_hash | 61 | 1 | 3 | 0 | 0 | 0 |
| docusaurus-io-005 | asset_hash | 65 | 1 | 2 | 0 | 0 | 0 |
| pnpm-io-001 | asset_hash | 9 | 1 | 1 | 0 | 0 | 1 |
| pnpm-io-002 | asset_hash | 9 | 1 | 1 | 0 | 0 | 1 |
| reactnative-dev-001 | asset_hash | 96 | 1 | 2 | 0 | 0 | 0 |
| reactnative-dev-002 | asset_hash | 104 | 1 | 2 | 0 | 0 | 0 |
| reactnative-dev-003 | asset_hash | 96 | 1 | 1 | 0 | 0 | 0 |
| reactnative-dev-004 | asset_hash | 104 | 1 | 1 | 0 | 0 | 0 |
| redux-js-org-001 | asset_hash | 64 | 1 | 1 | 0 | 0 | 0 |

| tool | pairs flagged of 20 | total units | median ms |
|---|---:|---:|---:|
| `difflib_lines` | **20** | 20 | 1.8 |
| `difflib_words` | **20** | 38 | 82.3 |
| `difflib_text` | 6 | 12 | 22.0 |
| `lxml_htmldiff` | 6 | 12 | 103.1 |
| `semdiff` | **2** | 2 | 522.0 |

## What the numbers mean

**A raw diff flags every single pair.** Twenty unchanged pages, twenty reported changes. For a
monitoring tool that is twenty alerts nobody wanted, which is the complaint this project exists
to answer (changedetection.io #2548). SemDiff reduces that to two, and both remaining ones have
a known cause (below).

**The volume per alert is small, and that is not the point.** Each flagged pair differs by one
to three units, not "hundreds of changes". The problem is the false-positive *rate*, not the
size of each diff. Where the diff is large is in bytes a human has to read: on the Docusaurus
and React Native pages, the single line `difflib_lines` calls changed is **4.7–5.4 KiB of
minified markup** for an eight-hex-character hash change (10.3% of `docusaurus-io-001`'s whole
document). On the Sphinx pages it is 47 bytes. Corpus-wide, 53 KiB of 1302 KiB sits inside a
line the line differ reports.

**The two text-shaped tools are quiet on 14 pairs for the wrong reason.** `difflib_text` and
`lxml_htmldiff` both report 0 on every `asset_hash` pair — not because they neutralize build
hashes, but because they never look at `<head>` or at a `<script src>`. That silence is bought
by discarding information, and the cost is demonstrable (`tests/baseline/test_metrics.py`):

- a meaningful link change, `href="/buy/sku-1"` → `href="/buy/sku-2"`, is **invisible** to
  `difflib_text`;
- the *identical* hash noise moved onto an `<img src>` **is** flagged by `lxml_htmldiff`;
- `lxml.html.diff` drops `<head>` entirely, and passes a body `<script src>` change through
  **unannotated** — the output shows the new value and marks no change at all, which is worse
  than ignoring it.

So their 6/20 is a property of where this corpus's noise happens to live, not evidence that
they handle it.

## The tradeoff: SemDiff is slower

SemDiff is the slowest tool in this comparison by a wide margin — **522 ms** median per pair
against 103 ms for `lxml.html.diff` and 1.8 ms for the line differ: roughly 5× the HTML-aware
differ and 290× the byte-level one. That is the price of parsing both documents and running
every normalization rule over the tree, and more than 95% of it is the rule engine rather than
the parser (F-012). Three of the five largest corpus pages are over the NFR-3 budget of 100 ms
per page, and no optimization work has been done yet (F-009, F-012).

Stated plainly: **this benchmark buys a 10× reduction in false positives with a 5× increase in
runtime.** For a monitoring host checking thousands of pages, that trade needs to be a choice
made with numbers in hand, which is why both columns are published together. The slowness is a
known, unaddressed defect, not a design goal.

## The two pairs SemDiff still flags

`pnpm-io-001` and `pnpm-io-002` are false positives of SemDiff's own, with one cause: FR-44
matches lowercase-hex content hashes, and Vite emits base64url ones
(`/assets/index-CxL6fshY.js`). Both pairs were admitted to the corpus by independent review
knowing the ruleset could not yet neutralize them, and both are `xfail(strict=True)` in
`tests/corpus/test_noise_only_gate.py`, so extending FR-44 will make those tests fail until
the exemption is removed. No rule was changed to improve this table.

## What this benchmark does not measure

- **Recall.** Every pair here is noise-only, so this measures false positives and nothing else.
  It says nothing about whether SemDiff detects real changes; that is NFR-5's job, on pairs
  that do not exist yet.
- **Four of the seven noise families.** The corpus is 14 `asset_hash` and 6 `timestamp` pairs.
  Real captures offered no `dynamic_class`, `hashed_id` or `token` churn at all (F-019, F-022,
  F-023), so FR-5, FR-6 and FR-7 have no real-world coverage here — only synthetic unit tests.
- **Layer 1 only.** `semdiff` in this table is `normalize(old) == normalize(new)`, not typed
  change objects. The change-detection layers do not exist yet.
- **More than one machine.** One laptop, one run of five. Treat the ratios as the result.
