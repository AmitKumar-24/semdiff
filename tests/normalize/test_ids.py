"""T-14: hashed-ID rule family (FR-6) — pattern rules plus a conservative entropy matcher."""

from __future__ import annotations

import pytest

from semdiff import NormalizationConfig, parse
from semdiff.normalize import BUILTIN_RULES, EntropyMatcher, RuleFamily, Target, apply_rules
from semdiff.normalize.rules.ids import ENTROPY_MIN_BITS, ENTROPY_MIN_LENGTH, ID_RULES

BY_ID = {rule.id: rule for rule in ID_RULES}

POSITIVE = {
    "id.hex_suffix": ["react-root-7a3b2c", "el-5f3a9c2b7d1e", "widget_0a1b2c3d", "app-root-deadbeef1"],
    "id.react_use_id": ["_R_lql3aqll6_", "_R_6hjaanlkmbjqfsua_", "radix-:R16i7hjtavbba:", ":r1:", "mui-_r_5a_"],
    "id.entropy": [
        "3f2504e04f8911d39a0c0305e82c3301", "b5a6a95bdecc42529577f59bf028a889",
        "gen-oo3sb09glshv616m", "gen-ts56zc4pz0lx9xf26gk7", "csrf-Z9x8Y7w6V5u4Tt3s2R1q",
    ],
}

NEGATIVE = [
    # semantic ids from the captures and the task brief
    "header", "main", "product-card", "login-form", "root", "api", "faq", "email", "features",
    "advantages-of-material-ui", "mui-product-selector", "json.JSONEncoder.default", "cmdoption-json-arg-outfile",
    "__docusaurus_skipToContent_fallback", "comparison-with-other-tools", "install-storybook",
    "__next", "__NEXT_DATA__", "_R_", "B:0", "S:1d", "P:21",
    # digits that are meaningful, not hashes
    "product-123456", "index-0", "id1", "h2-2024-annual-report", "section-4b", "table-row-12345678", "user-42-profile",
    "iso8601-format", "utf8-decoding", "md5checksum", "sha256sum", "item2024report", "q3fy2025results",
    "documentation2024", "report-documentation2024",
    # hex-looking words and letters-only strings
    "item-decade", "card-facade", "abcdefghijklmnop", "nav-beaded",
]


@pytest.mark.parametrize(("rule_id", "value"), [(r, v) for r, vs in POSITIVE.items() for v in vs])
def test_rule_matches_its_generator(rule_id: str, value: str) -> None:
    assert BY_ID[rule_id].matcher.matches(value)


@pytest.mark.parametrize("value", NEGATIVE)
def test_meaningful_ids_match_no_rule(value: str) -> None:
    assert [rule.id for rule in ID_RULES if rule.matcher.matches(value)] == []


def test_entropy_matcher_boundaries() -> None:
    matcher = EntropyMatcher(min_length=ENTROPY_MIN_LENGTH, min_entropy=ENTROPY_MIN_BITS)
    assert (ENTROPY_MIN_LENGTH, ENTROPY_MIN_BITS) == (16, 3.5)
    assert matcher.matches("a1b2c3d4e5f6g7h8")  # 16 chars, all distinct → 4.0 bits, interleaved
    assert not matcher.matches("a1b2c3d4e5f6g7h")  # 15 chars: one under the length floor
    assert not matcher.matches("abcdefghijklmnop")  # 4.0 bits but no digits
    assert not matcher.matches("1234567890123456")  # digits only
    assert not matcher.matches("aaaaaaaa11111111")  # 16 chars, interleaved once, 1.0 bit
    assert not matcher.matches("documentation2024")  # 3.62 bits but digits not interleaved
    assert matcher.matches("x-" + "a1b2c3d4e5f6g7h8" + "-y")  # entropy runs on the longest segment
    assert matcher.entropy_bits("aabb") == 1.0
    assert matcher.sub("pre-a1b2c3d4e5f6g7h8-post", "") == "pre--post"


def test_family_is_registered_with_stable_ids_and_phase() -> None:
    ids = [rule.id for rule in BUILTIN_RULES.ordered() if rule.family is RuleFamily.HASHED_ID]
    assert ids == sorted(BY_ID) == ["id.entropy", "id.hex_suffix", "id.react_use_id"]
    assert {rule.phase for rule in ID_RULES} == {20}
    assert all(rule.target is Target.ATTRIBUTE and rule.attributes == frozenset({"id"}) for rule in ID_RULES)


def test_end_to_end_strips_only_hashed_ids() -> None:
    doc = parse(
        b'<main id="main"><div id="react-root-7a3b2c" class="react-root-7a3b2c" data-id="react-root-7a3b2c">'
        b'<label id="_R_lql3aqll6_" for="_R_lql3aqll6_">x</label>'
        b'<span itemid="react-root-7a3b2c" id="product-card">y</span></div></main>'
    )
    result = apply_rules(doc, BUILTIN_RULES, NormalizationConfig())
    assert result.tree.css_first("main").attributes["id"] == "main"
    div = result.tree.css_first("div")
    assert "id" not in div.attributes
    assert div.attributes["class"] == "react-root-7a3b2c"  # class is not this family's business
    assert div.attributes["data-id"] == "react-root-7a3b2c"
    label = result.tree.css_first("label")
    assert "id" not in label.attributes
    assert label.attributes["for"] == "_R_lql3aqll6_"  # references are out of scope for T-14
    span = result.tree.css_first("span")
    assert span.attributes["itemid"] == "react-root-7a3b2c"
    assert span.attributes["id"] == "product-card"
    fired = [(a.rule_id, a.before, a.after) for a in result.applied_rules if a.rule_id.startswith("id.")]
    assert fired == [("id.hex_suffix", "react-root-7a3b2c", ""), ("id.react_use_id", "_R_lql3aqll6_", "")]
    assert (result.applied_rules[0].locator.css or "").endswith("> main > div")


@pytest.mark.parametrize("rule_id", sorted(BY_ID))
def test_each_rule_is_individually_toggleable(rule_id: str) -> None:
    value = POSITIVE[rule_id][0]
    doc = parse(f'<p id="{value}">x</p>'.encode())
    off = NormalizationConfig(disabled_rules=frozenset({rule_id}))
    assert apply_rules(doc, BUILTIN_RULES, off).tree.css_first("p").attributes["id"] == value
    assert "id" not in apply_rules(doc, BUILTIN_RULES, NormalizationConfig()).tree.css_first("p").attributes


def test_input_tree_not_mutated_and_output_deterministic() -> None:
    doc = parse(b'<div id="_R_abc123_"><p id="3f2504e04f8911d39a0c0305e82c3301">x</p></div>')
    before = doc.tree.html
    first = apply_rules(doc, BUILTIN_RULES, NormalizationConfig())
    second = apply_rules(doc, BUILTIN_RULES, NormalizationConfig())
    assert doc.tree.html == before
    assert first.tree.html == second.tree.html
    assert "id" not in first.tree.css_first("div").attributes
    assert "id" not in first.tree.css_first("p").attributes
