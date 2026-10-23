"""T-28: the README's documented-limitations section (NFR-11).

NFR-11 exists because the libraries this project is measured against lost credibility to
undocumented failure modes. So the section is gated the way a rule family is: each limitation
is a row in the catalogue below, every row names the words its bullet must contain, and the
evidence it cites must resolve to a real finding or decision. A bullet that is deleted,
hollowed out or quietly softened fails a test here.

The catalogue checks *content*, not the presence of an id: ``anchor`` only locates the bullet,
and ``must_say`` is what the bullet has to state. Three tests go further and compare the
documented claim against live behaviour or live data, so the prose cannot drift away from the
engine while still reading as true.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pytest

import semdiff
from semdiff.config import Config, ParserBackend
from tests.corpus.loader import load_pairs

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
FINDINGS = ROOT / "FINDINGS.md"
DECISIONS = ROOT / "docs" / "DECISIONS.md"

HEADING = "## Limitations"
GROUPS = (
    "Not implemented",
    "What normalization cannot reach",
    "Accepted recall costs",
    "Where the evidence is thin",
)
# Findings and decisions are three-digit (``F-022``, ``D-046``); open questions are two-digit
# (``Q-26``). A ``\d{3}`` pattern reads as the obvious one and silently drops every Q.
EVIDENCE_ID = re.compile(r"\b([FDQ]-\d{2,3})\b")
TABLE_ROW_ID = re.compile(r"^\|\s*([FDQ]-\d{2,3})\s*\|", re.M)


@dataclass(frozen=True)
class Limitation:
    """One bullet the section must carry, and what it must say."""

    key: str
    group: str
    anchor: str  # locates the bullet; must match exactly one
    must_say: tuple[str, ...]  # the claim itself, not merely its citation
    evidence: tuple[str, ...] = ()  # finding/decision ids the bullet must cite


CATALOGUE: tuple[Limitation, ...] = (
    Limitation(
        key="lxml_backend",
        group="Not implemented",
        anchor='parser="lxml"',
        must_say=("NotImplementedError", "selectolax", "T-11", "deferred"),
        evidence=("D-048",),
    ),
    Limitation(
        key="user_rules",
        group="Not implemented",
        anchor="extensible",
        must_say=("toggle", "config"),
    ),
    Limitation(
        key="rules_fired",
        group="Not implemented",
        anchor="--report",
        must_say=("apply_rules", "normalize()"),
    ),
    Limitation(
        key="performance",
        group="Not implemented",
        anchor="100 ms",
        must_say=("373 ms", "docs/BASELINE.md"),
    ),
    Limitation(
        key="attribute_names",
        group="What normalization cannot reach",
        anchor="attribute names",
        must_say=("data-v-", "value"),
        evidence=("F-022",),
    ),
    Limitation(
        key="protected_carriers",
        group="What normalization cannot reach",
        anchor="Server Component",
        must_say=("<script>", "<style>"),
        evidence=("D-029", "F-015"),
    ),
    Limitation(
        key="html_template",
        group="What normalization cannot reach",
        anchor="<template>",
        must_say=("selectolax",),
        evidence=("F-031",),
    ),
    Limitation(
        key="build_identity",
        group="What normalization cannot reach",
        anchor="build-identity",
        must_say=("build-time", "build-hash"),
        evidence=("Q-26", "F-014"),
    ),
    Limitation(
        key="human_datetime",
        group="What normalization cannot reach",
        anchor="parenthesised",
        must_say=("Sep 25, 2026 (15:12 UTC)",),
        evidence=("F-020",),
    ),
    Limitation(
        key="placeholder_collision",
        group="Accepted recall costs",
        anchor="stable prefix",
        must_say=("__semdiff__",),
        evidence=("F-029",),
    ),
    Limitation(
        key="entropy_href",
        group="Accepted recall costs",
        anchor="id.entropy",
        must_say=("fragment", "for="),
        evidence=("F-029",),
    ),
    Limitation(
        key="hidden_input",
        group="Accepted recall costs",
        anchor="token.session_input",
        must_say=("hidden", "disable"),
        evidence=("F-007",),
    ),
    Limitation(
        key="corpus_coverage",
        group="Where the evidence is thin",
        anchor="asset_hash",
        must_say=("timestamp", "unit tests"),
        evidence=("F-019", "F-023", "F-026"),
    ),
    Limitation(
        key="synthetic_recall",
        group="Where the evidence is thin",
        anchor="synthetic",
        must_say=("mutation", "captured"),
        evidence=("D-045",),
    ),
    Limitation(
        key="parser_build",
        group="Where the evidence is thin",
        anchor="node_hash",
        must_say=("foreign content", "parser build"),
        evidence=("D-046",),
    ),
)


def _readme() -> str:
    return README.read_text(encoding="utf-8")


def _section() -> str:
    """The Limitations section, up to the next top-level heading."""
    text = _readme()
    start = text.find(f"\n{HEADING}\n")
    assert start != -1, f"README has no {HEADING!r} section (NFR-11)"
    end = text.find("\n## ", start + 1)
    return text[start : end if end != -1 else len(text)]


def _bullets() -> list[tuple[str, str]]:
    """``(group heading, bullet text)`` for every bullet, continuation lines folded in."""
    out: list[tuple[str, str]] = []
    group = ""
    buffer: list[str] = []
    buffer_group = ""

    def flush() -> None:
        nonlocal buffer
        if buffer:
            out.append((buffer_group, " ".join(buffer)))
            buffer = []

    for line in _section().splitlines():
        if line.startswith("### "):
            flush()
            group = line[4:].strip()
        elif line.startswith("- "):
            flush()
            buffer = [line[2:].strip()]
            buffer_group = group
        elif line.strip():
            if buffer:
                buffer.append(line.strip())
        else:
            flush()
    flush()
    return out


def _bullet_for(limitation: Limitation) -> str:
    matches = [text for _, text in _bullets() if limitation.anchor in text]
    assert matches, f"no bullet mentions {limitation.anchor!r} ({limitation.key})"
    assert len(matches) == 1, f"{limitation.anchor!r} is ambiguous: {len(matches)} bullets"
    return matches[0]


def _row_ids(path: Path) -> set[str]:
    """Ids of the table rows in a document: ``| F-022 | …`` gives ``F-022``."""
    return set(TABLE_ROW_ID.findall(path.read_text(encoding="utf-8")))


# ---- placement and shape -------------------------------------------------------------------
def test_the_section_sits_between_guarantees_and_install() -> None:
    """Where a reader meets the caveats matters: straight after the promises and before the
    install instructions, not appended below the fold."""
    text = _readme()
    guarantees = text.find("### Guarantees")
    limitations = text.find(f"\n{HEADING}\n")
    install = text.find("\n## Install\n")
    assert -1 < guarantees < limitations < install


def test_the_four_kinds_of_limitation_are_distinguished() -> None:
    """Unsupported behaviour, a structural blind spot, a cost accepted on purpose and a gap in
    the evidence are four different things to someone evaluating this; they are not pooled."""
    section = _section()
    positions = [section.find(f"### {group}") for group in GROUPS]
    assert all(position != -1 for position in positions), dict(zip(GROUPS, positions))
    assert positions == sorted(positions)


def test_every_catalogued_group_is_a_real_heading() -> None:
    assert {limitation.group for limitation in CATALOGUE} == set(GROUPS)


# ---- the content of each limitation --------------------------------------------------------
@pytest.mark.parametrize("limitation", CATALOGUE, ids=lambda item: item.key)
def test_the_limitation_is_documented_with_its_substance(limitation: Limitation) -> None:
    """Not that the bullet exists — that it still says the thing that makes it a limitation."""
    bullet = _bullet_for(limitation)
    missing = [phrase for phrase in limitation.must_say if phrase not in bullet]
    assert not missing, f"{limitation.key}: bullet does not say {missing}"


@pytest.mark.parametrize("limitation", CATALOGUE, ids=lambda item: item.key)
def test_the_limitation_sits_under_the_right_heading(limitation: Limitation) -> None:
    bullet = _bullet_for(limitation)
    group = next(group for group, text in _bullets() if text == bullet)
    assert group == limitation.group


@pytest.mark.parametrize("limitation", CATALOGUE, ids=lambda item: item.key)
def test_the_limitation_cites_its_evidence(limitation: Limitation) -> None:
    bullet = _bullet_for(limitation)
    missing = [identifier for identifier in limitation.evidence if identifier not in bullet]
    assert not missing, f"{limitation.key}: bullet does not cite {missing}"


# ---- the evidence is real --------------------------------------------------------------------
def test_every_cited_id_resolves_to_a_finding_or_a_decision() -> None:
    """A citation nobody can follow is worse than none: it reads as evidence and is not."""
    known = _row_ids(FINDINGS) | _row_ids(DECISIONS)
    cited = set(EVIDENCE_ID.findall(_section()))
    assert cited, "the section cites no evidence at all"
    assert cited <= known, f"cited but defined nowhere: {sorted(cited - known)}"


def test_findings_parked_for_this_section_are_all_cited() -> None:
    """F-007 and F-026 each wrote themselves down as a 'documented limitation' candidate and
    then waited for this section. This is what stops the next one being forgotten the same way."""
    parked = {
        identifier
        for line in FINDINGS.read_text(encoding="utf-8").splitlines()
        if "documented limitation" in line.lower()
        for identifier in TABLE_ROW_ID.findall(line)
    }
    assert parked, "no finding parks itself for the limitations section any more — check why"
    assert parked <= set(EVIDENCE_ID.findall(_section())), sorted(parked)


# ---- the prose and the engine move together ---------------------------------------------------
def test_the_lxml_limitation_matches_what_the_parser_does() -> None:
    """If T-11 lands and the backend starts working, this fails and the bullet has to go — the
    only way a limitations list stays true as the code moves under it."""
    with pytest.raises(NotImplementedError, match="T-11"):
        semdiff.parse("<p>x</p>", config=Config(parser=ParserBackend.LXML))
    _bullet_for(next(item for item in CATALOGUE if item.key == "lxml_backend"))


def test_the_report_limitation_matches_what_normalize_returns() -> None:
    """The public entry point returns a bare string, so the rules it fired are not in the
    result — FR-11's reporting clause is met by ``apply_rules`` and the CLI, not by this."""
    assert isinstance(semdiff.normalize("<p>x</p>"), str)
    _bullet_for(next(item for item in CATALOGUE if item.key == "rules_fired"))


def test_the_documented_corpus_counts_match_the_fixtures() -> None:
    """The numbers in the prose are counted from ``corpus/`` here, so admitting a pair of a
    family the README calls uncovered cannot pass quietly."""
    families: dict[str, int] = {}
    for pair in load_pairs(category="noise_only"):
        for family in pair.label.noise_families or ():
            families[str(family)] = families.get(str(family), 0) + 1
    assert families == {"asset_hash": 14, "timestamp": 6}, families
    bullet = _bullet_for(next(item for item in CATALOGUE if item.key == "corpus_coverage"))
    for name, count in sorted(families.items()):
        assert f"{count} `{name}`" in bullet, f"README does not say {count} {name} pairs"
    for uncovered in ("dynamic_class", "hashed_id", "token"):
        assert uncovered in bullet


# ---- nothing was softened to make room --------------------------------------------------------
def test_the_guarantees_survived_the_caveats() -> None:
    """A limitations section earns nothing if it is paid for by quietly weakening the claims
    above it. All three guarantees are still stated, in the same words."""
    text = _readme()
    for claim in ("**Deterministic.**", "**Idempotent.**", "**Safe.**"):
        assert claim in text
    assert "`normalize(normalize(x)) == normalize(x)`" in text
