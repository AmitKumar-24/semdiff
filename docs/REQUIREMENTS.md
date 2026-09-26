# SemDiff — Requirements

Requirements are scoped so the MVP is v0.1 + v0.2 only. Everything that needs a nontrivial algorithm implementation (APTED alignment, EasyList cosmetic rule engine, plugin system, ML) is deliberately pushed to Future.

## MVP — Functional

### Input & parsing
**FR-1.** Accept two HTML snapshots (old, new) as strings or bytes, with optional source URL for provenance. No fetching in core.
**FR-2.** Parse with selectolax (Lexbor) by default; allow `parser="lxml"` for XPath-dependent paths. *Justification: parsing is solved; selectolax measured 2.39s vs lxml 9.09s vs BeautifulSoup 61.02s on 754 domains.*
**FR-3.** Tolerate malformed HTML without raising — both snapshots parse or the call returns a typed error object, never a partial diff.
**FR-4.** No JavaScript execution, no network I/O during a diff. JSON-LD injected client-side is simply absent; the engine must not silently retry over the network.

### Normalization (the MVP's core differentiator)
**FR-5.** Strip or canonicalize dynamic CSS classes via a configurable, shipped regex ruleset covering CSS-in-JS and utility-hash patterns (`css-[a-z0-9]{6,}`, `[A-Za-z]+_[a-z0-9]{5,}`, hashed suffixes from styled-components / Emotion / CSS Modules).
**FR-6.** Remove hashed or random `id` attributes by pattern plus a character-entropy threshold (e.g. `#react-root-7a3b2c`).
**FR-7.** Drop nonces, CSRF tokens, and session-token-shaped attribute values and hidden inputs.
**FR-8.** Canonicalize the tree: collapse whitespace, sort attributes, normalize self-closing forms, strip comments. Reformatting alone must produce zero changes. *Justification: difftastic's core insight, absent from every HTML differ reviewed.*
**FR-9.** Neutralize timestamps: ISO-8601 datetimes and relative-date phrasing ("3 minutes ago", "updated yesterday") in matched positions.
**FR-10.** Expose normalization as a public standalone API (`semdiff.normalize(html) -> html`) independent of diffing. *Justification: immediately useful to changedetection.io and urlwatch users before any semantics ship; earns adoption early.*
**FR-11.** Every normalization rule is individually toggleable and user-extensible via config, and the set of rules applied is reported in the result.
**FR-44.** Neutralize build hashes inside URL attributes (`src`, `href`, `srcset`): content-hashed bundle names (`main.3eef80bd.js`, `99013-8b54dcaea3573ec3.js`), framework build-id path segments, and cache-busting query strings on static assets. The hash is removed and the resource path kept, and only when the URL is recognisably a static asset — `youtube.com/watch?v=4anAwXYqLG8` has the same shape as a cache buster and must survive. *Justification: measured on the T-04 captures (F-013), this is the only difference between two snapshots of an unchanged Docusaurus page and the dominant one on Next.js sites; FR-5..FR-9 do not reach it.* (Numbering is append-only; this belongs with FR-5..FR-9.)

### Noise filtering (minimal in MVP)
**FR-12.** Remove `<script>`, `<style>`, `<noscript>`, `<iframe>`, and tracking pixels before diffing.
**FR-13.** Accept user-supplied CSS/XPath allow and deny lists. *Justification: compatibility bridge — changedetection.io and urlwatch users already have these selectors written.*
**FR-14.** Optional main-content scoping via trafilatura, restricting content-change detection to the article body. Off by default (it must not hide price blocks). *Justification: reuse the SIGIR '23 best-performing single extractor rather than rebuild heuristics.*

### Entity extraction — price and stock only
**FR-15.** Structured track: extract JSON-LD, Microdata, and RDFa with extruct in one pass; normalize to an internal entity model covering Product, Offer (`price`, `priceCurrency`, `availability`), and Article. *Justification: WDC found structured data on 50.60% of crawled pages, and ~96% of JSON-LD Offer entities carry `price` — highest-precision signal available and immune to CSS churn.*
**FR-16.** Heuristic fallback track: currency-symbol-plus-number regex for price; in-stock / out-of-stock phrase lexicon seeded from changedetection.io's restock texts. Emits into the same entity model so downstream layers are source-agnostic.
**FR-17.** Record extraction source (`json-ld`, `microdata`, `rdfa`, `heuristic`) on every extracted value; it drives confidence and is required for debugging.
**FR-18.** When both tracks produce a value and they disagree, emit both and flag the mismatch rather than silently picking one. *Justification: structured markup can be stale or inconsistent with visible content; the disagreement is itself a signal.*

### Alignment (simple in MVP)
**FR-19.** Align entities across snapshots by stable key, in priority order: schema.org `@id`, `sku`, `gtin`, `mpn`, `productID`, canonical URL. No key → no alignment; report as added/removed.
**FR-20.** Content-hash unchanged subtrees to skip them entirely. *Justification: the cheap half of difftastic's optimization, and the mitigation the research flagged for alignment cost.*
**FR-21.** MVP explicitly does not do tree-edit-distance alignment. Reordered unkeyed content is reported as added plus removed, and this limitation is documented.

### Change detection & output
**FR-22.** Emit `price_change` and `availability_change` from entity comparison; `content_added`, `content_removed`, and `text_edit` from the baseline text diff over normalized content.
**FR-23.** Every change is a pydantic object with: `type`, `entity`, `entity_key`, `field`, `old_value`, `new_value`, `currency` (where applicable), `confidence`, `source`, `provenance` (XPath and/or selector). *Justification: node-level output from xmldiff/diffDOM is the thing being replaced; confidence and provenance are essentially absent across all reviewed tools.*
**FR-24.** Confidence is deterministic and documented — a fixed function of extraction source and agreement, not a model score, in the MVP.
**FR-25.** Return a summary object with counts by change type alongside the change list.
**FR-26.** Emit an explicit empty result for no semantic change. *Justification: changedetection.io #2548 — empty diffs still firing alerts.*
**FR-27.** Numeric price comparison normalizes formatting (thousands separators, decimal commas, currency position) so `1.299,00` vs `1299.00` is not a change; a currency change is a change.
**FR-28.** Output schema carries a `schema_version` field and is versioned independently of the package. *Justification: xmldiff's README warns its output is unstable across versions — a direct adoption blocker for anything used as a backend.*
**FR-29.** A CLI: `semdiff old.html new.html --json`, plus `semdiff normalize file.html`.

## MVP — Non-functional

**NFR-1. Determinism.** Identical inputs and config produce byte-identical output. No network, no clock, no randomness, no model calls in the core path.
**NFR-2. Dependency budget.** Core install: selectolax, lxml, extruct, pydantic. trafilatura as an extra. No ML, no browser, no HTTP client. *Justification: the deliberate differentiator against Visualping's and Firecrawl's cloud-LLM approach; a monitoring host running thousands of checks cannot afford per-page inference.*
**NFR-3. Performance.** Target sub-100ms per page pair for a typical page on the parse-plus-normalize-plus-entity path; no super-linear blowup in MVP since TED is out of scope. Publish measured numbers on the test corpus rather than claims.
**NFR-4. Accuracy gate (v0.1).** On corpus pairs where only classes, IDs, tokens, and timestamps changed: **zero** change objects emitted. This is the release gate, and the headline benchmark against `lxml.html.diff` and difflib.
**NFR-5. Accuracy gate (v0.2).** ≥0.95 precision on `price_change` where JSON-LD Offer is present. Heuristic-track precision and recall measured and published separately, never blended into one number.
**NFR-6. Test corpus.** A versioned corpus of real before/after page pairs (e-commerce price/stock, articles, noise-only pairs), with labels, in-repo and runnable in CI. *Justification: no such benchmark exists for HTML diffing; it's how trafilatura won its category and it's the adoption lever.*
**NFR-7. Memory.** Bounded per diff; both snapshots plus trees held in memory, with a documented input size ceiling and a clear error above it.
**NFR-8. Safety.** All input treated as untrusted. Parse-only, no JS, no external entity resolution, no outbound requests from extruct paths.
**NFR-9. Packaging.** PyPI, Apache-2.0, extras `[content]` / `[all]`, Python 3.10+, typed (`py.typed`), no C-extension build requirement beyond wheels already published upstream.
**NFR-10. Observability.** Structured debug output showing which rules fired, which extraction track supplied each value, and which subtrees were hash-skipped — a diff that reports nothing must be explainable.
**NFR-11. Docs.** Documented limitations section stating plainly what the MVP does not do (no reorder robustness, no ad filtering beyond user selectors, no job/product-spec typing). *Justification: the reviewed libraries' credibility problem is undocumented failure modes — DaisyDiff pulled from MediaWiki, lxml's structural corruption.*

## Future — Functional

### v0.3 — noise, alignment, plugins
**FR-30.** EasyList / EasyPrivacy cosmetic and network rule application to a static DOM, with periodic list updates. *Justification: reuse battle-tested community rules; the thin adapter must be built because existing implementations assume a live browser.*
**FR-31.** APTED (or zss) tree-edit-distance alignment for unkeyed residual subtrees, behind content-hash shortcutting and a size/complexity cutoff with documented fallback. *Justification: the only reviewed approach robust to reordered nodes and injected ad slots; also the documented performance risk, hence gated.*
**FR-32.** Plugin interfaces for custom extractors, classifiers, and noise rules.
**FR-33.** `job_listing_change` via schema.org JobPosting keyed on `identifier`. *Justification: WDC shows JobPosting on ~63k hosts and 721% growth — real but far smaller than Product, so it follows price/stock.*
**FR-34.** `product_change` for title, specs, and images.
**FR-35.** `content_update` typed distinctly from raw `text_edit`, scoped to extracted main content.
**FR-36.** changedetection.io diff-backend shim and a urlwatch `diff_filter` plugin. *Justification: largest self-hosted base with the loudest documented noise complaints; fastest route to de facto standard.*
**FR-37.** Optional browser-rendered input adapter (accept a Playwright-rendered DOM) for JSON-LD injected client-side.

### v0.4 — ML hooks
**FR-38.** Embedding-based text similarity behind a provider interface to separate meaningful edits from trivial rewording; default provider is `difflib`-ratio, optional sentence-transformers under `[ml]`.
**FR-39.** Pluggable classifier interface at the semantic-classification layer.
**FR-40.** Training-data collection hook logging (old snapshot, new snapshot, emitted changes, optional human label) — production use becomes a labeled-corpus flywheel.
**FR-41.** Optional human-readable rendering of change objects for notifications.

### v1.0
**FR-42.** Public benchmark harness comparing SemDiff against `lxml.html.diff`, difflib, `xmldiff`, and diffDOM on the corpus.
**FR-43.** Integration examples for Scrapy and Firecrawl-style pipelines.

## Future — Non-functional

**NFR-12.** TED path must degrade gracefully: hard time and node-count budget, documented fallback to the MVP alignment, never an unbounded run.
**NFR-13.** Zero-ML-dependency operation remains fully supported at every version; `[ml]` is strictly additive.
**NFR-14.** Backward-compatible output schema within a major version; migration notes when `schema_version` bumps.
**NFR-15.** Noise rule lists versioned and pinnable so a list update cannot silently change a user's diff results.

## Scoping note

The MVP as written is roughly: parse adapters, ~8 normalization rule families, an extruct wrapper, two price/stock extractors, key-based entity alignment, a pydantic output schema, a CLI, and a labeled corpus with CI gates. No tree-edit-distance implementation, no filter-list engine, no plugin system, no ML — each of which is the kind of item that quietly consumes a month. That's a realistic single-developer build, and FR-10 alone (standalone normalization) is shippable and useful on its own if the rest slips.