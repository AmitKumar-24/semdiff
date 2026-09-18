# The AI-Aware HTML Difference Engine: Research, Architecture, and Roadmap for a Semantic HTML Change-Detection Library

## TL;DR
- **No existing open-source library produces semantic, structured change objects for HTML** — every notable tool is either a text/word differ (lxml.html.diff, htmldiff.js, DaisyDiff), a generic tree/data differ (xmldiff, diffDOM, deepdiff), or an extraction library (trafilatura, extruct) that does not diff. The gap is real and documented in GitHub issues and READMEs.
- The winning strategy is **not another diff algorithm** but a modular pipeline that composes best-in-class existing tools — selectolax/lxml for parsing, extruct for structured data, trafilatura for main-content extraction, APTED for tree alignment, EasyList-style rules for noise — behind a normalization + noise-filtering + entity-extraction + alignment + classification stack that emits typed JSON change objects (price, stock, content, job, product).
- Recommended path: ship a Python library (working name **SemDiff**) on PyPI, positioned as the semantic diff backend that changedetection.io, urlwatch, and Firecrawl-style tools can plug in to kill their #1 documented pain point — false-positive noise — with a real-world test corpus and benchmark as the lever for becoming the community standard.

## Key Findings

1. **The category of "semantic structured HTML diff" does not exist in open source.** Existing libraries cluster into three groups, none of which output structured semantic change objects: (a) word/inline HTML differs that emit `<ins>`/`<del>`-marked HTML; (b) tree/XML differs that emit edit scripts of insert/update/move/delete node operations; (c) content-extraction libraries that output clean text/JSON but do no diffing.

2. **The dominant Python HTML differ, `lxml.html.diff`, explicitly ignores structure and produces malformed output on structural change.** Its own docstring states markup is "generally ignored" and it works on body fragments only; a documented bug (lxml mailing list, Sept 2022; PR #350) shows it wrapping a newly inserted `<div id="middle">` around an unrelated `<div id="first">`, corrupting structure. Zulip issue #7219 documents abandoning Google's diff-match-patch for HTML because "it's a text differ, not an HTML differ, and so it ends up messing up the HTML tags."

3. **Change-monitoring tools confirm the core pain point: noisy diffs / false positives.** changedetection.io (a very widely used self-hosted monitor, ~31k GitHub stars) has extensive user complaints about noise: issue #14 ("Smart ignore") requests click-to-ignore blocks; discussion #2297 shows users unable to stop GitHub star/fork counters triggering alerts; discussion #1862 shows filters not stopping "members online" counters; issue #2548 documents empty diffs still triggering change detection. The maintainer's response was to bolt on LLM-based filtering — the README documents it verbatim: "AI change summaries — instead of staring at a raw diff, your notification reads 'Price dropped from $89.99 to $67.00' or '3 new products added to the listing'… Powered by LiteLLM." This confirms that deterministic diffing alone cannot separate meaningful from noise.

4. **Dynamic/hashed CSS classes and random IDs are a first-class breakage source** that no HTML differ normalizes away. CSS-in-JS (styled-components, Emotion, CSS Modules, Tailwind JIT) generate classes like `css-1dbjc4n` or `price_a1b2c3` that change every deployment; framework IDs like `#react-root-7a3b2c` change per load. Any raw DOM or attribute diff flags every deploy as a change. This is the single strongest justification for a dedicated normalization layer.

5. **Structured data is prevalent enough to anchor entity extraction.** Web Data Commons' October 2023 extraction report states: "we found structured data within 1.7 billion HTML pages out of the 3.4 billion pages in the crawl (50.60%). These pages originate from 15 million different pay-level domains out of the 34 million pay-level domains covered by the crawl (42.89%)." Product, Offer, LocalBusiness, JobPosting, and Article are all deployed on very large numbers of sites, and Offer entities carry price/currency/availability at very high rates — making schema.org/JSON-LD the highest-precision signal for price, stock, and job change detection when present, with heuristics as fallback.

6. **Prior art exists for every sub-problem — so most of the engine should be composed, not built.** Parsing (selectolax/lxml), structured-data extraction (extruct), main-content extraction (trafilatura, readability-lxml), tree edit distance (APTED, zss), noise rules (EasyList/EasyPrivacy), and structural code diffing as a design analogy (difftastic, GumTree) are all mature. The novel contribution is the **semantic classification layer** and the **typed change-object schema**, not the underlying primitives.

## Details

### Landscape: comparison of existing libraries

| Library / Tool | Language | What it does | Output | Structure/reorder robust? | Noise filtering? | Maintenance |
|---|---|---|---|---|---|---|
| `lxml.html.diff` | Python | Word-level inline diff (difflib) | `<ins>/<del>` HTML | No (structure "largely ignored"; corrupts on structural change) | No | Alive but diff module feature-frozen |
| `htmldiff` / `htmldiff2` | Python | Inline HTML diff (difflib/genshi/html5lib) | `<ins>/<del>` HTML | No | No | Largely dormant |
| `html-diff` | Python | BeautifulSoup Ratcliff–Obershelp inline diff | Visual HTML | No | No | Active, niche |
| `htmltreediff`/`html-tree-diff` | Python | Structure-aware tree diff | `<ins>/<del>` tree | Partial | No | Unmaintained (Py2-era) |
| `xmldiff` (Shoobx) | Python | XML tree edit script | Typed node ops + XPath | Yes (has `move`) | No | Active; output unstable across versions |
| `xtdiff` (cfpb) | Python | Chawathe hierarchical change detection | INSERT/UPDATE/MOVE/DELETE | Yes | No | **DEPRECATED** |
| `diff-match-patch` (Google) | Multi | Char/line text diff | Text ops | No (corrupts HTML tags) | No | Active |
| `deepdiff` | Python | Deep object comparison | Structured dict (filterable) | N/A (not HTML) | `exclude_paths` | Active |
| `htmldiffer` | Python | Visual HTML diff wrapper | Visual HTML | No | No | Effectively unmaintained |
| `htmldiff.js` (tnwinc/inkling) | JS | Word-level HTML diff | `<ins>/<del>` HTML | No ("algorithm isn't perfect") | No | Low activity |
| `diffDOM` (fiduswriter) | JS | Real DOM-node diff | JSON DOM ops (apply/undo) | Yes (node-level) | No | Active |
| `morphdom`/`virtual-dom` | JS | DOM patching engines | (applies, doesn't report) | Yes | No | Active |
| DaisyDiff | Java | Visual HTML tree diff | HTML/XML markup | Yes | No | Legacy; pulled from MediaWiki for "major errors" |
| APTED / zss | Python/Java | Tree edit distance algorithms | Edit distance/script | Yes (APTED tree-shape independent) | No | Reference implementations |
| trafilatura / readability / goose3 | Python | Main-content extraction (not diff) | Clean text/JSON | N/A | Yes (boilerplate) | Active |
| extruct (Scrapinghub) | Python | JSON-LD/Microdata/RDFa extraction | Structured entities | N/A | N/A | Active |
| selectolax | Python | Fast HTML parsing (Lexbor/Modest) | DOM/CSS queries | N/A | N/A | Active |
| difftastic / diffsitter / GumTree | Multi | Structural **code** diff (tree-sitter/AST) | Structural CLI/HTML | Yes | Whitespace-immune | Active |

**Python / PyPI (detail)**

- **`lxml.html.diff`.** Word-level inline differ on `difflib.SequenceMatcher`. Structure-blind by design — docs: "changes in markup are largely ignored; only changes in the content itself are highlighted"; operates on fragments, ignores `<head>`. Documented structural-corruption bug (lxml mailing list, 2022; PR #350). No noise filtering, no structured output, breaks on reordering.
- **`htmldiff2`.** A "friendly fork… upgraded for the diffengine project." Inline HTML diff only.
- **`html-diff`.** BeautifulSoup Ratcliff–Obershelp best-matching-subsequence with configurable "cuttable words." Still inline-HTML visual diff.
- **`htmltreediff`.** Closest older tree-aware attempt; emits `<ins>/<del>` in a merged tree; unmaintained; still visual, not typed change objects.
- **`xmldiff` (Shoobx).** Mature XML tree differ producing an **edit script** of typed actions (`insert`, `delete`, `move`, `update-text`, `update-attribute`) with XPath. Closest to structured output, but generic (no ads/price/stock concept), README warns output is unstable across versions, and on real HTML it drowns in low-level node ops. Excellent as a *component* model for our alignment layer, not a semantic solution.
- **`xtdiff` (cfpb).** Python implementation of the Chawathe et al. hierarchical change-detection algorithm. **Repo explicitly marked DEPRECATED** — confirming generic tree-diff-for-HTML has been tried and abandoned.
- **`diff-match-patch` (Google).** Char/line text diff; fast and robust but purely textual; Zulip documented it "messing up the HTML tags." Useful as a *text-similarity primitive*, not a page differ.
- **`deepdiff`.** Deep comparison of Python objects with `exclude_paths`, `significant_digits`, `ignore_order`. Not HTML-aware, but the **ideal model for output ergonomics** — structured, filterable change dictionaries — and already used by urlwatch's `deepdiff` filter for JSON.
- **Content-extraction libraries (components, not differs):** `trafilatura` is the benchmark-leading single open-source main-content extractor — credited as "Best single tool by ROUGE-LSum Mean F1 Page Scores" in Janek Bevendorff, Sanket Gupta, Johannes Kiesel, Benno Stein, "An Empirical Comparison of Web Content Extraction Algorithms," SIGIR '23, Taipei, July 2023, pp. 2594–2603 (DOI 10.1145/3539618.3591920), which compared 14 extractors across 8 combined datasets. `readability-lxml`, `newspaper3k/4k`, `goose3` (highest precision, low recall), `boilerpy3`, `jusText` are alternatives. `extruct` extracts JSON-LD/Microdata/RDFa/OpenGraph/Microformats in one pass — the backbone of our entity layer. `selectolax` (Lexbor engine) is dramatically faster than the alternatives: on the maintainer's benchmark over the main pages of the top 754 domains, "Beautiful Soup with html.parser took 61.02 seconds, lxml / Beautiful Soup with lxml took 9.09 seconds, and selectolax with Lexbor took 2.39 seconds."

**JavaScript / npm (detail)**
- **`htmldiff.js`.** CoffeeScript/JS port of Ruby htmldiff for WYSIWYG content; the htmldiff-js port's README notes "The diffing algorithm isn't perfect." Visual output, no semantics/noise handling.
- **`diffDOM` (fiduswriter).** Real DOM-node differ producing a JSON list of diff operations that can apply/undo/patch — genuinely structured, but low-level DOM ops (node/attribute/text), not semantic entities; built for live DOM sync; diffs everything including noise.
- **`morphdom`/`virtual-dom`.** DOM-patching engines that *apply* minimal mutations rather than *describe* them semantically.
- **`dom-compare`, `node-htmldiff`.** Niche/older; XML equality or word-diff.

**Java / algorithmic (detail)**
- **DaisyDiff.** Mature DOM-tree HTML diff with HTML and tag modes, outputs HTML/XML markup. Was integrated into MediaWiki's Visual Diff and then **pulled out due to "major errors"** (per its README). Human-readable visual diff, JVM-bound, no semantic typing, no noise filtering.
- **Tree edit distance: Zhang–Shasha (1989), RTED, APTED.** APTED (Pawlik & Augsten) is the state-of-the-art, tree-shape-independent TED; Python ports exist (`apted`, plus `zss`). Right engine for reorder-robust alignment, but computes only distance/edit scripts with no notion of what a node *means*. XyDiff is analogous prior art for XML/versioned-document change detection.

**Structural/semantic diff as design analogy**
- **difftastic, diffsitter, GumTree.** Structural code diffs via tree-sitter/AST + graph search (Dijkstra) or top-down/bottom-up matching (GumTree). difftastic's core insight — parse to a tree, diff structurally so reformatting/whitespace yields *no* change — is exactly the philosophy to port to HTML. Its author documents the hard parts (minimal edit scripts aren't always human-preferred; large-string literals and performance are hard). These validate the tree-based approach and prove demand for semantic diffing, but none target HTML pages or produce domain entities.

**Change-monitoring tools and their diff engines**
- **changedetection.io.** Text/line diff (Python difflib) after CSS/XPath/JSONPath/jq filtering; has "Ignore text," "Remove elements," "Trigger on text," restock/price detection, and recently LLM filtering/summaries. Powerful but manual and brittle: users hand-write selectors/regex per site, and GitHub issues (#14, #2548; discussions #2297, #1862, #2712) show persistent false positives from counters, reactions, and dynamic elements. Primary integration target and proof of pain.
- **urlwatch.** Filter pipeline (`css`, `xpath`, `element-by-id`, `html2text`, `re.sub`, `grep`, `strip`) → difflib diff → `diff_filter`; includes a `deepdiff` filter for JSON. Same manual, per-site model; docs/third-party writeups acknowledge "expect some trial and error" and selectors "break when sites change structure."
- **Huginn, Wachete, ChangeTower, Distill.io, Visualping, Fluxguard, Versionista (commercial).** Distill offers CSS/XPath/visual selectors and local+cloud monitoring; Visualping does screenshot/visual + text + element diff and layers AI summaries + natural-language "important change" classification. Visualping's own blog quantifies the noise problem: "Across our platform, AI classifies roughly 87% of detected changes as non-critical. That's the noise that never reaches your inbox… The remaining 13% trigger notifications" (a companion post reports that over a recent 30-day sample it "detected roughly 16.8 million page-level changes across about 1.5 million active monitors," flagging 11.5% and filtering 88.5% as noise). **The commercial state of the art is: cheap deterministic diff + an LLM to suppress noise** — validating the problem while leaving open an open-source, deterministic-first, structured-output library.
- **Firecrawl "Change Tracking."** Ships `changeStatus` (new/unchanged/changed/removed) plus Git-diff mode and a JSON mode with a custom schema to "track specific data changes… product details, pricing, or key text changes." The closest commercial move toward structured semantic diff, but a hosted API feature, not a reusable library, and the JSON mode requires the user to define the schema per use case.
- **ScrapeGraphAI / Crawl4AI / Firecrawl `/extract`.** LLM-based extraction to schemas/natural-language prompts — the industry solving "understand the page" with LLMs. But they are extraction, not diffing, and LLM-per-page is slow/costly/nondeterministic. Our design uses ML as a pluggable enhancement, not the core.

### Prior art for noise removal
- **EasyList / EasyPrivacy / Fanboy lists.** Community-maintained network + cosmetic filter rules (CSS-selector element hiding, tracker/analytics domain blocking) used by uBlock Origin, AdGuard, Brave, etc. A ready-made, battle-tested corpus for identifying ad/analytics/tracking elements — reusable directly in the noise-filtering layer.
- **Readability/trafilatura heuristics.** Density- and rule-based main-content identification is mature prior art for separating content from chrome (nav/footer/sidebar), reusable for scoping meaningful-change detection.

### Structured-data prevalence (justifies the entity-extraction layer)
From Web Data Commons (primary source, October 2023 extraction report): structured data was found in 1.7 billion of 3.4 billion crawled HTML pages (50.60%), from 15 million of 34 million pay-level domains (42.89%). Per-class deployment (October 2024 merged Microdata+JSON-LD "Hosts" counts): schema.org/Product on **3,309,209 hosts**, LocalBusiness on **1,456,650 hosts**, JobPosting on **63,320 hosts**. In the October 2023 embedded-JSON-LD data, Article appeared on ~2,097,719 domains, Product on ~1,928,725, Offer on ~1,907,027, LocalBusiness on ~1,141,250.

Critically for price/stock detection, Offer entities carry the needed fields at high rates. In the JSON-LD data, of 623,956,111 Offer entities, 598,320,243 include `price` (~95.9%) and 596,216,776 include `priceCurrency` (~95.6%). In Microdata, of 266,289,137 Offer entities, 245,071,737 include `price` (~92.0%), 234,753,822 `priceCurrency` (~88.2%), and 161,540,086 `availability` (~60.7%); at the domain level, 750,862 of 801,020 Offer domains (~93.7%) expose `price` and 574,512 (~71.7%) expose `availability`.

The WWW 2023 WDC paper (Alexander Brinkmann, Anna Primpeli, Christian Bizer, "The Web Data Commons Schema.org Data Set Series," WWW '23 Companion, DOI 10.1145/3543873.3587331) documents rapid growth: Product-annotating websites rose from 594K to 2.6M (430%), LocalBusiness 386K→1.2M (310%), and "of the JobPosting class increased from 7K websites to 50K (721%)." Its 2022 release totaled 106 billion RDF quads describing 3.1 billion entities from 12.8 million websites; schema.org adoption rose from 3.1% of websites in 2013 to 37.9% in 2022, and Product entities use the `offers` property on 86.16% of Product-publishing PLDs.

**Design implication:** where structured data exists (roughly half of pages, and the great majority of e-commerce/job pages), it is the highest-precision, most stable signal for detecting price, availability, and job changes — and it is inherently immune to CSS-class churn. Where absent, heuristics/regex (currency-symbol + number patterns; in-stock/out-of-stock phrase lists, as changedetection.io's restock detector already uses) and main-content extraction fill the gap.

### The gap, precisely stated
Every reviewed tool fails at least one of the five required properties for semantic change detection:
1. **Structure/reorder robustness** — text differs (lxml, htmldiff.js, difflib) fail; only TED-based alignment (APTED) or DOM-tree diff (diffDOM, xmldiff) handle it, and those emit low-level ops.
2. **Noise immunity (dynamic classes, random IDs, ads, timestamps, tokens)** — no differ normalizes these; monitors push the burden onto users via manual selectors/regex.
3. **Semantic typing (price vs stock vs content vs job)** — none produce this; the closest (Firecrawl JSON mode) requires a user-defined schema and a hosted LLM.
4. **Structured, machine-consumable output** — only xmldiff/diffDOM/deepdiff produce structures, and they are node-level, not entity-level.
5. **Confidence + provenance (xpath/selector, old/new value)** — essentially absent across the board.

### Proposed architecture — "SemDiff"
A modular, deterministic-first Python pipeline. Each layer is independently testable and swappable; ML is pluggable, never mandatory.

**Layer 0 — Parsing & fetching adapters.** Reuse `selectolax` (Lexbor) as the default fast parser; `lxml` where full XPath/CSSSelect is needed. **Build vs reuse: reuse** — parsing is solved and selectolax is far faster. Accept two HTML snapshots (old, new); optionally accept already-rendered DOM from Playwright for JS-heavy pages (as changedetection.io/Firecrawl do).

**Layer 1 — Normalization (the key differentiator).** Deterministically neutralize noise that breaks naive diffs:
- Strip/rename **dynamic CSS classes** via configurable regex signatures (`css-[a-z0-9]{6,}`, `[A-Za-z]+_[a-z0-9]{5,}`, hashed suffixes) — justified directly by the CSS-in-JS churn evidence.
- Drop **random/hashed IDs, nonces, session tokens, CSRF fields** (pattern- and entropy-based).
- Normalize **whitespace, attribute order, self-closing forms, and boilerplate timestamps/relative dates** ("3 minutes ago", ISO datetimes in known positions).
- Canonicalize the tree (sorted attributes, stripped comments) — the difftastic insight: reformatting should yield zero change.
This layer is why existing differs can't be "configured" into a solution: they have no normalization stage and treat every class/id/timestamp change as signal.

**Layer 2 — Noise filtering.** Remove ad/analytics/tracking/social elements before diffing, reusing **EasyList/EasyPrivacy cosmetic + network rules** and **trafilatura/readability** main-content scoping to separate content from chrome. Pluggable allow/deny by CSS/XPath for per-site overrides (compatibility bridge for changedetection.io/urlwatch users). **Build vs reuse: reuse** filter lists and extraction heuristics; **build** the thin adapter that applies cosmetic rules to a static DOM (most implementations assume a live browser).

**Layer 3 — Entity extraction.** Two-track:
- **Structured track (high precision):** `extruct` to pull JSON-LD/Microdata/RDFa → normalized entities (Product, Offer{price, priceCurrency, availability}, JobPosting, Article, BreadcrumbList). Justified by WDC prevalence + high Offer property coverage. **Reuse extruct.**
- **Heuristic track (fallback):** currency/number regex for prices, in-stock/out-of-stock phrase lexicons (extend changedetection.io's restock texts), title/spec/image extraction via trafilatura + selector heuristics, main-article body via trafilatura. Produces the same entity schema so downstream layers are source-agnostic.

**Layer 4 — Alignment (reorder-robust).** Align old/new entity trees and residual DOM subtrees using **APTED tree edit distance** (tree-shape independent) with content-hash shortcutting for unchanged subtrees (difftastic's "discard unchanged" optimization) to control cost. For extracted entities, align by stable keys (schema.org `@id`, `sku`/`gtin`/`mpn` for products, URL/`productID`, job `identifier`) before falling back to positional/TED alignment. **Build vs reuse: reuse APTED/zss** for the algorithm; **build** the entity-keyed alignment wrapper. This is what makes reordered DOM nodes, inserted ad slots, and shuffled list items *not* produce false diffs — the exact failure mode of lxml.html.diff and difflib-based monitors.

**Layer 5 — Semantic classification.** Map aligned differences to typed change objects: `price_change`, `availability_change`, `content_update`, `job_listing_change`, `product_change` (title/specs/images), `text_edit`, `content_added`, `content_removed`. Deterministic rules first (a changed `Offer.price` → `price_change` with high confidence); embedding-based text similarity (optional `sentence-transformers`) to distinguish a *meaningful* edit from a trivial reword; pluggable classifiers so ML models can be dropped in. **Build** this layer — it is the novel core no library provides.

**Layer 6 — Structured output.** Emit JSON change objects modeled on deepdiff's ergonomics but semantic:
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
  "provenance": {"xpath": "/html/body/.../script[@type='application/ld+json']", "selector": "..."}
}
```
Plus a summary object (counts by type) and an optional human-readable render. **Build** the schema; **reuse** deepdiff patterns.

**ML integration hooks (designed in from v0.1, activated later):** pluggable classifier interface at Layer 5; embedding similarity provider interface (default: none/`difflib` ratio; optional: sentence-transformers); training-data collection hook that logs (old_snapshot, new_snapshot, emitted_changes, optional human label) for building a labeled corpus — turning production use into a data flywheel for future models.

### Build-vs-reuse summary
| Sub-problem | Decision | Justification |
|---|---|---|
| HTML parsing | **Reuse** selectolax/lxml | Solved; selectolax far faster (2.39s vs 61.02s BeautifulSoup on 754-domain benchmark) |
| Structured-data extraction | **Reuse** extruct | Multi-syntax parsing is mature and error-prone to redo |
| Main-content extraction | **Reuse** trafilatura/readability | Benchmark-leading (SIGIR '23 best single tool); separates content from chrome |
| Noise rules | **Reuse** EasyList/EasyPrivacy | Battle-tested, community-maintained |
| Tree alignment | **Reuse** APTED/zss | State-of-the-art TED; reorder-robust |
| Text similarity | **Reuse** difflib/diff-match-patch/sentence-transformers | Proven primitives |
| Output ergonomics | **Reuse** deepdiff patterns | Already the de facto structured-diff UX |
| **Normalization layer** | **Build** | No differ has one; root cause of false positives |
| **Entity-keyed alignment** | **Build (thin)** | Wraps APTED with schema.org keys |
| **Semantic classification** | **Build** | The novel core; nothing provides typed change objects |
| **Typed change-object schema** | **Build** | The product's reason to exist |

## Recommendations

**Stage 1 — v0.1 (core).** Parsing adapters (selectolax default) + normalization layer (dynamic class/ID/timestamp/token neutralization) + a text/tree baseline diff, emitting a minimal structured change list. Ship the normalization layer as a standalone utility too — it has immediate value to changedetection.io/urlwatch users even before semantics. **Success threshold to proceed:** on a held-out corpus of real page pairs where only classes/IDs/timestamps changed, produce **zero** change objects (vs the many that lxml.html.diff/difflib emit).

**Stage 2 — v0.2 (entity extractors).** extruct-based structured track + heuristic price/stock track, emitting `price_change` and `availability_change` with confidence and provenance. **Threshold:** on a labeled e-commerce corpus, ≥0.95 precision on price changes where JSON-LD/Offer is present (justified by ~96% Offer price coverage), with graceful heuristic fallback measured separately.

**Stage 3 — v0.3 (structured output API + plugin system).** Finalize the JSON change-object schema, entity-keyed + APTED alignment, and a plugin interface for custom extractors/classifiers/noise rules. Ship adapters: a changedetection.io "diff backend" shim and a urlwatch `diff_filter`/filter plugin. **Threshold:** drop-in replacement demo that measurably reduces false-positive alerts on a public monitoring corpus vs difflib.

**Stage 4 — v0.4 (ML hooks).** Activate embedding-based "meaningful edit" detection (sentence-transformers optional dependency), pluggable classifiers, and the training-data collection hook. Keep everything deterministic-by-default so the library runs with zero ML dependencies. **Threshold:** embedding path improves precision/recall on ambiguous text edits over the rule-only baseline on the corpus.

**Stage 5 — v1.0 (community-standard positioning).** Publish (a) a **public benchmark and labeled test corpus** of real-world before/after page pairs across e-commerce (price/stock), news/articles, and job boards — the single highest-leverage adoption asset, since no such benchmark exists and it lets everyone compare tools objectively (mirroring how trafilatura won on the SIGIR '23 benchmark); (b) integration examples for changedetection.io, urlwatch, Scrapy, and Firecrawl-style pipelines; (c) clear docs on the deterministic-first, LLM-optional philosophy as the differentiator vs Visualping/Firecrawl's cloud-LLM approach.

**Packaging & positioning.**
- PyPI package, permissive license (Apache-2.0, matching trafilatura's relicensing and Crawl4AI), core install with zero heavy/ML deps; extras `[ml]`, `[browser]`, `[all]`. Use pydantic for the change-object schema (changedetection.io already standardized on pydantic).
- Position explicitly as **"the semantic diff backend"** — not a monitoring UI. Compete with nobody's product; become the library inside their products. changedetection.io's own move to LLM noise-filtering and Firecrawl's Change Tracking JSON mode show the whole industry needs exactly this component; offering it as deterministic, self-hostable, structured, and free is the wedge.
- Pursue changedetection.io integration first (largest self-hosted user base with the loudest documented noise complaints); a successful shim there is the fastest route to becoming the de facto standard.

**Benchmarks/thresholds that would change the plan.** If, on the v1.0 corpus, structured-data (extruct) coverage on target sites proves much lower than WDC's web-wide ~half (e.g., heavy JS-rendered SPAs hiding JSON-LD behind client rendering), prioritize the browser-render adapter and heuristic track earlier. If deterministic normalization + alignment already achieves >0.9 F1 on meaningful-change detection, defer ML (v0.4) indefinitely and market the zero-dependency story harder.

## Caveats
- **WDC figures are lower bounds and sampled.** Common Crawl covers ~30–40M "popular" pay-level domains and only a subset of each site's pages; WDC explicitly calls its data "the tip of the iceberg." Structured-data prevalence on *your* target sites may differ; validate per-vertical.
- **Property-coverage percentages** for Offer (price ~96% JSON-LD; availability ~61–72% Microdata) were computed from raw WDC counts and are format-specific; JSON-LD `availability` coverage was not directly published on the WDC page. Note also that the paper's headline totals (106B quads / 3.1B entities / 12.8M websites) refer to the 2022 release, while the 50.60%/42.89% figures are from the October 2023 extraction.
- **Structured data can be stale, injected client-side, or wrong.** JSON-LD may be rendered by JavaScript (missed by pure-HTTP fetches, as the Apify structured-data actor and others note) and may not match visible content ("veracity of semantic markup" is a known research concern). Cross-checking structured vs visible values is advisable and is itself a useful signal.
- **Some cited comparison points are secondary/promotional** (vendor blogs for Firecrawl/Visualping/Crawl4AI comparisons). The change-tracking *features* are confirmed from the vendors' own pages, but competitive claims (speeds, success rates, market-size projections) are marketing and are not relied upon in the design.
- **Visualping's "87% of changes are non-critical" figure** is vendor-reported; treated as directional evidence of the noise problem, not as validated ground truth.
- **APTED/TED cost** grows with tree size; difftastic's author documents real performance cliffs on large/heavily-changed inputs. Content-hash shortcutting and entity-first alignment are mitigations, but very large pages may need heuristics or windowing — a real engineering risk for the alignment layer.
- **Parser/differ benchmark numbers** (e.g., selectolax parse times) come from maintainers' own benchmarks and specific hardware; treat as indicative, not guaranteed.