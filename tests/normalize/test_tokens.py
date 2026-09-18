"""T-15: token rule family (FR-7) — nonces, CSRF, session-shaped hidden inputs; structure intact."""

from __future__ import annotations

import pytest

from semdiff import NormalizationConfig, parse
from semdiff.normalize import BUILTIN_RULES, NodePredicate, RegexMatcher, RuleFamily, Target, apply_rules
from semdiff.normalize.rules.tokens import TOKEN_RULES

BY_ID = {rule.id: rule for rule in TOKEN_RULES}
UUID_HEX = "3f2504e04f8911d39a0c0305e82c3301"
JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"


def strip_count(html: str) -> tuple[str, list[tuple[str, str, str]]]:
    result = apply_rules(parse(html.encode()), BUILTIN_RULES, NormalizationConfig())
    fired = [(a.rule_id, a.before, a.after) for a in result.applied_rules if a.rule_id.startswith("token.")]
    return result.tree.html or "", fired


# ---- positive: (html, expected rule id, expected stripped value) ------------------------------
POSITIVE = [
    ('<script nonce="r4nd0mN0nc3Value==" src="a.js"></script>', "token.nonce", "r4nd0mN0nc3Value=="),
    ('<style nonce="abcdefgh">p{}</style>', "token.nonce", "abcdefgh"),
    ('<form><input type="hidden" name="csrf_token" value="9f8e7d6c"></form>', "token.csrf_input", "9f8e7d6c"),
    ('<form><input type="hidden" name="authenticity_token" value="x"></form>', "token.csrf_input", "x"),
    ('<form><input type="hidden" name="__RequestVerificationToken" value="CfDJ8"></form>', "token.csrf_input", "CfDJ8"),
    ('<form><input type="hidden" name="csrfmiddlewaretoken" value="abc"></form>', "token.csrf_input", "abc"),
    ('<form><input type="hidden" name="_token" value="abc"></form>', "token.csrf_input", "abc"),
    ('<form><input type="hidden" name="_csrf" value="abc"></form>', "token.csrf_input", "abc"),
    ('<form><input type="hidden" name="__VIEWSTATE" value="/wEPDwUK"></form>', "token.csrf_input", "/wEPDwUK"),
    ('<form><input type="HIDDEN" name="XSRF-TOKEN" value="abc"></form>', "token.csrf_input", "abc"),
    ('<meta name="csrf-token" content="Zm9vYmFy">', "token.csrf_meta", "Zm9vYmFy"),
    ('<meta name="_csrf" content="Zm9vYmFy">', "token.csrf_meta", "Zm9vYmFy"),
    (f'<form><input type="hidden" name="state" value="{UUID_HEX}"></form>', "token.session_input", UUID_HEX),
    (f'<form><input type="hidden" name="payload" value="{JWT}"></form>', "token.session_input", JWT),
    (f'<div data-csrf="{UUID_HEX}">x</div>', "token.named_attr", UUID_HEX),
    (f'<div data-request-id="{UUID_HEX}">x</div>', "token.named_attr", UUID_HEX),
    (f'<div token="{UUID_HEX}">x</div>', "token.named_attr", UUID_HEX),
    (f'<div data-session-token="{UUID_HEX}">x</div>', "token.named_attr", UUID_HEX),
]

# ---- negative: nothing in the token family may fire ------------------------------------------
NEGATIVE = [
    '<form><input type="hidden" name="product_id" value="123456"></form>',
    '<form><input type="hidden" name="sku" value="SKU-2024-AB"></form>',
    '<form><input type="hidden" name="redirect" value="/checkout?step=2"></form>',
    '<form><input type="hidden" name="_method" value="patch"></form>',
    '<form><input type="hidden" name="locale" value="en-US"></form>',
    '<form><input type="hidden" name="quantity" value="1"></form>',
    '<form><input type="hidden" name="utf8" value="&#x2713;"></form>',
    '<form><input type="hidden" name="order" value="3f2504e0-4f89-11d3-9a0c-0305e82c3301"></form>',  # dashed UUID
    '<form><input type="hidden" name="csrf_token"></form>',  # nothing to strip
    '<form><input type="text" name="csrf_token" value="visible"></form>',  # not hidden
    '<form><input type="hidden" name="description" value="' + "a" * 40 + '"></form>',  # long but 0 bits
    '<meta name="csrf-param" content="authenticity_token">',
    '<meta name="description" content="A long description of the page with many words in it">',
    '<meta name="viewport" content="width=device-width, initial-scale=1">',
    '<script nonce="" src="a.js"></script>',
    '<script nonce="short" src="a.js"></script>',
    '<div data-token-count="12">x</div>',
    '<div data-session-name="checkout">x</div>',
    '<div data-token="short">x</div>',
    '<span itemprop="token" content="' + UUID_HEX + '">x</span>',  # protected attribute name
    '<div class="' + UUID_HEX + '" id="main">x</div>',  # other families' business, and id is semantic
]


@pytest.mark.parametrize(("html", "rule_id", "value"), POSITIVE, ids=[p[1] + ":" + p[2][:8] for p in POSITIVE])
def test_tokens_are_stripped_and_structure_kept(html: str, rule_id: str, value: str) -> None:
    body, fired = strip_count(html)
    assert fired == [(rule_id, value, "")]
    assert value not in body
    # the element itself, its tag and its other attributes survive
    tag = html.split()[0].lstrip("<").rstrip(">")
    assert f"<{tag}" in body


@pytest.mark.parametrize("html", NEGATIVE)
def test_meaningful_values_are_preserved(html: str) -> None:
    _, fired = strip_count(html)
    assert fired == []


def test_named_attr_boundary_is_conservative() -> None:
    # data-request-id="req-2024-09-17-0001" is 20 chars of the allowed charset: it IS stripped by the
    # named-attribute rule. That is the accepted edge of the rule — request ids are tokens by name.
    _, fired = strip_count('<div data-request-id="req-2024-09-17-0001">x</div>')
    assert fired == [("token.named_attr", "req-2024-09-17-0001", "")]
    _, fired = strip_count('<div data-request-id="req-2024-09-1">x</div>')  # 15 chars: under the floor
    assert fired == []


def test_session_input_boundaries() -> None:
    twenty_four = "a1b2c3d4e5f6g7h8a1b2c3d4"
    assert len(twenty_four) == 24
    _, fired = strip_count(f'<form><input type="hidden" name="x" value="{twenty_four}"></form>')
    assert [f[0] for f in fired] == ["token.session_input"]
    _, fired = strip_count(f'<form><input type="hidden" name="x" value="{twenty_four[:-1]}"></form>')
    assert fired == []
    # a JWT's longest alphanumeric run is its middle segment (27 chars here): inside the floor
    _, fired = strip_count(f'<form><input type="hidden" name="x" value="{JWT}"></form>')
    assert [f[0] for f in fired] == ["token.session_input"]


def test_csrf_input_fires_once_even_when_session_rule_would_match() -> None:
    _, fired = strip_count(f'<form><input type="hidden" name="csrf_token" value="{UUID_HEX}"></form>')
    assert fired == [("token.csrf_input", UUID_HEX, "")]  # first rule strips it; nothing left for the second


def test_node_predicate_semantics() -> None:
    doc = parse(b'<input type="hidden" name="a"><input type="text" name="a"><meta name="a">')
    hidden, text, meta = doc.tree.css("input, meta")
    pred = NodePredicate(tag="input", attributes=(("type", RegexMatcher(r"(?i)^hidden$")),))
    assert pred.matches(hidden) and not pred.matches(text) and not pred.matches(meta)
    assert NodePredicate(attributes=(("name", RegexMatcher("^a$")),)).matches(meta)
    assert not NodePredicate(attributes=(("missing", RegexMatcher(".*")),)).matches(meta)


def test_family_is_registered_with_stable_ids_and_phase() -> None:
    ids = [rule.id for rule in BUILTIN_RULES.ordered() if rule.family is RuleFamily.TOKEN]
    assert ids == sorted(BY_ID) == [
        "token.csrf_input", "token.csrf_meta", "token.named_attr", "token.nonce", "token.session_input",
    ]
    assert {rule.phase for rule in TOKEN_RULES} == {30}
    assert all(rule.target is Target.ATTRIBUTE for rule in TOKEN_RULES)


@pytest.mark.parametrize("rule_id", sorted(BY_ID))
def test_each_rule_is_individually_toggleable(rule_id: str) -> None:
    html, _, value = next(p for p in POSITIVE if p[1] == rule_id)
    off = NormalizationConfig(disabled_rules=frozenset({rule_id}))
    kept = apply_rules(parse(html.encode()), BUILTIN_RULES, off)
    assert value in (kept.tree.html or "")


def test_input_tree_not_mutated_and_output_deterministic() -> None:
    doc = parse(f'<form><input type="hidden" name="csrf_token" value="{UUID_HEX}"><script nonce="abcdefgh"></script></form>'.encode())
    before = doc.tree.html
    first = apply_rules(doc, BUILTIN_RULES, NormalizationConfig())
    second = apply_rules(doc, BUILTIN_RULES, NormalizationConfig())
    assert doc.tree.html == before
    assert first.tree.html == second.tree.html
    assert UUID_HEX not in (first.tree.html or "") and 'nonce="abcdefgh"' not in (first.tree.html or "")
    assert 'name="csrf_token"' in (first.tree.html or "")
