"""Phase-ordered rule registry and the generic rule engine (T-12).

The engine applies rules in ``(phase, id)`` order and reports every application.
Structured-data carriers are protected here, centrally (D-029): TEXT rules never enter
``<script>``/``<style>``/``<template>`` and attribute rules never touch microdata/RDFa
identity attributes. Rule families are registered from T-13 onwards.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable

from selectolax.lexbor import LexborHTMLParser, LexborNode

from semdiff.config import NormalizationConfig
from semdiff.locator import Locator
from semdiff.normalize.model import (
    Action,
    NormalizationRule,
    NormalizedDoc,
    RuleApplication,
    RuleFamily,
    Target,
)
from semdiff.parse import ParsedDoc

PROTECTED_TEXT_PARENTS = frozenset({"script", "style", "template"})
_FUSABLE_TARGETS = frozenset({Target.ATTRIBUTE, Target.ATTRIBUTE_VALUE, Target.ATTRIBUTE_SUBSTRING})
_PROTECTED_TEXT_SELECTOR = ", ".join(sorted(PROTECTED_TEXT_PARENTS))
PROTECTED_ATTRIBUTES = frozenset(
    {"itemid", "itemref", "itemtype", "itemprop", "itemscope", "about", "resource", "typeof", "property", "vocab", "prefix"}
)


class RuleRegistry:
    def __init__(self) -> None:
        self._rules: dict[str, NormalizationRule] = {}

    def register(self, rule: NormalizationRule) -> None:
        if rule.id in self._rules:
            raise ValueError(f"duplicate rule id {rule.id!r}")
        self._rules[rule.id] = rule
        try:
            self._check_phases()
        except ValueError:
            del self._rules[rule.id]
            raise

    def ordered(self) -> list[NormalizationRule]:
        return sorted(self._rules.values(), key=lambda r: (r.phase, r.id))

    def effective(self, config: NormalizationConfig) -> list[NormalizationRule]:
        """Rules that will run under ``config`` toggles (FR-11); unknown ids fail loud."""
        unknown = (config.disabled_rules | config.enabled_rules) - self._rules.keys()
        if unknown:
            raise ValueError(f"unknown rule ids in config: {sorted(unknown)}")
        return [
            r
            for r in self.ordered()
            if (r.enabled or r.id in config.enabled_rules) and r.id not in config.disabled_rules
        ]

    def _check_phases(self) -> None:
        canonical = [r for r in self._rules.values() if r.family is RuleFamily.CANONICAL]
        others = [r for r in self._rules.values() if r.family is not RuleFamily.CANONICAL]
        if canonical and others and min(r.phase for r in canonical) <= max(r.phase for r in others):
            raise ValueError("canonical rules must run in a later phase than every other rule")


def ruleset_fingerprint(registry: RuleRegistry) -> str:
    """sha256 over sorted ``(id, version)`` pairs — the engine-side input to ``config_hash`` (D-006, D-028)."""
    pairs = sorted((r.id, r.version) for r in registry.ordered())
    return hashlib.sha256(json.dumps(pairs, separators=(",", ":")).encode("utf-8")).hexdigest()


BUILTIN_RULES = RuleRegistry()


def builtin_ruleset_version() -> str:
    return ruleset_fingerprint(BUILTIN_RULES)


def apply_rules(doc: ParsedDoc, registry: RuleRegistry, config: NormalizationConfig) -> NormalizedDoc:
    """Run the effective rules over a copy of ``doc``'s tree; the input document is untouched."""
    tree = LexborHTMLParser(doc.tree.html or "")
    applications: list[RuleApplication] = []
    for run in _runs(registry.effective(config)):
        if len(run) > 1:
            applications.extend(_apply_attribute_rules(run, tree))
        else:
            applications.extend(_apply(run[0], tree))
    return NormalizedDoc(tree=tree, applied_rules=applications)


def _fusable(rule: NormalizationRule) -> bool:
    """Whether the fused pass can run ``rule``: exactly the rules ``_apply`` hands to
    ``_apply_attributes``."""
    return rule.target in _FUSABLE_TARGETS and rule.action not in (
        Action.CANONICALIZE,
        Action.REPLACE_WITH_PLACEHOLDER,
    )


def _runs(rules: list[NormalizationRule]) -> list[list[NormalizationRule]]:
    """The effective rules, with *consecutive* fusable attribute rules grouped into one run.

    Only neighbours are ever merged, so every rule keeps its ``(phase, id)`` position relative
    to every rule the fused pass cannot run: the TEXT rules, which sit between phase 30 and
    phase 50 in the builtin set, and the node-dropping and canonical transforms, which change
    the tree's shape and must still see it exactly when they did.
    """
    runs: list[list[NormalizationRule]] = []
    for rule in rules:
        if runs and _fusable(rule) and _fusable(runs[-1][-1]):
            runs[-1].append(rule)
        else:
            runs.append([rule])
    return runs


def _apply_attribute_rules(
    rules: list[NormalizationRule], tree: LexborHTMLParser
) -> list[RuleApplication]:
    """Run a run of attribute rules in one traversal, indexed by the names they can touch.

    One pass per rule costs a traversal and an ``_apply_attributes`` call per element per rule,
    and the builtin set spends 20 of them (F-009). Here each element is visited once and is
    offered only the rules that declare an attribute it actually carries. The index can
    over-admit -- an earlier rule in the same run may already have stripped the attribute --
    but it cannot under-admit, because no branch of ``_apply_attributes`` ever introduces an
    attribute name: names only disappear, or keep their value rewritten in place.

    Equivalence with one pass per rule rests on attribute rules being node-local: each touches
    only the node it is handed, never a sibling, an ancestor or the shape of the tree. So per
    element the rules still see each other's work in ``(phase, id)`` order, which is the only
    order in which they can interact. Reporting stays rule-major: each application is collected
    with its rule's position and the document order it was made in, then sorted back.
    """
    if tree.root is None:
        return []
    positions: dict[str, list[int]] = {}
    wildcard: list[int] = []  # a rule naming no attributes is free to touch any of them
    for position, rule in enumerate(rules):
        if rule.attributes:
            for name in rule.attributes:
                positions.setdefault(name, []).append(position)
        else:
            wildcard.append(position)
    collected: list[tuple[int, int, RuleApplication]] = []
    order = 0
    for node in tree.root.traverse():
        names = node.attributes if node.is_element_node else {}
        if not names:
            continue
        candidates = set(wildcard)
        for name in names:
            candidates.update(positions.get(name, ()))
        for position in sorted(candidates):
            for application in _apply_attributes(rules[position], node):
                collected.append((position, order, application))
                order += 1
    collected.sort(key=lambda item: (item[0], item[1]))
    return [application for _, _, application in collected]


def _apply(rule: NormalizationRule, tree: LexborHTMLParser) -> Iterable[RuleApplication]:
    """One rule, one traversal. Runs of attribute rules go through the fused pass instead."""
    if rule.action is Action.CANONICALIZE:
        if rule.transform is None:
            raise ValueError(f"rule {rule.id!r} is CANONICALIZE but has no transform")
        return rule.transform(rule, tree)
    if rule.action is Action.REPLACE_WITH_PLACEHOLDER:
        raise NotImplementedError("REPLACE_WITH_PLACEHOLDER arrives with T-18")
    nodes = list(tree.root.traverse(include_text=True)) if tree.root is not None else []
    if rule.target is Target.TEXT:
        protected = _protected_text_nodes(tree)
        return [
            a
            for node in nodes
            if node.tag == "-text" and node not in protected
            for a in _apply_text(rule, node)
        ]
    if rule.target is Target.NODE:
        return [a for node in nodes if node.is_element_node for a in _apply_node(rule, node)]
    return [a for node in nodes if node.is_element_node for a in _apply_attributes(rule, node)]


def _apply_text(rule: NormalizationRule, node: LexborNode) -> list[RuleApplication]:
    before = node.text_content or ""
    if not rule.matcher.matches(before):
        return []
    after = rule.matcher.sub(before, "")
    locator = Locator.for_node(node)
    node.replace_with(after)
    return [RuleApplication(rule.id, locator, before, after)]


def _protected_text_nodes(tree: LexborHTMLParser) -> set[LexborNode]:
    """D-029: every text node under <script>/<style>/<template>, which TEXT rules must not touch.

    Collected once per pass instead of walking each text node's ancestors: a node is protected
    iff it descends from a protected element, so selecting those elements and taking their text
    descendants decides exactly the same thing, without the per-node climb. Lexbor compares and
    hashes a node by the underlying DOM node rather than by the wrapper, so a node collected
    here is still found when the caller tests the nodes of its own traversal. The set is built
    per pass, never cached across rules, because rules mutate the tree between passes.
    """
    if tree.root is None:
        return set()
    return {
        text
        for element in tree.css(_PROTECTED_TEXT_SELECTOR)
        for text in element.traverse(include_text=True)
        if text.tag == "-text"
    }


def _apply_node(rule: NormalizationRule, node: LexborNode) -> list[RuleApplication]:
    if not rule.matcher.matches(node.tag or ""):
        return []
    before = node.html or ""
    locator = Locator.for_node(node)
    node.decompose()
    return [RuleApplication(rule.id, locator, before, "")]


def _apply_attributes(rule: NormalizationRule, node: LexborNode) -> list[RuleApplication]:
    out: list[RuleApplication] = []
    if rule.where is not None and not rule.where.matches(node):
        return out
    for name, value in sorted(node.attributes.items()):
        if name in PROTECTED_ATTRIBUTES or (rule.attributes and name not in rule.attributes):
            continue
        before = value or ""
        if rule.target is Target.ATTRIBUTE:
            if not rule.matcher.matches(before):
                continue
            locator = Locator.for_node(node)
            del node.attrs[name]
            out.append(RuleApplication(rule.id, locator, before, ""))
        elif rule.target is Target.ATTRIBUTE_SUBSTRING:  # rewrite in place; the attribute stays
            if not rule.matcher.matches(before):
                continue
            after = rule.matcher.sub(before, "")
            if after == before:
                continue
            locator = Locator.for_node(node)
            node.attrs[name] = after
            out.append(RuleApplication(rule.id, locator, before, after))
        else:  # ATTRIBUTE_VALUE: strip matching whitespace-separated tokens
            kept = [t for t in before.split() if not rule.matcher.matches(t)]
            after = " ".join(kept)
            if after == before or len(kept) == len(before.split()):
                continue
            locator = Locator.for_node(node)
            if after:
                node.attrs[name] = after
            else:
                del node.attrs[name]  # STRIP loses attribute presence; T-18's placeholder keeps it
            out.append(RuleApplication(rule.id, locator, before, after))
    return out
