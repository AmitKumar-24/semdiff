# SemDiff — Implementation Roadmap

Ordering principle: the smallest useful thing ships first, and it ships *alone*. `semdiff.normalize()` has standalone value to changedetection.io and urlwatch users before any diffing exists — so it's v0.1, released on PyPI by itself. Every phase after that is additive and independently releasable.

Task IDs are stable. Each task has a test that can fail on its own; nothing is "done" on inspection.

---

## Decisions that gate the start

Four of the Prompt 4 ambiguities block code, not docs. Settle them before T-01.

| Blocks | Decision needed |
|---|---|
| Phase 1 schema | **K** — field name namespace (normalized vocabulary vs schema.org-native) |
| Phase 2 schema | **A** — per-field vs per-entity change granularity |
| Phase 2 tests | **B** — multiple Offers per Product |
| Phase 2 scope | **C** — positional alignment for single-entity pages |

The rest (D–J, L) can be decided as their phase arrives. A, B, C, K change the output shape, and changing output shape after publishing `schema_version: 1.0` is the mistake `xmldiff` is remembered for.

---

## Phase 0 — Scaffolding

Two days. Not optional: the corpus harness is what makes every later gate real.

| ID | Task | Done when |
|---|---|---|
| T-00 | Repo, Apache-2.0, `pyproject.toml`, extras `[content]`/`[ml]`/`[all]`, `py.typed`, Python 3.10+ | `pip install -e .` works, mypy strict passes on an empty package |
| T-01 | `Config` object: immutable, serializable, `config_hash` over rule versions + pinned lists | Same config → same hash; any field change → different hash |
| T-02 | Typed error hierarchy: `ParseError`, `InputTooLargeError`, `AlignmentBudgetExceeded` | Each raises and serializes into `errors[]` |
| T-03 | Corpus harness: fixture loader, label format, per-layer assertion helpers, CI wiring | An empty corpus runs green in CI |
| T-04 | Corpus seed — **noise-only pairs** (20 real page pairs where only classes/IDs/tokens/timestamps changed) | 20 labeled pairs committed with source URLs and capture dates |

T-04 first, before any normalization code. It's the v0.1 gate, and writing the test corpus before the implementation is the only way it stays honest. Capture pairs by fetching the same URL across two deploys of CSS-in-JS-heavy sites.

---

## Phase 1 — v0.1: Normalization, standalone

The smallest useful release. No diffing at all.

| ID | Task | Depends | Done when |
|---|---|---|---|
| T-10 | `ParsedDoc` + selectolax adapter | T-00 | Malformed HTML parses without raising |
| T-11 | lxml adapter behind the same interface | T-10 | Both backends produce equivalent trees on corpus |
| T-12 | `NormalizationRule` / `RuleApplication` types, phase-ordered registry | T-01 | Rules register, execute in fixed phase order, report applications |
| T-13 | Rule family: dynamic classes (regex set: styled-components, Emotion, CSS Modules, utility hashes) | T-12 | Unit tests per generator pattern; each rule toggleable |
| T-14 | Rule family: hashed IDs (pattern + entropy threshold) | T-12 | Catches `#react-root-7a3b2c`, leaves `#main-nav` alone |
| T-15 | Rule family: tokens (nonce, CSRF, session-shaped hidden inputs) | T-12 | Token stripped, surrounding structure intact |
| T-16 | Rule family: timestamps (ISO-8601 + relative-date phrasing) | T-12 | "3 minutes ago" and ISO both neutralized |
| T-17 | Rule family: canonicalization (whitespace, attr order, self-closing, comments) — **phase last** | T-12 | Reformat-only input → zero rule-detectable difference |
| T-23 | Rule family: asset hashes in `src`/`href`/`srcset` (bundle hashes, build-id path segments, cache-buster queries) | T-12 | Two deploys of an unchanged page converge; `watch?v=` and other meaningful URLs survive |
| T-18 | `REPLACE_WITH_PLACEHOLDER` action distinct from `STRIP` | T-12 | Attribute presence preserved where it's structurally meaningful |
| T-19 | Public `semdiff.normalize(html, config) -> str` | T-13..18 | Idempotent: `normalize(normalize(x)) == normalize(x)` |
| T-20 | CLI `semdiff normalize file.html` | T-19 | Round-trips a file, `--report` lists fired rules |
| T-21 | **Gate:** noise-only corpus → normalized outputs byte-identical | T-19, T-23, T-04 | All 20 pairs identical after normalization |
| T-22 | Baseline comparison: same 20 pairs through `lxml.html.diff` and `difflib` | T-21 | Published table of their change counts vs zero |

**Release v0.1.** T-22 is the marketing asset, not an afterthought — "here are 20 real page pairs where the standard tools report hundreds of changes and this reports none" is the entire pitch. Post it where changedetection.io and urlwatch users are.

**Gate to Phase 2:** T-21 passes on all 20 pairs. If it doesn't, the rule set is wrong and no amount of semantic layering saves it.

---

## Phase 2 — v0.2: Price and stock

The first semantic release. Scope is narrow on purpose: two change types.

### 2a — Noise filtering (thin)

| ID | Task | Done when |
|---|---|---|
| T-30 | `FilteredDoc` + `Removal` types | Removals carry filter id and locator |
| T-31 | Builtin strip: `<script>`, `<style>`, `<noscript>`, `<iframe>`, tracking pixels | Corpus pixel-only changes yield nothing |
| T-32 | User CSS/XPath allow + deny lists | A changedetection.io selector applies unchanged |
| T-33 | Script exemption: JSON-LD blocks survive T-31 | JSON-LD reachable by Phase 2b after filtering |

T-33 is easy to get wrong and fatal if missed — stripping `<script>` naively deletes the highest-precision price signal.

### 2b — Entity extraction

| ID | Task | Depends | Done when |
|---|---|---|---|
| T-34 | `Money` (Decimal, nullable ISO-4217 currency), format-aware parsing | K decided | `1.299,00` == `1299.00`; currency mismatch ≠ equal |
| T-35 | `Availability` enum + schema.org URL → enum mapping | | All schema.org availability values mapped |
| T-36 | `Entity`, `EntityKey` (scheme + priority), `Field`, `Observation`, `Resolution` | A, K | Scheme-aware key equality; `sku:ABC` ≠ `gtin:ABC` |
| T-37 | Tri-state `FieldState`: value / absent / unknown | | Unparseable markup → `unknown`, not `absent` |
| T-38 | extruct wrapper → `EntitySet` (Product, Offer, Article) | T-36 | JSON-LD, Microdata, RDFa all map to one model |
| T-39 | Heuristic price extractor (currency-symbol + number) | T-34 | Emits `Observation` with `source=heuristic` |
| T-40 | Heuristic stock extractor (lexicon seeded from changedetection.io restock texts) | T-35 | Phrase list externalized and versioned |
| T-41 | `Resolution` + `Agreement` computation across tracks | T-38..40 | Discordant case produces both Observations, flagged |
| T-42 | `ExtractionGap` detection | T-37 | Markup-present-but-unparseable → gap, not absence |
| T-43 | Public `semdiff.extract(html) -> EntitySet` | T-38..42 | Standalone, useful without diffing |
| T-44 | Corpus: 30 product pairs — price change, stock change, both, neither; with and without markup | | Labeled, split by markup presence |

T-43 is the second standalone surface. Shipping `extract()` publicly costs nothing and gives people a reason to install before they need diffing.

### 2c — Alignment and classification

| ID | Task | Depends | Done when |
|---|---|---|---|
| T-45 | `AlignmentResult`, `AlignedPair`, `SubtreeSkip`, `AlignmentMethod` | T-36 | Matching invariant (5) asserted in tests |
| T-46 | Keyed alignment, fixed scheme priority | T-45 | `@id` binds before `sku` before canonical URL |
| T-47 | Content-hash subtree skip | T-45 | Identical subtrees never reach L5 |
| T-48 | Positional alignment, single-entity pages only, confidence ≤0.5 | C decided | Two-entity pages refuse positional |
| T-49 | `Change` type with `old_state`/`new_state` | T-37, A | Null is never ambiguous in output |
| T-50 | Classifier: `PRICE_CHANGE` | T-34, T-46 | `detail` carries delta, pct, direction |
| T-51 | Classifier: `AVAILABILITY_CHANGE` | T-35, T-46 | Enum transition, no free text |
| T-52 | Classifier: `ENTITY_ADDED` / `ENTITY_REMOVED` | T-46 | Unkeyed price change → add+remove (documented) |
| T-53 | Classifier: `EXTRACTION_GAP` — never a price change | T-42 | Invariant 2 asserted |
| T-54 | Classifier: `VALUE_DISCORDANCE` | T-41, D | Single-snapshot finding representable |
| T-55 | Confidence table + `ConfidenceBasis`; score recomputable from basis alone | T-50..54 | Invariant 4 asserted; table frozen for `schema_version` |
| T-56 | `Provenance` incl. `node_hash`, stage tagging, rule/removal ids | T-12, T-30 | Locator validity matches its stage |

### 2d — Output and release

| ID | Task | Done when |
|---|---|---|
| T-57 | pydantic `DiffResult`, `schema_version: "1.0"`, `Money.amount` as string | Float round-trip damage impossible |
| T-58 | `summary` block (counts, max confidence, gap/discordance flags) | Populated on every result |
| T-59 | `diagnostics` block (rules fired, removals, tracks, alignment, timings) | Empty `changes` is explainable |
| T-60 | Explicit empty result for no semantic change | Invariant 1 asserted |
| T-61 | `semdiff.diff(old, new, config)` + CLI `--json` | End-to-end on corpus |
| T-62 | Determinism test: identical input + config → byte-identical output (timings excluded) | Invariant 7 asserted in CI |
| T-63 | **Gate:** ≥0.95 precision on `price_change` where JSON-LD Offer present | Measured on T-44 |
| T-64 | **Gate:** heuristic-track precision/recall published *separately* | Never blended into one number |
| T-65 | Documented-limitations section: no reorder robustness, no ad filtering beyond user selectors, no job/product typing | In README, not buried |

**Release v0.2.** T-65 matters more than it looks. Undocumented failure modes are what cost DaisyDiff its MediaWiki integration; stating the gaps plainly is how a backend earns trust.

---

## Phase 3 — v0.3: Noise, alignment, integrations

Three independently releasable tracks. Ship whichever lands first as v0.3.x.

### 3a — Filter lists

| ID | Task | Done when |
|---|---|---|
| T-70 | EasyList/EasyPrivacy parser: cosmetic + network rules | Rule subset parsed, unsupported syntax reported not swallowed |
| T-71 | Static-DOM cosmetic rule applicator (the part no existing engine offers) | Selector-hiding rules apply without a browser |
| T-72 | List versioning + pinning | A list update cannot silently change results |
| T-73 | Corpus: ad-injection pairs | Injected ad slots → zero changes |

### 3b — TED alignment (highest risk)

| ID | Task | Done when |
|---|---|---|
| T-74 | APTED/zss adapter behind `AlignmentMethod.TREE_EDIT` | Produces pairs with similarity scores |
| T-75 | Hard budget: node count + wall clock, `BudgetReport` | Never an unbounded run |
| T-76 | Documented fallback to keyed alignment on budget exceeded | Fallback recorded in output, not silent |
| T-77 | Corpus: reordered-list pairs | Reorder → zero changes, not add+remove |
| T-78 | Performance regression test at p95 on large pages | Cliff behavior measured, published |

T-75 before T-74 in practice. difftastic's author documents real performance cliffs on large, heavily-changed inputs; building the budget first means the risky part can never ship ungated.

### 3c — Entity types and integrations

| ID | Task | Done when |
|---|---|---|
| T-79 | `JobPosting` + `JOB_LISTING_CHANGE`, keyed on `identifier` | Corpus of job-board pairs passes |
| T-80 | `PRODUCT_CHANGE`: title, specs, images (`Collection` comparison) | Image list reorder ≠ change |
| T-81 | trafilatura content scoping, off by default, text-only | Never scopes entity extraction |
| T-82 | Implicit `Article` synthesis, keyed on canonical URL | L decided; Invariant 9 has a subject |
| T-83 | `CONTENT_UPDATE` distinct from `TEXT_EDIT`, scoped to main content | Both types never describe same nodes |
| T-84 | Plugin interfaces: extractor, classifier, noise rule | Third-party extractor loads from entry point |
| T-85 | changedetection.io diff-backend shim | Runs against a live instance, honors existing selectors |
| T-86 | urlwatch `diff_filter` plugin | Installs and runs from urlwatch config |
| T-87 | Playwright-rendered-DOM input adapter | Client-injected JSON-LD reachable |
| T-88 | **Gate:** false-positive reduction vs difflib on a monitoring corpus | Measured, published |

T-85 is the adoption lever — the largest self-hosted base with the loudest documented noise complaints. Prioritize it over T-79/T-80 if bandwidth is tight.

---

## Phase 4 — v0.4: ML hooks

Interfaces exist from Phase 2 with deterministic defaults; this phase populates them. Core stays zero-ML.

| ID | Task | Done when |
|---|---|---|
| T-90 | `SimilarityProvider` interface, `difflib`-ratio default | Swappable, default requires no extra |
| T-91 | sentence-transformers provider under `[ml]` | Optional install; core unaffected |
| T-92 | Meaningful-edit threshold; suppressed edits counted in `diagnostics` | G decided; never silently dropped |
| T-93 | `Classifier` interface, pluggable at L5 | Rule classifiers and models share one contract |
| T-94 | `CollectionHook`: logs snapshots + emitted changes + optional label | Corpus flywheel operational |
| T-95 | Human-readable change rendering | For notification consumers |
| T-96 | **Gate:** embedding path beats rule-only baseline on ambiguous text edits | Measured on corpus |
| T-97 | Zero-ML operation still fully supported | CI job with core-only install |

---

## Phase 5 — v1.0: Standard positioning

| ID | Task | Done when |
|---|---|---|
| T-100 | Benchmark harness vs `lxml.html.diff`, difflib, `xmldiff`, diffDOM | One command, reproducible |
| T-101 | Corpus v1.0: e-commerce, articles, job boards, noise-only — versioned, licensed, public | Independently runnable by third parties |
| T-102 | Published benchmark results | The trafilatura/SIGIR'23 play — win on a public benchmark |
| T-103 | Integration examples: Scrapy, Firecrawl-style pipelines | Copy-pasteable |
| T-104 | `schema_version` stability policy + migration notes | Backward compat within major version guaranteed in writing |
| T-105 | Confidence table frozen and documented per schema version | Consumers can threshold safely |

---

## Critical path and cut lines

**Critical path:** T-04 → T-12 → T-13..17 → T-21 → T-38 → T-46 → T-50 → T-57 → T-63. Everything else is parallelizable or deferrable.

**If time runs out, cut in this order:**
1. T-79/T-80 (job + product typing) — real but smaller demand; WDC shows JobPosting on ~63k hosts against Product's ~3.3M
2. T-74..78 (TED) — highest risk, and keyed alignment covers the v0.2 targets
3. T-70..73 (filter lists) — user selectors (T-32) are a working interim
4. Phase 4 entirely — the deterministic story is the differentiator anyway

**Never cut:** T-04/T-21 (the gate that defines the project), T-62 (determinism), T-65 (documented limitations), T-101 (the corpus). Those four are the difference between a library people adopt as a backend and another abandoned differ.