"""T-16: timestamp rule family (FR-9) — ISO-8601 datetimes and relative-date phrasing, text only."""

from __future__ import annotations

import re

import pytest

from semdiff import NormalizationConfig, parse
from semdiff.normalize import BUILTIN_RULES, RuleFamily, Target, apply_rules
from semdiff.normalize.rules.timestamps import TIMESTAMP_RULES

BY_ID = {rule.id: rule for rule in TIMESTAMP_RULES}
# These tests inspect the serialized text as the timestamp family leaves it, before the
# canonicalization phase (T-17) collapses the surrounding whitespace.
NO_CANONICAL = NormalizationConfig(
    disabled_rules=frozenset(r.id for r in BUILTIN_RULES.ordered() if r.id.startswith("canonical."))
)


def normalize_text(html: str) -> tuple[str, list[tuple[str, str, str]]]:
    result = apply_rules(parse(html.encode()), BUILTIN_RULES, NO_CANONICAL)
    fired = [(a.rule_id, a.before, a.after) for a in result.applied_rules if a.rule_id.startswith("timestamp.")]
    return result.tree.html or "", fired


# (text, rule id, remaining text after the strip)
POSITIVE = [
    ("Generated 2026-09-17T10:42:07Z by the build", "timestamp.iso8601", "Generated  by the build"),
    ("at 2026-09-17T10:42:07.123+05:30", "timestamp.iso8601", "at "),
    ("at 2026-09-17T10:42:07-0700", "timestamp.iso8601", "at "),
    ("at 2026-09-17T10:42", "timestamp.iso8601", "at "),
    ("Built 2026-09-17 10:42:07 UTC", "timestamp.iso8601", "Built  UTC"),
    ("Last updated 3 minutes ago", "timestamp.relative_ago", "Last updated "),
    ("an hour ago", "timestamp.relative_ago", ""),
    ("2 days ago", "timestamp.relative_ago", ""),
    ("a few seconds ago", "timestamp.relative_ago", ""),
    ("10 years ago", "timestamp.relative_ago", ""),
    ("Edited 5 mins ago.", "timestamp.relative_ago", "Edited ."),
    ("just now", "timestamp.relative_phrase", ""),
    ("Saved moments ago", "timestamp.relative_phrase", "Saved "),
    ("Updated yesterday", "timestamp.relative_phrase", ""),
    ("Last updated today", "timestamp.relative_phrase", ""),
    ("Page last checked this morning", "timestamp.relative_phrase", "Page "),
    ("posted YESTERDAY", "timestamp.relative_phrase", ""),
]

# Legitimate content: no timestamp rule may fire.
NEGATIVE = [
    "Published 2026-09-17",  # date only
    "September 17, 2026",
    "17/09/2026",
    "Copyright 2026",
    "Version 2.4.1 released",
    "ISBN 978-3-16-148410-0",
    "Opens at 10:42",  # bare time
    "Meeting 10:42-11:30",
    "Today's deals",
    "Yesterday",
    "See you tomorrow",
    "3 minutes",  # no "ago"
    "in 5 minutes",
    "ago",
    "Agony and ecstasy",
    "Long ago, in a galaxy far away",  # not a quantity + unit
    "Once a day",
    "2 days",
    "2026-09-17T",  # truncated ISO, no time
    "Updated on 2026-09-17",
]


@pytest.mark.parametrize(("text", "rule_id", "remaining"), POSITIVE, ids=[p[0][:22] for p in POSITIVE])
def test_timestamps_are_neutralized_in_place(text: str, rule_id: str, remaining: str) -> None:
    html, fired = normalize_text(f"<p>{text}</p>")
    assert fired == [(rule_id, text, remaining)]
    assert re.search(r"<p>(.*?)</p>", html, re.S).group(1) == remaining  # type: ignore[union-attr]


@pytest.mark.parametrize("text", NEGATIVE)
def test_legitimate_dates_are_preserved(text: str) -> None:
    html, fired = normalize_text(f"<p>{text}</p>")
    assert fired == []
    assert text in html


def test_multiple_matches_in_one_text_node_yield_one_application() -> None:
    _, fired = normalize_text("<p>from 2026-09-17T10:00:00Z to 2026-09-17T11:00:00Z</p>")
    assert fired == [("timestamp.iso8601", "from 2026-09-17T10:00:00Z to 2026-09-17T11:00:00Z", "from  to ")]


def test_attributes_are_not_this_familys_business() -> None:
    html, fired = normalize_text(
        '<time datetime="2026-09-17T10:42:07Z">3 minutes ago</time><meta content="2026-09-17T10:42:07Z">'
    )
    assert fired == [("timestamp.relative_ago", "3 minutes ago", "")]
    assert 'datetime="2026-09-17T10:42:07Z"' in html
    assert 'content="2026-09-17T10:42:07Z"' in html


def test_script_style_template_content_is_protected() -> None:
    html, fired = normalize_text(
        '<script type="application/ld+json">{"dateModified":"2026-09-17T10:42:07Z"}</script>'
        "<style>/* 3 minutes ago 2026-09-17T10:42:07Z */</style>"
        "<template><div><p>Updated yesterday 2026-09-17T10:42:07Z</p></div></template>"
        "<p>2 days ago</p>"
    )
    assert fired == [("timestamp.relative_ago", "2 days ago", "")]
    assert '{"dateModified":"2026-09-17T10:42:07Z"}' in html
    assert "/* 3 minutes ago 2026-09-17T10:42:07Z */" in html
    assert "Updated yesterday 2026-09-17T10:42:07Z" in html


def test_family_is_registered_with_stable_ids_and_phase() -> None:
    ids = [rule.id for rule in BUILTIN_RULES.ordered() if rule.family is RuleFamily.TIMESTAMP]
    assert ids == sorted(BY_ID) == ["timestamp.iso8601", "timestamp.relative_ago", "timestamp.relative_phrase"]
    assert {rule.phase for rule in TIMESTAMP_RULES} == {40}
    assert all(rule.target is Target.TEXT for rule in TIMESTAMP_RULES)


@pytest.mark.parametrize("rule_id", sorted(BY_ID))
def test_each_rule_is_individually_toggleable(rule_id: str) -> None:
    text = next(p for p in POSITIVE if p[1] == rule_id)[0]
    off = NormalizationConfig(disabled_rules=NO_CANONICAL.disabled_rules | {rule_id})
    kept = apply_rules(parse(f"<p>{text}</p>".encode()), BUILTIN_RULES, off)
    assert text in (kept.tree.html or "")


def test_provenance_determinism_and_input_untouched() -> None:
    doc = parse(b"<div><span>x</span><p>Updated 3 minutes ago at 2026-09-17T10:42:07Z</p></div>")
    before = doc.tree.html
    first = apply_rules(doc, BUILTIN_RULES, NO_CANONICAL)
    second = apply_rules(doc, BUILTIN_RULES, NO_CANONICAL)
    assert doc.tree.html == before
    assert first.tree.html == second.tree.html
    fired = [a for a in first.applied_rules if a.rule_id.startswith("timestamp.")]
    assert [(a.rule_id, a.before, a.after) for a in fired] == [
        ("timestamp.iso8601", "Updated 3 minutes ago at 2026-09-17T10:42:07Z", "Updated 3 minutes ago at "),
        ("timestamp.relative_ago", "Updated 3 minutes ago at ", "Updated  at "),
    ]
    assert all((a.locator.css or "").endswith("> div > p:nth-child(2)") for a in fired)
    assert all(re.fullmatch(r"[0-9a-f]{64}", a.locator.node_hash) for a in fired)
    assert first.tree.css_first("p").text() == "Updated  at "
