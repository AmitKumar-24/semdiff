"""The pre-fusion engine — one traversal per rule — kept as the equivalence reference.

This is the body ``apply_rules`` had before runs of attribute rules were fused into a single
name-indexed pass. It reuses the production ``_apply`` deliberately: what differs between the
two engines is then only the grouping and the order applications are collected in, which is
exactly what the equivalence tests exist to pin.
"""

from __future__ import annotations

from selectolax.lexbor import LexborHTMLParser

from semdiff.config import NormalizationConfig
from semdiff.locator import Locator
from semdiff.normalize.model import NormalizedDoc, RuleApplication
from semdiff.normalize.registry import RuleRegistry, _apply
from semdiff.parse import ParsedDoc


def apply_rules_per_rule(
    doc: ParsedDoc, registry: RuleRegistry, config: NormalizationConfig
) -> NormalizedDoc:
    tree = LexborHTMLParser(doc.tree.html or "")
    applications: list[RuleApplication] = []
    for rule in registry.effective(config):
        applications.extend(_apply(rule, tree))
    return NormalizedDoc(tree=tree, applied_rules=applications)


def records(result: NormalizedDoc) -> list[tuple[str, str, str, Locator]]:
    """Everything an application reports — the provenance a caller can see, locator included."""
    return [(a.rule_id, a.before, a.after, a.locator) for a in result.applied_rules]
