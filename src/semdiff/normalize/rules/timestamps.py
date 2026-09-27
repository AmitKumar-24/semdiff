"""Timestamp rule family (T-16, FR-9): ISO-8601 datetimes and relative-date phrasing, in text.

Text-only and English-only. Only values that drift with the clock are neutralized: an ISO
datetime must carry a time component (date-only values are content), and "today" /
"yesterday" count only after an update-style verb. Attributes such as <time datetime> are
out of scope here. Matched spans are removed in place; the rest of the text node stays.
"""

from __future__ import annotations

from semdiff.normalize.model import Action, NormalizationRule, RegexMatcher, RuleFamily, Target

PHASE_TIMESTAMP = 40

_QUANTITY = r"(?:\d{1,4}|an?|one|two|three|four|five|six|seven|eight|nine|ten|a few|few|several|many)"
_UNIT = r"(?:seconds?|secs?|minutes?|mins?|hours?|hrs?|days?|weeks?|months?|years?|yrs?)"
_UPDATE_VERB = r"(?:last\s+)?(?:updated|modified|edited|posted|published|refreshed|generated|checked|synced|seen)"
_RELATIVE_DAY = r"(?:yesterday|today|tonight|this\s+(?:morning|afternoon|evening|week|month))"
# F-008: "Sep 25, 2026 (15:12 UTC)" — Sphinx's "last updated" footer and its relatives.
# The parenthesised clock time and the zone are both mandatory: they are what separates a
# build stamp from a prose date, which is content ("September 3, 2026", "Released Jan 2026").
_MONTH = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?"
    r"|Aug(?:ust)?|Sep(?:t|tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?"
)
_ZONE = r"(?:UTC|GMT|Z|[+-]\d{2}:?\d{2})"
_CLOCK = rf"\(\d{{1,2}}:\d{{2}}(?::\d{{2}})?\s+{_ZONE}\)"


def _rule(rule_id: str, pattern: str) -> NormalizationRule:
    return NormalizationRule(
        id=rule_id,
        family=RuleFamily.TIMESTAMP,
        target=Target.TEXT,
        matcher=RegexMatcher(pattern),
        action=Action.STRIP,
        phase=PHASE_TIMESTAMP,
    )


TIMESTAMP_RULES: tuple[NormalizationRule, ...] = (
    # 2026-09-17T10:42[:07[.123]][Z|+05:30|-0700]; "T" or a single space; the time part is mandatory.
    _rule("timestamp.iso8601", r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?"),
    # "3 minutes ago", "an hour ago", "a few seconds ago"
    _rule("timestamp.relative_ago", rf"(?i)\b{_QUANTITY}\s+{_UNIT}\s+ago\b"),
    # "Sep 25, 2026 (15:12 UTC)" / "September 3, 2026 (09:05 UTC)" (F-008)
    _rule("timestamp.human_datetime", rf"\b{_MONTH}\s+\d{{1,2}},?\s+\d{{4}}\s+{_CLOCK}"),
    # "just now", "moments ago", "updated yesterday", "last checked this morning"
    _rule("timestamp.relative_phrase", rf"(?i)\b(?:just now|moments ago|a moment ago|{_UPDATE_VERB}\s+{_RELATIVE_DAY})\b"),
)
