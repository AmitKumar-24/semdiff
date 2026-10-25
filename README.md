# SemDiff

Semantic HTML change detection. Two HTML snapshots in, typed change objects out
(`price_change`, `availability_change`, …) with confidence and provenance — instead of a raw
text or DOM diff. Deterministic core, no ML required, built to be the diff backend inside
monitoring tools and scraping pipelines.

**Status: pre-alpha.** Diffing is not implemented yet. What works today is the layer
underneath it — normalization — which is useful on its own.

## Normalization

Most "changes" a page monitor reports are not changes: a framework re-hashed its CSS class
names, a CSRF token rotated, a relative timestamp ticked over, a template re-indented.
`semdiff.normalize()` removes that noise and canonicalizes the tree, so two renders of an
unchanged page compare equal — with `==`, or with whatever differ you already use.

```python
import semdiff

semdiff.normalize(old_html) == semdiff.normalize(new_html)   # True if nothing real changed
```

```python
semdiff.normalize('<div class="card css-1dbjc4n"><!-- r4 --><p>Updated 3 minutes ago</p></div>')
# '<html><head></head><body><div class="card __semdiff__"><p>Updated</p></div></body></html>'
```

A hash is replaced, not deleted: `css-1dbjc4n` becomes `__semdiff__`. Both snapshots collapse
the same way, so the placeholder cannot invent a change, and keeping a stable prefix is what
still tells `tab-__semdiff__` from `panel-__semdiff__` (F-029).

```python
semdiff.normalize(html, config=None, *, encoding=None) -> str
```

Accepts `str` or `bytes` (decoded by declared encoding → BOM → `<meta charset>` → UTF-8) and
returns the canonical serialization. Raises `ParseError` on empty input, `InputTooLargeError`
above the configured ceiling (10 MiB by default), and `ValueError` if the config names a rule
that does not exist.

### What it removes

| Family | Examples |
|---|---|
| Dynamic classes | Emotion `css-1dbjc4n`, styled-components `sc-bdfBwQ`, CSS Modules `toggle_bT41`, Ant Design `acss-q7dsfq` |
| Hashed ids | `react-root-7a3b2c`, React `useId` (`:R2m:`), high-entropy generated ids |
| Tokens | `nonce` attributes, CSRF meta tags and hidden inputs, session-shaped attribute values |
| Timestamps | ISO-8601 datetimes, "3 minutes ago", "just now", "updated yesterday", build stamps like `Sep 25, 2026 (15:12 UTC)` |
| Canonicalization | comments, ASCII-whitespace collapse, attribute order, void/boolean-attribute spelling |

Microdata, RDFa and JSON-LD carriers are protected: no rule touches `itemprop`, `itemtype`,
`about`, `typeof` and their kin, and text inside `<script>`, `<style>` and `<template>` is
left alone. `&nbsp;` is content, not layout, and survives. Every rule is individually
toggleable and reports what it changed.

```python
from semdiff import Config, NormalizationConfig

config = Config(normalization=NormalizationConfig(disabled_rules=frozenset({"timestamp.relative_ago"})))
semdiff.normalize(html, config)
```

### Command line

```
semdiff normalize page.html                  # normalized HTML on stdout
cat page.html | semdiff normalize            # or from stdin
semdiff normalize page.html -o clean.html    # or straight to a file
semdiff normalize page.html --report         # which rules fired, on stderr
semdiff normalize page.html --disable-rule timestamp.relative_ago --disable-rule class.emotion
semdiff normalize page.html --config semdiff.json
```

`--report` writes to stderr, so stdout stays byte-identical with or without it:

```
$ semdiff normalize page.html --report > clean.html
parser selectolax/1.0.2
6 rules fired, 10 applications
  class.emotion           1
  id.hex_suffix           1
  timestamp.relative_ago  1
  asset.dotted_hash       1
  canonical.comments      1
  canonical.whitespace    5
```

Exit codes: `0` success, `2` bad command line, `3` parse error, `4` input too large,
`5` configuration error, `6` I/O error, `1` anything else.

### Guarantees

- **Deterministic.** Same input, same config and same parser build, same output — no clock,
  no network, no randomness. `Config.config_hash` covers the config and the ruleset version;
  the parser is the one input it does not cover, so `semdiff.parser_fingerprint()` names it
  (`selectolax/1.0.2`, for example) and `--report` prints it. Normalized output is identical
  across the selectolax versions CI covers; a `Locator.node_hash` on foreign content is not
  (F-027).
- **Idempotent.** `normalize(normalize(x)) == normalize(x)`.
- **Safe.** Input is untrusted: parse-only, no script execution, no external entity
  resolution, no outbound requests.

## Limitations

What SemDiff does not do, stated plainly: the failure modes a library leaves undocumented are
the ones that cost it trust. Each item names the evidence behind it — `FINDINGS.md` for the
observations, `docs/DECISIONS.md` for the decisions that accepted them.

### Not implemented

- **One parser backend.** `parser="lxml"` raises `NotImplementedError`. selectolax (Lexbor) is
  the only backend; the lxml adapter is T-11, deferred out of v0.1 to sit beside the provenance
  work that wants it, with no equivalence between the two backends claimed (D-048).
- **Rules are toggleable, not extensible.** Any shipped rule can be turned off or on through
  config, but no config field adds one. A custom rule means reaching past the public API into
  the registry, which is not a supported surface yet.
- **`normalize()` does not report what it changed.** It returns a string and nothing else. The
  rules that fired come from `apply_rules()`, or on stderr from `semdiff normalize --report`.
- **Slower than the 100 ms per-pair target.** The published benchmark measures a median of
  373 ms per pair against 125 ms for `lxml.html.diff` — about 3x, bought for twenty fewer false
  positives. The numbers, the machine and the method are in `docs/BASELINE.md`.

### What normalization cannot reach

- **Hashes that live in attribute names.** Every rule target addresses an attribute's value, a
  node or text; none addresses a name. Vue SFC scoped-style markers (`data-v-b483c686`)
  therefore survive, and they rebuild on every deploy (F-022).
- **Anything inside a protected carrier.** Text in `<script>` and `<style>` is never touched,
  which is what keeps JSON-LD and other structured data trustworthy (D-029). The cost: a
  streamed React Server Component payload whose chunk boundaries shift between deploys reads as
  a change that no rule can remove (F-015).
- **The contents of an HTML `<template>`.** Lexbor keeps them in a detached fragment, so no
  rule reaches them on the selectolax backend — they survive because they are unreachable, not
  because they are declined (F-031).
- **Stamps that name the build itself.** A nightly version string in body text, or ant.design's
  `<meta name="build-time">` and `<meta name="build-hash">`, is left alone. Whether a
  build-identity string is noise at all is still an open question (Q-26, F-014).
- **A human datetime whose clock time is not parenthesised.** `Sep 25, 2026 (15:12 UTC)` is
  neutralized; `Sep 25, 2026 at 15:12 UTC` and `2026/09/25 15:12 UTC` are not. The parentheses
  are doing real work as a false-positive fence, so widening the pattern needs its own
  calibration against negative cases (F-020).

### Accepted recall costs

Each of these costs recall and never precision — both snapshots collapse the same way, so none
of them can invent a change — and each was accepted rather than engineered around.

- **Two hashes with no stable prefix collide.** Both become `__semdiff__`, so a reference
  re-pointed from `_R_aaa_` to `_R_bbb_` is invisible. A stable prefix is what keeps the common
  cases apart: `tab-__semdiff__` and `panel-__semdiff__` still differ (F-029).
- **`id.entropy` does not reach inside an `href`.** It scores the longest alphanumeric run of a
  whole attribute value and cannot be fenced to the fragment after `#`, so an entropic id is
  rewritten in `id=` and `for=` and left alone in `href="#…"` (F-029).
- **`token.session_input` strips encoded hidden-input payloads.** A compressed payload in a
  hidden input has the same shape as a session token — ant.design's CodeSandbox demo sources
  are stripped as tokens. If you depend on hidden-input values, disable the rule (F-007).

### Where the evidence is thin

- **Three noise families have no real-world coverage.** The corpus is 14 `asset_hash` and
  6 `timestamp` pairs. Real captures offered no `dynamic_class`, `hashed_id` or `token` churn to
  admit, so those three families rest on unit tests alone (F-019, F-023, F-026).
- **Recall is gated on synthetic mutations.** The gate edits those same twenty captures in
  memory, one surgical change at a time, and asserts each edit survives normalization as
  itself. It cannot show how normalization behaves on the changes a real deploy happens to
  make; a corpus of captured real changes does not exist yet (D-045).
- **Determinism is qualified by the parser build.** Same input, same `config_hash`, same parser
  build, same output. Normalized output is identical across the selectolax versions CI covers,
  but a `Locator.node_hash` on foreign content is not: 464 of 23,204 application records differ
  between the 0.4 and 1.0 lines (D-046).

## Install

```
pip install semdiff-html
```

The distribution is `semdiff-html`, because `semdiff` on PyPI is an unrelated project. What
you write is unaffected — the import package and the command are both `semdiff`:

```python
import semdiff
semdiff.normalize(html)
```

```
semdiff normalize page.html
```

To work on it instead:

```
pip install -e ".[dev]"
```

Requires Python 3.11+. Runtime dependencies: `selectolax`, `pydantic`. `lxml` is needed
only by the baseline comparison in the test suite, so it lives in `[dev]`.
Two further extras are declared for layers that are not built yet — `semdiff-html[content]`
(trafilatura scoping) and `semdiff-html[ml]`, with `[all]` their union — so installing one
today adds a dependency and no capability. The names are fixed now because a requirements
file cannot be renamed retroactively (D-050).
Both selectolax lines are supported and tested: CI runs 0.4.13 and 1.0.0 against every
Python version, plus a weekly job on whatever is newest.

## Development

```
pytest -q
mypy --strict src/semdiff tests scripts
```

CI runs both on Python 3.11, 3.12 and 3.13, against selectolax 0.4.13 and 1.0.0.

## Documentation

`docs/` holds the design: `DOMAIN_MODEL.md` (authoritative), `ARCHITECTURE.md`,
`REQUIREMENTS.md`, `ROADMAP.md`, and `DECISIONS.md` for the decision log and open questions.
`FINDINGS.md` records observations that were deliberately not acted on.

## License

Apache-2.0.
