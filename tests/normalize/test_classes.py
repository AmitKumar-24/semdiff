"""T-13: dynamic-class rule family (FR-5) on the T-12 engine."""

from __future__ import annotations

import pytest

from semdiff import NormalizationConfig, parse
from semdiff.normalize import BUILTIN_RULES, RuleFamily, apply_rules
from semdiff.normalize.rules.classes import CLASS_RULES

BY_ID = {rule.id: rule for rule in CLASS_RULES}

# (rule id, tokens it must match). Real samples from the T-04 captures where possible.
POSITIVE = {
    "class.emotion": ["css-1dbjc4n", "css-ios753", "css-eu4da", "css-14f5s8o", "css-uscrbs"],
    "class.antd_style": ["acss-q7dsfq", "acss-11cbehh", "acss-1jyth9"],
    "class.styled_components.component": ["sc-bdfBwQ", "sc-AxjAm", "sc-1a2b3c4-0"],
    "class.styled_components.generated": ["bcMPWx", "hJkLmn", "eXvGbs"],
    "class.css_modules": [
        "categoryLinkLabel_O4bj", "codeBlockContainer_jDV4", "toggle_bT41", "iconExternalLink_Rdzz",
        "themedComponent_bJGS", "Home_main__abc12", "price_a1b2c3",
    ],
    "class.leading_underscore_hash": ["_1x2y3z4", "_abcde", "_1abc2de"],
}

# Meaningful / static class names that no rule may touch.
NEGATIVE = [
    "MuiTypography-root", "MuiGrid-grid-xs-12", "MuiSvgIcon-fontSizeMedium", "MuiBox-root",
    "ant-table-cell", "ant-col-xs-24", "ant-table-row-level-0", "anticon",
    "footer__item", "menu__list-item", "navbar__link", "dropdown__link", "table-of-contents__link",
    "theme-doc-sidebar-item-category-level-1", "docs-version-3.10.2", "col--3", "col",
    "px-2", "py-[5px]", "hover:text-blue-500", "dark:hover:border-slate-600", "focus-visible:ui-ring-2",
    "nav_item", "btn_primary", "is-active", "js-toggle", "clean-btn", "h1", "btn", "card", "markdown-body",
    "navBar", "isOpen", "css-loader-x", "css-1abc2de-Button", "css", "sc", "_", "__",
]


@pytest.mark.parametrize(("rule_id", "token"), [(r, t) for r, ts in POSITIVE.items() for t in ts])
def test_rule_matches_its_generator(rule_id: str, token: str) -> None:
    assert BY_ID[rule_id].matcher.matches(token)


@pytest.mark.parametrize("token", NEGATIVE)
def test_static_classes_match_no_rule(token: str) -> None:
    assert [rule.id for rule in CLASS_RULES if rule.matcher.matches(token)] == []


def test_family_is_registered_with_stable_ids_and_phase() -> None:
    ids = [rule.id for rule in BUILTIN_RULES.ordered() if rule.family is RuleFamily.DYNAMIC_CLASS]
    assert ids == sorted(BY_ID)  # all registered, phase-ordered by id within the family
    assert {rule.phase for rule in CLASS_RULES} == {10}
    assert all(rule.attributes == frozenset({"class"}) for rule in CLASS_RULES)
    assert all(rule.enabled for rule in CLASS_RULES)


def test_end_to_end_strip_preserves_static_tokens_and_order() -> None:
    doc = parse(
        b'<div class="MuiBox-root css-1p1nqj6 markdown-body categoryLinkLabel_O4bj">'
        b'<p id="css-1p1nqj6" class="css-9zz9zz">x</p><span itemprop="css-1p1nqj6" class="kept">y</span></div>'
    )
    result = apply_rules(doc, BUILTIN_RULES, NormalizationConfig())
    assert result.tree.css_first("div").attributes["class"] == "MuiBox-root markdown-body"
    assert "class" not in result.tree.css_first("p").attributes  # every token stripped → attribute gone
    assert result.tree.css_first("p").attributes["id"] == "css-1p1nqj6"  # not a class: untouched by T-13
    assert result.tree.css_first("span").attributes["itemprop"] == "css-1p1nqj6"
    fired = [(a.rule_id, a.before, a.after) for a in result.applied_rules if a.rule_id.startswith("class.")]
    assert fired == [
        ("class.css_modules", "MuiBox-root css-1p1nqj6 markdown-body categoryLinkLabel_O4bj", "MuiBox-root css-1p1nqj6 markdown-body"),
        ("class.emotion", "MuiBox-root css-1p1nqj6 markdown-body", "MuiBox-root markdown-body"),
        ("class.emotion", "css-9zz9zz", ""),
    ]


@pytest.mark.parametrize("rule_id", sorted(BY_ID))
def test_each_rule_is_individually_toggleable(rule_id: str) -> None:
    token = POSITIVE[rule_id][0]
    doc = parse(f'<p class="{token} static">x</p>'.encode())
    off = NormalizationConfig(disabled_rules=frozenset({rule_id}))
    assert apply_rules(doc, BUILTIN_RULES, off).tree.css_first("p").attributes["class"] == f"{token} static"
    assert apply_rules(doc, BUILTIN_RULES, NormalizationConfig()).tree.css_first("p").attributes["class"] == "static"


def test_input_tree_not_mutated_and_output_deterministic() -> None:
    doc = parse(b'<div class="css-1abc2d a"><p class="sc-bdfBwQ bcMPWx b">x</p></div>')
    before = doc.tree.html
    first = apply_rules(doc, BUILTIN_RULES, NormalizationConfig())
    second = apply_rules(doc, BUILTIN_RULES, NormalizationConfig())
    assert doc.tree.html == before
    assert first.tree.html == second.tree.html
    assert first.tree.css_first("div").attributes["class"] == "a"
    assert first.tree.css_first("p").attributes["class"] == "b"

