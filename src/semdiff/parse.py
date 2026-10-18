"""L0 — parsing adapter (T-10). Untrusted bytes in, a traversable tree out. Nothing else.

selectolax (Lexbor) is the default backend (FR-2). It never raises on malformed markup,
executes no scripts, resolves no external entities, and performs no I/O (FR-4, NFR-8).
Lexbor decodes ``bytes`` as UTF-8 only, so encoding detection is done here first.
"""

from __future__ import annotations

import codecs
import re
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version

from selectolax.lexbor import LexborHTMLParser

from semdiff.config import Config, ParserBackend
from semdiff.errors import InputTooLargeError, ParseError

PARSER_ID = "selectolax"


def _installed_version() -> str:
    try:
        return version(PARSER_ID)
    except PackageNotFoundError:  # a vendored or zipped install has no distribution metadata
        return "unknown"


PARSER_VERSION = _installed_version()


def parser_fingerprint() -> str:
    """``selectolax/1.0.0`` — the parser build that produced a result (D-046).

    ``config_hash`` deliberately does not cover this: the parser is a property of the
    environment rather than of the configuration, and folding it in would change every
    published hash whenever an upstream release lands. So the determinism contract reads
    "same input, same ``config_hash``, **same parser build**", and this is how a caller
    records the third term. Normalized output is identical across the versions CI covers;
    what does move between them is a ``Locator.node_hash`` on foreign content (F-027).
    """
    return f"{PARSER_ID}/{PARSER_VERSION}"


_PRESCAN_BYTES = 2048  # HTML spec "prescan a byte stream" looks at the first 1024+; be generous
_META_CHARSET = re.compile(rb"""<meta[^>]*charset\s*=\s*["']?\s*([A-Za-z0-9_.:-]+)""", re.IGNORECASE)
_BOMS = ((codecs.BOM_UTF8, "utf-8-sig"), (codecs.BOM_UTF16_LE, "utf-16"), (codecs.BOM_UTF16_BE, "utf-16"))


@dataclass(frozen=True)
class ParsedDoc:
    """DOMAIN_MODEL §2: ``(tree, encoding, parser_id, url)``, plus the parser's version.

    ``parser_version`` is additive and defaulted (D-046): ``parser_id`` keeps its existing
    value, so nothing that reads it today changes, and provenance can still name the exact
    build.
    """

    tree: LexborHTMLParser
    encoding: str
    parser_id: str
    url: str | None
    parser_version: str = PARSER_VERSION


def parse(
    html: bytes | str,
    *,
    url: str | None = None,
    encoding: str | None = None,
    config: Config | None = None,
) -> ParsedDoc:
    """Parse one snapshot. Raises ``InputTooLargeError`` (NFR-7) or ``ParseError`` (FR-3)."""
    config = config or Config()
    if config.parser is not ParserBackend.SELECTOLAX:
        raise NotImplementedError(f"parser backend {config.parser.value!r} arrives with T-11")

    data = html.encode("utf-8") if isinstance(html, str) else html
    if len(data) > config.max_input_bytes:
        raise InputTooLargeError(len(data), config.max_input_bytes)

    if isinstance(html, str):
        text, used = html, "utf-8"
    else:
        used = _resolve_encoding(data, encoding)
        text = data.decode(used, errors="replace")

    if not text.strip():
        raise ParseError("input is empty")
    return ParsedDoc(
        tree=LexborHTMLParser(text),
        encoding=used,
        parser_id=PARSER_ID,
        url=url,
        parser_version=PARSER_VERSION,
    )


def _resolve_encoding(data: bytes, declared: str | None) -> str:
    """Declared encoding wins; then BOM; then ``<meta charset>``; then UTF-8."""
    if declared is not None:
        return _known(declared) or "utf-8"
    for bom, name in _BOMS:
        if data.startswith(bom):
            return name
    match = _META_CHARSET.search(data[:_PRESCAN_BYTES])
    if match:
        return _known(match.group(1).decode("ascii", errors="replace")) or "utf-8"
    return "utf-8"


def _known(name: str) -> str | None:
    """The caller's spelling, lowercased, if Python knows the codec; else ``None``."""
    try:
        codecs.lookup(name)
    except LookupError:
        return None
    return name.lower()
