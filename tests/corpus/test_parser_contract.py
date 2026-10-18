"""T-25: what must not move when the parser build moves (F-027, D-046).

`config_hash` covers the configuration and the ruleset, not the parser, so a result is
reproducible only for a given parser build. That makes the parser a silent input, and the
corpus gates cannot see it: T-21, the fused-equivalence suite and the T-24 recall gate all
compare two documents processed by the *same* parser, so a parser change moves both sides
and every one of them stays green. Exactly that happened — selectolax 1.0.0 stopped
lowercasing spec-adjusted foreign-content attribute keys (`viewBox`, not `viewbox`), which
switched `canonical.attr_order` off for every `<svg>`; 36 of these 40 snapshots normalized
differently and all three gates passed anyway.

So this file pins the output itself, against digests recorded in `parser_contract.json`:

* the normalized bytes of all 40 snapshots, and
* every application record **except** `node_hash` — rule id, before, after and locator path.

`node_hash` is deliberately outside the contract. It fingerprints the node's own attributes
(D-044) including the spelling of their names, so the same document yields a different hash
for a `<svg>` on 0.4.x and on 1.0.0: 464 of 23,204 records, all on foreign content. Lowercasing
names inside the fingerprint would hide that, and D-046 declined to redefine D-044 for it. The
difference is therefore asserted as a known property rather than papered over.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
from typing import cast

import pytest
from selectolax.lexbor import LexborNode

from semdiff import Config, normalize, parse
from semdiff.config import NormalizationConfig
from semdiff.locator import _node_hash
from semdiff.normalize.registry import BUILTIN_RULES, apply_rules
from tests.corpus.labels import Category
from tests.corpus.loader import Pair, load_pairs

PAIRS = load_pairs(category=Category.NOISE_ONLY)
CONTRACT_PATH = pathlib.Path(__file__).with_name("parser_contract.json")
CONTRACT = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
SNAPSHOTS = [
    pytest.param(pair, which, id=f"{pair.id}-{which}")
    for pair in PAIRS
    for which in ("old", "new")
]


def digests(raw: bytes) -> dict[str, str]:
    """The two digests the contract pins, for one snapshot.

    The record digest leaves ``node_hash`` out on purpose; everything else about an
    application — which rule fired, on what, to what effect, and where — is parser-independent
    and is pinned.
    """
    output = normalize(raw, config=Config())
    result = apply_rules(parse(raw, config=Config()), BUILTIN_RULES, NormalizationConfig())
    records = [
        [app.rule_id, app.before, app.after, app.locator.css, app.locator.xpath]
        for app in result.applied_rules
    ]
    return {
        "output": hashlib.sha256(output.encode("utf-8")).hexdigest(),
        "records": hashlib.sha256(
            json.dumps(records, ensure_ascii=False).encode("utf-8")
        ).hexdigest(),
    }


@pytest.mark.parametrize(("pair", "which"), SNAPSHOTS)
def test_snapshot_matches_the_recorded_parser_contract(pair: Pair, which: str) -> None:
    raw = pair.old_bytes if which == "old" else pair.new_bytes
    recorded = CONTRACT["snapshots"][f"{pair.id}-{which}"]
    measured = digests(raw)
    assert measured["output"] == recorded["output"], (
        f"{pair.id}-{which}: normalized output changed. If this followed a parser upgrade, it is "
        f"the parser moving the engine's output — see F-027 before re-recording the contract."
    )
    assert measured["records"] == recorded["records"], (
        f"{pair.id}-{which}: application records changed (node_hash excluded)."
    )


def test_the_contract_covers_every_snapshot() -> None:
    """A contract that quietly stopped covering a document would pass without testing it."""
    assert set(CONTRACT["snapshots"]) == {f"{pair.id}-{which}" for pair in PAIRS for which in ("old", "new")}
    assert len(CONTRACT["snapshots"]) == len(PAIRS) * 2 == 40
    assert CONTRACT["verified_on"], "the contract must say which parser builds produced it"


def test_node_hash_is_deliberately_outside_the_contract() -> None:
    """The known, accepted parser-dependent field (D-046 rider 2).

    ``_node_hash`` hashes the attribute *names* as the parser reports them, so the spelling a
    parser version chooses for a foreign-content key changes the fingerprint. The real parsers
    cannot both be present in one process, so the mechanism is asserted against two nodes that
    differ only in that spelling.
    """

    class _Node:
        """The three attributes ``_node_hash`` reads from an element."""

        def __init__(self, attributes: dict[str, str]) -> None:
            self.tag = "svg"
            self.attributes = attributes
            self.is_element_node = True
            self.html = "<svg>"
            self.text_content = None

    lowercased = cast(LexborNode, _Node({"viewbox": "0 0 16 16", "width": "18"}))
    adjusted = cast(LexborNode, _Node({"viewBox": "0 0 16 16", "width": "18"}))
    assert _node_hash(lowercased) != _node_hash(adjusted)
    assert _node_hash(lowercased) == _node_hash(cast(LexborNode, _Node({"viewbox": "0 0 16 16", "width": "18"})))


def test_node_hash_is_stable_within_a_run() -> None:
    """Outside the cross-version contract, but still deterministic here and now (NFR-1)."""
    raw = PAIRS[0].old_bytes
    first = apply_rules(parse(raw, config=Config()), BUILTIN_RULES, NormalizationConfig())
    second = apply_rules(parse(raw, config=Config()), BUILTIN_RULES, NormalizationConfig())
    assert [app.locator.node_hash for app in first.applied_rules] == [
        app.locator.node_hash for app in second.applied_rules
    ]
