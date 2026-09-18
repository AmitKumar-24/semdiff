# SemDiff — Architecture

A seven-layer pipeline. Each layer is a pure function over typed data, independently testable, and swappable. Anything with a mature open-source solution is reused; only three things are built from scratch.

## Design principles

**Pure and deterministic.** No network, no clock, no randomness, no model calls in the core path. Two snapshots in, change objects out. This is what lets it run as a diff backend inside changedetection.io at thousands of checks per host — the thing cloud-LLM approaches can't do.

**Deterministic first, ML pluggable.** ML sits behind an interface at Layer 5 only, under an optional extra. It never becomes a required dependency.

**Fail loud, fail typed.** Malformed input returns a typed error, never a partial diff. Undocumented failure modes are what cost DaisyDiff its MediaWiki integration and what makes `lxml.html.diff`'s structural corruption dangerous.

**Normalize before comparing, always.** No reviewed differ has a normalization stage. That absence is the root cause of the false-positive problem, and it's why those libraries can't be configured into a solution.

## Pipeline overview

```
(old_html, new_html)
        │
   L0 ─ Parse ──────────────► two ParsedDocs
        │
   L1 ─ Normalize ──────────► two NormalizedDocs   ← standalone public API
        │
   L2 ─ Noise filter ───────► two FilteredDocs
        │
   L3 ─ Extract entities ───► two EntitySets (+ residual DOM)
        │
   L4 ─ Align ──────────────► AlignmentResult (pairs / added / removed)
        │
   L5 ─ Classify ───────────► list[Change]
        │
   L6 ─ Serialize ──────────► DiffResult (JSON, schema_version'd)
```

Each layer receives the previous layer's output plus an immutable `Config`. Nothing reaches back upstream. That constraint is what makes the corpus tests meaningful at layer granularity.

---

## L0 — Parsing adapters

**Responsibility.** Turn untrusted bytes into a traversable tree. Nothing else.

**In:** `bytes | str`, optional source URL, optional declared encoding.
**Out:** `ParsedDoc` — tree handle, detected encoding, parser identity, source URL for provenance.

**Dependencies:** `selectolax` (Lexbor) as default; `lxml` selectable when full XPath is needed downstream.

**Build vs reuse — reuse.** Parsing is solved and selectolax is decisively faster: 2.39s against lxml's 9.09s and BeautifulSoup's 61.02s across 754 domains. Nothing to gain by touching it.

**Notes.** Two parser backends behind one interface, because provenance XPaths (FR-23) are easier with lxml while throughput favors Lexbor. No JS execution, no XML external entities, no outbound fetch. Client-side-injected JSON-LD is simply absent here, and Layer 3 reports it as absent rather than retrying over the network — the browser adapter is a v0.3 input concern, not a parser concern.

---

## L1 — Normalization

**Responsibility.** The layer the whole project rests on. Strip everything that changes without meaning changing.

**In:** `ParsedDoc`.
**Out:** `NormalizedDoc` — canonical tree, plus the list of rules that fired.

**Dependencies:** none beyond L0. Pure Python regex and tree walks.

**Build vs reuse — build.** There is nothing to reuse. No HTML differ reviewed has a normalization stage at all.

**Rule families**, each independently toggleable:

| Family | Neutralizes | Example |
|---|---|---|
| Dynamic classes | CSS-in-JS / utility hashes | `css-1dbjc4n`, `price_a1b2c3` |
| Hashed IDs | framework root and instance IDs | `#react-root-7a3b2c` |
| Tokens | nonces, CSRF, session-shaped values | hidden inputs, `nonce=` |
| Canonicalization | whitespace, attribute order, self-closing, comments | reformatting → zero change |
| Timestamps | ISO-8601 and relative dates | "3 minutes ago" |

**Why regex plus entropy, not regex alone.** Class and ID hashes vary by bundler. A pattern list catches the known generators; a character-entropy threshold catches the rest without a per-site rule. Both are configurable, and FR-11 requires reporting which fired — a diff that reports nothing must be explainable.

**This layer ships as `semdiff.normalize(html) -> html`.** Standalone, independent of diffing. It's useful to changedetection.io and urlwatch users before any semantics exist, which makes it the earliest credible adoption surface and the fallback deliverable if the rest of the MVP slips.

**Ordering matters and is fixed.** Canonicalization runs last, after attribute-level rules, so attribute sorting doesn't mask a stripped class. The order is part of the determinism contract (NFR-1), not an implementation detail.

---

## L2 — Noise filtering

**Responsibility.** Remove ads, analytics, trackers, and chrome before anything is compared.

**In:** `NormalizedDoc`.
**Out:** `FilteredDoc` — tree with noise subtrees removed, plus removal provenance.

**Dependencies:** MVP none; v0.3 adds an EasyList/EasyPrivacy rule adapter; optional `trafilatura` for content scoping.

**Build vs reuse — reuse the rules, build the thin adapter.** EasyList and EasyPrivacy are battle-tested and community-maintained; writing ad heuristics from scratch would be both wasted work and worse. But existing implementations (uBlock, AdGuard, Brave) assume a live browser for cosmetic rules, so applying selector-hiding rules to a static parsed DOM is a small adapter that must be built. Same for content scoping: `trafilatura` is the SIGIR '23 best single extractor — reuse it, don't rebuild density heuristics.

**MVP scope is deliberately thin:** strip `<script>`, `<style>`, `<noscript>`, `<iframe>`, tracking pixels, plus user-supplied CSS/XPath allow and deny lists. That last part is a compatibility bridge — changedetection.io and urlwatch users already have those selectors written, and honoring them makes the shim a drop-in rather than a migration.

**Content scoping is off by default.** trafilatura extracts the article body, which is right for `content_update` and wrong for price blocks — it would silently hide the thing a price monitor cares about. So it scopes text-change detection only, never entity extraction, and the user opts in.

**Filter lists are versioned and pinnable** (NFR-15). A silent list update that changes a user's diff results would break determinism from the outside.

---

## L3 — Entity extraction

**Responsibility.** Turn a filtered tree into typed entities. Two tracks, one output model.

**In:** `FilteredDoc`.
**Out:** `EntitySet` (Product, Offer, Article; later JobPosting) plus the residual DOM that produced no entities.

**Dependencies:** `extruct`; regex and lexicons for the heuristic track.

**Build vs reuse — reuse extruct, build the normalization-to-entity-model mapping and the heuristic track.** extruct parses JSON-LD, Microdata, RDFa, OpenGraph, and Microformats in one pass; multi-syntax parsing is mature and error-prone to redo. What doesn't exist is a mapping from extruct's raw output to a stable internal entity model, or a fallback for the half of the web without markup.

**Structured track (high precision).** extruct → normalized entities. Offer carries `price`, `priceCurrency`, `availability`. This is the highest-value reuse decision in the whole design: Web Data Commons found structured data on 50.60% of crawled pages and 42.89% of pay-level domains, and ~96% of JSON-LD Offer entities carry `price` (Microdata ~92% price, ~61% availability). Crucially, markup lives in a `<script>` block or attributes that don't carry presentational hashes, so it's inherently immune to the CSS churn that breaks every DOM differ.

**Heuristic track (fallback).** Currency-symbol-plus-number regex; in-stock/out-of-stock phrase lexicon seeded from changedetection.io's restock texts — proven vocabulary, already field-tested at scale. Emits into the same entity model, so L4 and L5 never know which track produced a value.

**Both tracks record `source`** (`json-ld` / `microdata` / `rdfa` / `heuristic`), which drives confidence at L5 and makes precision measurable per track — required by NFR-5, which forbids blending the two into one number.

**On disagreement, emit both and flag it.** Structured markup can be stale or contradict visible content; the "veracity of semantic markup" problem is documented in the literature. A mismatch between JSON-LD price and visible price is not noise to be resolved — it's a finding, and for a price monitor often the most interesting one.

---

## L4 — Alignment

**Responsibility.** Decide what in the old snapshot corresponds to what in the new one.

**In:** two `EntitySet`s plus residual DOMs.
**Out:** `AlignmentResult` — matched pairs, unmatched-old (removed), unmatched-new (added).

**Dependencies:** MVP none; v0.3 adds `apted` or `zss`.

**Build vs reuse — reuse APTED for the algorithm, build the entity-keyed wrapper.** APTED is the state-of-the-art tree-edit-distance algorithm and tree-shape independent; reimplementing TED would be pure waste. But TED has no notion of what a node means, so the keyed layer above it is ours.

**MVP: keys and hashes only.**
1. Align entities by stable key, in priority: `@id`, `sku`, `gtin`, `mpn`, `productID`, canonical URL.
2. Content-hash subtrees; identical hash means skip entirely — difftastic's discard-unchanged optimization, and the mitigation the research flagged for alignment cost.
3. Unkeyed residual content: no alignment. Reported as added plus removed, and this limitation is stated plainly in the docs.

**Why TED is deliberately deferred to v0.3.** It's the single largest implementation and performance risk in the design — difftastic's author documents real cliffs on large, heavily-changed inputs. Gating it behind hash shortcutting and a hard node-count and time budget, with documented fallback to keyed alignment (NFR-12), is the only responsible way to add it. Shipping it in the MVP would risk the unbounded-run failure that makes a library unusable as a backend.

**What the MVP loses by that choice:** reordered unkeyed list items and inserted ad slots that survive L2 produce an added-plus-removed pair rather than "no change." For keyed e-commerce and job entities — the v0.2 targets — keys carry it. For prose, L5's text comparison absorbs most of it. Documented, not hidden.

---

## L5 — Semantic classification

**Responsibility.** Turn aligned differences into typed, confident change objects. This is the novel core.

**In:** `AlignmentResult`.
**Out:** `list[Change]`.

**Dependencies:** MVP `difflib`; optional `sentence-transformers` under `[ml]` at v0.4.

**Build vs reuse — build.** Nothing in open source does this. `xmldiff` and `diffDOM` emit node-level ops; the text differs emit marked-up HTML; the extraction libraries don't diff. The closest prior art is Firecrawl's Change Tracking JSON mode, and that's a hosted API feature requiring a user-defined schema per use case.

**Rules first, in a fixed order.** A changed `Offer.price` on a keyed pair is a `price_change` — deterministic, high confidence, no inference needed. Same for `availability`. Text differences over normalized content produce `text_edit`, `content_added`, `content_removed`.

**Price comparison normalizes formatting before comparing** (FR-27): thousands separators, decimal commas, currency position. `1.299,00` against `1299.00` is not a change. A currency change is.

**Confidence is a documented function, not a score.** In the MVP it derives from extraction source and cross-track agreement — JSON-LD Offer with heuristic agreement at the top, heuristic-only lower. Publishing the function matters more than the numbers: a consumer building alerting logic needs to know what a 0.9 means.

**The ML seam is designed in now, activated at v0.4.** Three interfaces exist from v0.1, with deterministic defaults:
- `SimilarityProvider` — default `difflib` ratio; later embeddings, to separate a meaningful edit from a trivial reword.
- `Classifier` — pluggable, so a trained model can replace or augment a rule.
- `CollectionHook` — logs (old snapshot, new snapshot, emitted changes, optional label). Production use becomes a labeled-corpus flywheel, which is the only realistic path to training data for this problem.

Defining the seams in v0.1 costs almost nothing and prevents the refactor that otherwise arrives with the first model.

---

## L6 — Output serialization

**Responsibility.** Emit a stable, machine-consumable contract.

**In:** `list[Change]` plus run metadata.
**Out:** `DiffResult` — changes, summary counts by type, `schema_version`, debug trace.

**Dependencies:** `pydantic`.

**Build vs reuse — build the schema, borrow deepdiff's ergonomics.** `deepdiff`'s structured, filterable change dictionaries are already the de facto UX for structured diffing in Python, and urlwatch ships a `deepdiff` filter for JSON — so the shape is familiar to exactly the users being targeted. The entity-level semantics are new. pydantic is chosen partly because changedetection.io already standardized on it, which makes the shim cheaper.

**Change object:**

```json
{
  "type": "price_change",
  "entity": "Product/Offer",
  "entity_key": "sku:ABC123",
  "field": "price",
  "old_value": "89.99",
  "new_value": "67.00",
  "currency": "USD",
  "confidence": 0.98,
  "source": "json-ld",
  "provenance": {"xpath": "...", "selector": "..."}
}
```

**`schema_version` is versioned independently of the package**, because `xmldiff`'s README warns its output is unstable across versions — a direct adoption blocker for anything meant to be a backend. If the output contract can shift under a consumer, nobody builds on it.

**An explicit empty result** for no semantic change, addressing changedetection.io #2548 where empty diffs still fired alerts.

**Debug trace** (NFR-10) reports which normalization rules fired, which track supplied each value, and which subtrees were hash-skipped. For a library whose value proposition is *not* reporting things, explainability is not optional.

---

## Cross-cutting

**Config.** One immutable object threaded through all layers: parser choice, normalization rule toggles, filter lists and pins, user selectors, extraction track preferences, confidence thresholds, provider implementations. Serializable, so a config plus inputs fully determines output — that's the determinism contract and the reproducibility story for the corpus.

**Errors.** Typed at every layer: `ParseError`, `InputTooLargeError`, `AlignmentBudgetExceeded`. Never a partial diff presented as complete.

**Public API, small on purpose:**
```python
semdiff.diff(old, new, config=None) -> DiffResult
semdiff.normalize(html, config=None) -> str
semdiff.extract(html, config=None) -> EntitySet
```
Plus a CLI: `semdiff old.html new.html --json` and `semdiff normalize file.html`. Exposing `normalize` and `extract` separately isn't API bloat — each is independently useful, and each gives a user a reason to install before they need the full diff.

**Test corpus as a first-class module.** Versioned, labeled, in-repo, runnable in CI, with per-layer fixtures: noise-only pairs (must yield zero changes, NFR-4), price and stock pairs with and without markup, article pairs. No benchmark exists for HTML diffing, and building one is how trafilatura won its category on the SIGIR '23 comparison. It also gates every release rather than decorating the README.

## Build-vs-reuse at a glance

| Layer | Decision | One-line reason |
|---|---|---|
| L0 Parse | Reuse selectolax/lxml | Solved; ~25× faster than BeautifulSoup |
| L1 Normalize | **Build** | No existing differ has one; root cause of false positives |
| L2 Noise | Reuse EasyList + trafilatura; build static-DOM adapter | Rules are battle-tested; existing engines assume a browser |
| L3 Extract | Reuse extruct; build entity mapping + heuristics | Multi-syntax parsing mature; nothing covers markup-free pages |
| L4 Align | Reuse APTED; **build** keyed wrapper | TED is state of the art; it has no semantics |
| L5 Classify | **Build** | Nothing in open source emits typed semantic changes |
| L6 Output | Build schema; borrow deepdiff ergonomics | Familiar shape to urlwatch users; entity semantics are new |

Three things are genuinely built: normalization, entity-keyed alignment, and semantic classification. Everything else is composition. That ratio is the plan — it keeps the MVP inside one developer's reach and keeps the project from competing with libraries that already win their category.