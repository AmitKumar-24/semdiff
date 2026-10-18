"""Typed access to a query that may return nothing (T-25).

``css_first`` is declared ``LexborNode | None`` by selectolax 1.0.0, where 0.4.x declared the
no-default overload as returning ``LexborNode``. Tests that index straight into the result
therefore pass ``mypy --strict`` on one parser build and fail on the other — 86 errors across
seven files, none of them in ``src/`` (D-046). Going through ``one()`` states the expectation
once, in a place where a missing element is a clear test failure rather than an ``AttributeError``
on ``None``.

Tests that are *about* absence keep calling ``css_first`` directly and compare with ``None``.
"""

from __future__ import annotations

from selectolax.lexbor import LexborHTMLParser, LexborNode


def one(scope: LexborHTMLParser | LexborNode, selector: str) -> LexborNode:
    """The first element matching ``selector``, which the caller asserts exists."""
    node = scope.css_first(selector)
    assert node is not None, f"no element matched {selector!r}"
    return node
