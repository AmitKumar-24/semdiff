"""T-18: ``REPLACE_WITH_PLACEHOLDER`` — the action, and what it must never do.

STRIP conflates "this value was noise" with "this attribute was never here", so
``<div class="css-1abc2d">`` and ``<div>`` normalized alike and a real structural change
disappeared (DOMAIN_MODEL §10). The placeholder keeps the attribute and puts a constant sentinel
where the match was. Because that sentinel is a constant and not a counter, an id and the
attributes referencing it are rewritten to the same text and the reference still resolves
(F-006) — which is also why nothing here may depend on a node's position.
"""

from __future__ import annotations

import pytest

from semdiff import NormalizationConfig, normalize, parse
from semdiff.normalize import (
    BUILTIN_RULES,
    PLACEHOLDER,
    Action,
    GroupMatcher,
    Matcher,
    NormalizationRule,
    NormalizedDoc,
    RegexMatcher,
    RuleFamily,
    RuleRegistry,
    Target,
    apply_rules,
)
from tests.corpus.labels import Category
from tests.corpus.loader import load_pairs


def rule(
    rule_id: str,
    target: Target,
    matcher: Matcher,
    *,
    attributes: frozenset[str] = frozenset(),
    phase: int = 10,
) -> NormalizationRule:
    return NormalizationRule(
        id=rule_id,
        family=RuleFamily.DYNAMIC_CLASS,
        target=target,
        matcher=matcher,
        action=Action.REPLACE_WITH_PLACEHOLDER,
        phase=phase,
        attributes=attributes,
    )


def run(html: bytes, *rules: NormalizationRule) -> NormalizedDoc:
    registry = RuleRegistry()
    for one in rules:
        registry.register(one)
    return apply_rules(parse(html), registry, NormalizationConfig())


def shipped(html: bytes) -> NormalizedDoc:
    return apply_rules(parse(html), BUILTIN_RULES, NormalizationConfig())


def reported(result: NormalizedDoc) -> list[tuple[str, str, str]]:
    return [(a.rule_id, a.before, a.after) for a in result.applied_rules]


def body(result: NormalizedDoc) -> str:
    return (result.tree.css_first("body").html or "").removeprefix("<body>").removesuffix("</body>")


HASHED = rule("t.attr", Target.ATTRIBUTE, RegexMatcher(r"^h-[0-9a-f]{6}$"), attributes=frozenset({"id"}))
TOKENS = rule("t.value", Target.ATTRIBUTE_VALUE, RegexMatcher(r"^h-[0-9a-f]{6}$"), attributes=frozenset({"class"}))
SPAN = rule("t.substring", Target.ATTRIBUTE_SUBSTRING, GroupMatcher(r"-(?P<hash>[0-9a-f]{6})$"), attributes=frozenset({"id"}))
TEXT = rule("t.text", Target.TEXT, RegexMatcher(r"\d+ minutes ago"), phase=40)


# --- one test per target ---------------------------------------------------------------------
def test_attribute_target_keeps_the_attribute_and_reports_both_sides() -> None:
    result = run(b'<p id="h-1a2b3c">x</p>', HASHED)
    assert result.tree.css_first("p").attributes["id"] == PLACEHOLDER
    assert reported(result) == [("t.attr", "h-1a2b3c", PLACEHOLDER)]


def test_attribute_value_target_replaces_the_token_in_place() -> None:
    """Position and token count are the point: a dropped token would move its neighbours."""
    result = run(b'<p class="a h-1a2b3c b h-9f8e7d">x</p>', TOKENS)
    assert result.tree.css_first("p").attributes["class"] == f"a {PLACEHOLDER} b {PLACEHOLDER}"
    assert reported(result) == [("t.value", "a h-1a2b3c b h-9f8e7d", f"a {PLACEHOLDER} b {PLACEHOLDER}")]


def test_attribute_substring_target_keeps_the_rest_of_the_value() -> None:
    result = run(b'<p id="tab-1a2b3c">x</p>', SPAN)
    assert result.tree.css_first("p").attributes["id"] == f"tab-{PLACEHOLDER}"
    assert reported(result) == [("t.substring", "tab-1a2b3c", f"tab-{PLACEHOLDER}")]


def test_text_target_keeps_the_text_node_in_the_tree() -> None:
    result = run(b"<p>Updated 3 minutes ago.</p>", TEXT)
    assert result.tree.css_first("p").text() == f"Updated {PLACEHOLDER}."
    assert reported(result) == [("t.text", "Updated 3 minutes ago.", f"Updated {PLACEHOLDER}.")]


def test_node_target_is_rejected_when_the_rule_is_registered() -> None:
    """An element is dropped or kept; there is nothing for a sentinel to stand in for."""
    registry = RuleRegistry()
    with pytest.raises(ValueError, match="NODE"):
        registry.register(rule("t.node", Target.NODE, RegexMatcher(r"^aside$")))


# --- idempotence and no-op suppression -------------------------------------------------------
# Matchers that accept the sentinel itself. ``token.nonce``'s shipped matcher
# (^[A-Za-z0-9+/=_-]{8,}$) does exactly this, so the guard is not hypothetical: without it such a
# rule would rewrite its own output and report a change on every pass.
SELF_ATTR = rule("t.self.attr", Target.ATTRIBUTE, RegexMatcher(r"^[A-Za-z0-9_]{8,}$"), attributes=frozenset({"id"}))
SELF_VALUE = rule("t.self.value", Target.ATTRIBUTE_VALUE, RegexMatcher(r"^[A-Za-z0-9_]{8,}$"), attributes=frozenset({"class"}))
SELF_SPAN = rule("t.self.span", Target.ATTRIBUTE_SUBSTRING, GroupMatcher(r"(?P<hash>[A-Za-z0-9_]{8,})$"), attributes=frozenset({"id"}))
SELF_TEXT = rule("t.self.text", Target.TEXT, RegexMatcher(r"__semdiff__"), phase=40)


@pytest.mark.parametrize(
    ("html", "rules"),
    [
        (b'<p id="__semdiff__">x</p>', (SELF_ATTR,)),
        (b'<p class="a __semdiff__">x</p>', (SELF_VALUE,)),
        (b'<p id="tab-__semdiff__">x</p>', (SELF_SPAN,)),
        (b"<p>Updated __semdiff__.</p>", (SELF_TEXT,)),
    ],
    ids=["attribute", "attribute-value", "attribute-substring", "text"],
)
def test_a_value_that_is_already_the_sentinel_reports_nothing(
    html: bytes, rules: tuple[NormalizationRule, ...]
) -> None:
    """Each of these rules accepts the sentinel, so each would loop without the no-op guard."""
    before = parse(html).tree.html
    result = run(html, *rules)
    assert reported(result) == []
    assert result.tree.html == before


EVERY_FAMILY = (
    b'<div class="MuiBox-root css-1p1nqj6 acss-9zz9z _1a2b3c4 sc-bdfBwQ bcMPWx keep" '
    b'id="react-root-7a3b2c" data-csrf="Zm9vYmFyMTIzNDU2Nzg5">'
    b'<label id="_R_lql3aqll6_" for="_R_lql3aqll6_">x</label>'
    b'<button aria-controls="panel-1a2b3c tab-9f8e7d">b</button>'
    b'<a href="#sect-7a3b2c">frag</a>'
    b'<div id="3f2504e04f8911d39a0c0305e82c3301">uuid</div>'
    b'<input type="hidden" name="csrf_token" value="aG93IG5vdyBicm93biBjb3c">'
    b"<p>Updated 3 minutes ago</p>"
    b'<img src="/assets/js/main.3eef80bd.js">'
    b"</div>"
)


def test_the_whole_shipped_ruleset_is_idempotent() -> None:
    """The sentinel must not be matched by the rule that produced it, nor by any other: a second
    normalization changes nothing *and reports nothing*. One document carrying a positive for
    every family, so a future rule that re-fires on the sentinel fails right here.
    """
    once = normalize(EVERY_FAMILY)
    assert PLACEHOLDER in once
    assert normalize(once) == once
    assert reported(shipped(once.encode())) == []


@pytest.mark.parametrize("pair_id", ["redux-js-org-001", "docusaurus-io-001"])
def test_idempotent_on_a_real_capture(pair_id: str) -> None:
    pair = next(p for p in load_pairs(category=Category.NOISE_ONLY) if p.id == pair_id)
    once = normalize(pair.old_bytes)
    assert normalize(once) == once
    assert reported(shipped(once.encode())) == []


# --- references (F-006) ----------------------------------------------------------------------
REFERENCES = (
    b'<div><label id="_R_abc_" for="_R_abc_">a</label>'
    b'<button aria-controls="panel-1a2b3c tab-9f8e7d" aria-labelledby="static lbl-4d5e6f">b</button>'
    b'<a href="#react-root-7a3b2c">fragment</a>'
    b'<a href="/docs/page#sect-7a3b2c">deep fragment</a>'
    b'<a href="/assets/js/main-1a2b3c.js">asset</a>'
    b'<a href="/releases/v2-1a2b3c">path segment</a>'
    b'<label for="3f2504e04f8911d39a0c0305e82c3301">uuid</label>'
    b'<p id="3f2504e04f8911d39a0c0305e82c3301">uuid target</p>'
    b'<table><tr><td headers="col-1a2b3c static">cell</td></tr></table></div>'
)


def test_an_id_and_the_reference_to_it_end_up_identical() -> None:
    result = shipped(REFERENCES)
    label, uuid_label = result.tree.css("label")
    assert label.attributes["id"] == label.attributes["for"] == PLACEHOLDER
    assert uuid_label.attributes["for"] == result.tree.css_first("p").attributes["id"] == PLACEHOLDER


def test_id_lists_keep_their_static_entries_and_their_order() -> None:
    result = shipped(REFERENCES)
    button = result.tree.css_first("button")
    assert button.attributes["aria-controls"] == f"panel-{PLACEHOLDER} tab-{PLACEHOLDER}"
    assert button.attributes["aria-labelledby"] == f"static lbl-{PLACEHOLDER}"
    assert result.tree.css_first("td").attributes["headers"] == f"col-{PLACEHOLDER} static"


def test_href_is_touched_only_inside_a_fragment() -> None:
    """The id patterns may start at the value's start, after whitespace or after a ``#`` — never
    after a ``/``. That fence is what keeps FR-44's bundle hashes out of this family's reach."""
    links = shipped(REFERENCES).tree.css("a")
    assert links[0].attributes["href"] == f"#react-root-{PLACEHOLDER}"
    assert links[1].attributes["href"] == f"/docs/page#sect-{PLACEHOLDER}"
    assert links[2].attributes["href"] == "/assets/js/main-1a2b3c.js"  # FR-44's hash, at phase 50
    # The last one is what the start fence alone protects: a path segment that ends in exactly
    # the shape of a hashed id, with no extension after it to save it.
    assert links[3].attributes["href"] == "/releases/v2-1a2b3c"


def test_two_distinct_hashes_without_a_stable_prefix_collide() -> None:
    """A documented limitation, asserted so it stays visible (F-029): the sentinel is a constant,
    so two different random ids become the same text, and a reference re-pointed from one to the
    other is invisible. A stable prefix is what keeps the common cases apart.
    """
    html = b'<p id="_R_aaa_">a</p><p id="_R_bbb_">b</p><p id="tab-1a2b3c">c</p><p id="panel-9f8e7d">d</p>'
    ids = [node.attributes["id"] for node in shipped(html).tree.css("p")]
    assert ids == [PLACEHOLDER, PLACEHOLDER, f"tab-{PLACEHOLDER}", f"panel-{PLACEHOLDER}"]


# --- what must never happen ------------------------------------------------------------------
def test_boolean_and_empty_attributes_are_left_alone() -> None:
    """``<input disabled>`` carries no value; giving it one would invent HTML meaning."""
    permissive = rule("t.any", Target.ATTRIBUTE, RegexMatcher(r"(?s)^.*$"), attributes=frozenset())
    html = b'<input disabled id="" class="">'
    result = run(html, permissive)
    assert reported(result) == []
    assert result.tree.html == parse(html).tree.html


def test_an_unmatched_value_comes_through_byte_identical() -> None:
    """A class value with odd whitespace and no matching token must report nothing: rebuilding
    the token list would otherwise renormalize the spacing and report *that* as a change.
    Regression — it briefly did, and attributed the change to whichever rule ran first."""
    html = b'<p class="yt-lite ">x</p><p class="a  b">y</p>'
    result = run(html, TOKENS)
    assert reported(result) == []
    assert body(result) == '<p class="yt-lite ">x</p><p class="a  b">y</p>'


def test_protected_attributes_are_never_placeholdered() -> None:
    html = b'<span itemid="react-root-7a3b2c" itemprop="css-1abc2d" about="_R_abc_">x</span>'
    span = shipped(html).tree.css_first("span")
    assert span.attributes["itemid"] == "react-root-7a3b2c"
    assert span.attributes["itemprop"] == "css-1abc2d"
    assert span.attributes["about"] == "_R_abc_"


def test_the_input_tree_is_untouched_and_the_output_deterministic() -> None:
    doc = parse(REFERENCES)
    before = doc.tree.html
    first = apply_rules(doc, BUILTIN_RULES, NormalizationConfig())
    again = apply_rules(doc, BUILTIN_RULES, NormalizationConfig())
    assert doc.tree.html == before
    assert first.tree.html == again.tree.html
    assert reported(first) == reported(again)


def test_a_placeholder_rule_is_toggleable_like_any_other() -> None:
    html = b'<p id="react-root-7a3b2c" class="css-1abc2d keep">x</p>'
    off = NormalizationConfig(disabled_rules=frozenset({"id.hex_suffix", "class.emotion"}))
    kept = apply_rules(parse(html), BUILTIN_RULES, off).tree.css_first("p")
    assert kept.attributes["id"] == "react-root-7a3b2c"
    assert kept.attributes["class"] == "css-1abc2d keep"
    on = shipped(html).tree.css_first("p")
    assert on.attributes["id"] == f"react-root-{PLACEHOLDER}"
    assert on.attributes["class"] == f"{PLACEHOLDER} keep"
