# SemDiff — Project Brief

## Problem

Every open-source HTML diff tool answers the wrong question. They tell you *what bytes changed*; nobody needs that. They fall into three buckets, none of which produce semantic output:

- **Text/word differs** (`lxml.html.diff`, `htmldiff2`, `html-diff`, `htmldiff.js`, DaisyDiff) emit `<ins>`/`<del>`-marked HTML. `lxml.html.diff`'s own docs say markup is "largely ignored"; a documented bug (lxml PR #350) shows it corrupting structure on an inserted `<div>`. Zulip abandoned diff-match-patch because "it's a text differ, not an HTML differ."
- **Tree/object differs** (`xmldiff`, `diffDOM`, `deepdiff`) emit low-level node ops — insert/update/move/delete with XPath. Structured, but node-level, with no concept of a price or a job posting. `xtdiff`, the Python Chawathe implementation, is marked **DEPRECATED** — generic tree-diff-for-HTML has been tried and shelved.
- **Extraction libraries** (`trafilatura`, `extruct`, `readability`) understand pages but don't diff them.

Downstream, monitoring tools inherit the gap. changedetection.io and urlwatch both run difflib over filtered text, pushing the entire burden of meaning onto users writing per-site CSS/XPath/regex. The result is documented false-positive noise: star counters, "members online" widgets, reactions, even empty diffs triggering alerts (changedetection.io issues #14, #2548; discussions #2297, #1862). The maintainer's fix was to bolt on LLM summaries — "Price dropped from $89.99 to $67.00" — which is an admission that deterministic diffing alone can't separate signal from noise. Visualping reports filtering ~87% of detected changes as non-critical.

Five properties are needed for semantic change detection. No tool has all five: reorder/structure robustness, immunity to dynamic classes and random IDs, semantic typing, structured output, and confidence plus provenance.

## Target users

- **Monitoring tool maintainers and self-hosters** — changedetection.io and urlwatch users drowning in false positives, who currently hand-maintain selectors per site.
- **Scraping and data engineers** running price/stock/job pipelines who need "did the price change" rather than a diff blob.
- **Anyone building change-aware agents or RAG pipelines** who needs deterministic, typed change events instead of LLM-per-page cost and nondeterminism.

## Core value

Two HTML snapshots in, typed JSON change objects out — `price_change`, `availability_change`, `content_update`, `job_listing_change`, `product_change`, `text_edit`, `content_added`, `content_removed` — each with old/new value, confidence, extraction source, and XPath provenance. Deterministic by default, zero ML dependencies in the core install, self-hostable.

The wedge is the normalization layer. CSS-in-JS hashes (`css-1dbjc4n`), framework IDs, nonces, and relative timestamps change on every deploy, and no existing differ neutralizes them — which is precisely why existing tools cannot be *configured* into a solution. They have no normalization stage at all.

Where the engine can lean on structured data it does: Web Data Commons found structured data on 50.60% of crawled pages, and ~96% of JSON-LD `Offer` entities carry `price`. That makes schema.org the highest-precision, CSS-churn-immune signal for price and stock, with heuristics as fallback.

## MVP (v0.1–v0.2)

**v0.1 — normalization + baseline diff.** selectolax/lxml parsing adapters; the normalization layer (dynamic class and hashed-ID stripping, timestamp and token neutralization, tree canonicalization); a baseline diff emitting a minimal structured change list. Ship normalization as a standalone utility — it has value to monitoring users before any semantics land.

Gate to proceed: on real page pairs where only classes, IDs, and timestamps changed, emit **zero** change objects, against the many that difflib and `lxml.html.diff` produce.

**v0.2 — price and stock.** `extruct` structured track plus a heuristic track (currency regex, in-stock/out-of-stock lexicons extending changedetection.io's restock texts), emitting `price_change` and `availability_change` with confidence and provenance.

Gate: ≥0.95 precision on price changes where JSON-LD `Offer` is present, heuristic fallback measured separately.

## Non-goals

- **Not another DOM diff library.** No node-level edit scripts — `xmldiff` and `diffDOM` already do that well and get reused where needed.
- **Not a rewrite of solved primitives.** Parsing, structured-data extraction, main-content extraction, tree edit distance, and ad/tracker filter lists are all reused (selectolax, extruct, trafilatura, APTED/zss, EasyList/EasyPrivacy).
- **Not visual or screenshot diffing.**
- **Not a monitoring product.** No UI, no scheduler, no notifications. The goal is to be the library inside changedetection.io, urlwatch, and Scrapy pipelines, not to compete with them.
- **Not LLM-first.** ML is a pluggable Layer 5 enhancement behind an `[ml]` extra, never a required dependency — the explicit differentiator against Visualping's and Firecrawl's cloud-LLM approach.

## What makes it different

| | Existing tools | SemDiff |
|---|---|---|
| Output | `<ins>`/`<del>` HTML, or node ops | Typed semantic change objects |
| Dynamic classes / random IDs | Flag every deploy as a change | Normalized away before diffing |
| Reordered nodes, injected ad slots | False positives (difflib-based) | Entity-keyed + APTED alignment |
| Ads, analytics, trackers | Manual per-site selectors | EasyList rules + content scoping |
| Price / stock / job awareness | None | `extruct` + heuristic entity layer |
| Confidence + provenance | Essentially absent | On every change object |
| Noise suppression method | Cloud LLM (changedetection.io, Visualping) | Deterministic, LLM optional |

The closest prior art is Firecrawl's Change Tracking JSON mode — and it's a hosted API feature requiring a user-defined schema per use case, not a reusable library.

The adoption lever is a public labeled corpus of real before/after page pairs across e-commerce, news, and job boards. No such benchmark exists, and it's how `trafilatura` won its category on the SIGIR '23 comparison. Paired with a changedetection.io diff-backend shim, that's the realistic route from library to community standard.