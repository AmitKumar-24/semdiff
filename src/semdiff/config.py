"""Immutable, serializable pipeline configuration and its deterministic hash (T-01).

A ``Config`` plus the two input snapshots fully determines a diff's output (NFR-1).
``config_hash`` covers every config field and the engine-owned built-in ruleset
version, so a change to either the user's settings or a shipped rule's definition
is visible in the output (DOMAIN_MODEL §12-J).
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Any

from pydantic import field_serializer, model_validator

from semdiff._models import FrozenModel

class ParserBackend(StrEnum):
    """L0 parser selection (FR-2)."""

    SELECTOLAX = "selectolax"
    LXML = "lxml"


class NormalizationConfig(FrozenModel):
    """Per-rule toggles for L1 (FR-11). Built-in rules are enabled unless listed here."""

    disabled_rules: frozenset[str] = frozenset()
    enabled_rules: frozenset[str] = frozenset()

    @field_serializer("disabled_rules", "enabled_rules")
    def _sorted(self, value: frozenset[str]) -> list[str]:
        return sorted(value)

    @model_validator(mode="after")
    def _no_overlap(self) -> NormalizationConfig:
        overlap = self.disabled_rules & self.enabled_rules
        if overlap:
            raise ValueError(f"rules both enabled and disabled: {sorted(overlap)}")
        return self


class Config(FrozenModel):
    """The single configuration object threaded through every pipeline layer."""

    parser: ParserBackend = ParserBackend.SELECTOLAX
    max_input_bytes: int = 10 * 1024 * 1024  # NFR-7 ceiling; larger input raises InputTooLargeError
    normalization: NormalizationConfig = NormalizationConfig()

    def to_canonical_json(self) -> str:
        """Compact JSON with sorted keys and sorted sets; the only serialized form."""
        return _canonical_json(self.model_dump(mode="json"))

    @classmethod
    def from_json(cls, text: str) -> Config:
        return cls.model_validate_json(text)

    @property
    def config_hash(self) -> str:
        # Local import: the registry depends on Config, so the dependency runs this way only here.
        from semdiff.normalize.registry import builtin_ruleset_version

        payload = {
            "ruleset_version": builtin_ruleset_version(),
            "config": self.model_dump(mode="json"),
        }
        digest = hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
        return f"sha256:{digest}"


def _canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
