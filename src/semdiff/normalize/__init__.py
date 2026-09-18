"""L1 — normalization: rule model, phase-ordered registry (T-12) and built-in families (T-13+)."""

from semdiff.normalize.model import (
    Action,
    EntropyMatcher,
    Matcher,
    NodePredicate,
    NormalizationRule,
    NormalizedDoc,
    RegexMatcher,
    RuleApplication,
    RuleFamily,
    Target,
)
from semdiff.normalize.registry import BUILTIN_RULES, RuleRegistry, apply_rules

import semdiff.normalize.rules  # noqa: E402, F401  (registers the built-in families; must stay last)

__all__ = [
    "BUILTIN_RULES",
    "Action",
    "EntropyMatcher",
    "Matcher",
    "NodePredicate",
    "NormalizationRule",
    "NormalizedDoc",
    "RegexMatcher",
    "RuleApplication",
    "RuleFamily",
    "RuleRegistry",
    "Target",
    "apply_rules",
]
