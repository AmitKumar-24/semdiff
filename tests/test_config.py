"""T-01: immutable, serializable Config with a deterministic config_hash."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from semdiff import Config, NormalizationConfig, ParserBackend


def test_defaults() -> None:
    cfg = Config()
    assert cfg.parser is ParserBackend.SELECTOLAX
    assert cfg.normalization.disabled_rules == frozenset()
    assert cfg.normalization.enabled_rules == frozenset()


def test_immutable_top_level_and_nested() -> None:
    cfg = Config()
    with pytest.raises(ValidationError):
        cfg.parser = ParserBackend.LXML
    with pytest.raises(ValidationError):
        cfg.normalization.disabled_rules = frozenset({"x"})


def test_unknown_field_rejected() -> None:
    with pytest.raises(ValidationError):
        Config.model_validate({"parser": "lxml", "not_a_field": 1})
    with pytest.raises(ValidationError):
        NormalizationConfig.model_validate({"bogus": True})


def test_overlapping_toggles_rejected() -> None:
    with pytest.raises(ValidationError):
        NormalizationConfig(disabled_rules=frozenset({"a", "b"}), enabled_rules=frozenset({"b"}))


def test_same_config_same_hash() -> None:
    a = Config(normalization=NormalizationConfig(disabled_rules=frozenset({"b", "a"})))
    b = Config(normalization=NormalizationConfig(disabled_rules=frozenset(["a", "b"])))
    assert a == b
    assert a.config_hash == b.config_hash
    assert Config().config_hash == Config().config_hash


def test_json_round_trip_preserves_equality_and_hash() -> None:
    cfg = Config(
        parser=ParserBackend.LXML,
        normalization=NormalizationConfig(disabled_rules=frozenset({"z", "y"}), enabled_rules=frozenset({"x"})),
    )
    text = cfg.to_canonical_json()
    restored = Config.from_json(text)
    assert restored == cfg
    assert restored.config_hash == cfg.config_hash
    # canonical form: compact, sorted keys, sets sorted
    assert text == json.dumps(json.loads(text), sort_keys=True, separators=(",", ":"))
    assert json.loads(text)["normalization"]["disabled_rules"] == ["y", "z"]


@pytest.mark.parametrize(
    "variant",
    [
        Config(parser=ParserBackend.LXML),
        Config(normalization=NormalizationConfig(disabled_rules=frozenset({"x"}))),
        Config(normalization=NormalizationConfig(enabled_rules=frozenset({"y"}))),
    ],
    ids=["parser", "disabled_rules", "enabled_rules"],
)
def test_any_field_change_changes_hash(variant: Config) -> None:
    assert variant.config_hash != Config().config_hash


def _field_names(model: type[BaseModel]) -> set[str]:
    names: set[str] = set()
    for name, info in model.model_fields.items():
        names.add(name)
        annotation = info.annotation
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            names |= _field_names(annotation)
    return names


def _json_keys(node: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            keys.add(key)
            keys |= _json_keys(value)
    elif isinstance(node, list):
        for item in node:
            keys |= _json_keys(item)
    return keys


def test_every_field_is_covered_by_canonical_json() -> None:
    """No field, present or future, may be silently excluded from the hash payload."""
    payload = json.loads(Config().to_canonical_json())
    missing = _field_names(Config) - _json_keys(payload)
    assert missing == set()


def test_hash_format() -> None:
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", Config().config_hash)


def test_ruleset_version_is_part_of_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    before = Config().config_hash
    from semdiff.normalize import registry  # module object: `semdiff.normalize` the attribute is the function

    monkeypatch.setattr(registry, "builtin_ruleset_version", lambda: "test-bump")
    assert Config().config_hash != before


def test_hash_is_identical_across_interpreters() -> None:
    code = (
        "from semdiff import Config, NormalizationConfig, ParserBackend;"
        "print(Config(parser=ParserBackend.LXML, normalization=NormalizationConfig("
        "disabled_rules=frozenset({'q','w','e','r','t','y'}), enabled_rules=frozenset({'a','s','d'}))).config_hash)"
    )
    local = Config(
        parser=ParserBackend.LXML,
        normalization=NormalizationConfig(
            disabled_rules=frozenset({"q", "w", "e", "r", "t", "y"}), enabled_rules=frozenset({"a", "s", "d"})
        ),
    ).config_hash
    for seed in ("0", "12345"):
        out = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            check=True,
            env={**os.environ, "PYTHONHASHSEED": seed},
        )
        assert out.stdout.strip() == local

