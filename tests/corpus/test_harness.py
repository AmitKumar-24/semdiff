"""T-03: unit tests for the corpus harness itself, on synthetic fixtures in tmp_path."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from tests.corpus.assertions import assert_expected_change_types, assert_normalized_identical
from tests.corpus.labels import PairLabel
from tests.corpus.loader import CorpusError, load_pairs

LABEL: dict[str, Any] = {
    "label_version": "1",
    "category": "noise_only",
    "url": "https://example.org/page",
    "captured_old": "2026-09-16T10:42:07Z",
    "captured_new": "2026-09-16T10:44:19Z",
    "content_type": "text/html; charset=utf-8",
    "expected": {"change_types": []},
    "noise_families": ["dynamic_class", "timestamp"],
    "notes": "reviewed by hand",
    "license": "CC-BY-4.0",
    "terms_url": "https://example.org/terms",
    "attribution": "Example Org",
    "basis": "permissive",
}


def make_pair(
    root: Path,
    category: str = "noise_only",
    pair_id: str = "example-org-001",
    label: dict[str, Any] | None = None,
    old: bytes = b"<p>old</p>",
    new: bytes = b"<p>new</p>",
    omit: str | None = None,
) -> Path:
    d = root / category / pair_id
    d.mkdir(parents=True)
    files = {
        "old.html": old,
        "new.html": new,
        "pair.json": json.dumps({**LABEL, "category": category, **(label or {})}).encode(),
    }
    for name, content in files.items():
        if name != omit:
            (d / name).write_bytes(content)
    return d


def test_valid_fixture_loads(tmp_path: Path) -> None:
    make_pair(tmp_path, old=b"<p>a</p>", new=b"<p>b</p>")
    pairs = load_pairs(tmp_path)
    assert len(pairs) == 1
    pair = pairs[0]
    assert pair.id == "example-org-001"
    assert pair.category == "noise_only"
    assert pair.dir == tmp_path / "noise_only" / "example-org-001"
    assert pair.label.url == "https://example.org/page"
    assert pair.label.captured_old.isoformat() == "2026-09-16T10:42:07+00:00"
    assert pair.label.noise_families == ["dynamic_class", "timestamp"]
    assert pair.old_bytes == b"<p>a</p>"
    assert pair.new_bytes == b"<p>b</p>"


def test_empty_root_loads_nothing(tmp_path: Path) -> None:
    assert load_pairs(tmp_path) == []
    (tmp_path / "noise_only").mkdir()
    assert load_pairs(tmp_path) == []


def test_unknown_category_dir_rejected(tmp_path: Path) -> None:
    make_pair(tmp_path, category="mystery")
    with pytest.raises(CorpusError, match="mystery"):
        load_pairs(tmp_path)


@pytest.mark.parametrize("missing", ["old.html", "new.html", "pair.json"])
def test_missing_file_rejected(tmp_path: Path, missing: str) -> None:
    make_pair(tmp_path, omit=missing)
    with pytest.raises(CorpusError, match=missing):
        load_pairs(tmp_path)


@pytest.mark.parametrize("bad_id", ["Example-Org-001", "example.org-001", "example-org-1", "001"])
def test_bad_fixture_id_rejected(tmp_path: Path, bad_id: str) -> None:
    make_pair(tmp_path, pair_id=bad_id)
    with pytest.raises(CorpusError, match="id"):
        load_pairs(tmp_path)


def test_category_mismatch_rejected(tmp_path: Path) -> None:
    make_pair(tmp_path, category="article", label={"category": "product"})
    with pytest.raises(CorpusError, match="category"):
        load_pairs(tmp_path)


def test_duplicate_id_across_categories_rejected(tmp_path: Path) -> None:
    make_pair(tmp_path, category="noise_only", pair_id="dup-host-001")
    make_pair(tmp_path, category="article", pair_id="dup-host-001")
    with pytest.raises(CorpusError, match="dup-host-001"):
        load_pairs(tmp_path)


def test_noise_only_requires_no_expected_changes() -> None:
    with pytest.raises(ValidationError):
        PairLabel.model_validate({**LABEL, "expected": {"change_types": ["price_change"]}})
    PairLabel.model_validate({**LABEL, "category": "product", "expected": {"change_types": ["price_change"]}})


@pytest.mark.parametrize(
    "override",
    [
        {"reviewed_by": "someone"},
        {"noise_families": ["css"]},
        {"basis": "fair-use"},
        {"label_version": "2"},
        {"url": "ftp://example.org"},
        {"captured_old": "2026-09-16"},
        {"captured_old": "2026-09-16T10:42:07"},
    ],
    ids=["extra-field", "bad-noise-family", "bad-basis", "bad-version", "bad-url", "date-only", "naive-datetime"],
)
def test_invalid_labels_rejected(override: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        PairLabel.model_validate({**LABEL, **override})


def test_optional_fields_may_be_omitted() -> None:
    minimal = {k: v for k, v in LABEL.items() if k not in {"noise_families", "notes"}}
    label = PairLabel.model_validate(minimal)
    assert label.noise_families is None
    assert label.notes is None


def test_pairs_sorted_by_id(tmp_path: Path) -> None:
    make_pair(tmp_path, pair_id="zeta-org-001")
    make_pair(tmp_path, pair_id="alpha-org-002")
    make_pair(tmp_path, category="article", pair_id="alpha-org-001")
    assert [p.id for p in load_pairs(tmp_path)] == ["alpha-org-001", "alpha-org-002", "zeta-org-001"]
    assert [p.id for p in load_pairs(tmp_path, category="article")] == ["alpha-org-001"]


def test_assert_normalized_identical(tmp_path: Path) -> None:
    make_pair(tmp_path, old=b"<p>x</p>", new=b"<p>y</p>")
    pair = load_pairs(tmp_path)[0]
    assert_normalized_identical(pair, lambda _: "same")
    with pytest.raises(AssertionError, match="example-org-001"):
        assert_normalized_identical(pair, lambda b: b.decode())


def test_assert_expected_change_types(tmp_path: Path) -> None:
    make_pair(tmp_path)
    make_pair(
        tmp_path,
        category="product",
        pair_id="shop-org-001",
        label={"expected": {"change_types": ["price_change", "availability_change"]}},
    )
    noise, product = load_pairs(tmp_path)
    assert_expected_change_types(noise, [])
    assert_expected_change_types(product, ["availability_change", "price_change"])
    with pytest.raises(AssertionError, match="price_change"):
        assert_expected_change_types(noise, ["price_change"])
