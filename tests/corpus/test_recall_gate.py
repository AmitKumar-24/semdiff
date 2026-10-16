"""T-24 acceptance gate: a real change must survive normalization (D-045).

T-21 proves normalization stays quiet on twenty unchanged pages. This is its other half — that
it still speaks when something real changes. Each of the same twenty captures is mutated in
memory, one surgical edit at a time, and the edit must come through ``normalize()`` *as itself*:
the new literal present, or the removed one one occurrence shorter. The noise controls mutate the
same documents with deploy noise of a shape the rules already handle, and demand byte-identical
output — otherwise this gate would be satisfied by a ``normalize()`` that does nothing at all.

The mutations are **synthetic edits to real captures**, which is weaker evidence than a captured
real-change pair and is not a substitute for one: NFR-5's corpus of real changes does not exist
yet. ``docs/BASELINE.md`` states the distinction, D-045 records why this is the method anyway.

Nothing under ``corpus/`` is ever written. ``test_no_fixture_was_modified`` re-hashes every
fixture file after the whole catalogue has run and proves it.
"""

from __future__ import annotations

import functools
import hashlib

import pytest

from semdiff import normalize
from tests.corpus.labels import Category
from tests.corpus.loader import CORPUS_ROOT, Pair, load_pairs
from tests.corpus.mutations import CATALOGUE, Expect, Mutation

PAIRS = load_pairs(category=Category.NOISE_ONLY)

# Measured applicability, pinned. A class that stops reaching this many documents has lost
# coverage — a fixture changed shape, or a locator silently stopped matching — and that must
# fail loudly rather than quietly parametrize fewer cases. Floors are raised when the corpus
# grows, never lowered to keep a green run.
FLOORS: dict[str, int] = {
    "R1": 20, "R2": 7, "R3": 8, "R4": 7, "R5": 7, "R6": 11, "R7": 20,
    "R8": 13, "R9": 20, "R10": 20, "R11": 20, "R12": 6, "R13": 20,
    "N1": 12, "N2": 20, "N3": 6, "N4": 20, "N5": 20, "N6": 20,
}
TOTAL_CASES = 277


@functools.lru_cache(maxsize=64)
def baseline(raw: bytes) -> str:
    """``normalize()`` of an unmutated capture, computed once per document."""
    return normalize(raw)


def applicable(mutation: Mutation) -> list[Pair]:
    return [pair for pair in PAIRS if mutation.build(pair.old_bytes) is not None]


Case = tuple[Mutation, Pair]


def cases(expect: Expect) -> list[Case]:
    return [
        (mutation, pair)
        for mutation in CATALOGUE
        if mutation.expect is expect
        for pair in applicable(mutation)
    ]


def case_id(case: Case) -> str:
    return f"{case[0].id}-{case[1].id}"


VISIBLE_CASES = cases(Expect.VISIBLE)
IDENTICAL_CASES = cases(Expect.IDENTICAL)


@pytest.mark.parametrize(
    ("mutation", "pair"), VISIBLE_CASES, ids=[case_id(case) for case in VISIBLE_CASES]
)
def test_a_real_change_survives_normalization(mutation: Mutation, pair: Pair) -> None:
    edit = mutation.build(pair.old_bytes)
    assert edit is not None  # parametrized only over documents this mutation applies to
    assert edit.mutated != pair.old_bytes, f"{mutation.id}: the mutation changed nothing"
    assert edit.present or edit.removed, f"{mutation.id}: nothing to look for proves nothing"

    before, after = baseline(pair.old_bytes), normalize(edit.mutated)
    assert after != before, f"{mutation.id} on {pair.id}: {mutation.label} was erased"
    for literal in edit.present:
        # A count, not a presence test: two captures already carry a non-breaking space (written
        # `&#160;`, re-serialized `&nbsp;`), so R11's marker is not absent to begin with.
        assert after.count(literal) == before.count(literal) + 1, (
            f"{mutation.id} on {pair.id}: {literal!r} appears "
            f"{after.count(literal)} times, expected {before.count(literal) + 1}"
        )
    for literal in edit.removed:
        assert after.count(literal) == before.count(literal) - 1, (
            f"{mutation.id} on {pair.id}: {literal!r} appears "
            f"{after.count(literal)} times, expected {before.count(literal) - 1}"
        )


@pytest.mark.parametrize(
    ("mutation", "pair"), IDENTICAL_CASES, ids=[case_id(case) for case in IDENTICAL_CASES]
)
def test_known_noise_still_normalizes_identically(mutation: Mutation, pair: Pair) -> None:
    edit = mutation.build(pair.old_bytes)
    assert edit is not None
    assert edit.mutated != pair.old_bytes, f"{mutation.id}: the mutation changed nothing"

    after = normalize(edit.mutated)
    source = edit.mutated.decode("utf-8", errors="replace")
    for literal in edit.erased:
        assert literal in source, f"{mutation.id} on {pair.id}: {literal!r} is not in the input"
        assert literal not in after, f"{mutation.id} on {pair.id}: {literal!r} was not erased"
    assert after == baseline(pair.old_bytes), f"{mutation.id} on {pair.id}: {mutation.label} leaked"


def test_every_mutation_class_reaches_its_floor() -> None:
    """Each class covers at least as many documents as it did when the floor was measured."""
    measured = {mutation.id: len(applicable(mutation)) for mutation in CATALOGUE}
    assert set(measured) == set(FLOORS), "the catalogue and the floors have drifted apart"
    short = {name: count for name, count in measured.items() if count < FLOORS[name]}
    assert not short, f"lost coverage: {short} against floors {FLOORS}"


def test_the_gate_is_as_large_as_it_was_measured_to_be() -> None:
    """A guard against the gate quietly shrinking to nothing — the failure mode of a parametrized
    suite is zero cases, which passes."""
    assert len(VISIBLE_CASES) + len(IDENTICAL_CASES) >= TOTAL_CASES
    assert len(VISIBLE_CASES) >= 179 and len(IDENTICAL_CASES) >= 98
    every = VISIBLE_CASES + IDENTICAL_CASES
    assert len({case_id(case) for case in every}) == len(every), "duplicate case ids"


def test_both_expectations_are_represented() -> None:
    """A gate of recall cases alone would pass on a normalizer that does nothing; a gate of
    controls alone would pass on one that erases everything."""
    kinds = {mutation.expect for mutation in CATALOGUE}
    assert kinds == {Expect.VISIBLE, Expect.IDENTICAL}
    assert sum(m.expect is Expect.IDENTICAL for m in CATALOGUE) >= 5


def test_the_provisional_row_says_what_it_is_waiting_on() -> None:
    """R6 pins today's treatment of a visible build-identity stamp. Q-26 is open on whether that
    shape is noise; if it resolves the other way this row becomes a documented limit, and the
    note is what makes that a decision rather than a surprise."""
    version = next(mutation for mutation in CATALOGUE if mutation.id == "R6")
    assert "Q-26" in version.provisional and "Provisional" in version.provisional
    assert all(not m.provisional for m in CATALOGUE if m.id != "R6")


def test_no_fixture_was_modified() -> None:
    """Mutation is in memory only. Every fixture file is re-hashed after the whole catalogue has
    been built against every document."""
    def digest() -> dict[str, str]:
        return {
            str(path.relative_to(CORPUS_ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(CORPUS_ROOT.rglob("*"))
            if path.is_file()
        }

    before = digest()
    for mutation in CATALOGUE:
        for pair in PAIRS:
            mutation.build(pair.old_bytes)
            mutation.build(pair.new_bytes)
    assert digest() == before
    assert len(before) >= len(PAIRS) * 3, "a fixture is missing its old.html, new.html or pair.json"
