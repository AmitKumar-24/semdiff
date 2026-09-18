"""Shared pydantic base for every SemDiff model."""

from pydantic import BaseModel, ConfigDict


class FrozenModel(BaseModel):
    """Immutable, and unknown keys fail loud."""

    model_config = ConfigDict(frozen=True, extra="forbid")
