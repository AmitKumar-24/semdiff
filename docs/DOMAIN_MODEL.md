# SemDiff — Domain Model

The model has one job: make "what changed, semantically" expressible as data, with enough structure that a consumer can act on a change without re-reading the HTML. Everything below is normative for implementation.

## 1. Vocabulary

Fixed terms. Used consistently in code, docs, and tests.

| Term | Meaning |
|---|---|
| **Snapshot** | One HTML capture of one URL at one time. The atomic input. |
| **Document** | A Snapshot after a pipeline stage. Four flavors: Parsed, Normalized, Filtered, plus the residual tree after extraction. |
| **Locator** | A pointer into a Document (XPath and/or CSS selector). Stage-relative, not absolute across stages. |
| **Entity** | A semantic thing on the page: a Product, an Offer, an Article, later a JobPosting. |
| **EntityKey** | The identity of an Entity across snapshots. Distinct from its position in the tree. |
| **Field** | A named slot on an Entity (`price`, `availability`, `title`). |
| **Observation** | One extracted value for one Field, from one track, at one Locator. A Field may have several. |
| **Resolution** | The single value chosen for a Field from its Observations, plus the reason. |
| **Alignment** | The correspondence between old and new Entities. |
| **Change** | One typed, semantic difference between an aligned pair. The output unit. |
| **DiffResult** | The complete output for one Snapshot pair. |

Two distinctions that carry most of the model's weight:

**Observation vs Resolution.** Extraction produces many candidate values per Field (JSON-LD says 67.00, a regex on the visible DOM says 89.99). The model keeps both and records which won. Collapsing them at extraction time destroys the mismatch signal, which for a price monitor is often the most interesting finding.

**Absent vs Unknown vs Value.** A Field is tri-state. `Value` means extracted. `Absent` means the page genuinely doesn't assert it. `Unknown` means extraction could not determine it (markup present but unparseable, or client-side injected and therefore invisible to a fetch-only pipeline). Two-valued logic here produces the single worst class of false positive: a JSON-LD block that moves to client-side rendering between deploys looks exactly like a product going out of stock. This distinction is the model's most important invariant.

## 2. Type layers

```python
Snapshot        = (content: bytes, url: str | None, label: str)   # "old" | "new"
ParsedDoc       = (tree, encoding, parser_id, url)
NormalizedDoc   = (tree, applied_rules: list[RuleApplication])
FilteredDoc     = (tree, removals: list[Removal])
ExtractionResult = (entities: EntitySet, residual_tree, gaps: list[ExtractionGap])
```

Each stage is a distinct type, not a mutated tree. Locators captured at stage *n* are only valid against stage *n*, and `Provenance` records which stage it came from. Without that, a reported XPath silently points at a node that normalization deleted.

## 3. Entity model

```python
class EntityType(StrEnum):
    PRODUCT = "Product"
    OFFER = "Offer"
    ARTICLE = "Article"
    JOB_POSTING = "JobPosting"      # v0.3

class Entity:
    type: EntityType
    key: EntityKey | None            # None ⇒ unkeyed, alignment falls back
    fields: dict[FieldName, Field]
    parent: EntityRef | None         # Offer → Product
    locator: Locator
    extraction_source: Source        # dominant track for this entity

class EntityKey:
    scheme: KeyScheme                # AT_ID | SKU | GTIN | MPN | PRODUCT_ID | CANONICAL_URL | JOB_IDENTIFIER
    value: str
    priority: int                    # lower binds first
```

`EntityKey` is a value object with a scheme, not a bare string. Priority is fixed and part of the determinism contract: `@id` → `sku` → `gtin` → `mpn` → `productID` → canonical URL. Comparison is scheme-aware, so `sku:ABC` never matches `gtin:ABC`.

```python
class Field:
    name: FieldName
    observations: list[Observation]
    resolution: Resolution

class Observation:
    value: FieldValue
    source: Source                   # JSON_LD | MICRODATA | RDFA | HEURISTIC
    locator: Locator
    raw: str                         # pre-coercion, for debugging

class Resolution:
    state: Literal["value", "absent", "unknown"]
    value: FieldValue | None
    chosen_source: Source | None
    agreement: Agreement             # SINGLE | CONCORDANT | DISCORDANT | NONE
    reason: str
```

`Agreement` feeds directly into confidence and is what makes the cross-track mismatch case representable rather than lossy.

## 4. Field value types

Typed, not strings. Comparison semantics live on the type, which is where formatting normalization belongs.

```python
class Money:
    amount: Decimal                  # Decimal, never float
    currency: str | None             # ISO-4217; None ⇒ unknown currency
    raw: str

    # equality: amount equal AND currency equal-or-both-None
    # "1.299,00" and "1299.00" parse to the same amount

class Availability(StrEnum):         # normalized from schema.org + lexicon
    IN_STOCK, OUT_OF_STOCK, PREORDER, BACKORDER, DISCONTINUED, LIMITED, UNKNOWN

class TextBlock:
    text: str                        # post-normalization
    hash: str                        # content hash, for skip logic
    token_count: int

class Scalar:  str | int | Decimal | bool | date
class Collection: list[FieldValue]   # images, specs
```

`Money` with `Decimal` and an explicit nullable currency is not fussiness. Float arithmetic on prices produces spurious changes, and a page that states a number without a currency is common enough that conflating it with a currency-bearing price is wrong.

## 5. Change taxonomy

A Change is a triple: **subject** (what), **predicate** (which field), **operation** (how it moved). The closed type set is a projection of that triple, which keeps the taxonomy extensible without renaming existing types.

```python
class ChangeType(StrEnum):
    # entity-field changes
    PRICE_CHANGE        = "price_change"
    AVAILABILITY_CHANGE = "availability_change"
    PRODUCT_CHANGE      = "product_change"        # v0.3
    JOB_LISTING_CHANGE  = "job_listing_change"    # v0.3
    # entity lifecycle
    ENTITY_ADDED        = "entity_added"
    ENTITY_REMOVED      = "entity_removed"
    # content changes
    CONTENT_UPDATE      = "content_update"        # v0.3, scoped to main content
    TEXT_EDIT           = "text_edit"
    CONTENT_ADDED       = "content_added"
    CONTENT_REMOVED     = "content_removed"
    # meta
    EXTRACTION_GAP      = "extraction_gap"
    VALUE_DISCORDANCE   = "value_discordance"

class Operation(StrEnum):
    ADDED, REMOVED, MODIFIED, APPEARED, DISAPPEARED
```

Two meta types carry real weight and neither exists in any reviewed tool:

`EXTRACTION_GAP` fires when a Field was `value` in old and `unknown` in new (or vice versa). It is explicitly *not* a `price_change`. This is the direct answer to the client-side-rendering problem, and it lets a consumer route it to "check your scraper" instead of "alert the buyer."

`VALUE_DISCORDANCE` fires when tracks disagree within a single snapshot. It is a property of one snapshot, not of a pair, which is a structural exception worth being explicit about: a DiffResult can contain Changes that describe state rather than transition.

```python
class Change:
    type: ChangeType
    operation: Operation
    entity_type: EntityType | None
    entity_key: EntityKey | None
    field: FieldName | None
    old_value: FieldValue | None
    old_state: FieldState            # value | absent | unknown
    new_value: FieldValue | None
    new_state: FieldState
    confidence: Confidence
    provenance: Provenance
    detail: dict                     # type-specific; e.g. delta, pct, similarity
```

Carrying `old_state` and `new_state` alongside the values is what makes `null` unambiguous in the JSON output. A consumer never has to guess whether a null means "not there" or "couldn't tell."

## 6. Confidence model

Confidence is a **derived, documented function**, not a score and not a probability. Publishing the function matters more than the numbers, because a consumer writing alert thresholds needs to know what 0.9 means.

```python
class Confidence:
    score: float                     # [0,1], quantized to 2dp
    basis: ConfidenceBasis           # the structured inputs
    rule_id: str                     # which table row produced it

class ConfidenceBasis:
    source: Source
    agreement: Agreement
    key_scheme: KeyScheme | None     # alignment strength
    alignment_method: AlignmentMethod
```

MVP table (illustrative shape, exact values to be fixed and frozen per `schema_version`):

| Source | Agreement | Alignment | Score |
|---|---|---|---|
| JSON-LD | concordant with heuristic | keyed | 0.98 |
| JSON-LD | single track | keyed | 0.95 |
| Microdata / RDFa | single track | keyed | 0.90 |
| JSON-LD | discordant | keyed | 0.60 + `VALUE_DISCORDANCE` |
| Heuristic | single track | keyed | 0.70 |
| Heuristic | single track | positional | 0.50 |

Two constraints. Confidence is reproducible from `basis` alone, so the table is testable in isolation. And it is never multiplied into an aggregate page score, because a page-level number would invite exactly the threshold tuning that the structured output exists to eliminate.

## 7. Provenance model

```python
class Provenance:
    stage: PipelineStage             # which Document the locator is valid against
    locator: Locator
    source: Source
    extractor_id: str                # e.g. "extruct.jsonld", "heuristic.price.v1"
    old_locator: Locator | None      # nodes move; both sides are recorded
    normalization_rules: list[str]   # rule ids applied to this subtree
    noise_removals: list[str]        # filter ids that touched siblings

class Locator:
    xpath: str | None
    css: str | None
    node_hash: str                   # survives reordering; XPath does not
```

`node_hash` exists because XPath is positional and a diff whose provenance breaks on an inserted ad slot is not provenance. Recording the normalization rules that touched a subtree is what makes a null result explainable, per the observability requirement.

## 8. Normalization rule model

Rules are first-class data so they can be toggled, versioned, extended, and reported.

```python
class NormalizationRule:
    id: str                          # "class.css_in_js.hash", stable forever
    family: RuleFamily               # DYNAMIC_CLASS | HASHED_ID | TOKEN | CANONICAL | TIMESTAMP
    target: Target                   # ATTRIBUTE_VALUE | ATTRIBUTE | NODE | TEXT
    matcher: Matcher                 # regex | entropy threshold | tag/attr predicate
    action: Action                   # STRIP | REPLACE_WITH_PLACEHOLDER | DROP_NODE | CANONICALIZE
    phase: int                       # fixed execution order
    enabled: bool

class RuleApplication:
    rule_id: str
    locator: Locator
    before: str
    after: str
```

Three constraints. `phase` is fixed and canonicalization is last, so attribute sorting cannot mask a stripped class. Rule ids are permanent, because they appear in output provenance and users will pin them. And `REPLACE_WITH_PLACEHOLDER` exists as a distinct action from `STRIP`: replacing a hashed class with a sentinel preserves the structural fact that a class was there, which strip would lose and which matters when the presence of an attribute is itself meaningful.

## 9. Alignment result model

```python
class AlignmentResult:
    pairs: list[AlignedPair]
    added: list[Entity]              # new only
    removed: list[Entity]            # old only
    skipped: list[SubtreeSkip]       # hash-identical, not compared
    budget: BudgetReport             # v0.3 TED: exceeded? fell back?

class AlignedPair:
    old: Entity
    new: Entity
    method: AlignmentMethod          # KEYED | HASH_IDENTICAL | POSITIONAL | TREE_EDIT (v0.3)
    key_scheme: KeyScheme | None
    score: float | None              # TED similarity, None for keyed

class SubtreeSkip:
    hash: str
    locator: Locator
```

Alignment method propagates into confidence, so a positional guess is never reported as confidently as a `sku` match. `skipped` is retained in the output rather than discarded: it is the evidence that the engine looked and found nothing, which is what distinguishes a meaningful empty result from a silent failure.

One asymmetry to note: `added`/`removed` at the Entity level and `ENTITY_ADDED`/`ENTITY_REMOVED` at the Change level are the same fact at two layers. L5 must not also emit `CONTENT_ADDED` for the same nodes, or listing pages will double-report every item.

## 10. JSON output schema

```json
{
  "schema_version": "1.0",
  "engine_version": "0.2.1",
  "config_hash": "sha256:…",
  "old": { "url": "…", "label": "old", "content_hash": "sha256:…" },
  "new": { "url": "…", "label": "new", "content_hash": "sha256:…" },

  "summary": {
    "total": 2,
    "by_type": { "price_change": 1, "availability_change": 1 },
    "max_confidence": 0.98,
    "has_extraction_gap": false,
    "has_discordance": false
  },

  "changes": [
    {
      "type": "price_change",
      "operation": "modified",
      "entity_type": "Offer",
      "entity_key": { "scheme": "sku", "value": "ABC123" },
      "field": "price",
      "old_value": { "amount": "89.99", "currency": "USD" },
      "old_state": "value",
      "new_value": { "amount": "67.00", "currency": "USD" },
      "new_state": "value",
      "detail": { "delta": "-22.99", "pct": -25.55, "direction": "decrease" },
      "confidence": {
        "score": 0.98,
        "rule_id": "conf.jsonld.concordant.keyed",
        "basis": {
          "source": "json-ld",
          "agreement": "concordant",
          "key_scheme": "sku",
          "alignment_method": "keyed"
        }
      },
      "provenance": {
        "stage": "filtered",
        "source": "json-ld",
        "extractor_id": "extruct.jsonld",
        "locator": { "xpath": "/html/body/script[2]", "node_hash": "…" },
        "old_locator": { "xpath": "/html/body/script[1]", "node_hash": "…" },
        "normalization_rules": ["canonical.attr_order"],
        "noise_removals": []
      }
    }
  ],

  "diagnostics": {
    "applied_rules": [{ "rule_id": "class.css_in_js.hash", "count": 412 }],
    "noise_removed": [{ "filter_id": "builtin.script", "count": 17 }],
    "extraction": {
      "tracks_used": ["json-ld", "heuristic"],
      "entities": { "Product": 1, "Offer": 1 },
      "gaps": []
    },
    "alignment": { "keyed": 1, "positional": 0, "skipped_subtrees": 143,
                   "budget_exceeded": false },
    "timings_ms": { "parse": 7, "normalize": 11, "filter": 3,
                    "extract": 19, "align": 4, "classify": 2 }
  },

  "errors": []
}
```

Notes on the shape. `Money` serializes `amount` as a **string**, not a JSON number, to survive round-tripping without float damage. `config_hash` plus both `content_hash`es make a result fully reproducible, which is what the corpus tests assert against. `diagnostics` is a sibling of `changes`, never interleaved, so a consumer can ignore it wholesale. An empty `changes: []` with a populated `diagnostics` is the explicit no-semantic-change result.

## 11. Invariants

Assert these in tests; they are the model's contract.

1. `changes == []` ⟺ no semantic change was detected. An error never produces an empty change list; it populates `errors`.
2. A Change with `old_state == "unknown"` or `new_state == "unknown"` has type `EXTRACTION_GAP`. Never `PRICE_CHANGE` or `AVAILABILITY_CHANGE`.
3. Every Change with a `field` has a resolvable `entity_key` **or** `alignment_method != "keyed"`. A keyed change without a key is a bug.
4. `confidence.score` is recomputable from `confidence.basis` alone.
5. Each old Entity appears in at most one `AlignedPair` and, if unpaired, in exactly one of `added`/`removed`. Alignment is a matching, not a relation.
6. Nodes in `skipped` produce no Changes.
7. Identical input plus identical `config_hash` produces byte-identical output, `timings_ms` excluded.
8. Provenance `stage` matches the Document its `locator` is valid against.
9. Entity-level and content-level changes never describe the same nodes.

## 12. Ambiguities you must decide before implementation

These are genuine forks, not details. Each changes the schema or the test corpus, so deciding them late is expensive. Recommendations given, but they're yours to make.

**A. Change granularity: per-field or per-entity?**
A product whose price, title, and three images change: five Changes or one `product_change` with a nested field list? Per-field is simpler to consume and filter; per-entity matches how a human reads it and avoids five notifications for one edit.
*Recommendation:* per-field as the atom, with `summary.by_entity` counts so consumers can group. Do not add a nesting mode later; pick one now, because it is the schema's shape.

**B. Multiple Offers per Product.**
Variants, sellers, and condition tiers all produce sibling Offers. Do you diff every Offer, or resolve a canonical price (lowest? `priceSpecification`?) and diff that? Marketplace pages can carry dozens of Offers, most irrelevant.
*Recommendation:* diff all keyed Offers, and additionally emit a `PRICE_CHANGE` on the parent Product for a documented canonical selection (lowest in-stock). Do not silently pick one.

**C. Unkeyed entities in the MVP.**
Without TED, an unkeyed Offer that changes price is `ENTITY_REMOVED` + `ENTITY_ADDED`, not `PRICE_CHANGE`. Acceptable for v0.2, or does positional alignment for single-entity pages get added?
*Recommendation:* allow positional alignment only when both snapshots contain exactly one entity of that type, at confidence ≤0.5. It covers most product detail pages at negligible risk and costs a few lines.

**D. Is `VALUE_DISCORDANCE` a Change at all?**
It describes one snapshot, not a transition, which breaks the "Change = difference between pair" definition. Alternatives: put it in `diagnostics`, or keep it in `changes` as a first-class finding.
*Recommendation:* keep it in `changes`. A JSON-LD price contradicting the visible price is exactly what a price monitor should surface. But if you make that call, amend the definition of Change in the docs to "a typed finding about the pair," or the model is internally inconsistent.

**E. Snapshot ordering and symmetry.**
Is `diff(a, b)` required to be the exact inverse of `diff(b, a)`? Full antisymmetry is elegant and constrains the confidence table (a gap in one direction must score like a gap in the other).
*Recommendation:* require order-sensitivity (old→new is meaningful) but assert in tests that type and operation invert cleanly. Do not promise value-level symmetry for text changes.

**F. Text change granularity.**
`TEXT_EDIT` at what unit: block, sentence, or word? Blocks are cheap and stable; words reproduce the noise problem the project exists to solve.
*Recommendation:* block-level in the MVP, with a similarity ratio in `detail`. Sentence-level waits for the embedding provider at v0.4, where it's actually decidable.

**G. Meaningful-edit threshold.**
`TEXT_EDIT` with `difflib` ratio 0.98 is almost certainly noise. Is there a default cutoff, and is a suppressed edit invisible or reported at low confidence?
*Recommendation:* a documented default cutoff, suppressed edits counted in `diagnostics` but absent from `changes`. Silent suppression with no count is the failure mode that erodes trust in exactly this category of tool.

**H. Currency change semantics.**
Price 89.99 USD → 89.99 EUR. One `PRICE_CHANGE` with a currency delta, a separate `CURRENCY_CHANGE`, or `VALUE_DISCORDANCE`? Common on geo-localized pages served from different IPs, which means it is frequently an artifact of *your* fetching, not the site.
*Recommendation:* `PRICE_CHANGE` with `detail.currency_changed: true` and `detail.delta: null`. Never compute a cross-currency delta.

**I. Listing pages: entity churn or content churn?**
A category page where 3 of 40 products rotate. Three `ENTITY_ADDED` plus three `ENTITY_REMOVED`, or one aggregate "listing changed"? Invariant 9 forbids reporting both.
*Recommendation:* entity-level only, never content-level, for any subtree that yielded entities. Add `summary.by_type` counts so a consumer can threshold on churn volume.

**J. Does `config` belong in the output, or only its hash?**
Full config aids reproducibility but may contain user selectors that reveal internal logic, and it bloats every result.
*Recommendation:* hash only, with a `--emit-config` flag. Hash must cover rule versions and pinned filter lists, or reproducibility is a fiction.

**K. Field name namespace.**
Are field names schema.org-native (`availability`, `offers.price`) or a SemDiff-normalized vocabulary (`stock_status`, `price`)? Native means zero mapping work and a documentation shortcut; normalized means heuristic-track fields don't need invented schema.org paths.
*Recommendation:* a normalized flat vocabulary, with the schema.org path retained in `provenance`. Heuristic extraction has no natural schema.org path, and forcing one would be a lie in the provenance field.

**L. What is an Entity on a page with no entities at all?**
A news article without markup: is there one implicit `Article` Entity wrapping main content, or is the page entity-free and everything is a content change? This determines whether `CONTENT_UPDATE` is an entity-field change or a free-floating change.
*Recommendation:* synthesize a single implicit `Article` from trafilatura output when content scoping is enabled, keyed on canonical URL. It makes the model uniform, and Invariant 9 then has a clean subject to attach to.