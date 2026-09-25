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
# '<html><head></head><body><div class="card"><p>Updated</p></div></body></html>'
```

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
| Timestamps | ISO-8601 datetimes, "3 minutes ago", "just now", "updated yesterday" |
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

### Guarantees

- **Deterministic.** Same input and config, same output — no clock, no network, no randomness.
  `Config.config_hash` covers the ruleset version, so a result is reproducible.
- **Idempotent.** `normalize(normalize(x)) == normalize(x)`.
- **Safe.** Input is untrusted: parse-only, no script execution, no external entity
  resolution, no outbound requests.

## Install

```
pip install -e ".[dev]"
```

Requires Python 3.11+. Runtime dependencies: `selectolax`, `lxml`, `extruct`, `pydantic`.

## Development

```
pytest -q
mypy --strict src/semdiff tests scripts
```

CI runs both on Python 3.11, 3.12 and 3.13.

## Documentation

`docs/` holds the design: `DOMAIN_MODEL.md` (authoritative), `ARCHITECTURE.md`,
`REQUIREMENTS.md`, `ROADMAP.md`, and `DECISIONS.md` for the decision log and open questions.
`FINDINGS.md` records observations that were deliberately not acted on.

## License

Apache-2.0.
