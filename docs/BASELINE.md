# Baseline comparison (T-22)

What the standard tools report on the 20 `noise_only` corpus pairs, measured rather than
asserted. Every pair is a real before/after capture of a page whose content did not change
(admitted by independent human review, D-021), so **every change any tool reports here is a
false positive**. SemDiff reports none of them.

Reproduce it:

```
python -m tests.baseline.report            # the tables below
python -m tests.baseline.report --json     # machine-readable
python -m tests.baseline.report --repeat 5
```

Measured on Python 3.12.10, Windows 11, lxml 6.1.3, selectolax 0.4.11, best of 5 runs.
Timings are wall clock for a whole pair (both snapshots) on one laptop that was **not idle** —
about 70% of its CPU was going to unrelated desktop applications — and three runs of the same
command minutes apart spread the absolute numbers by a factor of two:

| run | `difflib_lines` | `difflib_words` | `difflib_text` | `lxml_htmldiff` | `semdiff` | `semdiff` ÷ `lxml_htmldiff` |
|---|---:|---:|---:|---:|---:|---:|
| 1 | 1.6 | 51.8 | 13.4 | 64.6 | 185.9 | 2.88 |
| 2 | 2.2 | 100.5 | 26.3 | 127.4 | 360.7 | 2.83 |
| 3 (published below) | 1.7 | 66.9 | 24.6 | 124.6 | 372.8 | 2.99 |

The change counts are identical in all three runs; only the milliseconds move. **Compare the
tools against each other, not against another machine's numbers** — the last column is the one
figure that survived a 2× swing in machine load.

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
| pnpm-io-001 | asset_hash | 9 | 1 | 1 | 0 | 0 | 0 |
| pnpm-io-002 | asset_hash | 9 | 1 | 1 | 0 | 0 | 0 |
| reactnative-dev-001 | asset_hash | 96 | 1 | 2 | 0 | 0 | 0 |
| reactnative-dev-002 | asset_hash | 104 | 1 | 2 | 0 | 0 | 0 |
| reactnative-dev-003 | asset_hash | 96 | 1 | 1 | 0 | 0 | 0 |
| reactnative-dev-004 | asset_hash | 104 | 1 | 1 | 0 | 0 | 0 |
| redux-js-org-001 | asset_hash | 64 | 1 | 1 | 0 | 0 | 0 |

| tool | pairs flagged of 20 | total units | median ms |
|---|---:|---:|---:|
| `difflib_lines` | **20** | 20 | 1.7 |
| `difflib_words` | **20** | 38 | 66.9 |
| `difflib_text` | 6 | 12 | 24.6 |
| `lxml_htmldiff` | 6 | 12 | 124.6 |
| `semdiff` | **0** | 0 | 372.8 |

## What the numbers mean

**A raw diff flags every single pair.** Twenty unchanged pages, twenty reported changes. For a
monitoring tool that is twenty alerts nobody wanted, which is the complaint this project exists
to answer (changedetection.io #2548). SemDiff reports nothing on any of the twenty.

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

SemDiff is still the slowest tool in this comparison — **373 ms** median per pair against
125 ms for `lxml.html.diff` and 1.7 ms for the line differ: 3.0× the HTML-aware differ and
219× the byte-level one. That is the price of parsing both documents and running every
normalization rule over the tree, and it is almost all rule engine: parsing a document takes
**2.46 ms**, 1.3% of `normalize()`, measured on this same corpus and machine.

Three optimizations have landed since this table was first published, and the ratio moved from
**5.1× `lxml.html.diff` to 2.9×** (523.9 ms against 103.1 ms, before). The controlled A/Bs
below put their combined saving at roughly 56 ms per document off about 135 ms — 1.7×, which is
what the published ratio independently shows (5.08 → 2.90 is 1.75×).

**NFR-3 is not met.** The target is sub-100 ms per page pair. The median pair here is 373 ms,
and the quietest of the three runs still measured 186 ms. The 79 ms per document from the
controlled A/B is not evidence to the contrary: it is a single document at the quietest moment
of the session, not the pair path NFR-3 names, and the same measurement taken on a busier
machine minutes later gave 184 ms. What has changed is the size of the gap — 3× the HTML-aware
differ rather than 5× — and that the remaining cost is now profiled rather than suspected
(F-009, F-012).

Stated plainly: **this benchmark trades a 3× increase in runtime for twenty fewer false
positives.** For a monitoring host checking thousands of pages that trade needs to be a choice
made with numbers in hand, which is why both columns are published together. The slowness is a
known defect being worked down, not a design goal.

## Two kinds of measurement here

The table above is the **end-to-end benchmark**: in-repo, reproducible with the commands at the
top, measuring the whole public path (`normalize(old) == normalize(new)`) exactly as a caller
meets it. Its weakness is visible in the three-run table — the absolute milliseconds swing by a
factor of two with whatever else the machine is doing, which is more than any single
optimization here is worth. It cannot settle a 5% question, and F-012 records that lesson being
learned the hard way.

Each optimization was therefore measured by a **controlled interleaved A/B**: the shipped
function and a verbatim copy of the pre-change code, alternating in one process over all 40
corpus snapshots, best of five. Both variants meet the same machine load, so load drift cancels
instead of being mistaken for a result. Those harnesses were one-off and are not in the
repository; what is in the repository is the equivalence evidence, which is the part that must
not rot.

| change | what it replaced | measured |
|---|---|---|
| `canonical.attr_order` skips elements with fewer than two attributes | re-serializing every element's start tag to read back its attribute names | 1.56× on the rule, 101 ms corpus-wide, ≈3.9% of `normalize()` |
| the protected text-node set is precomputed once per rule pass | an ancestor walk per text node per TEXT rule | 3.40× on the TEXT passes, 24.4 ms per document |
| consecutive attribute rules share one name-indexed traversal | one traversal and one call per element per rule, 20 of them | 1.37× on `apply_rules`, 26.4 ms per document, 25% of `normalize()` |

Not one of the three touches a rule, an id, a version, a phase or the `config_hash`. Each was
checked for exactness before it was timed, on all 40 corpus snapshots: byte-identical
serialized trees and identical application records, locators included. For the third that check
is now a test rather than a script — `tests/corpus/test_fused_attribute_equivalence.py`, one
case per snapshot, against the pre-fusion engine kept in `tests/normalize/reference.py`.

## How the last two were closed

Until FR-44 was extended, `pnpm-io-001` and `pnpm-io-002` were false positives of SemDiff's
own: FR-44 matched lowercase-hex content hashes only, and Vite emits base64url ones
(`/assets/index-CxL6fshY.js`). Both were admitted to the corpus by independent review knowing
the ruleset could not yet neutralize them, and both were `xfail(strict=True)` in
`tests/corpus/test_noise_only_gate.py`.

`asset.dotted_base64` and `asset.dashed_base64` (D-042) closed the gap, the strict xfails
became failures, and the exemption list is now empty — which is the mechanism working as
designed rather than a list quietly going stale. The rule was written against the 83 base64url
hashes observed across the capture rounds and the non-hash segments standing in the same
position; it was not tuned to these two fixtures, and no fixture was edited.

## What this benchmark does not measure

- **Recall.** Every pair here is noise-only, so this measures false positives and nothing else.
  It says nothing about whether SemDiff detects real changes; that is NFR-5's job, on pairs
  that do not exist yet.
- **Four of the seven noise families.** The corpus is 14 `asset_hash` and 6 `timestamp` pairs.
  Real captures offered no `dynamic_class`, `hashed_id` or `token` churn at all (F-019, F-022,
  F-023), so FR-5, FR-6 and FR-7 have no real-world coverage here — only synthetic unit tests.
- **Layer 1 only.** `semdiff` in this table is `normalize(old) == normalize(new)`, not typed
  change objects. The change-detection layers do not exist yet.
- **More than one machine.** One laptop, three runs of five, and the laptop was not idle.
  Treat the ratios as the result.
