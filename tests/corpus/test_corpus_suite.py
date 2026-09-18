"""The corpus suite that runs on every task (CLAUDE §5). Green on an empty corpus (T-03)."""

from __future__ import annotations

import pytest

from tests.corpus.loader import CORPUS_ROOT, Pair, load_pairs

PAIRS = load_pairs(CORPUS_ROOT)


def test_corpus_layout_is_valid() -> None:
    """Every directory under corpus/ is a known category holding well-formed fixtures."""
    assert CORPUS_ROOT.is_dir()
    assert len({p.id for p in PAIRS}) == len(PAIRS)


@pytest.mark.parametrize("pair", PAIRS, ids=[p.id for p in PAIRS])
def test_pair_is_well_formed(pair: Pair) -> None:
    assert pair.dir.name == pair.id
    assert pair.label.category == pair.category
    assert pair.old_bytes
    assert pair.new_bytes
