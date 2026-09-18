"""T-02: typed error hierarchy that raises and serializes into ``errors[]``."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from semdiff import (
    AlignmentBudgetExceeded,
    ErrorRecord,
    InputTooLargeError,
    ParseError,
    SemDiffError,
)

ALL_ERRORS: list[type[SemDiffError]] = [ParseError, InputTooLargeError, AlignmentBudgetExceeded]


@pytest.mark.parametrize("cls", ALL_ERRORS)
def test_hierarchy(cls: type[SemDiffError]) -> None:
    assert issubclass(cls, SemDiffError)
    assert issubclass(cls, Exception)


def test_each_raises_and_is_caught_by_root() -> None:
    instances: list[SemDiffError] = [
        ParseError("bad html"),
        InputTooLargeError(12, 10),
        AlignmentBudgetExceeded("over budget"),
    ]
    for exc in instances:
        with pytest.raises(SemDiffError):
            raise exc


def test_str_is_message() -> None:
    assert str(ParseError("bad html")) == "bad html"
    assert str(AlignmentBudgetExceeded("over budget")) == "over budget"


def test_type_ids_are_frozen_contract() -> None:
    assert ParseError.type_id == "parse_error"
    assert InputTooLargeError.type_id == "input_too_large"
    assert AlignmentBudgetExceeded.type_id == "alignment_budget_exceeded"
    assert len({cls.type_id for cls in ALL_ERRORS}) == len(ALL_ERRORS)


def test_parse_error_record() -> None:
    record = ParseError("bad html", snapshot="new").to_record()
    assert record == ErrorRecord(type="parse_error", message="bad html", snapshot="new", detail={})


def test_input_too_large_record() -> None:
    exc = InputTooLargeError(12, 10, snapshot="old")
    record = exc.to_record()
    assert record.type == "input_too_large"
    assert record.snapshot == "old"
    assert record.detail == {"size": 12, "limit": 10}
    assert "12" in record.message and "10" in record.message


def test_alignment_budget_exceeded_record() -> None:
    record = AlignmentBudgetExceeded("over budget").to_record()
    assert record.type == "alignment_budget_exceeded"
    assert record.message == "over budget"
    assert record.snapshot is None
    assert record.detail == {}


def test_error_record_is_frozen_and_strict() -> None:
    record = ErrorRecord(type="parse_error", message="x")
    with pytest.raises(ValidationError):
        record.message = "y"
    with pytest.raises(ValidationError):
        ErrorRecord.model_validate({"type": "parse_error", "message": "x", "extra": 1})
    with pytest.raises(ValidationError):
        ErrorRecord(type="parse_error", message="x", snapshot="middle")  # type: ignore[arg-type]


def test_error_record_json_is_deterministic_and_round_trips() -> None:
    a = ErrorRecord(type="input_too_large", message="m", detail={"size": 2, "limit": 1})
    b = ErrorRecord(type="input_too_large", message="m", detail={"limit": 1, "size": 2})
    assert a.model_dump_json() == b.model_dump_json()
    assert list(json.loads(a.model_dump_json())["detail"]) == ["limit", "size"]
    assert ErrorRecord.model_validate_json(a.model_dump_json()) == a
