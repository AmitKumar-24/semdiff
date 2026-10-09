"""T-21 acceptance gate: every ``noise_only`` pair must normalize to byte-identical output.

This is the release gate of NFR-4 at layer 1 — on a pair whose only differences are noise,
`normalize()` must erase them completely, so a differ downstream sees nothing. One test per
fixture, so a failure names the pair.

Two fixtures are **expected red** and marked ``xfail(strict=True)``: they were admitted by
independent review (D-021), not by what the ruleset can do, and the shipped ruleset cannot
neutralize them yet. ``strict=True`` is the point — the day FR-44 learns these hashes, the
xfail turns into a failure and forces this list to shrink. The list is never grown to make
a red fixture quiet; a new red pair means either the rules or the label is wrong.
"""

from __future__ import annotations

import pytest

from semdiff import normalize
from tests.corpus.assertions import assert_normalized_identical
from tests.corpus.labels import Category
from tests.corpus.loader import Pair, load_pairs

# Empty, and the whole corpus is expected green. It last held ``pnpm-io-001`` and
# ``pnpm-io-002``, whose Vite base64url hashes (``/assets/index-CxL6fshY.js``) FR-44's
# hex-only patterns could not reach; ``asset.dashed_base64`` closed that gap and the strict
# xfails turned into failures, which is how this list is meant to shrink.
KNOWN_RED: frozenset[str] = frozenset()
KNOWN_RED_REASON = "admitted by independent review before the ruleset could neutralize it"

# T-21's gate is the full noise_only corpus, which is why the target count is asserted below.
NOISE_ONLY_TARGET = 20
NOISE_ONLY = load_pairs(category=Category.NOISE_ONLY)

PARAMS = [
    pytest.param(
        pair,
        id=pair.id,
        marks=[pytest.mark.xfail(reason=KNOWN_RED_REASON, strict=True)] if pair.id in KNOWN_RED else [],
    )
    for pair in NOISE_ONLY
]


@pytest.mark.parametrize("pair", PARAMS)
def test_noise_only_pair_normalizes_identically(pair: Pair) -> None:
    assert_normalized_identical(pair, normalize)


def test_gate_covers_the_whole_noise_only_corpus() -> None:
    """Every fixture is parametrized, and the corpus has reached T-21's target size."""
    assert [p.id for p in NOISE_ONLY] == [p.id for p in load_pairs(category=Category.NOISE_ONLY)]
    assert len(PARAMS) == len(NOISE_ONLY)
    assert len(NOISE_ONLY) >= NOISE_ONLY_TARGET, f"T-21 needs {NOISE_ONLY_TARGET} noise_only pairs"


def test_known_red_fixtures_still_exist() -> None:
    """A renamed or removed fixture must not leave a stale exemption behind."""
    assert KNOWN_RED <= {p.id for p in NOISE_ONLY}


def test_most_of_the_corpus_is_expected_green() -> None:
    """The exemption list is a short, deliberate exception — not a way of life."""
    assert len(KNOWN_RED) * 4 <= len(NOISE_ONLY), "too many exempt fixtures for this to be a gate"
