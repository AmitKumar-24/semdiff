"""``pair.json`` label format, version 1 (D-012, D-015, D-016, D-018, D-021, Q-22)."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, field_validator, model_validator

# <host>-<NNN>, host with dots as dashes, e.g. "mui-com-001" (D-018).
FIXTURE_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*-[0-9]{3}$")


class Category(StrEnum):
    NOISE_ONLY = "noise_only"
    PRODUCT = "product"
    ARTICLE = "article"
    AD_INJECTION = "ad_injection"
    REORDER = "reorder"
    JOB = "job"


class NoiseFamily(StrEnum):
    """The differences a noise_only pair may contain (D-021, extended by D-036)."""

    DYNAMIC_CLASS = "dynamic_class"
    HASHED_ID = "hashed_id"
    TOKEN = "token"
    TIMESTAMP = "timestamp"
    ASSET_HASH = "asset_hash"


class Basis(StrEnum):
    PERMISSIVE = "permissive"
    CASE_BY_CASE = "case-by-case"


class _Strict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Expected(_Strict):
    change_types: list[str]


class PairLabel(_Strict):
    label_version: Literal["1"]
    category: Category
    url: str
    captured_old: AwareDatetime
    captured_new: AwareDatetime
    content_type: str
    expected: Expected
    noise_families: list[NoiseFamily] | None = None
    notes: str | None = None
    license: str
    terms_url: str
    attribution: str
    basis: Basis

    @field_validator("url", "terms_url")
    @classmethod
    def _http_url(cls, value: str) -> str:
        if not value.startswith(("http://", "https://")):
            raise ValueError(f"not an http(s) URL: {value!r}")
        return value

    @model_validator(mode="after")
    def _noise_only_has_no_changes(self) -> PairLabel:
        if self.category is Category.NOISE_ONLY and self.expected.change_types:
            raise ValueError("noise_only pairs must expect no change types")
        return self
