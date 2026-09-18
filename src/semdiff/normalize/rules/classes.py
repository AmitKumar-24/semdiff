"""Dynamic-class rule family (T-13, FR-5): CSS-in-JS and CSS-modules hashes in ``class``.

Each rule targets one generator so it can be toggled and reported on its own. Every rule
strips matching whitespace-separated tokens from ``class`` only; static tokens keep their
order. Patterns are calibrated on the T-04 captures (MUI, Ant Design, Docusaurus).
"""

from __future__ import annotations

from semdiff.normalize.model import Action, NormalizationRule, RegexMatcher, RuleFamily, Target

PHASE_DYNAMIC_CLASS = 10

# A CSS-modules suffix is "hash-like" when it has a digit or mixed case; plain words like
# nav_item stay. (?=...) lookaheads keep the whole thing one declarative regex.
_HASHLIKE_SUFFIX = r"(?=[A-Za-z0-9]{4,8}$)(?=.*\d|.*[a-z].*[A-Z]|.*[A-Z].*[a-z])[A-Za-z0-9]+"


def _rule(rule_id: str, pattern: str) -> NormalizationRule:
    return NormalizationRule(
        id=rule_id,
        family=RuleFamily.DYNAMIC_CLASS,
        target=Target.ATTRIBUTE_VALUE,
        matcher=RegexMatcher(pattern),
        action=Action.STRIP,
        phase=PHASE_DYNAMIC_CLASS,
        attributes=frozenset({"class"}),
    )


CLASS_RULES: tuple[NormalizationRule, ...] = (
    # Emotion / MUI: css-<base36 hash>; real hashes are 5+ chars. Dev-only "-label" suffixes are
    # not supported. Known ambiguity: a static "css-loader"-style name is indistinguishable.
    _rule("class.emotion", r"^css-[a-z0-9]{5,}$"),
    # antd-style (Ant Design 5): acss-<hash>
    _rule("class.antd_style", r"^acss-[a-z0-9]{5,}$"),
    # styled-components component ids: sc-<id>[-n]
    _rule("class.styled_components.component", r"^sc-[A-Za-z0-9-]{5,}$"),
    # styled-components generated class: 6 letters, lowercase start, at least two capitals.
    # The one heuristic in the family; disable it if a site uses 6-letter camelCase names.
    _rule("class.styled_components.generated", r"^(?=(?:[a-z]*[A-Z]){2})[a-z][A-Za-z]{5}$"),
    # CSS Modules: <local>_<hash> (Docusaurus, webpack), <file>_<local>__<hash> (Next.js)
    _rule("class.css_modules", r"^[A-Za-z][A-Za-z0-9-]*(?:_[A-Za-z0-9-]+)*?_{1,2}" + _HASHLIKE_SUFFIX + "$"),
    # vanilla-extract / Linaria / Stitches: _<hash>
    _rule("class.leading_underscore_hash", r"^_[A-Za-z0-9]{5,}$"),
)
