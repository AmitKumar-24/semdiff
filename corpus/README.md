# SemDiff test corpus

Real before/after HTML page pairs with labels (NFR-6). The corpus is test data: it lives
at the repository root, is excluded from the wheel and sdist, and is loaded by the
harness in `tests/corpus/`. It runs as part of `pytest` on every change.

**Fixtures are never edited to make code pass.** A fixture that looks mislabeled is
reported, not fixed in place.

## Layout

```
corpus/<category>/<id>/old.html    # bytes exactly as received
corpus/<category>/<id>/new.html    # bytes exactly as received
corpus/<category>/<id>/pair.json   # label, version 1
```

`<category>` is one of: `noise_only`, `product`, `article`, `ad_injection`, `reorder`, `job`.

`<id>` is `<host>-<NNN>` — the host with dots replaced by dashes, then a three-digit
sequence, e.g. `mui-com-001`. Ids are stable once created and unique across the corpus.

## `pair.json` — label version 1

| Field | Type | Meaning |
|---|---|---|
| `label_version` | `"1"` | Label format version |
| `category` | string | Must equal the parent directory name |
| `url` | http(s) URL | Source URL of both captures |
| `captured_old` | ISO-8601 datetime, timezone required | e.g. `2026-09-16T10:42:07Z` |
| `captured_new` | ISO-8601 datetime, timezone required | |
| `content_type` | string | The `Content-Type` response header |
| `expected.change_types` | list of strings | Change types the engine must emit; `[]` for `noise_only` |
| `noise_families` | list, optional | Which allowed noise families the reviewer observed: `dynamic_class`, `hashed_id`, `token`, `timestamp` |
| `notes` | string, optional | Reviewer notes |
| `license` | string | SPDX id of the page content, or `proprietary` |
| `terms_url` | http(s) URL | Where the page's terms/license are stated |
| `attribution` | string | Who the content belongs to |
| `basis` | `permissive` \| `case-by-case` | Redistribution basis |

Unknown fields are rejected.

## `noise_only` admission rule

A pair is `noise_only` only when manual comparison confirms that, after accounting for
the allowed noise families — dynamic CSS class values, dynamic/hash-like ids,
token/session-like values, and timestamp values — the meaningful visible text and DOM
structure are unchanged. Any other meaningful text, element, attribute, or structural
change disqualifies the pair.

This rule is deliberately not defined in terms of SemDiff's own normalization rules.

## Capture and licensing

Pages are captured by an external script (never by the library): raw HTTP GET, fixed
User-Agent, no cookies or authentication, redirects followed, `robots.txt` respected,
response bytes stored verbatim. The repository's `.gitattributes` marks `corpus/**` as
binary so Git never translates a fixture's line endings on checkout. Sources are permissively licensed by default; any
case-by-case source is recorded as such in its label. A corpus `NOTICE` with the
takedown contact is added with the first fixtures.
