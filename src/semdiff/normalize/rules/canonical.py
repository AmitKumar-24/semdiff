"""Canonicalization family (T-17, FR-8) — always the last phase.

Reformatting alone must produce zero difference. Three whole-tree transforms:
comments are dropped, inter-element whitespace is collapsed the way a renderer would
collapse it, and attributes are sorted by name. Void/self-closing forms, boolean
attributes, tag/attribute-name case and entity spelling are already unified by the
canonical serializer (D-032: Lexbor's ``tree.html``) and need no rule.
"""

from __future__ import annotations

import re

from selectolax.lexbor import LexborHTMLParser, LexborNode

from semdiff.locator import Locator
from semdiff.normalize.model import (
    Action,
    NormalizationRule,
    RegexMatcher,
    RuleApplication,
    RuleFamily,
    Target,
)
from semdiff.normalize.registry import PROTECTED_TEXT_PARENTS

PHASE_CANONICAL = 90

# Whitespace touching these elements is layout, not content. Whitespace between inline
# elements (<b>a</b> <i>b</i>) is rendered and is kept as a single space.
BLOCK_TAGS = frozenset(
    "html head body title meta link base script style noscript template div p ul ol li dl dt dd "
    "table thead tbody tfoot tr td th caption colgroup col section article aside header footer nav "
    "main form fieldset legend h1 h2 h3 h4 h5 h6 hr br pre blockquote figure figcaption address "
    "details summary iframe canvas video audio picture source track option optgroup".split()
)
PRESERVED_WHITESPACE_TAGS = frozenset({"pre", "textarea"}) | PROTECTED_TEXT_PARENTS
_WS = re.compile(r"\s+")
_ANY = RegexMatcher(r"(?s)^.*$")  # tree transforms do not use the matcher


def _element_sibling(node: LexborNode, forward: bool) -> LexborNode | None:
    sibling = node.next if forward else node.prev
    while sibling is not None and sibling.tag == "-comment":
        sibling = sibling.next if forward else sibling.prev
    return sibling


def _is_block(node: LexborNode | None) -> bool:
    return node is not None and node.is_element_node and (node.tag or "") in BLOCK_TAGS


def _under_preserved(node: LexborNode) -> bool:
    ancestor = node.parent
    while ancestor is not None:
        if (ancestor.tag or "") in PRESERVED_WHITESPACE_TAGS:
            return True
        ancestor = ancestor.parent
    return False


def _document(tree: LexborHTMLParser) -> LexborNode | None:
    """The #document node, so comments and text outside <html> are reachable too."""
    root = tree.root
    return None if root is None else (root.parent or root)


def strip_comments(rule: NormalizationRule, tree: LexborHTMLParser) -> list[RuleApplication]:
    out: list[RuleApplication] = []
    start = _document(tree)
    if start is None:
        return out
    for node in [n for n in start.traverse(include_text=True) if n.tag == "-comment"]:
        out.append(RuleApplication(rule.id, Locator.for_node(node), node.html or "", ""))
        node.decompose()
    if tree.root is not None:
        tree.root.merge_text_nodes()  # text split only by a removed comment becomes one node again
    return out


def collapse_whitespace(rule: NormalizationRule, tree: LexborHTMLParser) -> list[RuleApplication]:
    out: list[RuleApplication] = []
    if tree.root is None:
        return out
    for node in [n for n in tree.root.traverse(include_text=True) if n.tag == "-text"]:
        if _under_preserved(node):
            continue
        before = node.text_content or ""
        prev_sib, next_sib = _element_sibling(node, False), _element_sibling(node, True)
        at_start = prev_sib is None or _is_block(prev_sib)
        at_end = next_sib is None or _is_block(next_sib)
        after = _WS.sub(" ", before)
        if after == " ":
            after = "" if (at_start or at_end) else " "
        else:
            if at_start:
                after = after.lstrip(" ")
            if at_end:
                after = after.rstrip(" ")
        if after == before:
            continue
        locator = Locator.for_node(node)
        if after:
            node.replace_with(after)
        else:
            node.decompose()
        out.append(RuleApplication(rule.id, locator, before, after))
    return out


_START_TAG_ATTR = re.compile(r"""\s([^\s=/>"']+)(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]*))?""")


def _serialized_names(node: LexborNode) -> list[str] | None:
    """Attribute names as the serializer spells them (``viewBox``), in source order.

    ``node.attributes`` keys are lowercased, but Lexbor keeps the spec-adjusted spelling of
    foreign-content attributes; re-inserting through the lowercase key would lose it.
    """
    html = node.html or ""
    end = html.find(">")
    names = _START_TAG_ATTR.findall(html[: end if end >= 0 else len(html)])
    return names if [n.lower() for n in names] == list(node.attributes) else None


def sort_attributes(rule: NormalizationRule, tree: LexborHTMLParser) -> list[RuleApplication]:
    out: list[RuleApplication] = []
    if tree.root is None:
        return out
    for node in [n for n in tree.root.traverse() if n.is_element_node]:
        names = _serialized_names(node)
        if names is None:
            continue  # start tag could not be read back safely: leave this element alone
        ordered = sorted(names, key=str.lower)
        if names == ordered:
            continue
        locator = Locator.for_node(node)
        values = dict(node.attributes)
        for name in names:
            del node.attrs[name.lower()]
        for name in ordered:
            node.attrs[name] = values[name.lower()] or ""
        out.append(RuleApplication(rule.id, locator, " ".join(names), " ".join(ordered)))
    return out


def _rule(rule_id: str, transform: object) -> NormalizationRule:
    return NormalizationRule(
        id=rule_id,
        family=RuleFamily.CANONICAL,
        target=Target.NODE,
        matcher=_ANY,
        action=Action.CANONICALIZE,
        phase=PHASE_CANONICAL,
        transform=transform,  # type: ignore[arg-type]
    )


CANONICAL_RULES: tuple[NormalizationRule, ...] = (
    _rule("canonical.attr_order", sort_attributes),
    _rule("canonical.comments", strip_comments),
    _rule("canonical.whitespace", collapse_whitespace),
)
