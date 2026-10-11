"""``Locator`` (DOMAIN_MODEL §7): a positional CSS path plus a fingerprint of the node itself.

The fingerprint used to hash ``node.html`` — the element's whole serialized subtree — which made
provenance depend on edits to unrelated children and so on the order rules happened to run in
(F-030). D-044 narrowed it to the node: its tag and attributes. These tests pin both halves of
that, the part that changed and the parts that must not have.
"""

from __future__ import annotations

import re

from selectolax.lexbor import LexborHTMLParser, LexborNode

from semdiff.locator import Locator

NESTED = '<div id="outer" class="a"><p id="inner" class="b">text</p></div>'


def tree_of(html: str) -> LexborHTMLParser:
    return LexborHTMLParser(html)


def nodes_of(html: str) -> list[LexborNode]:
    tree = tree_of(html)
    assert tree.root is not None
    return list(tree.root.traverse(include_text=True))


def first(html: str, tag: str) -> LexborNode:
    return next(n for n in nodes_of(html) if n.tag == tag)


def test_a_descendant_rewrite_leaves_its_ancestor_fingerprint_alone() -> None:
    """The point of D-044. The ancestor did not change, so its provenance must not either."""
    tree = tree_of(NESTED)
    outer, inner = tree.css_first("div"), tree.css_first("p")
    before_outer, before_inner = Locator.for_node(outer), Locator.for_node(inner)

    inner.attrs["class"] = "rewritten"  # what a normalization rule does to a descendant
    assert Locator.for_node(outer) == before_outer
    assert Locator.for_node(inner) != before_inner


def test_a_descendant_text_rewrite_also_leaves_the_ancestor_alone() -> None:
    tree = tree_of(NESTED)
    assert tree.root is not None
    outer = tree.css_first("div")
    before = Locator.for_node(outer)
    text = next(n for n in tree.root.traverse(include_text=True) if n.tag == "-text")
    text.replace_with("something else entirely")
    assert "something else" in (outer.html or "")  # the subtree really did change
    assert Locator.for_node(outer) == before


def test_the_fingerprint_still_changes_when_the_node_itself_changes() -> None:
    tree = tree_of(NESTED)
    node = tree.css_first("p")
    original = Locator.for_node(node).node_hash

    node.attrs["class"] = "c"
    changed = Locator.for_node(node).node_hash
    assert changed != original

    del node.attrs["class"]
    assert Locator.for_node(node).node_hash not in (original, changed)


def test_attribute_order_does_not_affect_the_fingerprint() -> None:
    """Attributes are sorted before hashing, so canonical.attr_order cannot move it."""
    first = Locator.for_node(tree_of('<p id="a" class="b">x</p>').css_first("p"))
    second = Locator.for_node(tree_of('<p class="b" id="a">x</p>').css_first("p"))
    assert first.node_hash == second.node_hash


def test_two_attribute_sets_that_would_collide_under_a_flat_join_do_not() -> None:
    a = Locator.for_node(tree_of('<p a="b c=d">x</p>').css_first("p"))
    b = Locator.for_node(tree_of('<p a="b" c="d">x</p>').css_first("p"))
    assert a.node_hash != b.node_hash


def test_a_boolean_attribute_hashes_like_an_empty_one() -> None:
    """The canonical serializer unifies the two forms (D-032), so the fingerprint follows it."""
    boolean = Locator.for_node(tree_of("<input disabled>").css_first("input"))
    empty = Locator.for_node(tree_of('<input disabled="">').css_first("input"))
    assert boolean.node_hash == empty.node_hash


def test_a_text_node_hashes_its_own_text_and_a_comment_its_own_markup() -> None:
    html = "<div>hello<!-- note --></div>"
    text = first(html, "-text")
    comment = first(html, "-comment")
    assert Locator.for_node(text).node_hash == Locator.for_node(first("<p>hello</p>", "-text")).node_hash
    assert Locator.for_node(comment).node_hash != Locator.for_node(text).node_hash
    # both report the *parent* path, since a text node has no CSS path of its own
    assert Locator.for_node(text).css == Locator.for_node(comment).css == "html > body:nth-child(2) > div"


def test_the_unchanged_half_of_the_locator() -> None:
    """Everything except the fingerprint is exactly as it was: xpath is still None on selectolax
    and the CSS path is still positional among element siblings."""
    tree = tree_of("<div><p>a</p><p>b</p><span><p>c</p></span></div>")
    second_p, nested_p = tree.css("p")[1], tree.css("span p")[0]
    assert Locator.for_node(second_p).xpath is None
    assert Locator.for_node(second_p).css == "html > body:nth-child(2) > div > p:nth-child(2)"
    assert Locator.for_node(nested_p).css == "html > body:nth-child(2) > div > span:nth-child(3) > p"


def test_the_fingerprint_is_a_deterministic_sha256() -> None:
    first = Locator.for_node(tree_of(NESTED).css_first("p")).node_hash
    second = Locator.for_node(tree_of(NESTED).css_first("p")).node_hash
    assert first == second
    assert re.fullmatch(r"[0-9a-f]{64}", first)


def test_identical_elements_in_different_places_share_a_fingerprint() -> None:
    """What the fingerprint is *for*: it identifies the node by what it is, so it survives the
    node moving — which is also why it cannot double as a uniqueness key."""
    tree = tree_of('<div><p class="x">one</p></div><section><p class="x">two</p></section>')
    first, second = tree.css("p")
    assert Locator.for_node(first).node_hash == Locator.for_node(second).node_hash
    assert Locator.for_node(first).css != Locator.for_node(second).css
