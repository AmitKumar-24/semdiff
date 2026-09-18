"""``Locator`` — a pointer into a Document (DOMAIN_MODEL §7). Stage-relative, never absolute."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from selectolax.lexbor import LexborNode


@dataclass(frozen=True)
class Locator:
    xpath: str | None
    css: str | None
    node_hash: str  # survives reordering; a positional path does not

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
    raw = node.text_content if node.tag == "-text" else (node.html or "")
    return hashlib.sha256((raw or "").encode("utf-8")).hexdigest()
