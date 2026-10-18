"""``Locator`` — a pointer into a Document (DOMAIN_MODEL §7). Stage-relative, never absolute."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from selectolax.lexbor import LexborNode


@dataclass(frozen=True)
class Locator:
    xpath: str | None
    css: str | None
    node_hash: str  # the node itself, not its subtree (D-044); survives reordering

    @classmethod
    def for_node(cls, node: LexborNode, cache: PathCache | None = None) -> Locator:
        """Locator for an element or text node as it is *right now* (pre-mutation).

        Both fields are computed here and now, cache or no cache: a locator records the node as
        the rule found it, which is why it is taken before the rewrite. ``cache`` only changes
        how the css path is *arrived at* — see ``PathCache`` for the lifetime it is valid for.
        """
        target = node if node.tag not in ("-text", "-comment") or node.parent is None else node.parent
        css = _css_path(target) if cache is None else cache.path(target)
        return cls(xpath=None, css=css, node_hash=_node_hash(node))


def _segment(node: LexborNode) -> str:
    """``p`` or ``p:nth-child(2)`` — this element's own step, positional among element siblings."""
    position = 1
    sibling = node.prev
    while sibling is not None:
        if sibling.is_element_node:
            position += 1
        sibling = sibling.prev
    tag = node.tag or ""
    return tag if position == 1 else f"{tag}:nth-child({position})"


def _at_root(node: LexborNode | None) -> bool:
    """Whether the walk upwards has run out of path to build."""
    return node is None or node.tag in ("", "#document") or node.is_document_node


def _css_path(node: LexborNode) -> str:
    """``html > body > div:nth-child(2) > p`` — positional among element siblings, 1-based."""
    parts: list[str] = []
    current: LexborNode | None = node
    while not _at_root(current):
        assert current is not None
        parts.append(_segment(current))
        current = current.parent
    return " > ".join(reversed(parts))


class PathCache:
    """Element css paths already computed during **one pass over one tree** (T-27).

    ``_css_path`` climbs to the root and counts previous siblings at every level: ~14 parent
    hops but ~114 sibling hops per call on the corpus, and the engine makes one call per
    application. Sibling applications share almost all of that walk, so an ancestor's path is
    computed once and the walk stops at the first element already known.

    Keyed by ``mem_id``, the underlying DOM node's address, **not** by the node: two wrappers
    for the same node compare equal, but ``LexborNode.__eq__`` is proportional to the
    serialized subtree — 765 µs for a 58 KB ``<html>`` against 0.6 µs for a leaf — so a
    node-keyed cache spends more on dict probes than the walk it saves (F-032).

    That key is an address, so a cache is only valid while every element it has seen is still
    alive. Two rules keep it so, and both are the caller's to honour:

    * one cache per pass, never reused across passes, so nothing survives a rule that may
      reshape the tree between passes; and
    * no cache at all for a pass that can destroy an element — ``DROP_NODE`` (``_apply_node``)
      and user-supplied ``CANONICALIZE`` transforms, which the engine never hands one to.

    Attribute rewrites, text replacement and comment removal cannot invalidate an entry: they
    free text and comment nodes, which are never keys here, and they leave every element in
    place. ``Locator.for_node`` resolves a text or comment node to its parent element before
    asking for a path, so only elements are ever cached or looked up.

    **Neither rule is enforced at runtime**, and that is a measured choice rather than an
    oversight (T-27). Counting the tree's elements once per pass to detect a breach costs 58 ms
    against the 192 ms this cache saves on the corpus, and reports the breach only after the
    wrong paths have been handed out. Re-checking the queried node's own step on every hit
    costs 59 ms and still misses the case that matters: when an *ancestor* shifts, the check
    passes and the cache answers ``div:nth-child(3)`` for a node that is now
    ``div:nth-child(2)``. Both spend about 30% of the gain to buy a partial guard, so the
    invariant stays a convention of this module and the engine's. What would catch a violation
    is the evidence that already exists: ``tests/corpus/test_fused_attribute_equivalence.py``
    and the per-rule reference engine recompute every locator with no cache at all, and
    ``tests/corpus/parser_contract.json`` pins every ``css`` value of all 40 snapshots.
    """

    __slots__ = ("_paths",)

    def __init__(self) -> None:
        self._paths: dict[int, str] = {}

    def path(self, node: LexborNode) -> str:
        """The same string ``_css_path`` returns, reusing any ancestor already computed."""
        chain: list[LexborNode] = []
        current: LexborNode | None = node
        prefix = ""
        while not _at_root(current):
            assert current is not None
            known = self._paths.get(current.mem_id)
            if known is not None:
                prefix = known
                break
            chain.append(current)
            current = current.parent
        for element in reversed(chain):
            part = _segment(element)
            prefix = f"{prefix} > {part}" if prefix else part
            self._paths[element.mem_id] = prefix
        return prefix


def _node_hash(node: LexborNode) -> str:
    """Fingerprint of the node *itself* — never of its descendants (D-044, F-030).

    Hashing ``node.html`` made provenance order-dependent: the same rewrite of the same
    attribute recorded a different hash depending on whether a descendant had already been
    rewritten, which differs between one traversal per rule and the fused attribute pass. A
    locator points at a node, so its fingerprint is a property of that node: the tag and
    attributes of an element, the content of a text or comment node. It still survives the node
    moving, and it still changes when the node itself changes.
    """
    if node.tag == "-text":
        raw = node.text_content or ""
    elif node.is_element_node:
        # ``repr`` of the tag and the sorted (name, value) pairs: deterministic, and quoted, so
        # two different attribute sets cannot collide the way a flat join would. A boolean
        # attribute hashes like an empty one, as the canonical serializer unifies them (D-032).
        raw = repr((node.tag or "", sorted((n, v or "") for n, v in node.attributes.items())))
    else:
        raw = node.html or ""  # a comment or doctype has no children to pull in
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
