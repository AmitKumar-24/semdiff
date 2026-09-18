"""T-17: canonicalization family (FR-8) — the last phase; reformatting alone yields zero difference."""

from __future__ import annotations

import pytest

from semdiff import NormalizationConfig, parse
from semdiff.normalize import BUILTIN_RULES, Action, RuleFamily, apply_rules
from semdiff.normalize.rules.canonical import CANONICAL_RULES, PHASE_CANONICAL

BY_ID = {rule.id: rule for rule in CANONICAL_RULES}


def canon(html: str, config: NormalizationConfig | None = None) -> str:
    return apply_rules(parse(html.encode()), BUILTIN_RULES, config or NormalizationConfig()).tree.html or ""


def fired(html: str) -> list[tuple[str, str, str]]:
    result = apply_rules(parse(html.encode()), BUILTIN_RULES, NormalizationConfig())
    return [(a.rule_id, a.before, a.after) for a in result.applied_rules if a.rule_id.startswith("canonical.")]


# ---- equivalent inputs: every member of a group must canonicalize to the same bytes ------------
EQUIVALENT = {
    "pretty-vs-minified": [
        "<div><p>Hello <b>world</b></p><ul><li>a</li><li>b</li></ul></div>",
        "<div>\n  <p>\n    Hello   <b>world</b>\n  </p>\n  <ul>\n    <li>a</li>\n    <li>b</li>\n  </ul>\n</div>\n",
        "<div>\r\n\t<p>Hello <b>world</b></p>\r\n\t<ul><li>a</li>\r\n<li>b</li></ul></div>",
    ],
    "attribute-order": [
        '<a href="/x" class="btn" data-k="v" id="main">t</a>',
        '<a id="main" data-k="v" class="btn" href="/x">t</a>',
        '<a class="btn" href="/x" id="main" data-k="v">t</a>',
    ],
    "self-closing-and-boolean": [
        '<p>a<br>b<br>c<img src="x" alt="">d<input disabled></p>',
        '<p>a<br/>b<br />c<img src="x" alt="" />d<input disabled=""></p>',
        '<p>a<br/>b<br />c<img alt="" src="x"/>d<input disabled=""></p>',
    ],
    "comments": [
        "<div><p>x</p><p>y</p></div>",
        "<div><!-- lead --><p>x</p><!-- between --><p>y</p><!-- trail --></div>",
        "<!-- top --><div><p>x</p><p>y</p></div><!-- bottom -->",
    ],
    "case-and-quoting": [
        '<div class="A" data-x="y">t</div>',
        "<DIV CLASS=A Data-X='y'>t</DIV>",
    ],
    "inline-spacing": [
        "<p><b>a</b> <i>b</i> c</p>",
        "<p><b>a</b>\n<i>b</i>\n\tc</p>",
        "<p><b>a</b>   <i>b</i>     c   </p>",
    ],
}


@pytest.mark.parametrize("group", sorted(EQUIVALENT))
def test_equivalent_inputs_canonicalize_identically(group: str) -> None:
    outputs = {canon(html) for html in EQUIVALENT[group]}
    assert len(outputs) == 1, outputs


def test_boolean_attribute_value_disabled_disabled_is_a_real_difference() -> None:
    # disabled="disabled" is a different attribute value from disabled="" — the parser keeps it
    assert canon('<input disabled="disabled">') != canon("<input disabled>")


# ---- differences that must survive -------------------------------------------------------------
DISTINCT = [
    ("<p>Hello world</p>", "<p>Hello  World</p>"),  # case in content
    ("<p>a b</p>", "<p>ab</p>"),  # a space between words is content
    ("<p>x</p>", "<div>x</div>"),  # structure
    ('<a href="/x">t</a>', '<a href="/y">t</a>'),  # attribute value
    ('<a href="/x">t</a>', '<a href="/x" rel="nofollow">t</a>'),  # attribute presence
    ("<pre>a\n  b</pre>", "<pre>a b</pre>"),  # preformatted whitespace is content
    ("<textarea> x </textarea>", "<textarea>x</textarea>"),
    ("<p><b>a</b> <i>b</i></p>", "<p><b>a</b><i>b</i></p>"),  # inline space is rendered
    ("<ul><li>a</li><li>b</li></ul>", "<ul><li>b</li><li>a</li></ul>"),  # order is content (T-77)
]


@pytest.mark.parametrize(("left", "right"), DISTINCT, ids=[d[0][:24] for d in DISTINCT])
def test_meaningful_differences_remain(left: str, right: str) -> None:
    assert canon(left) != canon(right)


def test_comments_stripped_with_provenance() -> None:
    assert fired("<div><!-- lead --><p>x</p></div>") == [("canonical.comments", "<!-- lead -->", "")]
    assert "<!--" not in canon("<div><!-- a --><p>x<!-- b --></p></div>")
    assert canon("<p>x <!-- c --> y</p>") == canon("<p>x y</p>")  # text around a removed comment merges


def test_whitespace_collapse_with_provenance() -> None:
    apps = fired("<div>\n  <p>\n    Hello   world\n  </p>\n</div>")
    assert [a for a in apps if a[0] == "canonical.whitespace"] == [
        ("canonical.whitespace", "\n  ", ""),
        ("canonical.whitespace", "\n    Hello   world\n  ", "Hello world"),
        ("canonical.whitespace", "\n", ""),
    ]


def test_attribute_order_with_provenance() -> None:
    apps = fired('<a id="main" class="btn" href="/x">t</a>')
    assert apps == [("canonical.attr_order", "id class href", "class href id")]
    assert canon('<a id="main" class="btn" href="/x">t</a>').count('<a class="btn" href="/x" id="main">') == 1
    assert fired('<a class="btn" href="/x" id="main">t</a>') == []  # already sorted: nothing reported


def test_protected_content_untouched() -> None:
    html = (
        '<script type="application/ld+json">{ "a":  1 }</script>'
        "<style>p {  color: red; }</style>"
        "<template><p>  keep   this  </p></template>"
        "<pre>  keep\n   this</pre><textarea>  raw  </textarea>"
    )
    out = canon(html)
    assert '{ "a":  1 }' in out and "p {  color: red; }" in out
    assert "<p>  keep   this  </p>" in out
    assert "keep\n   this" in out and ">  raw  <" in out


def test_canonicalization_is_last_and_idempotent() -> None:
    order = [r.id for r in BUILTIN_RULES.ordered()]
    canonical_ids = [i for i in order if i.startswith("canonical.")]
    assert order[-len(canonical_ids):] == canonical_ids
    assert {r.phase for r in CANONICAL_RULES} == {PHASE_CANONICAL} and PHASE_CANONICAL > 40
    assert all(r.action is Action.CANONICALIZE and r.family is RuleFamily.CANONICAL for r in CANONICAL_RULES)
    assert sorted(BY_ID) == ["canonical.attr_order", "canonical.comments", "canonical.whitespace"]
    messy = '<div>\n  <!-- c -->\n  <a id="m" class="b" href="/x">\n    t\n  </a>\n</div>'
    once = canon(messy)
    assert canon(once) == once  # fixpoint
    assert fired(once) == []  # and nothing left to report


@pytest.mark.parametrize("rule_id", sorted(BY_ID))
def test_each_rule_is_individually_toggleable(rule_id: str) -> None:
    html = '<div>\n  <!-- c --><a id="m" class="b">t</a>\n</div>'
    off = NormalizationConfig(disabled_rules=frozenset({rule_id}))
    assert canon(html, off) != canon(html)


def test_input_tree_not_mutated_and_output_deterministic() -> None:
    doc = parse(b'<div>\n  <!-- c -->\n  <a id="m" class="b">t</a>\n</div>')
    before = doc.tree.html
    first = apply_rules(doc, BUILTIN_RULES, NormalizationConfig())
    second = apply_rules(doc, BUILTIN_RULES, NormalizationConfig())
    assert doc.tree.html == before
    assert first.tree.html == second.tree.html == '<html><head></head><body><div><a class="b" id="m">t</a></div></body></html>'


def test_foreign_content_attribute_case_survives_sorting() -> None:
    # Found on mui.com: viewBox is spec-adjusted by the parser; re-inserting via the lowercase key
    # produced "viewbox" on the first pass and "viewBox" on the second — no fixpoint.
    html = '<svg width="18" viewBox="0 0 16 16" fill="none"><path d="M0 0"/></svg>'
    once = canon(html)
    assert '<svg fill="none" viewBox="0 0 16 16" width="18">' in once
    assert canon(once) == once
