"""Baseline differs for T-22: what the standard tools report on a noise-only pair.

Every metric answers one question — *how many changes would this tool show a user* — as a
single integer, so the comparison is one number per tool per pair and 0 means "reports
nothing". Four baselines, chosen because each is what somebody actually runs today:

``difflib_raw_lines``
    ``difflib`` over the raw HTML split into lines: urlwatch's default and what any
    ``diff``-based or body-hash check does. On a minified page the whole document is one
    line, so this metric saturates at 1 — which is the failure mode, not a measurement
    artifact: the tool reports "the page changed" and shows you the page.
``difflib_raw_words``
    The same comparison at whitespace-token granularity, which is what the line metric
    *would* have reported had the HTML been pretty-printed. This is the honest measure of
    how much of the document a byte-level differ flags.
``difflib_text_words``
    ``difflib`` over extracted visible text with ``<script>`` and ``<style>`` removed:
    changedetection.io's model. Quiet on attribute-only noise — but blind to attribute
    changes in general, which is a different thing from being right.
``lxml_html_diff_marks``
    ``<ins>``/``<del>`` markers emitted by ``lxml.html.diff.htmldiff``. It diffs
    body content and annotates ``href`` and ``<img src>`` changes, drops ``<head>``
    entirely, and passes a body ``<script src>`` through *unannotated* — so a change there
    is silently swallowed rather than reported.

``semdiff_changes`` is the thing under test, reported the same way: 0 when the two
snapshots normalize to byte-identical output, 1 when they do not.

Test support and benchmark only. Nothing here is imported by ``src/semdiff``.
"""

from __future__ import annotations

import difflib
import re

from lxml.html.diff import htmldiff  # type: ignore[import-untyped]  # lxml ships no stubs
from selectolax.lexbor import LexborHTMLParser

from semdiff import normalize

_INS_DEL = re.compile(r"<(?:ins|del)[\s>]")
_STRIPPED_FROM_TEXT = "script, style"


def _decode(data: bytes) -> str:
    # The corpus holds response bytes; decoding losslessly is not the point here, measuring is.
    return data.decode("utf-8", "replace")


def _changed_units(old: list[str], new: list[str]) -> int:
    """Units touched by the diff: for a replacement, the larger of the two sides."""
    matcher = difflib.SequenceMatcher(a=old, b=new, autojunk=False)
    return sum(
        max(i2 - i1, j2 - j1) for tag, i1, i2, j1, j2 in matcher.get_opcodes() if tag != "equal"
    )


def _visible_text_words(data: bytes) -> list[str]:
    tree = LexborHTMLParser(data)
    for node in tree.css(_STRIPPED_FROM_TEXT):
        node.decompose()
    body = tree.body
    return (body.text(separator=" ") if body is not None else "").split()


def difflib_raw_lines(old: bytes, new: bytes) -> int:
    return _changed_units(_decode(old).splitlines(), _decode(new).splitlines())


def changed_line_bytes(old: bytes, new: bytes) -> int:
    """Bytes of ``new`` that sit inside a line the line diff reports as changed.

    This is what ``difflib_raw_lines`` hides: on minified HTML the one changed line is the
    whole document, so "1 change" means "here is the entire page again".
    """
    old_lines, new_lines = _decode(old).splitlines(), _decode(new).splitlines()
    matcher = difflib.SequenceMatcher(a=old_lines, b=new_lines, autojunk=False)
    return sum(
        len("\n".join(new_lines[j1:j2]).encode("utf-8"))
        for tag, _i1, _i2, j1, j2 in matcher.get_opcodes()
        if tag != "equal"
    )


def difflib_raw_words(old: bytes, new: bytes) -> int:
    return _changed_units(_decode(old).split(), _decode(new).split())


def difflib_text_words(old: bytes, new: bytes) -> int:
    return _changed_units(_visible_text_words(old), _visible_text_words(new))


def lxml_html_diff_marks(old: bytes, new: bytes) -> int:
    marked: str = htmldiff(_decode(old), _decode(new))
    return len(_INS_DEL.findall(marked))


def semdiff_changes(old: bytes, new: bytes) -> int:
    return 0 if normalize(old) == normalize(new) else 1


BASELINES: tuple[tuple[str, str], ...] = (
    ("difflib_raw_lines", "difflib, raw HTML, lines"),
    ("difflib_raw_words", "difflib, raw HTML, words"),
    ("difflib_text_words", "difflib, visible text, words"),
    ("lxml_html_diff_marks", "lxml.html.diff, ins/del marks"),
    ("semdiff_changes", "SemDiff normalize"),
)
