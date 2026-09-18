"""Token rule family (T-15, FR-7): nonces, CSRF tokens, session-shaped values — structure intact.

Every rule removes one attribute (the token) and leaves the element, its tag and its other
attributes in place, so a CSRF field is still visibly a CSRF field after normalization.
"""

from __future__ import annotations

from semdiff.normalize.model import (
    Action,
    EntropyMatcher,
    Matcher,
    NodePredicate,
    NormalizationRule,
    RegexMatcher,
    RuleFamily,
    Target,
)

PHASE_TOKEN = 30
SESSION_MIN_LENGTH = 24  # catches hex UUIDs and JWT segments (27); a dashed UUID's longest run is 12
SESSION_MIN_BITS = 3.5

_HIDDEN_INPUT = NodePredicate(tag="input", attributes=(("type", RegexMatcher(r"(?i)^hidden$")),))
_CSRF_NAME = RegexMatcher(
    r"(?i)^(?:[_-]?(?:csrf|xsrf)(?:[_-]?token)?|_?token|authenticity_token|csrfmiddlewaretoken"
    r"|__requestverificationtoken|__?antiforgery.*|__viewstate|__viewstategenerator|__eventvalidation)$"
)
_TOKEN_CHARSET_16 = RegexMatcher(r"^[A-Za-z0-9+/=._-]{16,}$")

# Attribute names that denote a token. Exact names only (optionally data- prefixed, optionally
# suffixed -token/-id/-value), so data-token-count and data-session-name are never touched.
_TOKEN_BASES = ("csrf", "xsrf", "nonce", "token", "session", "sessid", "sessionid",
                "request-id", "requestid", "trace-id", "traceid", "correlation-id", "correlationid")
TOKEN_ATTRIBUTE_NAMES = frozenset(
    f"{prefix}{base}{suffix}"
    for prefix in ("", "data-")
    for base in _TOKEN_BASES
    for suffix in ("", "-token", "-id", "-value", "_token")
) - {"nonce"}  # nonce itself belongs to token.nonce


def _rule(
    rule_id: str, attributes: frozenset[str], matcher: Matcher, where: NodePredicate | None = None
) -> NormalizationRule:
    return NormalizationRule(
        id=rule_id,
        family=RuleFamily.TOKEN,
        target=Target.ATTRIBUTE,
        matcher=matcher,
        action=Action.STRIP,
        phase=PHASE_TOKEN,
        attributes=attributes,
        where=where,
    )


TOKEN_RULES: tuple[NormalizationRule, ...] = (
    # CSP nonces are random by definition; 8+ chars of base64-ish so an empty/placeholder value stays.
    _rule("token.nonce", frozenset({"nonce"}), RegexMatcher(r"^[A-Za-z0-9+/=_-]{8,}$")),
    # <input type=hidden name=<csrf-ish>> → value dropped, field kept.
    _rule("token.csrf_input", frozenset({"value"}), RegexMatcher(r"."), where=NodePredicate(tag="input", attributes=(
        ("type", RegexMatcher(r"(?i)^hidden$")), ("name", _CSRF_NAME)))),
    # <meta name="csrf-token" content=…> (Rails and friends). "csrf-param" names a field, not a token.
    _rule("token.csrf_meta", frozenset({"content"}), RegexMatcher(r"."), where=NodePredicate(tag="meta", attributes=(
        ("name", RegexMatcher(r"(?i)^(?:x-)?(?:csrf|xsrf)[-_]?token$|^_?csrf$")),))),
    # Any hidden input whose value is a long random run (hex UUID, JWT, signed state).
    _rule("token.session_input", frozenset({"value"}), EntropyMatcher(min_length=SESSION_MIN_LENGTH, min_entropy=SESSION_MIN_BITS),
          where=_HIDDEN_INPUT),
    # Attributes *named* like tokens (data-csrf, data-request-id, token, …) holding 16+ token chars.
    _rule("token.named_attr", TOKEN_ATTRIBUTE_NAMES, _TOKEN_CHARSET_16),
)
