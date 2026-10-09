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
| `noise_families` | list, optional | Which allowed noise families the reviewer observed: `dynamic_class`, `hashed_id`, `token`, `timestamp`, `asset_hash` (D-036) |
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

## Admission limits and recorded rejections

At most **six fixtures per host**, so that no single site or page generator can dominate the
accuracy gate. A candidate that passes the independent review but exceeds the cap is rejected
as surplus, and the reason is recorded here rather than left implicit.

A pair is also rejected, however clean the review, when admitting it would put sensitive or
credential-shaped material into the repository.

| Candidate | Round | Verdict | Reason |
|---|---|---|---|
| `docs.python.org/3/library/bisect.html` | 3 | Rejected, surplus | Qualified as a `timestamp` pair, but docs.python.org was at the six-per-host cap. Of the six qualifying Python pairs it is the closest shape-twin of `heapq` (1173 vs 1200 elements, 49.9 vs 59.6 KB), so dropping it costs the least independence; the five admitted pairs span 387 to 1780 elements. |
| `tauri.app/start/` | 3 | Rejected, sensitive material | The only difference was a rotating `data-netlify-cwv-token` JWT, which embeds Netlify site, account and deploy ids. Admitting the pair would commit a signed token to the repository and would trip secret scanners. The pair is otherwise clean, and the token family is in any case outside the families accepted during T-21 collection. |

`pnpm-io-001` and `pnpm-io-002` were admitted deliberately as **known-red** fixtures: the
review found a single Vite base64url asset hash, which FR-44's original hex-only pattern did
not match, so SemDiff did not yet normalize either pair to equality. They were the regression
target for the FR-44 extension, on the same pattern as `docs-python-org-001` before D-041.
D-042 shipped that extension and both pairs now normalize identically; the exemption list in
`tests/corpus/test_noise_only_gate.py` is empty and the whole corpus is expected green. No rule
was changed to accommodate a fixture, and no fixture is ever edited to make code pass.


## Capture and licensing

Pages are captured by an external script (never by the library): raw HTTP GET, fixed
User-Agent, no cookies or authentication, redirects followed, `robots.txt` respected,
response bytes stored verbatim. The repository's `.gitattributes` marks `corpus/**` as
binary so Git never translates a fixture's line endings on checkout. Sources are permissively licensed by default; any
case-by-case source is recorded as such in its label. A corpus `NOTICE` with the
takedown contact is added with the first fixtures.
