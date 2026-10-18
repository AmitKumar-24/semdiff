"""T-10: L0 parsing adapter (selectolax) — FR-1, FR-2, FR-3, NFR-7, NFR-8."""

from __future__ import annotations

import re
from importlib import metadata

import pytest

import semdiff
from semdiff import (
    PARSER_ID,
    PARSER_VERSION,
    Config,
    InputTooLargeError,
    ParseError,
    ParsedDoc,
    ParserBackend,
    parse,
    parser_fingerprint,
)
from tests.nodes import one

WELL_FORMED = b"<!doctype html><html><head><title>t</title></head><body><p>hello</p></body></html>"


def test_well_formed_bytes() -> None:
    doc = parse(WELL_FORMED, url="https://example.org/x")
    assert isinstance(doc, ParsedDoc)
    assert doc.parser_id == "selectolax"
    assert doc.url == "https://example.org/x"
    assert doc.encoding == "utf-8"
    assert one(doc.tree, "p").text() == "hello"


@pytest.mark.parametrize(
    "html",
    [
        b"<div><p>unclosed<span>text",
        b"</b>stray close <i>text</b></p>",
        b"<form><form><input name=a></form>text</form>",
        b"<p>text<table><tr><td>cell<p>more",
        b"\xc3\x28\xa0\xa1<p>garbage bytes then text</p>",  # invalid UTF-8, not a BOM
    ],
)
def test_malformed_html_never_raises(html: bytes) -> None:
    doc = parse(html)
    assert "text" in doc.tree.body.text()  # type: ignore[union-attr]


def test_str_input() -> None:
    doc = parse("<p>café</p>")
    assert doc.encoding == "utf-8"
    assert one(doc.tree, "p").text() == "café"


def test_oversized_input_rejected() -> None:
    cfg = Config(max_input_bytes=64)
    ok = b"<p>" + b"x" * 57 + b"</p>"  # exactly 64 bytes
    assert len(ok) == 64
    assert parse(ok, config=cfg).tree.css_first("p") is not None
    with pytest.raises(InputTooLargeError) as info:
        parse(ok + b"!", config=cfg)
    assert info.value.to_record().detail == {"size": 65, "limit": 64}
    with pytest.raises(InputTooLargeError):
        parse("y" * 65, config=cfg)  # str is measured as UTF-8 bytes


def test_default_ceiling_is_10_mib() -> None:
    assert Config().max_input_bytes == 10 * 1024 * 1024


@pytest.mark.parametrize("html", [b"", "", b"   \n\t", "  "])
def test_empty_input_is_parse_error(html: bytes | str) -> None:
    with pytest.raises(ParseError):
        parse(html)


def test_declared_encoding_wins() -> None:
    doc = parse(b"<p>caf\xe9</p>", encoding="latin-1")
    assert doc.encoding == "latin-1"
    assert one(doc.tree, "p").text() == "café"


def test_meta_charset_is_honoured() -> None:
    html = b'<html><head><meta charset="iso-8859-1"></head><body><p>caf\xe9</p></body></html>'
    doc = parse(html)
    assert doc.encoding == "iso-8859-1"
    assert one(doc.tree, "p").text() == "café"


def test_undecodable_bytes_never_raise() -> None:
    doc = parse(b"<p>ok \xff\xfe\xfd bad</p>", encoding="utf-8")
    assert "ok" in one(doc.tree, "p").text()


def test_lxml_backend_deferred_to_t11() -> None:
    with pytest.raises(NotImplementedError, match="T-11"):
        parse(WELL_FORMED, config=Config(parser=ParserBackend.LXML))


def test_parse_is_deterministic() -> None:
    a = parse(WELL_FORMED).tree.html
    b = parse(WELL_FORMED).tree.html
    assert a == b


def test_no_entity_expansion_or_script_execution() -> None:
    html = (
        b'<!DOCTYPE x [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
        b"<html><body><p>&xxe;</p><script>document.body.innerHTML='pwned'</script></body></html>"
    )
    doc = parse(html)
    paragraph = one(doc.tree, "p")  # the script did not run: body was not replaced
    assert paragraph.text() == "&xxe;"  # the external entity was not resolved or expanded


# ---- parser identity (T-25, D-046) ---------------------------------------------------------
def test_parsed_doc_names_the_parser_build() -> None:
    """``parser_id`` keeps its old value and ``parser_version`` is additive, so provenance can
    name the exact build without changing anything a caller already reads."""
    doc = parse(b"<p>x</p>")
    assert doc.parser_id == PARSER_ID == "selectolax"
    assert doc.parser_version == PARSER_VERSION == metadata.version("selectolax")
    assert re.fullmatch(r"\d+\.\d+.*", doc.parser_version)


def test_the_fingerprint_is_what_config_hash_does_not_cover() -> None:
    """D-046: ``config_hash`` covers the config and the ruleset, the fingerprint covers the
    parser build. A result is reproducible against both together, which is why the CLI report
    prints the second one."""
    assert parser_fingerprint() == f"{PARSER_ID}/{PARSER_VERSION}"
    assert PARSER_VERSION not in Config().config_hash
    assert semdiff.parser_fingerprint() == parser_fingerprint()


def test_exposing_the_parser_did_not_change_the_public_api() -> None:
    """``normalize()`` still returns ``str`` and ``ParsedDoc`` is still constructible without
    the new field — additive, not a new result type."""
    assert isinstance(semdiff.normalize("<p>x</p>"), str)
    bare = ParsedDoc(tree=parse(b"<p>x</p>").tree, encoding="utf-8", parser_id="selectolax", url=None)
    assert bare.parser_version == PARSER_VERSION
