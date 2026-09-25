"""T-19: the public normalization entry point (FR-10).

``semdiff.normalize()`` is L1 on its own: parse (T-10) → the phase-ordered engine over the
built-in families (T-12..T-17) → canonical serialization (D-032). It is deterministic — the
same input and config always produce the same string — and idempotent, because the
canonicalization phase runs last and reaches a fixpoint.
"""

from __future__ import annotations

from semdiff.config import Config
from semdiff.normalize.registry import BUILTIN_RULES, apply_rules
from semdiff.parse import parse


def normalize(html: bytes | str, config: Config | None = None, *, encoding: str | None = None) -> str:
    """Return ``html`` with presentational noise removed and the tree canonicalized.

    ``bytes`` are decoded as T-10 decides (declared ``encoding`` → BOM → ``<meta charset>``
    → UTF-8); the result is always ``str``. Raises ``InputTooLargeError`` (NFR-7),
    ``ParseError`` (FR-3), or ``ValueError`` if the config toggles an unknown rule id.
    """
    config = config or Config()
    doc = parse(html, encoding=encoding, config=config)
    return apply_rules(doc, BUILTIN_RULES, config.normalization).tree.html or ""
