"""``Locator`` (DOMAIN_MODEL §7): a positional CSS path plus a fingerprint of the node itself.

The fingerprint used to hash ``node.html`` — the element's whole serialized subtree — which made
provenance depend on edits to unrelated children and so on the order rules happened to run in
(F-030). D-044 narrowed it to the node: its tag and attributes. These tests pin both halves of
that, the part that changed and the parts that must not have.
"""

from __future__ import annotations

import re

from selectolax.lexbor import LexborHTMLParser, LexborNode

from semdiff.locator import Locator, PathCache, _css_path
from tests.nodes import one

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
    outer, inner = one(tree, "div"), one(tree, "p")
    before_outer, before_inner = Locator.for_node(outer), Locator.for_node(inner)

    inner.attrs["class"] = "rewritten"  # what a normalization rule does to a descendant
    assert Locator.for_node(outer) == before_outer
    assert Locator.for_node(inner) != before_inner


def test_a_descendant_text_rewrite_also_leaves_the_ancestor_alone() -> None:
    tree = tree_of(NESTED)
    assert tree.root is not None
    outer = one(tree, "div")
    before = Locator.for_node(outer)
    text = next(n for n in tree.root.traverse(include_text=True) if n.tag == "-text")
    text.replace_with("something else entirely")
    assert "something else" in (outer.html or "")  # the subtree really did change
    assert Locator.for_node(outer) == before


def test_the_fingerprint_still_changes_when_the_node_itself_changes() -> None:
    tree = tree_of(NESTED)
    node = one(tree, "p")
    original = Locator.for_node(node).node_hash

    node.attrs["class"] = "c"
    changed = Locator.for_node(node).node_hash
    assert changed != original

    del node.attrs["class"]
    assert Locator.for_node(node).node_hash not in (original, changed)


def test_attribute_order_does_not_affect_the_fingerprint() -> None:
    """Attributes are sorted before hashing, so canonical.attr_order cannot move it."""
    first = Locator.for_node(one(tree_of('<p id="a" class="b">x</p>'), "p"))
    second = Locator.for_node(one(tree_of('<p class="b" id="a">x</p>'), "p"))
    assert first.node_hash == second.node_hash


def test_two_attribute_sets_that_would_collide_under_a_flat_join_do_not() -> None:
    a = Locator.for_node(one(tree_of('<p a="b c=d">x</p>'), "p"))
    b = Locator.for_node(one(tree_of('<p a="b" c="d">x</p>'), "p"))
    assert a.node_hash != b.node_hash


def test_a_boolean_attribute_hashes_like_an_empty_one() -> None:
    """The canonical serializer unifies the two forms (D-032), so the fingerprint follows it."""
    boolean = Locator.for_node(one(tree_of("<input disabled>"), "input"))
    empty = Locator.for_node(one(tree_of('<input disabled="">'), "input"))
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
    first = Locator.for_node(one(tree_of(NESTED), "p")).node_hash
    second = Locator.for_node(one(tree_of(NESTED), "p")).node_hash
    assert first == second
    assert re.fullmatch(r"[0-9a-f]{64}", first)


def test_identical_elements_in_different_places_share_a_fingerprint() -> None:
    """What the fingerprint is *for*: it identifies the node by what it is, so it survives the
    node moving — which is also why it cannot double as a uniqueness key."""
    tree = tree_of('<div><p class="x">one</p></div><section><p class="x">two</p></section>')
    first, second = tree.css("p")
    assert Locator.for_node(first).node_hash == Locator.for_node(second).node_hash
    assert Locator.for_node(first).css != Locator.for_node(second).css

# --- the pass-scoped path cache (T-27, F-032) ------------------------------------------------
# The cache is keyed by ``mem_id``, the DOM node's address, because a node-keyed dict pays
# ``LexborNode.__eq__`` and that cost grows with the subtree. An address is only an identity
# while the node is alive, so what these pin is the agreement with the uncached walk and the
# lifetime the agreement depends on.

SHIFTING = '<div><p id="a">x</p><aside>drop me</aside><p id="b">z</p></div>'


def test_the_cache_agrees_with_the_walk_on_every_element() -> None:
    tree = tree_of('<div><p>a</p><section><span>b</span><span>c</span></section><p>d</p></div>')
    assert tree.root is not None
    elements = [n for n in tree.root.traverse() if n.is_element_node]
    assert len(elements) == 9  # html, head, body, div, p, section, span, span, p
    cache = PathCache()
    assert [cache.path(n) for n in elements] == [_css_path(n) for n in elements]


def test_the_cache_agrees_with_the_walk_on_text_and_comment_nodes() -> None:
    """Both resolve to the parent element before a path is asked for, so both must match."""
    tree = tree_of("<div><p>one</p><!-- two --><p>three</p></div>")
    assert tree.root is not None
    cache = PathCache()
    for node in tree.root.traverse(include_text=True):
        assert Locator.for_node(node, cache) == Locator.for_node(node)


def test_a_second_lookup_returns_the_same_path() -> None:
    tree = tree_of(SHIFTING)
    cache = PathCache()
    second = tree.css("p")[1]
    assert cache.path(second) == cache.path(second) == _css_path(second)


def test_the_cache_is_what_makes_a_sibling_cheap() -> None:
    """The ancestors are shared, so the second sibling must not re-walk them: its entry is
    added, and every ancestor is already there from the first."""
    tree = tree_of(SHIFTING)
    cache = PathCache()
    first, second = tree.css("p")[0], tree.css("p")[1]
    cache.path(first)
    cached_after_first = dict(cache._paths)
    cache.path(second)
    added = set(cache._paths) - set(cached_after_first)
    assert added == {second.mem_id}


def test_a_cache_that_outlives_a_structural_change_goes_stale() -> None:
    """Anti-vacuity for the lifetime rule. Dropping the ``<aside>`` moves the second ``<p>``
    from the third child to the second, and a cache that survived the drop would keep saying
    the old path — which is exactly why the engine builds one per pass and gives none to the
    pass that can destroy an element.
    """
    tree = tree_of(SHIFTING)
    cache = PathCache()
    second = tree.css("p")[1]
    before = cache.path(second)
    assert before.endswith("p:nth-child(3)")

    aside = one(tree, "aside")
    aside.decompose()

    assert cache.path(second) == before  # stale: the cache still answers from the old shape
    fresh = _css_path(second)
    assert fresh.endswith("p:nth-child(2)")
    assert fresh != before
    assert PathCache().path(second) == fresh  # a per-pass cache is right again
