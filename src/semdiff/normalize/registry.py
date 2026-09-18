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
    for rule in registry.effective(config):
        applications.extend(_apply(rule, tree))
    return NormalizedDoc(tree=tree, applied_rules=applications)


def _apply(rule: NormalizationRule, tree: LexborHTMLParser) -> Iterable[RuleApplication]:
    if rule.action is Action.CANONICALIZE:
        if rule.transform is None:
            raise ValueError(f"rule {rule.id!r} is CANONICALIZE but has no transform")
        return rule.transform(rule, tree)
    if rule.action is Action.REPLACE_WITH_PLACEHOLDER:
        raise NotImplementedError("REPLACE_WITH_PLACEHOLDER arrives with T-18")
    nodes = list(tree.root.traverse(include_text=True)) if tree.root is not None else []
    if rule.target is Target.TEXT:
        return [a for node in nodes if node.tag == "-text" for a in _apply_text(rule, node)]
    if rule.target is Target.NODE:
        return [a for node in nodes if node.is_element_node for a in _apply_node(rule, node)]
    return [a for node in nodes if node.is_element_node for a in _apply_attributes(rule, node)]


def _apply_text(rule: NormalizationRule, node: LexborNode) -> list[RuleApplication]:
    if _inside_protected(node):
        return []
    before = node.text_content or ""
    if not rule.matcher.matches(before):
        return []
    after = rule.matcher.sub(before, "")
    locator = Locator.for_node(node)
    node.replace_with(after)
    return [RuleApplication(rule.id, locator, before, after)]


def _inside_protected(node: LexborNode) -> bool:
    """D-029: a text node anywhere under <script>/<style>/<template> is off limits."""
    ancestor = node.parent
    while ancestor is not None:
        if ancestor.tag in PROTECTED_TEXT_PARENTS:
            return True
        ancestor = ancestor.parent
    return False


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
