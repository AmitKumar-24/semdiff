"""Hashed-ID rule family (T-14, FR-6): pattern rules plus a conservative entropy rule on ``id``.

Every rule removes the whole ``id`` attribute (STRIP). Thresholds were calibrated on the
T-04 captures and a survey of semantic ids; see tests/normalize/test_ids.py for the record.
"""

from __future__ import annotations

from semdiff.normalize.model import (
    Action,
    EntropyMatcher,
    Matcher,
    NormalizationRule,
    RegexMatcher,
    RuleFamily,
    Target,
)

PHASE_HASHED_ID = 20
ENTROPY_MIN_LENGTH = 16  # below this, random base36 runs sit at ~3.1-3.3 bits, level with words
ENTROPY_MIN_BITS = 3.5  # 16+ char random hex/base36 runs score 3.5-4.0; mixed words stay under


def _rule(rule_id: str, matcher: Matcher) -> NormalizationRule:
    return NormalizationRule(
        id=rule_id,
        family=RuleFamily.HASHED_ID,
        target=Target.ATTRIBUTE,
        matcher=matcher,
        action=Action.STRIP,
        phase=PHASE_HASHED_ID,
        attributes=frozenset({"id"}),
    )


ID_RULES: tuple[NormalizationRule, ...] = (
    # <name>-<hex hash>: the FR-6 example react-root-7a3b2c. The hash segment must contain both a
    # digit and a letter, so product-123456 and item-decade are untouched.
    _rule("id.hex_suffix", RegexMatcher(r"^[A-Za-z][A-Za-z0-9_-]*[-_](?=[0-9a-f]*[0-9])(?=[0-9a-f]*[a-f])[0-9a-f]{6,}$")),
    # React useId: _R_…_ / _r_…_ (React 19) and :R…: / :r…: (React 18), with any prefix (radix-:R…:).
    _rule("id.react_use_id", RegexMatcher(r"(?:_[Rr]_[a-z0-9]*_|:[Rr][a-z0-9]*:)$")),
    # Catch-all for long random tokens (UUID hex, session/CSRF-shaped ids).
    _rule("id.entropy", EntropyMatcher(min_length=ENTROPY_MIN_LENGTH, min_entropy=ENTROPY_MIN_BITS)),
)
