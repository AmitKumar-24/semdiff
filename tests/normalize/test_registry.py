"""T-12: rule model, phase-ordered registry, toggles, application reporting."""

from __future__ import annotations

import re

import pytest

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
from semdiff.normalize.registry import BUILTIN_RULES, ruleset_fingerprint

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
    div = result.tree.css_first("div")
    assert div.attributes["class"] == "card"
    assert result.tree.css_first("p").attributes["class"] == "kept"
    assert [a.rule_id for a in result.applied_rules] == ["test.class.css", "test.class.css"]
    first = result.applied_rules[0]
    assert (first.before, first.after) == ("card css-1abc2d", "card")
    assert first.locator.css == "html > body:nth-child(2) > div"
    assert re.fullmatch(r"[0-9a-f]{64}", first.locator.node_hash)
    assert first.locator.xpath is None


def test_attribute_strip_and_node_drop_and_text_strip() -> None:
    doc = parse(HTML)
    result = apply_rules(doc, make_registry(ID_RULE, NODE_RULE, TEXT_RULE), NormalizationConfig())
    div = result.tree.css_first("div")
    assert "id" not in div.attributes
    assert result.tree.css_first("aside") is None
    assert result.tree.css_first("p").text() == "Hello, "
    ids = [a.rule_id for a in result.applied_rules]
    assert ids == ["test.id.hash", "test.node.aside", "test.text.relative"]  # phase order 20, 30, 40


def test_structured_data_carriers_are_protected() -> None:
    doc = parse(HTML)
    protective = rule("test.any.attr", target=Target.ATTRIBUTE, pattern=r"^css-notouch$", attributes=frozenset())
    result = apply_rules(doc, make_registry(protective, CLASS_RULE, TEXT_RULE), NormalizationConfig())
    span = result.tree.css_first("span")
    assert span.attributes["itemprop"] == "css-notouch"
    assert span.attributes["about"] == "css-notouch"
    assert result.tree.css_first("script").text() == '{"date":"3 minutes ago"}'


def test_disabled_rules_do_not_fire() -> None:
    doc = parse(HTML)
    cfg = NormalizationConfig(disabled_rules=frozenset({"test.class.css"}))
    result = apply_rules(doc, make_registry(CLASS_RULE), cfg)
    assert result.tree.css_first("div").attributes["class"] == "card css-1abc2d"
    assert result.applied_rules == []


def test_unimplemented_or_misdeclared_actions_fail_loud() -> None:
    doc = parse(HTML)
    placeholder = rule("test.future", action=Action.REPLACE_WITH_PLACEHOLDER, phase=90)
    with pytest.raises(NotImplementedError, match="T-18"):
        apply_rules(doc, make_registry(placeholder), NormalizationConfig())
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
