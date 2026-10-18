"""T-12: rule model, phase-ordered registry, toggles, application reporting."""

from __future__ import annotations

import re

import pytest
from selectolax.lexbor import LexborHTMLParser

from semdiff import Config, NormalizationConfig, parse
from semdiff.normalize import (
    Action,
    NormalizationRule,
    RegexMatcher,
    RuleFamily,
    RuleRegistry,
    Target,
    apply_rules,
)
from semdiff.normalize.registry import (
    BUILTIN_RULES,
    _fusable,
    _protected_text_nodes,
    _runs,
    ruleset_fingerprint,
)
from tests.normalize.reference import apply_rules_per_rule, records
from tests.nodes import one

HTML = (
    b'<div id="react-root-7a3b2c" class="card css-1abc2d" data-token="abc">'
    b'<p class="css-9zz9zz kept">Hello, 3 minutes ago</p>'
    b'<span itemprop="css-notouch" about="css-notouch">x</span>'
    b'<script type="application/ld+json">{"date":"3 minutes ago"}</script>'
    b"<aside>drop me</aside></div>"
)


def rule(
    rule_id: str,
    *,
    family: RuleFamily = RuleFamily.DYNAMIC_CLASS,
    target: Target = Target.ATTRIBUTE_VALUE,
    pattern: str = r"^css-[a-z0-9]{6}$",
    attributes: frozenset[str] = frozenset({"class"}),
    action: Action = Action.STRIP,
    phase: int = 10,
    enabled: bool = True,
    version: int = 1,
) -> NormalizationRule:
    return NormalizationRule(
        id=rule_id,
        family=family,
        target=target,
        matcher=RegexMatcher(pattern),
        attributes=attributes,
        action=action,
        phase=phase,
        enabled=enabled,
        version=version,
    )


CLASS_RULE = rule("test.class.css")
ID_RULE = rule(
    "test.id.hash", family=RuleFamily.HASHED_ID, target=Target.ATTRIBUTE,
    pattern=r"-[0-9a-f]{6}$", attributes=frozenset({"id"}), phase=20,
)
TEXT_RULE = rule(
    "test.text.relative", family=RuleFamily.TIMESTAMP, target=Target.TEXT,
    pattern=r"\d+ minutes ago", attributes=frozenset(), phase=40,
)
NODE_RULE = rule(
    "test.node.aside", family=RuleFamily.TOKEN, target=Target.NODE,
    pattern=r"^aside$", attributes=frozenset(), action=Action.DROP_NODE, phase=30,
)


def make_registry(*rules: NormalizationRule) -> RuleRegistry:
    registry = RuleRegistry()
    for r in rules:
        registry.register(r)
    return registry


def test_rule_model_is_frozen_and_typed() -> None:
    with pytest.raises(AttributeError):
        CLASS_RULE.id = "other"  # type: ignore[misc]
    assert CLASS_RULE.version == 1
    assert CLASS_RULE.matcher.matches("css-1abc2d")
    assert not CLASS_RULE.matcher.matches("card")


def test_registry_orders_by_phase_then_id() -> None:
    registry = make_registry(TEXT_RULE, NODE_RULE, rule("test.b", phase=10), rule("test.a", phase=10), ID_RULE)
    assert [r.id for r in registry.ordered()] == [
        "test.a", "test.b", "test.id.hash", "test.node.aside", "test.text.relative",
    ]


def test_duplicate_id_rejected() -> None:
    registry = make_registry(CLASS_RULE)
    with pytest.raises(ValueError, match="test.class.css"):
        registry.register(rule("test.class.css", pattern="x"))


def test_canonical_rule_must_be_last_phase() -> None:
    canonical = rule("test.canon", family=RuleFamily.CANONICAL, phase=10, action=Action.CANONICALIZE)
    with pytest.raises(ValueError, match="canonical"):
        make_registry(CLASS_RULE, canonical)
    with pytest.raises(ValueError, match="canonical"):
        make_registry(rule("test.canon", family=RuleFamily.CANONICAL, phase=90, action=Action.CANONICALIZE), rule("test.late", phase=90))
    make_registry(CLASS_RULE, rule("test.canon", family=RuleFamily.CANONICAL, phase=90, action=Action.CANONICALIZE))


def test_toggles_from_config() -> None:
    registry = make_registry(CLASS_RULE, rule("test.optin", enabled=False, pattern="^kept$"))
    default = [r.id for r in registry.effective(NormalizationConfig())]
    assert default == ["test.class.css"]
    toggled = registry.effective(
        NormalizationConfig(disabled_rules=frozenset({"test.class.css"}), enabled_rules=frozenset({"test.optin"}))
    )
    assert [r.id for r in toggled] == ["test.optin"]


def test_unknown_toggle_id_fails_loud() -> None:
    registry = make_registry(CLASS_RULE)
    with pytest.raises(ValueError, match="test.nope"):
        registry.effective(NormalizationConfig(disabled_rules=frozenset({"test.nope"})))
    with pytest.raises(ValueError, match="test.nope"):
        registry.effective(NormalizationConfig(enabled_rules=frozenset({"test.nope"})))


def test_attribute_value_strip_reports_application() -> None:
    doc = parse(HTML)
    result = apply_rules(doc, make_registry(CLASS_RULE), NormalizationConfig())
    div = one(result.tree, "div")
    assert div.attributes["class"] == "card"
    assert one(result.tree, "p").attributes["class"] == "kept"
    assert [a.rule_id for a in result.applied_rules] == ["test.class.css", "test.class.css"]
    first = result.applied_rules[0]
    assert (first.before, first.after) == ("card css-1abc2d", "card")
    assert first.locator.css == "html > body:nth-child(2) > div"
    assert re.fullmatch(r"[0-9a-f]{64}", first.locator.node_hash)
    assert first.locator.xpath is None


def test_attribute_strip_and_node_drop_and_text_strip() -> None:
    doc = parse(HTML)
    result = apply_rules(doc, make_registry(ID_RULE, NODE_RULE, TEXT_RULE), NormalizationConfig())
    div = one(result.tree, "div")
    assert "id" not in div.attributes
    assert result.tree.css_first("aside") is None
    assert one(result.tree, "p").text() == "Hello, "
    ids = [a.rule_id for a in result.applied_rules]
    assert ids == ["test.id.hash", "test.node.aside", "test.text.relative"]  # phase order 20, 30, 40


def test_attribute_substring_rewrites_in_place_and_keeps_the_attribute() -> None:
    # T-23 added ATTRIBUTE_SUBSTRING: unlike ATTRIBUTE and ATTRIBUTE_VALUE it must not
    # remove the attribute — only the matched span goes.
    from semdiff.normalize.model import GroupMatcher

    substring = NormalizationRule(
        id="test.substring",
        family=RuleFamily.ASSET_HASH,
        target=Target.ATTRIBUTE_SUBSTRING,
        matcher=GroupMatcher(r"(?P<hash>-[0-9a-f]{6})(?=\.js$)"),
        action=Action.STRIP,
        phase=50,
        attributes=frozenset({"src"}),
    )
    doc = parse(b'<script src="/a/b-1a2b3c.js" data-src="/a/b-1a2b3c.js"></script>')
    result = apply_rules(doc, make_registry(substring), NormalizationConfig())
    script = one(result.tree, "script")
    assert script.attributes["src"] == "/a/b.js"
    assert script.attributes["data-src"] == "/a/b-1a2b3c.js"  # outside the rule's scope
    assert [(a.rule_id, a.before, a.after) for a in result.applied_rules] == [
        ("test.substring", "/a/b-1a2b3c.js", "/a/b.js")
    ]


def test_group_matcher_requires_a_hash_group() -> None:
    from semdiff.normalize.model import GroupMatcher

    with pytest.raises(ValueError, match="hash"):
        GroupMatcher(r"-[0-9a-f]{6}")


def test_structured_data_carriers_are_protected() -> None:
    doc = parse(HTML)
    protective = rule("test.any.attr", target=Target.ATTRIBUTE, pattern=r"^css-notouch$", attributes=frozenset())
    result = apply_rules(doc, make_registry(protective, CLASS_RULE, TEXT_RULE), NormalizationConfig())
    span = one(result.tree, "span")
    assert span.attributes["itemprop"] == "css-notouch"
    assert span.attributes["about"] == "css-notouch"
    assert one(result.tree, "script").text() == '{"date":"3 minutes ago"}'


def test_disabled_rules_do_not_fire() -> None:
    doc = parse(HTML)
    cfg = NormalizationConfig(disabled_rules=frozenset({"test.class.css"}))
    result = apply_rules(doc, make_registry(CLASS_RULE), cfg)
    assert one(result.tree, "div").attributes["class"] == "card css-1abc2d"
    assert result.applied_rules == []


def test_unimplemented_or_misdeclared_actions_fail_loud() -> None:
    """T-18 implemented REPLACE_WITH_PLACEHOLDER, so what must fail loud moved: the action is
    meaningless for a NODE target (an element is dropped or kept), and that is now rejected when
    the rule is registered rather than when it runs."""
    doc = parse(HTML)
    node_placeholder = rule(
        "test.future", action=Action.REPLACE_WITH_PLACEHOLDER, target=Target.NODE,
        pattern=r"^aside$", attributes=frozenset(), phase=90,
    )
    with pytest.raises(ValueError, match="NODE"):
        make_registry(node_placeholder)
    no_transform = rule("test.canon", action=Action.CANONICALIZE, family=RuleFamily.CANONICAL, phase=90)
    with pytest.raises(ValueError, match="transform"):
        apply_rules(doc, make_registry(no_transform), NormalizationConfig())


def test_apply_is_deterministic_and_input_doc_untouched() -> None:
    doc = parse(HTML)
    before = doc.tree.html
    a = apply_rules(doc, make_registry(CLASS_RULE, ID_RULE, NODE_RULE, TEXT_RULE), NormalizationConfig())
    b = apply_rules(doc, make_registry(CLASS_RULE, ID_RULE, NODE_RULE, TEXT_RULE), NormalizationConfig())
    assert a.tree.html == b.tree.html
    assert [(x.rule_id, x.before, x.after) for x in a.applied_rules] == [(x.rule_id, x.before, x.after) for x in b.applied_rules]
    assert doc.tree.html == before


def test_ruleset_fingerprint_tracks_versions_and_feeds_config_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    v1 = make_registry(rule("test.x", version=1))
    v2 = make_registry(rule("test.x", version=2))
    assert ruleset_fingerprint(v1) != ruleset_fingerprint(v2)
    assert ruleset_fingerprint(v1) == ruleset_fingerprint(make_registry(rule("test.x", version=1, pattern="other")))
    before = Config().config_hash
    from semdiff.normalize import registry  # module object: `semdiff.normalize` the attribute is the function

    monkeypatch.setattr(registry, "BUILTIN_RULES", v2)
    assert Config().config_hash != before


def test_builtin_registry_holds_only_shipped_families() -> None:
    families = {r.family for r in BUILTIN_RULES.ordered()}
    assert families == set(RuleFamily)  # every family ships (T-13..T-17)


# --- D-029 text protection -------------------------------------------------------------------
# The protected set is precomputed once per rule pass, so these pin the behaviour it replaces:
# a text node under <script>/<style>/<template> is never rewritten, however deep it sits.

STAMP_RULE = rule(
    "test.text.stamp", family=RuleFamily.TIMESTAMP, target=Target.TEXT,
    pattern=r"STAMP", attributes=frozenset(), phase=40,
)
PROTECTED_HTML = {
    "script": b"<p>at STAMP</p><script>var t = 'STAMP';</script>",
    "style": b"<p>at STAMP</p><style>.a:after{content:'STAMP'}</style>",
    # A <template> in foreign content, because an HTML one has nothing a rule could reach:
    # Lexbor keeps HTML template contents in a detached fragment (see the test below). Inside
    # <svg> the name carries no special parsing rule, so the children are ordinary nodes a
    # traversal does offer — which is where the "template" entry in the set earns its keep.
    "template": b"<p>at STAMP</p><svg><template>STAMP</template></svg>",
}


@pytest.mark.parametrize("tag", ["script", "style", "template"])
def test_text_rules_never_enter_a_protected_element(tag: str) -> None:
    """Each case has a text node a traversal really does hand to the rule, and the rule must
    decline all three while rewriting the ordinary ``<p>`` beside them."""
    result = apply_rules(parse(PROTECTED_HTML[tag]), make_registry(STAMP_RULE), NormalizationConfig())
    assert "STAMP" in (one(result.tree, tag).html or "")
    assert one(result.tree, "p").text() == "at "
    assert [(a.rule_id, a.before, a.after) for a in result.applied_rules] == [
        ("test.text.stamp", "at STAMP", "at ")
    ]


def test_an_html_templates_contents_are_unreachable_rather_than_protected() -> None:
    """The honest limit of the case above, asserted as the parser property it is.

    Lexbor puts the contents of an HTML ``<template>`` in a detached fragment: ``child`` is
    ``None``, a CSS query inside it finds nothing, ``text()`` is empty and a traversal yields no
    node for it. So a TEXT rule cannot reach that text whether or not the tag is protected, and
    the content survives for the wrong reason. The tag stays in ``PROTECTED_TEXT_PARENTS``
    because the foreign-content case above *is* reachable, because ``canonical.whitespace``
    reads the same set, and because a second backend (T-11) may expose these nodes — on lxml
    they are ordinary children. See F-031.
    """
    tree = LexborHTMLParser("<template><p>STAMP</p></template>")
    assert tree.root is not None
    template = one(tree, "template")
    assert template.child is None and template.text() == "" and tree.css("template p") == []
    assert [n.tag for n in tree.root.traverse(include_text=True) if n.tag == "-text"] == []
    assert "STAMP" in (template.html or "")  # serialization is the only way to it

    result = apply_rules(parse(b"<template>STAMP</template>"), make_registry(STAMP_RULE), NormalizationConfig())
    assert result.applied_rules == []  # nothing was offered, so nothing was declined
    assert "STAMP" in (one(result.tree, "template").html or "")


def test_protection_covers_deep_and_foreign_content() -> None:
    html = (
        b"<div><section><style>deep STAMP</style></section></div>"
        b"<svg><script>svg STAMP</script></svg><p>plain STAMP</p>"
    )
    result = apply_rules(parse(html), make_registry(STAMP_RULE), NormalizationConfig())
    assert [(a.before, a.after) for a in result.applied_rules] == [("plain STAMP", "plain ")]
    assert "deep STAMP" in (one(result.tree, "style").html or "")
    assert "svg STAMP" in (one(result.tree, "script").html or "")


def test_protection_holds_after_earlier_text_nodes_are_replaced() -> None:
    """A pass precomputes the set and then rewrites text as it walks. Replacing one text node
    must not cost a later protected node its protection, so interleave the two kinds.
    """
    html = (
        b"<p>a STAMP</p><script>keep STAMP</script><p>b STAMP</p>"
        b"<style>keep STAMP</style><p>c STAMP</p>"
    )
    result = apply_rules(parse(html), make_registry(STAMP_RULE), NormalizationConfig())
    assert [(a.before, a.after) for a in result.applied_rules] == [
        ("a STAMP", "a "), ("b STAMP", "b "), ("c STAMP", "c ")
    ]
    assert one(result.tree, "script").text() == "keep STAMP"
    assert "keep STAMP" in (one(result.tree, "style").html or "")


def test_protected_set_membership_survives_a_second_traversal() -> None:
    """What the precompute rests on: Lexbor hashes and compares a node by the DOM node it wraps,
    not by the wrapper object, so a set built from one traversal answers for another. Pinned
    here so a backend that drops that behaviour fails loudly instead of quietly rewriting
    script contents (the F-027 lesson).
    """
    tree = LexborHTMLParser("<p>x</p><script>s</script>")
    protected = _protected_text_nodes(tree)
    assert tree.root is not None
    texts = [n for n in tree.root.traverse(include_text=True) if n.tag == "-text"]
    assert [n.text_content for n in texts if n in protected] == ["s"]
    assert [n.text_content for n in texts if n not in protected] == ["x"]


# --- the fused attribute pass ----------------------------------------------------------------
# Runs of consecutive attribute rules share one traversal, so these pin the two things fusing
# could plausibly break: the order rules interact in on a given node, and the order their
# applications are reported in.

CLASS_A = rule("test.fused.a", pattern=r"^a-\d$", phase=10)
CLASS_B = rule("test.fused.b", pattern=r"^b-\d$", phase=11)
TWO_ELEMENTS = b'<p class="a-1 b-1 keep">x</p><span class="a-2 b-2">y</span>'


def test_several_rules_on_one_attribute_report_in_rule_major_order() -> None:
    """Reporting is rule-major and document-order within a rule, as one pass per rule gave.

    The ``before`` values are the proof that the rules still interact per node in (phase, id)
    order: ``test.fused.b`` sees the class list ``test.fused.a`` already shortened.
    """
    result = apply_rules(parse(TWO_ELEMENTS), make_registry(CLASS_A, CLASS_B), NormalizationConfig())
    assert [(a.rule_id, a.before, a.after) for a in result.applied_rules] == [
        ("test.fused.a", "a-1 b-1 keep", "b-1 keep"),
        ("test.fused.a", "a-2 b-2", "b-2"),
        ("test.fused.b", "b-1 keep", "keep"),
        ("test.fused.b", "b-2", ""),
    ]
    assert one(result.tree, "p").attributes["class"] == "keep"
    assert "class" not in one(result.tree, "span").attributes  # STRIP took the last token


def test_fused_run_matches_one_pass_per_rule_including_locators() -> None:
    registry = make_registry(CLASS_A, CLASS_B, ID_RULE, TEXT_RULE, NODE_RULE)
    doc = parse(TWO_ELEMENTS + HTML)
    assert records(apply_rules(doc, registry, NormalizationConfig())) == records(
        apply_rules_per_rule(doc, registry, NormalizationConfig())
    )


def test_a_rule_naming_no_attributes_joins_the_run_and_sees_every_element() -> None:
    """``attributes=frozenset()`` means "any attribute", so the index cannot place such a rule
    by name; it has to be offered every element that carries attributes at all.

    ``CLASS_A`` is here only to make the run two rules long -- a lone rule needs no fusing and
    would take the one-pass-per-rule path, leaving the wildcard handling untested. The wildcard
    sits at the earlier phase, so it is the one that fires.
    """
    wildcard = rule("test.fused.any", target=Target.ATTRIBUTE, pattern=r"^a-1$", attributes=frozenset(), phase=9)
    registry = make_registry(wildcard, CLASS_A)
    assert [len(run) for run in _runs(registry.effective(NormalizationConfig()))] == [2]
    html = b'<p class="a-1">x</p><input value="a-1"><br data-x="a-1">'
    result = apply_rules(parse(html), registry, NormalizationConfig())
    assert [(a.rule_id, a.before) for a in result.applied_rules] == [
        ("test.fused.any", "a-1"), ("test.fused.any", "a-1"), ("test.fused.any", "a-1")
    ]
    assert "class" not in one(result.tree, "p").attributes


def test_a_rule_whose_attribute_an_earlier_rule_removed_reports_nothing() -> None:
    """The name index over-admits here -- both rules are offered the element because it carried
    ``id`` when the traversal reached it -- and over-admitting must stay harmless."""
    first = rule("test.fused.id1", target=Target.ATTRIBUTE, pattern=r"^gone$", attributes=frozenset({"id"}), phase=20)
    second = rule("test.fused.id2", target=Target.ATTRIBUTE, pattern=r"^gone$", attributes=frozenset({"id"}), phase=21)
    result = apply_rules(parse(b'<p id="gone">x</p>'), make_registry(first, second), NormalizationConfig())
    assert [a.rule_id for a in result.applied_rules] == ["test.fused.id1"]


def test_a_dropped_node_is_never_offered_to_a_later_attribute_rule() -> None:
    """Why only *consecutive* attribute rules fuse: a DROP_NODE rule between two attribute
    phases changes the tree's shape, so the later attribute rule must run after it, not with
    the earlier one."""
    dropper = rule("test.fused.drop", target=Target.NODE, pattern=r"^aside$", action=Action.DROP_NODE,
                   attributes=frozenset(), phase=30)
    late = rule("test.fused.src", target=Target.ATTRIBUTE, pattern=r"^/gone$", attributes=frozenset({"src"}), phase=50)
    html = b'<aside><img src="/gone"></aside><img src="/gone">'
    registry = make_registry(CLASS_A, dropper, late)
    result = apply_rules(parse(html), registry, NormalizationConfig())
    assert [a.rule_id for a in result.applied_rules] == ["test.fused.drop", "test.fused.src"]
    assert one(result.tree, "img").attributes.get("src") is None
    assert records(result) == records(apply_rules_per_rule(parse(html), registry, NormalizationConfig()))
    assert [len(run) for run in _runs(registry.effective(NormalizationConfig()))] == [1, 1, 1]


def test_nested_elements_get_the_same_provenance_from_either_engine() -> None:
    """F-030, closed by D-044. The fused pass visits a node once; one pass per rule finishes each
    rule over the whole document first. So when a descendant is rewritten by an *earlier* rule of
    the same run, the two engines meet the ancestor with its subtree in different states — which
    used to change the ancestor's ``node_hash``, because that hashed the subtree. The fingerprint
    is the node's own now, so every record matches, locator included.
    """
    inner = rule("test.nest.inner", pattern=r"^inner-[a-z]{5}$", phase=10)
    outer = rule("test.nest.outer", pattern=r"^outer-[a-z]{5}$", phase=11)
    registry = make_registry(inner, outer)
    assert [len(run) for run in _runs(registry.effective(NormalizationConfig()))] == [2]  # fused
    html = (
        b'<div class="outer-aaaaa keep">'
        b'<p class="inner-bbbbb keep"><span class="outer-ccccc">x</span></p>'
        b"</div>"
    )
    doc = parse(html)
    fused = apply_rules(doc, registry, NormalizationConfig())
    per_rule = apply_rules_per_rule(doc, registry, NormalizationConfig())
    assert records(fused) == records(per_rule)
    assert [(a.rule_id, a.before, a.after) for a in fused.applied_rules] == [
        ("test.nest.inner", "inner-bbbbb keep", "keep"),
        ("test.nest.outer", "outer-aaaaa keep", "keep"),
        ("test.nest.outer", "outer-ccccc", ""),
    ]


def test_runs_partition_the_ruleset_without_reordering_it() -> None:
    rules = BUILTIN_RULES.effective(NormalizationConfig())
    runs = _runs(rules)
    assert [r for run in runs for r in run] == rules  # nothing reordered, nothing lost
    assert all(len(run) == 1 or all(_fusable(r) for r in run) for run in runs)
    # Phases 10-30 fuse into one pass and phase 50 into another; the TEXT and canonical rules
    # keep a pass each. Expect to update this shape when rules are added -- what matters is
    # that the attribute rules land in as few runs as their phase neighbours allow.
    assert [len(run) for run in runs] == [14, 1, 1, 1, 1, 6, 1, 1, 1]
    assert sum(1 for r in rules if _fusable(r)) == 20  # 20 traversals became 2
