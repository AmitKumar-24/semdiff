"""Fixture loader for ``corpus/`` (D-012, D-017, D-018)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from pydantic import ValidationError

from tests.corpus.labels import FIXTURE_ID_RE, Category, PairLabel

CORPUS_ROOT = Path(__file__).resolve().parents[2] / "corpus"
FIXTURE_FILES = ("old.html", "new.html", "pair.json")


class CorpusError(Exception):
    """A fixture violates the corpus layout or label contract."""


@dataclass(frozen=True)
class Pair:
    id: str
    category: Category
    dir: Path
    label: PairLabel

    @cached_property
    def old_bytes(self) -> bytes:
        return (self.dir / "old.html").read_bytes()

    @cached_property
    def new_bytes(self) -> bytes:
        return (self.dir / "new.html").read_bytes()


def load_pairs(root: Path = CORPUS_ROOT, category: Category | str | None = None) -> list[Pair]:
    """Load every fixture under ``root``, sorted by id. Raises ``CorpusError`` on any defect."""
    pairs: list[Pair] = []
    seen: dict[str, Path] = {}
    for category_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        try:
            dir_category = Category(category_dir.name)
        except ValueError:
            raise CorpusError(f"unknown category directory: {category_dir.name}") from None
        for pair_dir in sorted(p for p in category_dir.iterdir() if p.is_dir()):
            pair = _load_pair(pair_dir, dir_category)
            if pair.id in seen:
                raise CorpusError(f"duplicate fixture id {pair.id}: {seen[pair.id]} and {pair_dir}")
            seen[pair.id] = pair_dir
            pairs.append(pair)
    if category is not None:
        wanted = Category(category)
        pairs = [p for p in pairs if p.category is wanted]
    return sorted(pairs, key=lambda p: p.id)


def _load_pair(pair_dir: Path, dir_category: Category) -> Pair:
    pair_id = pair_dir.name
    if not FIXTURE_ID_RE.match(pair_id):
        raise CorpusError(f"fixture id {pair_id!r} does not match <host>-<NNN>")
    for name in FIXTURE_FILES:
        if not (pair_dir / name).is_file():
            raise CorpusError(f"{pair_id}: missing {name}")
    try:
        label = PairLabel.model_validate(json.loads((pair_dir / "pair.json").read_text("utf-8")))
    except (ValidationError, ValueError) as exc:
        raise CorpusError(f"{pair_id}: invalid pair.json: {exc}") from exc
    if label.category is not dir_category:
        raise CorpusError(
            f"{pair_id}: label category {label.category.value!r} != directory {dir_category.value!r}"
        )
    return Pair(id=pair_id, category=dir_category, dir=pair_dir, label=label)
