"""T-24: the mutation catalogue behind the layer-1 recall gate (D-045).

Each mutation makes **one surgical edit** to a real capture's bytes and hands the result back in
memory. Nothing under ``corpus/`` is ever written, and a fixture's ``pair.json`` is read for its
label and nothing else: a capture and its metadata are evidence, not a scratchpad.

Two kinds of mutation, and the asymmetry is the whole design:

``Expect.VISIBLE``
    a change a reader would notice. ``normalize()`` must keep it, and keep it *as itself* — the
    new literal has to appear in the output, not merely make the output different.
``Expect.IDENTICAL``
    deploy noise of a shape the shipped rules already handle. ``normalize()`` must erase it, so
    the output stays byte-identical to the unmutated document's.

The noise controls are **self-calibrated**: they rotate a hash the shipped rules were observed
to match on that very document, rather than a hash-shaped string invented here. That matters —
probing the corpus for the obvious ``name-[0-9a-f]{6,}`` class shape finds *zero* instances even
though the engine rewrites about 100 class tokens per document, because the real patterns are
Emotion and CSS-modules shaped (F-005). A hand-written control would have tested a pattern no
capture contains.

Markers are all shorter than 16 characters and carry no ``[-_]``-fenced hex tail, so no shipped
rule can match them: ``EntropyMatcher`` needs 16 characters, the id patterns need the fence, and
the class rules only read ``class``.
"""

from __future__ import annotations

import functools
import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from semdiff import Config, parse
from semdiff.config import NormalizationConfig
from semdiff.normalize.registry import BUILTIN_RULES, apply_rules


class Expect(StrEnum):
    VISIBLE = "visible"  # a real change: normalization must not erase it
    IDENTICAL = "identical"  # known noise: normalization must erase it


@dataclass(frozen=True)
class Edit:
    """One in-memory mutation, with what its normalized output must and must not contain."""

    mutated: bytes
    present: tuple[str, ...] = ()  # VISIBLE: exactly one more occurrence than in the original's
    removed: tuple[str, ...] = ()  # VISIBLE: exactly one fewer occurrence than in the original's
    erased: tuple[str, ...] = ()  # IDENTICAL: in the mutated *input*, absent from its output


@dataclass(frozen=True)
class Mutation:
    id: str
    expect: Expect
    label: str
    build: Callable[[bytes], Edit | None]  # ``None`` when this document has no target for it
    provisional: str = ""  # a note that this row pins today's behaviour pending a decision


# ---- locating a target --------------------------------------------------------------------

# A mutation inside one of these would prove nothing: the text is protected (D-029) or its
# whitespace is preserved, so normalization declines it whatever the rules say. Script bodies in
# particular are full of markup-shaped strings that the patterns below would happily match.
_PRESERVED = (b"script", b"style", b"pre", b"textarea", b"template")


def _outside_preserved(raw: bytes, position: int) -> bool:
    """Whether ``position`` sits outside every protected or whitespace-preserved element."""
    head = raw[:position].lower()
    return all(head.count(b"<" + tag) <= head.count(b"</" + tag) for tag in _PRESERVED)


def _splice(raw: bytes, start: int, end: int, replacement: bytes) -> bytes:
    return raw[:start] + replacement + raw[end:]


def _collapsed(text: bytes) -> str:
    """The text as the canonical whitespace rule will leave it, so it can be searched for."""
    return re.sub(r"[\t\n\f\r ]+", " ", text.decode("utf-8", errors="replace")).strip()


def _any(match: re.Match[bytes]) -> bool:
    """No condition beyond the pattern itself and the preserved-element check."""
    return True


def _first_target(
    raw: bytes, pattern: re.Pattern[bytes], accept: Callable[[re.Match[bytes]], bool]
) -> re.Match[bytes] | None:
    """The first match outside a preserved element that ``accept`` also agrees to."""
    for match in pattern.finditer(raw):
        if _outside_preserved(raw, match.start()) and accept(match):
            return match
    return None


# ---- VISIBLE: text ------------------------------------------------------------------------

_WORD = re.compile(rb"[A-Za-z]{5,}")


def _text_edit(tag: bytes, marker: str, minimum: int) -> Callable[[bytes], Edit | None]:
    """Replace one word of visible text inside ``<tag>`` with ``marker``."""
    pattern = re.compile(
        rb"<" + tag + rb"[^>]*>([^<>&]{" + str(minimum).encode() + rb",})</" + tag + rb">"
    )

    def build(raw: bytes) -> Edit | None:
        match = _first_target(raw, pattern, lambda m: _WORD.search(m.group(1)) is not None)
        if match is None:
            return None
        word = _WORD.search(match.group(1))
        assert word is not None  # _first_target only accepted a match that has one
        start = match.start(1) + word.start()
        mutated = _splice(raw, start, start + len(word.group()), marker.encode())
        return Edit(mutated, present=(marker,))

    return build


def _version_edit(raw: bytes) -> Edit | None:
    """Bump a visible ``x.y.z`` — a build-identity change in content position (F-021, Q-26)."""
    pattern = re.compile(rb">[^<>]{0,120}?\b(\d+\.\d+\.\d+)\b")
    match = _first_target(raw, pattern, _any)
    if match is None:
        return None
    return Edit(_splice(raw, match.start(1), match.end(1), b"77.88.99"), present=("77.88.99",))


def _nbsp_edit(raw: bytes) -> Edit | None:
    """One ASCII space inside a paragraph becomes a non-breaking space.

    This is F-010's exact shape: ``canonical.whitespace`` once collapsed Unicode whitespace, so
    ``a&nbsp;b`` and ``a b`` normalized alike and a real edit was invisible. No capture in the
    corpus contains an NBSP, so this case has to inject what it tests.
    """
    pattern = re.compile(rb"<p[^>]*>[^<>&]*?[A-Za-z]( )[A-Za-z][^<>&]*?</p>")
    match = _first_target(raw, pattern, _any)
    if match is None:
        return None
    return Edit(_splice(raw, match.start(1), match.end(1), b"&nbsp;"), present=("&nbsp;",))


# ---- VISIBLE: attributes and structure ----------------------------------------------------


def _link_edit(raw: bytes) -> Edit | None:
    """Re-point an internal link. The new path is letters only, so FR-44 cannot reach it."""
    pattern = re.compile(rb'href="(/[A-Za-z0-9][A-Za-z0-9/_-]{4,})"')
    match = _first_target(raw, pattern, lambda m: b"." not in m.group(1))
    if match is None:
        return None
    mutated = _splice(raw, match.start(1), match.end(1), b"/docs/t24link")
    return Edit(mutated, present=('href="/docs/t24link"',))


def _image_edit(raw: bytes) -> Edit | None:
    """Point an ``<img>`` at a different file — a name change, not a hash rotation."""
    pattern = re.compile(
        rb'<img[^>]*\ssrc="([^"?#]*/)?([A-Za-z0-9_-]{3,})(\.(?:png|jpg|jpeg|svg|webp|gif))"'
    )
    match = _first_target(raw, pattern, _any)
    if match is None:
        return None
    marker = "t24img" + match.group(3).decode()
    return Edit(_splice(raw, match.start(2), match.end(3), marker.encode()), present=(marker,))


def _attribute_removed(raw: bytes) -> Edit | None:
    """Drop an ``alt`` — a real accessibility change, and one no rule family touches."""
    pattern = re.compile(rb'(\salt="([^"]{3,})")')
    match = _first_target(raw, pattern, lambda m: b"&" not in m.group(2))
    if match is None:
        return None
    literal = f'alt="{match.group(2).decode()}"'
    return Edit(_splice(raw, match.start(1), match.end(1), b""), removed=(literal,))


def _value_differs(want: bytes) -> Callable[[re.Match[bytes]], bool]:
    """Accept a match whose captured value is not already what we would write."""

    def accept(match: re.Match[bytes]) -> bool:
        return match.group(1) != want

    return accept


def _attribute_value(raw: bytes) -> Edit | None:
    """Change a meaningful attribute value: the document's language, else a link relation."""
    candidates = (
        (re.compile(rb'\slang="([a-zA-Z-]{2,5})"'), b"de-AT", 'lang="de-AT"'),
        (re.compile(rb'\srel="(stylesheet|canonical|next|prev)"'), b"nofollow", 'rel="nofollow"'),
    )
    for pattern, replacement, marker in candidates:
        match = _first_target(raw, pattern, _value_differs(replacement))
        if match is not None:
            mutated = _splice(raw, match.start(1), match.end(1), replacement)
            return Edit(mutated, present=(marker,))
    return None


def _paragraph_removed(raw: bytes) -> Edit | None:
    """Delete a paragraph. Its text is matched on the collapsed form, and the assertion counts
    occurrences rather than demanding uniqueness, so a repeated phrase still proves the loss."""
    pattern = re.compile(rb"<p[^>]*>([^<>&]{25,})</p>")
    match = _first_target(raw, pattern, lambda m: _collapsed(m.group(1)) != "")
    if match is None:
        return None
    return Edit(_splice(raw, match.start(), match.end(), b""), removed=(_collapsed(match.group(1)),))


def _paragraph_added(raw: bytes) -> Edit | None:
    """Insert a paragraph just inside ``</body>``, with no surrounding whitespace, so the element
    itself is the only thing that is new."""
    position = raw.lower().rfind(b"</body>")
    if position < 0:
        return None
    mutated = _splice(raw, position, position, b"<p>t24newparagraph</p>")
    return Edit(mutated, present=("t24newparagraph",))


def _class_token_changed(raw: bytes) -> Edit | None:
    """Rename one class token. FR-5 is explicit that this must stay visible: a page that stops
    emitting a class must not look unchanged, which is why the class rules substitute a sentinel
    instead of dropping the attribute (D-043). The marker is a plain token no class rule matches.
    """
    pattern = re.compile(rb'\sclass="([^"]{2,})"')
    token = re.compile(rb"[A-Za-z][A-Za-z0-9_-]{2,}")
    match = _first_target(raw, pattern, lambda m: token.search(m.group(1)) is not None)
    if match is None:
        return None
    first = token.search(match.group(1))
    assert first is not None  # _first_target only accepted a match that has one
    start = match.start(1) + first.start()
    mutated = _splice(raw, start, start + len(first.group()), b"t24class")
    return Edit(mutated, present=("t24class",))


def _reference_retargeted(raw: bytes) -> Edit | None:
    """Re-point an id reference whose value is *not* hash-shaped, so no id rule collapses it.

    The hash-shaped case has the opposite expectation and is F-029(1)'s documented limit, pinned
    by ``tests/normalize/test_placeholder.py``. It is a known recall gap, not a gate failure.
    """
    pattern = re.compile(rb'\s(?:for|aria-controls|aria-labelledby|aria-describedby)="([^" ]{3,})"')

    def plain(match: re.Match[bytes]) -> bool:
        value = match.group(1)
        return re.fullmatch(rb"[A-Za-z][A-Za-z0-9]*", value) is not None and len(value) < 16

    match = _first_target(raw, pattern, plain)
    if match is None:
        return None
    return Edit(_splice(raw, match.start(1), match.end(1), b"t24refaaaa"), present=("t24refaaaa",))


# ---- IDENTICAL: noise the shipped rules already handle ------------------------------------

_DIGITS = "0123456789"
_HEX = "abcdef"


def _rotate(text: str) -> str:
    """A different string of the same shape: digits stay digits, hex letters stay hex letters,
    case is preserved. A rotated hash has to still look like a hash to the same rule."""
    out: list[str] = []
    for char in text:
        if char in _DIGITS:
            out.append(_DIGITS[(_DIGITS.index(char) + 5) % 10])
        elif char in _HEX:
            out.append(_HEX[(_HEX.index(char) + 3) % 6])
        elif char.isascii() and char.isalpha():
            base = "a" if char.islower() else "A"
            out.append(chr((ord(char) - ord(base) + 13) % 26 + ord(base)))
        else:
            out.append(char)
    return "".join(out)


def _rotate_tail(token: str) -> str:
    """Rotate the hashed *tail* of a token and leave any stable prefix alone.

    Rotating the whole token would destroy the prefix the rule matches on — ``css-1abc2d`` would
    become ``pff-6def7a``, which ``class.emotion`` no longer recognizes, and the control would
    fail on its own mutation rather than on the engine. So the rotation starts after the last
    ``-`` or ``_``, or over the last four characters when the token has neither.
    """
    fence = max(token.rfind("-"), token.rfind("_"))
    start = fence + 1 if fence >= 0 else max(len(token) - 4, 0)
    return token[:start] + _rotate(token[start:])


def _changed_span(before: str, after: str) -> tuple[int, int] | None:
    """The one span ``before`` → ``after`` rewrote, found by trimming the common ends.

    STRIP removes that span and the placeholder substitutes the sentinel for it, so this reads
    the hashed part out of either action without knowing which rule fired.
    """
    limit = min(len(before), len(after))
    prefix = 0
    while prefix < limit and before[prefix] == after[prefix]:
        prefix += 1
    suffix = 0
    while suffix < limit - prefix and before[-1 - suffix] == after[-1 - suffix]:
        suffix += 1
    if prefix + suffix >= len(before):
        return None
    return prefix, len(before) - suffix


@functools.lru_cache(maxsize=64)
def _applications(raw: bytes) -> tuple[tuple[str, str, str], ...]:
    """``(family, before, after)`` for every rule the shipped engine fired on this document."""
    result = apply_rules(parse(raw, config=Config()), BUILTIN_RULES, NormalizationConfig())
    return tuple((app.rule_id.split(".")[0], app.before, app.after) for app in result.applied_rules)


def _rotate_family(family: str) -> Callable[[bytes], Edit | None]:
    """Rotate one hash this document's own rule applications identify as noise."""

    def build(raw: bytes) -> Edit | None:
        for seen_family, before, after in _applications(raw):
            if seen_family != family:
                continue
            span = _changed_span(before, after)
            if span is None or before.encode("utf-8") not in raw:
                continue  # no single changed span, or the value is entity-encoded in the source
            start, end = span
            token = before[start:end]
            rotated = _rotate_tail(token)
            if rotated == token:
                continue
            value = before[:start] + rotated + before[end:]
            return Edit(raw.replace(before.encode("utf-8"), value.encode("utf-8"), 1), erased=(rotated,))
        return None

    return build


def _timestamp_rotated(raw: bytes) -> Edit | None:
    """Move a timestamp's clock. Rotating every digit could leave the pattern behind, and the
    clock is the part FR-9's patterns require, so moving it keeps the shape and changes the
    value."""
    clock = re.compile(r"\b([01]\d|2[0-3]):[0-5]\d\b")
    for family, before, _after in _applications(raw):
        if family != "timestamp":
            continue
        match = clock.search(before)
        if match is None or before.encode("utf-8") not in raw:
            continue
        rotated = before[: match.start()] + "19:07" + before[match.end() :]
        if rotated == before:
            continue
        return Edit(raw.replace(before.encode("utf-8"), rotated.encode("utf-8"), 1), erased=("19:07",))
    return None


def _reformatted(raw: bytes) -> Edit | None:
    """Re-indent: lengthen an existing run of inter-tag whitespace, inside ``<body>``.

    Two fences, both learned the hard way. It has to lengthen an existing run rather than
    introduce one, because ``canonical.whitespace`` collapses a run to a single space and does
    not trim, so whitespace where there was none is a real difference — correctly so, and not
    what this control is about. And it has to be inside ``<body>``: the tree builder discards
    whitespace-only text in ``<head>``, so a run there is erased by the parser rather than by the
    rule, and the control would pass even with whitespace collapse switched off.
    """
    body = raw.lower().find(b"<body")
    if body < 0:
        return None
    pattern = re.compile(rb">(\s+)<")
    match = _first_target(raw[body:], pattern, _any)
    if match is None:
        return None
    return Edit(_splice(raw, body + match.start(1), body + match.end(1), b"\n\n      \t"))


def _ascending(match: re.Match[bytes]) -> bool:
    """Accept only a pair already in sorted order, so swapping it is something to undo.

    Without this the control could swap a pair that is *already* descending, which
    ``canonical.attr_order`` then sorts into the order the mutation wrote — asserting nothing.
    """
    first, second = (group.split(b"=")[0] for group in (match.group(1), match.group(2)))
    return first < second


def _attributes_reordered(raw: bytes) -> Edit | None:
    """Swap two attributes on one element; ``canonical.attr_order`` sorts them back."""
    pattern = re.compile(rb'<[a-z][a-z0-9]*\s+([a-z-]+="[^"]*")\s+([a-z-]+="[^"]*")')
    match = _first_target(raw, pattern, _ascending)
    if match is None:
        return None
    swapped = match.group(2) + b" " + match.group(1)
    return Edit(
        _splice(raw, match.start(1), match.end(2), swapped),
        erased=(swapped.decode("utf-8", errors="replace"),),
    )


def _comment_inserted(raw: bytes) -> Edit | None:
    """Insert a comment where it adds no whitespace; ``canonical.comments`` drops it."""
    match = _first_target(raw, re.compile(rb"><"), _any)
    if match is None:
        return None
    position = match.start() + 1
    return Edit(_splice(raw, position, position, b"<!-- t24 -->"), erased=("<!-- t24 -->",))


# ---- the catalogue ------------------------------------------------------------------------

CATALOGUE: tuple[Mutation, ...] = (
    Mutation("R1", Expect.VISIBLE, "a word of paragraph text", _text_edit(b"p", "t24textedit", 25)),
    Mutation("R2", Expect.VISIBLE, "a word of heading text", _text_edit(b"h1", "t24headedit", 12)),
    Mutation("R3", Expect.VISIBLE, "a word of list-item text", _text_edit(b"li", "t24listedit", 12)),
    Mutation("R4", Expect.VISIBLE, "an internal link target", _link_edit),
    Mutation("R5", Expect.VISIBLE, "an image source filename", _image_edit),
    Mutation(
        "R6",
        Expect.VISIBLE,
        "a visible version string",
        _version_edit,
        provisional=(
            "Provisional, Q-26-sensitive: Q-26 is open on whether a visible build-identity stamp "
            "is noise. This row pins today's behaviour — no shipped rule touches it — and becomes "
            "a documented limit if that decision goes the other way (F-021, F-025)."
        ),
    ),
    Mutation("R7", Expect.VISIBLE, "an attribute removed", _attribute_removed),
    Mutation("R8", Expect.VISIBLE, "an attribute value changed", _attribute_value),
    Mutation("R9", Expect.VISIBLE, "a paragraph removed", _paragraph_removed),
    Mutation("R10", Expect.VISIBLE, "a paragraph added", _paragraph_added),
    Mutation("R11", Expect.VISIBLE, "a space becomes an NBSP (F-010)", _nbsp_edit),
    Mutation("R12", Expect.VISIBLE, "an id reference re-pointed", _reference_retargeted),
    Mutation("R13", Expect.VISIBLE, "a class token renamed", _class_token_changed),
    Mutation("N1", Expect.IDENTICAL, "a class hash rotated", _rotate_family("class")),
    Mutation("N2", Expect.IDENTICAL, "an asset hash rotated", _rotate_family("asset")),
    Mutation("N3", Expect.IDENTICAL, "a timestamp rotated", _timestamp_rotated),
    Mutation("N4", Expect.IDENTICAL, "whitespace re-indented", _reformatted),
    Mutation("N5", Expect.IDENTICAL, "attributes reordered", _attributes_reordered),
    Mutation("N6", Expect.IDENTICAL, "a comment inserted", _comment_inserted),
)

BY_ID: dict[str, Mutation] = {mutation.id: mutation for mutation in CATALOGUE}
