"""T-19: the public ``semdiff.normalize()`` API (FR-10).

The pipeline behind it is T-10 parse → T-12 engine over the T-13..T-17 families →
canonical serialization (D-032). These tests exercise it only through the public entry
point; per-family behaviour is covered in ``tests/normalize/``.
"""

from __future__ import annotations

import pytest

import semdiff
from semdiff import (
    Config,
    InputTooLargeError,
    NormalizationConfig,
    ParseError,
    ParserBackend,
    normalize,
)

# Two renders of the same page. Every difference belongs to one of the five noise families;
# nothing semantic changes. Pretty-printed vs minified, comments and attribute order differ too.
NOISE_OLD = """<!DOCTYPE html>
<html><head>
  <meta charset="utf-8">
  <meta name="csrf-token" content="Zm9vYmFyMTIzNDU2Nzg5">
  <title>Widget</title>
</head>
<body>
  <!-- render 4a3f -->
  <div id="react-root-7a3b2c" class="layout css-1dbjc4n">
    <h1 class="title sc-bdfBwQ">Widget</h1>
    <p class="body css-ios753">Price: $19.99</p>
    <p>Updated 3 minutes ago</p>
    <form><input type="hidden" name="csrf_token" value="9f8e7d6c1a2b"></form>
  </div>
</body></html>
"""

NOISE_NEW = (
    '<!DOCTYPE html><html><head><meta charset="utf-8">'
    '<meta name="csrf-token" content="YmFyZm9vOTg3NjU0MzIx"><title>Widget</title></head><body>'
    "<!-- render 91ce -->"
    '<div class="layout css-14f5s8o" id="react-root-4f8e1d">'
    '<h1 class="title sc-AxjAm">Widget</h1>'
    '<p class="body css-uscrbs">Price: $19.99</p>'
    "<p>Updated 5 hours ago</p>"
    '<form><input type="hidden" value="4d5e6f7a8b9c" name="csrf_token"></form>'
    "</div></body></html>"
)

SEMANTIC_NEW = NOISE_NEW.replace("$19.99", "$24.99")


# ---- surface ----------------------------------------------------------------------------------
def test_normalize_is_the_public_entry_point() -> None:
    assert semdiff.normalize is normalize
    assert "normalize" in semdiff.__all__
    assert callable(normalize)


def test_engine_internals_remain_importable() -> None:
    # `normalize` shadows the `semdiff.normalize` subpackage attribute exactly as `parse`
    # already shadows `semdiff.parse`; `from ... import` must keep working.
    from semdiff.normalize import BUILTIN_RULES, apply_rules
    from semdiff.normalize.rules.classes import CLASS_RULES

    assert BUILTIN_RULES.ordered() and callable(apply_rules) and CLASS_RULES


def test_returns_a_string_and_wraps_a_fragment_in_a_document() -> None:
    out = normalize("<p>hello</p>")
    assert isinstance(out, str)
    assert out == "<html><head></head><body><p>hello</p></body></html>"


# ---- what it is for ---------------------------------------------------------------------------
def test_noise_only_renders_normalize_to_the_same_bytes() -> None:
    assert normalize(NOISE_OLD) == normalize(NOISE_NEW)


def test_a_real_change_survives_normalization() -> None:
    assert normalize(NOISE_OLD) != normalize(SEMANTIC_NEW)
    assert "$24.99" in normalize(SEMANTIC_NEW)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ('<div class="card css-1dbjc4n">x</div>', '<div class="card css-14f5s8o">x</div>'),
        ('<div id="react-root-7a3b2c">x</div>', '<div id="react-root-4f8e1d">x</div>'),
        ('<meta name="csrf-token" content="Zm9vYmFy">', '<meta name="csrf-token" content="YmFyZm9v">'),
        ("<p>Updated 3 minutes ago</p>", "<p>Updated 5 hours ago</p>"),
        ("<div>\n  <p>a  b</p>\n  <!-- c -->\n</div>", "<div><p>a b</p></div>"),
    ],
    ids=["dynamic_class", "hashed_id", "token", "timestamp", "canonical"],
)
def test_every_family_is_reachable_through_the_public_api(old: str, new: str) -> None:
    assert normalize(old) == normalize(new)


def test_structured_data_carriers_survive() -> None:
    out = normalize('<script type="application/ld+json">{"price":  "19.99"}</script>')
    assert '{"price":  "19.99"}' in out


# ---- invariants -------------------------------------------------------------------------------
IDEMPOTENCE_CASES = [NOISE_OLD, NOISE_NEW, "<p>plain</p>", "<div><!-- c --><a id='m' class='b'> t </a></div>", ""]


@pytest.mark.parametrize("html", IDEMPOTENCE_CASES[:-1], ids=["noise_old", "noise_new", "plain", "messy"])
def test_normalize_is_idempotent(html: str) -> None:
    once = normalize(html)
    assert normalize(once) == once


def test_output_is_deterministic_and_input_is_untouched() -> None:
    source = NOISE_OLD
    raw = NOISE_OLD.encode()
    assert normalize(source) == normalize(source)
    assert normalize(raw) == normalize(source)
    assert source == NOISE_OLD and raw == NOISE_OLD.encode()


def test_bytes_and_str_agree_and_encoding_can_be_declared() -> None:
    assert normalize("<p>café</p>") == normalize("<p>café</p>".encode())
    latin1 = "<p>café</p>".encode("latin-1")
    assert normalize(latin1, encoding="latin-1") == normalize("<p>café</p>")
    assert "café" not in normalize(latin1)  # undeclared latin-1 is not guessed


def test_non_breaking_space_is_content_not_layout() -> None:
    # F-010: only ASCII whitespace collapses, so an nbsp edit stays visible.
    assert normalize("<p>a&nbsp;b</p>") != normalize("<p>a b</p>")
    assert "a&nbsp;b" in normalize("<p>a b</p>")
    assert normalize("<p>a \t\n b</p>") == normalize("<p>a b</p>")


def test_output_encoding_contract() -> None:
    # D-034: str out, XML-special characters as entities, everything else literal,
    # and an existing <meta charset> is preserved verbatim rather than rewritten.
    out = normalize("<p>caf&eacute; &amp; 3 &lt; 5 &gt; 1 &quot;q&quot;</p>")
    assert 'café &amp; 3 &lt; 5 &gt; 1 "q"' in out
    assert '<meta charset="iso-8859-1">' in normalize(b'<meta charset="iso-8859-1"><p>x</p>')


# ---- configuration ----------------------------------------------------------------------------
def test_config_toggles_reach_the_engine() -> None:
    html = '<div class="card css-1dbjc4n"><p>Updated 3 minutes ago</p></div>'
    off = Config(normalization=NormalizationConfig(disabled_rules=frozenset({"timestamp.relative_ago"})))
    assert "3 minutes ago" not in normalize(html)
    assert "3 minutes ago" in normalize(html, off)
    assert "css-1dbjc4n" not in normalize(html, off)  # the other families still run
    assert normalize(html, config=off) == normalize(html, off)  # config is also accepted by name


def test_unknown_rule_id_in_the_config_fails_loud() -> None:
    bad = Config(normalization=NormalizationConfig(disabled_rules=frozenset({"no.such.rule"})))
    with pytest.raises(ValueError, match="no.such.rule"):
        normalize("<p>x</p>", bad)


def test_unimplemented_parser_backend_is_reported() -> None:
    with pytest.raises(NotImplementedError, match="T-11"):
        normalize("<p>x</p>", Config(parser=ParserBackend.LXML))


# ---- bad input --------------------------------------------------------------------------------
@pytest.mark.parametrize("html", ["", "   \n\t ", b""], ids=["empty", "whitespace", "empty_bytes"])
def test_empty_input_raises_parse_error(html: str | bytes) -> None:
    with pytest.raises(ParseError):
        normalize(html)


def test_oversized_input_raises_before_parsing() -> None:
    with pytest.raises(InputTooLargeError) as excinfo:
        normalize("<p>" + "x" * 200 + "</p>", Config(max_input_bytes=64))
    assert excinfo.value.to_record().type == "input_too_large"


@pytest.mark.parametrize(
    "html",
    [
        "<div><p>unclosed<div>nested</div>",
        "<p>stray</p></p></div>",
        "<table><tr><td>cell</table>",
        "<div class=unquoted id=x>t</div>",
        "<p>a<b>bold<i>both</b>italic</i></p>",
    ],
)
def test_malformed_html_is_repaired_not_rejected(html: str) -> None:
    out = normalize(html)
    assert out.startswith("<html>") and normalize(out) == out
