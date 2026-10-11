"""Hashed-ID rule family (T-14, FR-6): pattern rules plus a conservative entropy rule.

Every rule replaces the hashed part of the value with ``PLACEHOLDER`` and keeps the attribute
(T-18, D-043) instead of removing it, so ``id="react-root-7a3b2c"`` becomes
``id="react-root-__semdiff__"``. Two things follow. The structural fact that the element carried
an id survives, so a page that stops emitting one is still a difference rather than something
normalization erased. And the reference survives with it (F-006): the same rules run over the
attributes that point at an id, rewriting ``for="react-root-7a3b2c"`` to the same text, so the
pair still resolves — no document-wide mapping, no state, nothing position-dependent.

The matchers' verdicts are unchanged by T-18; only what replaces the match changed. Thresholds
were calibrated on the T-04 captures and a survey of semantic ids, and
tests/normalize/test_ids.py keeps that record.
"""

from __future__ import annotations

from semdiff.normalize.model import (
    Action,
    EntropyMatcher,
    GroupMatcher,
    Matcher,
    NormalizationRule,
    RuleFamily,
    Target,
)

PHASE_HASHED_ID = 20
ENTROPY_MIN_LENGTH = 16  # below this, random base36 runs sit at ~3.1-3.3 bits, level with words
ENTROPY_MIN_BITS = 3.5  # 16+ char random hex/base36 runs score 3.5-4.0; mixed words stay under

# Attributes whose value is an id, or a whitespace-separated list of ids (HTML and ARIA).
ID_REFERENCE_ATTRIBUTES = frozenset(
    {
        "aria-activedescendant", "aria-controls", "aria-describedby", "aria-details",
        "aria-errormessage", "aria-flowto", "aria-labelledby", "aria-owns",
        "for", "form", "headers", "list",
    }
)

# ``href`` joins those for fragment links, and the *pattern* enforces that, not the attribute
# list: a match may begin at the start of the value, after whitespace (one entry of an id list)
# or after a ``#`` — never after a ``/`` or a ``.``. That fence is what keeps an id rule out of
# ``/assets/main-1a2b3c.js``, which is FR-44's hash and must not be touched here.
_START = r"(?:^|(?<=[\s#]))"
_END = r"(?=$|\s)"
PATTERN_ATTRIBUTES = ID_REFERENCE_ATTRIBUTES | {"id", "href"}
# The entropy matcher works on the longest alphanumeric run of the whole value and cannot be
# fenced to a fragment, so it stays off ``href`` entirely (F-029).
ENTROPY_ATTRIBUTES = ID_REFERENCE_ATTRIBUTES | {"id"}


def _rule(rule_id: str, matcher: Matcher, attributes: frozenset[str]) -> NormalizationRule:
    return NormalizationRule(
        id=rule_id,
        family=RuleFamily.HASHED_ID,
        target=Target.ATTRIBUTE_SUBSTRING,  # the matched span goes; the attribute stays
        matcher=matcher,
        action=Action.REPLACE_WITH_PLACEHOLDER,
        phase=PHASE_HASHED_ID,
        version=2,  # v2: placeholder instead of STRIP, and id references too (T-18)
        attributes=attributes,
    )


ID_RULES: tuple[NormalizationRule, ...] = (
    # <name>-<hex hash>: the FR-6 example react-root-7a3b2c. The hash segment must contain both a
    # digit and a letter, so product-123456 and item-decade are untouched. The prefix sits outside
    # the (?P<hash>) group and survives, which is what keeps tab-__semdiff__ and panel-__semdiff__
    # distinguishable — a reference to one cannot resolve to the other.
    _rule(
        "id.hex_suffix",
        GroupMatcher(
            _START + r"[A-Za-z][A-Za-z0-9_-]*[-_]"
            r"(?P<hash>(?=[0-9a-f]*[0-9])(?=[0-9a-f]*[a-f])[0-9a-f]{6,})" + _END
        ),
        PATTERN_ATTRIBUTES,
    ),
    # React useId: _R_…_ / _r_…_ (React 19) and :R…: / :r…: (React 18), with any prefix
    # (radix-:R…:). The prefix is lazy and excludes / and ., so a path segment cannot be walked
    # into from the start of an href.
    _rule(
        "id.react_use_id",
        GroupMatcher(_START + r"[A-Za-z0-9_:-]*?(?P<hash>_[Rr]_[a-z0-9]*_|:[Rr][a-z0-9]*:)" + _END),
        PATTERN_ATTRIBUTES,
    ),
    # Catch-all for long random tokens (UUID hex, session/CSRF-shaped ids). ``EntropyMatcher.sub``
    # replaces the random run alone, so gen-oo3sb09glshv616m keeps its gen- prefix.
    _rule(
        "id.entropy",
        EntropyMatcher(min_length=ENTROPY_MIN_LENGTH, min_entropy=ENTROPY_MIN_BITS),
        ENTROPY_ATTRIBUTES,
    ),
)
