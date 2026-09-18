"""Per-layer assertion helpers. They take callables so they can exist before the API does."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from tests.corpus.loader import Pair


def assert_normalized_identical(pair: Pair, normalize: Callable[[bytes], str]) -> None:
    """T-21 / NFR-4 (layer 1): both snapshots normalize to byte-identical text."""
    old = normalize(pair.old_bytes)
    new = normalize(pair.new_bytes)
    if old == new:
        return
    old_lines, new_lines = old.splitlines(), new.splitlines()
    for index, (a, b) in enumerate(zip(old_lines, new_lines, strict=False)):
        if a != b:
            raise AssertionError(
                f"{pair.id}: normalized outputs differ at line {index + 1}:\n  old: {a!r}\n  new: {b!r}"
            )
    raise AssertionError(
        f"{pair.id}: normalized outputs differ in length: {len(old_lines)} vs {len(new_lines)} lines"
    )


def assert_expected_change_types(pair: Pair, observed: Sequence[str]) -> None:
    """NFR-4 / T-44: the observed change types equal the label's expectation, order-insensitive."""
    expected = sorted(pair.label.expected.change_types)
    actual = sorted(observed)
    if actual != expected:
        raise AssertionError(f"{pair.id}: expected change types {expected}, observed {actual}")
