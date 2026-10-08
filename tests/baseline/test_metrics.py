"""The T-22 baselines measure what they claim to, including where they are blind.

These are unit tests on tiny synthetic documents, not on the corpus: the corpus-wide numbers
come from ``python -m tests.baseline.report``, and SemDiff's own side of the comparison is
already asserted pair by pair in ``tests/corpus/test_noise_only_gate.py``. Re-normalizing all
20 pairs here would just double the suite's slowest work.
"""

from __future__ import annotations

import pytest

from tests.baseline.metrics import (
    changed_line_bytes,
    difflib_raw_lines,
    difflib_raw_words,
    difflib_text_words,
    lxml_html_diff_marks,
    semdiff_changes,
)
from tests.corpus.labels import Category
from tests.corpus.loader import load_pairs

PAGE = b"<html><head><title>t</title></head><body><p>hello world</p></body></html>"

METRICS = (difflib_raw_lines, difflib_raw_words, difflib_text_words, lxml_html_diff_marks, semdiff_changes)


@pytest.mark.parametrize("metric", METRICS, ids=lambda m: m.__name__)
def test_identical_input_reports_nothing(metric: object) -> None:
    assert callable(metric)
    assert metric(PAGE, PAGE) == 0


# ---- what each baseline counts ----------------------------------------------------------
def test_line_metric_counts_changed_lines() -> None:
    old = b"<p>a</p>\n<p>b</p>\n<p>c</p>"
    new = b"<p>a</p>\n<p>B</p>\n<p>c</p>"
    assert difflib_raw_lines(old, new) == 1


def test_line_metric_saturates_at_one_on_a_single_line_document() -> None:
    # The minified case: one line changed means the whole document is reported back.
    old = b"<p>a</p><p>b</p><p>c</p>"
    new = b"<p>a</p><p>B</p><p>c</p>"
    assert difflib_raw_lines(old, new) == 1
    assert changed_line_bytes(old, new) == len(new)


def test_word_metric_counts_tokens_not_lines() -> None:
    old = b"<p>one two three</p>"
    new = b"<p>one TWO three</p>"
    assert difflib_raw_words(old, new) == 1


def test_text_metric_ignores_script_and_style_bodies() -> None:
    old = b"<body><p>x</p><script>var a=1</script><style>i{color:red}</style></body>"
    new = b"<body><p>x</p><script>var a=2</script><style>i{color:blue}</style></body>"
    assert difflib_text_words(old, new) == 0
    assert difflib_raw_words(old, new) > 0


# ---- where the text-shaped baselines are blind -------------------------------------------
def test_text_metric_is_blind_to_a_meaningful_attribute_change() -> None:
    """Being quiet on attribute noise is not the same as being right about attributes."""
    old = b'<body><a href="/buy/sku-1">buy</a></body>'
    new = b'<body><a href="/buy/sku-2">buy</a></body>'
    assert difflib_text_words(old, new) == 0
    assert lxml_html_diff_marks(old, new) > 0  # lxml does annotate link targets


def test_lxml_drops_head_entirely() -> None:
    old = b'<html><head><script src="/a.1111aaaa.js"></script></head><body><p>x</p></body></html>'
    new = b'<html><head><script src="/a.2222bbbb.js"></script></head><body><p>x</p></body></html>'
    assert lxml_html_diff_marks(old, new) == 0


def test_lxml_swallows_a_body_script_src_change_without_marking_it() -> None:
    """Worse than ignoring: the output shows the new value and reports no change."""
    old = b'<body><p>x</p><script src="/a.1111aaaa.js"></script></body>'
    new = b'<body><p>x</p><script src="/a.2222bbbb.js"></script></body>'
    assert lxml_html_diff_marks(old, new) == 0


def test_lxml_does_flag_an_image_hash_change() -> None:
    """The same asset-hash noise is visible to lxml when it sits on an <img>."""
    old = b'<body><img src="/hero.1111aaaa.png"></body>'
    new = b'<body><img src="/hero.2222bbbb.png"></body>'
    assert lxml_html_diff_marks(old, new) > 0


# ---- SemDiff's side ----------------------------------------------------------------------
def test_semdiff_erases_noise_the_baselines_report() -> None:
    old = b'<body><p>Updated 3 minutes ago</p><script src="/a.1111aaaa.js"></script></body>'
    new = b'<body><p>Updated 5 hours ago</p><script src="/a.2222bbbb.js"></script></body>'
    assert semdiff_changes(old, new) == 0
    assert difflib_raw_words(old, new) > 0
    assert difflib_text_words(old, new) > 0


def test_semdiff_keeps_a_real_change() -> None:
    old = b"<body><p>$10.00</p></body>"
    new = b"<body><p>$12.00</p></body>"
    assert semdiff_changes(old, new) == 1


# ---- the premise of the comparison -------------------------------------------------------
def test_every_corpus_pair_really_differs_in_bytes() -> None:
    """A baseline table is only meaningful if every pair is a genuine before/after."""
    pairs = load_pairs(category=Category.NOISE_ONLY)
    assert pairs
    for pair in pairs:
        assert pair.old_bytes != pair.new_bytes, pair.id
        assert difflib_raw_lines(pair.old_bytes, pair.new_bytes) > 0, pair.id
