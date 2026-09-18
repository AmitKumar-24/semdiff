# CLAUDE.md — Operating Instructions for SemDiff

This file governs how you work in this repository. Read it fully before doing anything else.

---

## 0. What this project is

SemDiff is a Python library that takes two HTML snapshots and returns **typed semantic change objects** — `price_change`, `availability_change`, `content_update`, and so on — instead of a raw HTML or DOM diff.

It is **not** another DOM differ. `xmldiff` and `diffDOM` already emit node-level edit scripts and are reused where node-level work is needed. It is **not** a monitoring product: no UI, no scheduler, no notifications. The goal is to be the diff backend inside changedetection.io, urlwatch, and Scrapy pipelines.

Three things are genuinely built here: **normalization**, **entity-keyed alignment**, and **semantic classification**. Everything else is composition of existing libraries. If you find yourself writing a parser, an ad-filter heuristic, a content extractor, or a tree-edit-distance algorithm, stop — see §7.

---

## 1. First action: inspect, then propose. Do not write production code yet.

On your first turn in this repository, in this order:

1. **Inspect the repository.** List the tree. Read `pyproject.toml`, any existing source, tests, CI config, and every file under `docs/`.
2. **Read the design documents.** They are the source of truth, in this precedence order:
   1. `docs/domain-model.md` — highest precedence for types, schema, invariants
   2. `docs/architecture.md` — layer boundaries and build-vs-reuse
   3. `docs/requirements.md` — FR/NFR identifiers
   4. `docs/roadmap.md` — task IDs and phase gates
   5. `docs/brief.md` — positioning and non-goals
3. **Report your understanding** in under 400 words: what the pipeline is, what the current repository state is, which roadmap phase is actually in progress, and what the next unblocked task is.
4. **List every contradiction, gap, or ambiguity you found** between the documents and the code. Do not resolve any of them yourself.
5. **Propose a plan for the next task only** — not the phase, not the project. The plan states: task ID, files to touch, the test you will write first, the assertion that proves it works, and an estimated diff size in lines.
6. **Stop and wait for my approval.**

If `docs/` is missing or incomplete, say so and stop. Do not reconstruct the design from this file — this file is a summary, not the specification.

---

## 2. Working agreement

- **One roadmap task per change set.** Task IDs (`T-13`, `T-46`) come from `docs/roadmap.md`. Reference the ID in every plan, commit message, and report.
- **Test first, always.** Write the failing test, show me it fails for the right reason, then implement.
- **Small steps.** Target under 200 lines of production diff per task. If a task needs more, split it and tell me how before starting.
- **Never implement a task I have not approved.** Not even a "quick" adjacent fix.
- **No commits unless I explicitly ask.** Leave changes in the working tree.
- **Everything runs locally and passes before you report done.** No "should work" — run it.
- Keep your reports short and factual. I prefer concise iterative exchanges over long summaries.

---

## 3. Hard rules

Violating any of these is a failed task, regardless of whether tests pass.

1. **No unrelated changes.** No opportunistic refactors, reformatting, renames, dependency bumps, or drive-by fixes. If you spot something worth changing, add it to a `FINDINGS.md` list and mention it in your report. Do not act on it.
2. **No new dependencies without approval.** The core install is `selectolax`, `lxml`, `extruct`, `pydantic`. Nothing else. `trafilatura` lives behind `[content]`, ML behind `[ml]`.
3. **No network, clock, randomness, or model calls in the core diff path.** This is the determinism contract (NFR-1) and the project's differentiator. A `datetime.now()` or a `requests.get()` in `semdiff/` core is a failed task.
4. **No ML in the core.** ML is a pluggable provider behind an interface, with a deterministic default. The library must run fully with a core-only install.
5. **Never change the output schema without explicit approval.** `schema_version` is a public contract. `xmldiff`'s unstable output across versions is a documented adoption blocker we are deliberately avoiding.
6. **Never silently resolve an open design decision.** See §9.
7. **Never weaken a test or a gate to make a change pass.** If a gate fails, report it and stop.
8. **Treat all HTML input as untrusted.** Parse-only. No JS execution, no XML external entity resolution, no outbound requests from any extraction path.

---

## 4. Per-task workflow

For each approved task, follow this loop and report at the end of it:

1. **Restate** the task ID, the requirement IDs it satisfies, and the invariants it must not break.
2. **Write the test.** Place it so it can fail independently. Run it. Show the failure.
3. **Implement** the smallest thing that passes.
4. **Run the gates** (§5). All of them, not just the new test.
5. **Self-review** against the checklist in §8. Report what you found, including anything you fixed.
6. **Report:** files changed with line counts, test output, gate status, anything you deliberately did not do, and any finding added to `FINDINGS.md`.
7. **Stop.** Do not start the next task.

---

## 5. Tests, gates, and benchmarks

The corpus harness (`T-03`) and the noise-only corpus (`T-04`) come before implementation code. They are what make the gates real.

**Run on every task:**
- Unit tests for the touched layer
- `mypy --strict`
- Determinism test (`T-62`): identical input plus identical `config_hash` produces byte-identical output, `timings_ms` excluded
- Full corpus suite

**Phase gates — do not declare a phase complete until these pass:**

| Gate | Requirement |
|---|---|
| v0.1 (`T-21`) | Noise-only corpus: **zero** change objects. All 20 pairs byte-identical after normalization. |
| v0.1 (`T-22`) | Baseline table published: same pairs through `lxml.html.diff` and `difflib`, change counts recorded. |
| v0.2 (`T-63`) | ≥0.95 precision on `price_change` where JSON-LD `Offer` is present. |
| v0.2 (`T-64`) | Heuristic-track precision and recall published **separately**. Never blended with the structured track into one number. |
| v0.3 (`T-78`) | TED performance regression test at p95 on large pages; cliff behavior measured. |
| v0.3 (`T-88`) | False-positive reduction vs difflib measured on a monitoring corpus. |
| v0.4 (`T-96`) | Embedding path beats the rule-only baseline on ambiguous text edits. |
| v0.4 (`T-97`) | CI job with a core-only install still passes everything. |

**Benchmarks are deliverables, not diagnostics.** `T-22` and `T-102` are the adoption argument. Any benchmark you produce must be reproducible with one command, state its hardware, and be committed with its raw output.

**Corpus discipline:** labeled fixtures with source URL and capture date. Never modify a corpus fixture to make code pass. If a fixture looks mislabeled, report it.

---

## 6. Invariants — assert these in tests

From `docs/domain-model.md`. These are the model's contract. Each one needs a test that fails if it is broken.

1. `changes == []` ⟺ no semantic change detected. An error never yields an empty change list; it populates `errors`.
2. A change with `old_state` or `new_state` of `unknown` has type `EXTRACTION_GAP` — never `PRICE_CHANGE` or `AVAILABILITY_CHANGE`.
3. Every change with a `field` has a resolvable `entity_key` **or** `alignment_method != "keyed"`.
4. `confidence.score` is recomputable from `confidence.basis` alone.
5. Alignment is a matching: each old entity appears in at most one `AlignedPair`, and if unpaired, in exactly one of `added`/`removed`.
6. Nodes in `skipped` produce no changes.
7. Identical input plus identical `config_hash` produces byte-identical output (`timings_ms` excluded).
8. Provenance `stage` matches the document its `locator` is valid against.
9. Entity-level and content-level changes never describe the same nodes.

**The tri-state field rule deserves special care.** `value` / `absent` / `unknown` are distinct. A JSON-LD block that moves to client-side rendering between deploys must produce `EXTRACTION_GAP`, not "out of stock". Two-valued logic here is the worst false-positive class in the whole design.

---

## 7. Build vs reuse — do not reinvent

| Concern | Use | Never build |
|---|---|---|
| Parsing | `selectolax` (Lexbor) default, `lxml` for XPath | A parser |
| Structured data | `extruct` (JSON-LD, Microdata, RDFa) | A microdata parser |
| Main content | `trafilatura` behind `[content]` | Density heuristics |
| Noise rules | EasyList / EasyPrivacy lists | Ad-detection heuristics |
| Tree edit distance | `apted` or `zss` | A TED algorithm |
| Text similarity | `difflib` default, sentence-transformers under `[ml]` | A similarity metric |
| Output ergonomics | Borrow `deepdiff`'s shape | — |

**Build only:** the normalization rule engine (L1), the entity-keyed alignment wrapper over APTED (L4), and semantic classification (L5). Two thin adapters are also ours because no upstream offers them: applying EasyList *cosmetic* rules to a static DOM (existing engines assume a live browser), and mapping extruct's raw output to the internal entity model.

If a task seems to require building something in the "never build" column, stop and ask. You have misread the task.

---

## 8. Code review checklist

Self-review against this before reporting. Report what the review found.

- Does the change touch exactly one pipeline layer? Cross-layer changes need approval.
- Does data flow strictly forward? No layer reaches upstream.
- Is the new code deterministic? No clock, network, randomness, set-iteration order, or dict-order dependence.
- Are all monetary values `Decimal`, never `float`? Does `Money` serialize `amount` as a **string**?
- Is field state tri-valued everywhere it is read, not just where it is written?
- Are rule IDs, filter IDs, and extractor IDs stable? They appear in output provenance and users will pin them.
- Is normalization phase order preserved, with canonicalization last?
- Does anything new appear in `diagnostics` so an empty result stays explainable (NFR-10)?
- Are error paths typed, and do they populate `errors` rather than returning a partial diff?
- Is any newly discovered limitation documented in the README limitations section (`T-65`)?
- Are there any `TODO`s or commented-out code left behind? Remove them or list them.

---

## 9. Open design decisions — never resolve these silently

`docs/domain-model.md` §12 lists ambiguities A–L. If a task requires one of them, **stop and ask**. Note my answer in `docs/decisions.md` with the date before continuing.

**These four block Phase 1 and Phase 2 and must be settled before the code they gate:**

| ID | Decision | Gates |
|---|---|---|
| **K** | Field name namespace: normalized vocabulary vs schema.org-native | Phase 1 schema, `T-34`, `T-36` |
| **A** | Change granularity: per-field vs per-entity | Phase 2 schema, `T-36`, `T-49` |
| **B** | Multiple `Offer`s per `Product`: diff all, or resolve a canonical price | Phase 2 tests |
| **C** | Positional alignment for single-entity pages: allowed or not | `T-48` |

D–L can wait for their phase. Recognizing that a task has hit one of them is part of the task.

---

## 10. Stop and ask when

- A task needs a new dependency, a schema change, or a change to the confidence table
- A gate fails and the fix is not obviously within the task's scope
- Two design documents contradict each other
- A design decision from §9 is required
- The implementation would exceed ~200 lines of production diff
- A corpus fixture looks mislabeled or a test looks wrong
- You believe the plan I approved is the wrong approach — say so before implementing, not after

Asking is always cheaper than a large unapproved change. Default to asking.

---

## 11. Report format

Keep it to this shape:

```
Task: T-13 (dynamic class normalization) — FR-5
Files: semdiff/normalize/rules/classes.py (+84), tests/normalize/test_classes.py (+61)
Tests: 14 passed. mypy strict clean. Determinism ok. Corpus 20/20.
Gates: T-21 not yet reachable (needs T-17).
Not done: entropy-based fallback — that is T-14.
Findings: 1 added to FINDINGS.md (extruct pins an old lxml minor).
Next unblocked: T-14. Awaiting approval.
```

No prose summaries of what the code does. I can read the diff.

---

## 12. Current state

**Phase 0** — scaffolding. Nothing is implemented.

The first task is `T-04`: build the noise-only corpus of 20 real page pairs where only CSS classes, IDs, tokens, and timestamps changed, before any normalization code exists. It is the v0.1 gate and the project's central claim. Writing the corpus before the implementation is the only way it stays honest.

`T-00` through `T-03` may be proposed alongside it.

Start with §1.