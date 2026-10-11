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
    def for_node(cls, node: LexborNode) -> Locator:
        """Locator for an element or text node as it is *right now* (pre-mutation)."""
        target = node if node.tag not in ("-text", "-comment") or node.parent is None else node.parent
        return cls(xpath=None, css=_css_path(target), node_hash=_node_hash(node))


def _css_path(node: LexborNode) -> str:
    """``html > body > div:nth-child(2) > p`` — positional among element siblings, 1-based."""
    parts: list[str] = []
    current: LexborNode | None = node
    while current is not None and current.tag not in ("", "#document") and not current.is_document_node:
        position = 1
        sibling = current.prev
        while sibling is not None:
            if sibling.is_element_node:
                position += 1
            sibling = sibling.prev
        tag = current.tag or ""
        parts.append(tag if position == 1 else f"{tag}:nth-child({position})")
        current = current.parent
    return " > ".join(reversed(parts))


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
