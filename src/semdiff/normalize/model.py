"""L1 rule model (DOMAIN_MODEL §8) — rules are first-class data: toggled, versioned, reported."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from enum import StrEnum
from collections.abc import Callable
from typing import Protocol, runtime_checkable

from selectolax.lexbor import LexborHTMLParser, LexborNode

from semdiff.locator import Locator


class RuleFamily(StrEnum):
    DYNAMIC_CLASS = "dynamic_class"
    HASHED_ID = "hashed_id"
    TOKEN = "token"
    CANONICAL = "canonical"
    TIMESTAMP = "timestamp"


class Target(StrEnum):
    ATTRIBUTE_VALUE = "attribute_value"  # whitespace-separated tokens of an attribute
    ATTRIBUTE = "attribute"  # the whole attribute
    NODE = "node"  # an element, matched by tag name
    TEXT = "text"  # a text node


class Action(StrEnum):
    STRIP = "strip"
    REPLACE_WITH_PLACEHOLDER = "replace_with_placeholder"  # T-18
    DROP_NODE = "drop_node"
    CANONICALIZE = "canonicalize"  # T-17


@runtime_checkable
class Matcher(Protocol):
    def matches(self, value: str) -> bool: ...

    def sub(self, value: str, replacement: str) -> str:
        """Replace every matched span; used for TEXT targets."""
        ...


@dataclass(frozen=True)
class RegexMatcher:
    pattern: str
    _compiled: re.Pattern[str] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_compiled", re.compile(self.pattern))

    def matches(self, value: str) -> bool:
        return self._compiled.search(value) is not None

    def sub(self, value: str, replacement: str) -> str:
        return self._compiled.sub(replacement, value)


_ALNUM_RUN = re.compile(r"[A-Za-z0-9]+")
_DIGIT_THEN_LETTER = re.compile(r"[0-9][A-Za-z]")
_LETTER_THEN_DIGIT = re.compile(r"[A-Za-z][0-9]")


@dataclass(frozen=True)
class EntropyMatcher:
    """Matches values whose longest alphanumeric run looks random (T-14, FR-6).

    Three fences, all required: the run is at least ``min_length`` long, digits and letters
    are interleaved in both directions, and its Shannon entropy is at least ``min_entropy``
    bits. Entropy alone does not separate hashes from words; the fences do.
    """

    min_length: int
    min_entropy: float

    @staticmethod
    def entropy_bits(text: str) -> float:
        counts = Counter(text)
        n = len(text)
        return -sum(c / n * math.log2(c / n) for c in counts.values()) if n else 0.0

    def _segment(self, value: str) -> str | None:
        runs: list[str] = _ALNUM_RUN.findall(value)
        if not runs:
            return None
        run = max(runs, key=len)
        if (
            len(run) < self.min_length
            or not _DIGIT_THEN_LETTER.search(run)
            or not _LETTER_THEN_DIGIT.search(run)
            or self.entropy_bits(run) < self.min_entropy
        ):
            return None
        return run

    def matches(self, value: str) -> bool:
        return self._segment(value) is not None

    def sub(self, value: str, replacement: str) -> str:
        run = self._segment(value)
        return value if run is None else value.replace(run, replacement, 1)


@dataclass(frozen=True)
class NodePredicate:
    """The "tag/attr predicate" matcher kind (DOMAIN_MODEL §8): scopes a rule to certain elements."""

    tag: str | None = None
    attributes: tuple[tuple[str, Matcher], ...] = ()  # every listed attribute must exist and match

    def matches(self, node: LexborNode) -> bool:
        if self.tag is not None and node.tag != self.tag:
            return False
        attrs = node.attributes
        for name, matcher in self.attributes:
            value = attrs.get(name)
            if value is None or not matcher.matches(value):
                return False
        return True


@dataclass(frozen=True)
class NormalizationRule:
    id: str  # permanent: appears in provenance and users pin it
    family: RuleFamily
    target: Target
    matcher: Matcher
    action: Action
    phase: int  # fixed execution order; canonicalization is last
    enabled: bool = True
    version: int = 1  # bump when the rule's behaviour changes (D-028); feeds config_hash
    attributes: frozenset[str] = frozenset()  # ATTRIBUTE/ATTRIBUTE_VALUE targets; empty = any attribute
    where: NodePredicate | None = None  # element scope for attribute targets; None = any element
    # CANONICALIZE rules are whole-tree transforms: (rule, tree) -> applications. Unused otherwise.
    transform: Callable[[NormalizationRule, LexborHTMLParser], list[RuleApplication]] | None = None


@dataclass(frozen=True)
class RuleApplication:
    rule_id: str
    locator: Locator
    before: str
    after: str


@dataclass(frozen=True)
class NormalizedDoc:
    """DOMAIN_MODEL §2: ``(tree, applied_rules)``."""

    tree: LexborHTMLParser
    applied_rules: list[RuleApplication]
