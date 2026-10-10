"""The fused attribute pass must be indistinguishable from one traversal per rule.

Fusing is a performance change, so the whole corpus is the evidence: every snapshot of every
pair is normalized by both engines and compared on the serialized tree *and* on the full
provenance record — rule id, before, after and locator, in order. Two tests per pair, one per
snapshot, so a failure names the document rather than the corpus.

This is the expensive test in the suite by design (NFR-1 determinism is cheap to assert and
cheap to lose). It runs the shipped engine against ``tests.normalize.reference``, which is the
pre-fusion body of ``apply_rules``.
"""

from __future__ import annotations

import pytest

from semdiff import Config, parse
from semdiff.config import NormalizationConfig
from semdiff.normalize.registry import BUILTIN_RULES, apply_rules
from tests.corpus.labels import Category
from tests.corpus.loader import Pair, load_pairs
from tests.normalize.reference import apply_rules_per_rule, records

PAIRS = load_pairs(category=Category.NOISE_ONLY)
SNAPSHOTS = [
    pytest.param(pair, which, id=f"{pair.id}-{which}")
    for pair in PAIRS
    for which in ("old", "new")
]


@pytest.mark.parametrize(("pair", "which"), SNAPSHOTS)
def test_fused_pass_matches_one_pass_per_rule(pair: Pair, which: str) -> None:
    raw = pair.old_bytes if which == "old" else pair.new_bytes
    doc = parse(raw, config=Config())
    config = NormalizationConfig()

    fused = apply_rules(doc, BUILTIN_RULES, config)
    per_rule = apply_rules_per_rule(doc, BUILTIN_RULES, config)

    assert fused.tree.html == per_rule.tree.html
    assert records(fused) == records(per_rule)


def test_the_corpus_really_exercises_the_fused_pass() -> None:
    """A guard on the test above: it proves nothing if no attribute rule ever fires."""
    doc = parse(PAIRS[0].old_bytes, config=Config())
    result = apply_rules(doc, BUILTIN_RULES, NormalizationConfig())
    fired = {a.rule_id for a in result.applied_rules}
    assert any(rule_id.startswith("asset.") for rule_id in fired)
    assert len(fired) > 1
