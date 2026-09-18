"""Typed error hierarchy (T-02).

Every failure inside the pipeline is a ``SemDiffError`` subclass. Layers raise them;
the public API boundary converts them into ``ErrorRecord`` entries in ``errors[]``
so a caller never receives a partial diff presented as complete (FR-3, ARCHITECTURE
"Fail loud, fail typed").
"""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import field_serializer

from semdiff._models import FrozenModel

SnapshotLabel = Literal["old", "new"]
DetailValue = str | int | None


class ErrorRecord(FrozenModel):
    """One element of ``DiffResult.errors``."""

    type: str
    message: str
    snapshot: SnapshotLabel | None = None
    detail: dict[str, DetailValue] = {}

    @field_serializer("detail")
    def _sorted_detail(self, value: dict[str, DetailValue]) -> dict[str, DetailValue]:
        return dict(sorted(value.items()))


class SemDiffError(Exception):
    """Root of the hierarchy. ``type_id`` is the stable id used in ``errors[].type``."""

    type_id: ClassVar[str] = "semdiff_error"

    def __init__(self, message: str, *, snapshot: SnapshotLabel | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.snapshot = snapshot

    def detail(self) -> dict[str, DetailValue]:
        return {}

    def to_record(self) -> ErrorRecord:
        return ErrorRecord(
            type=self.type_id, message=self.message, snapshot=self.snapshot, detail=self.detail()
        )


class ParseError(SemDiffError):
    """A snapshot could not be parsed into a tree (FR-3)."""

    type_id = "parse_error"


class InputTooLargeError(SemDiffError):
    """A snapshot exceeds the documented input size ceiling (NFR-7)."""

    type_id = "input_too_large"

    def __init__(self, size: int, limit: int, *, snapshot: SnapshotLabel | None = None) -> None:
        super().__init__(f"input is {size} bytes; ceiling is {limit} bytes", snapshot=snapshot)
        self.size = size
        self.limit = limit

    def detail(self) -> dict[str, DetailValue]:
        return {"size": self.size, "limit": self.limit}


class AlignmentBudgetExceeded(SemDiffError):
    """Tree-edit-distance alignment ran past its budget (v0.3, T-75). Fields arrive with T-75."""

    type_id = "alignment_budget_exceeded"
