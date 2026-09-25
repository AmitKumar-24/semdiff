"""SemDiff: semantic HTML change detection."""

from semdiff.config import Config, NormalizationConfig, ParserBackend
from semdiff.errors import (
    AlignmentBudgetExceeded,
    ErrorRecord,
    InputTooLargeError,
    ParseError,
    SemDiffError,
)
from semdiff.normalize.api import normalize
from semdiff.parse import ParsedDoc, parse

__version__ = "0.0.0"

__all__ = [
    "AlignmentBudgetExceeded",
    "Config",
    "ErrorRecord",
    "InputTooLargeError",
    "NormalizationConfig",
    "ParseError",
    "ParsedDoc",
    "ParserBackend",
    "SemDiffError",
    "__version__",
    "normalize",
    "parse",
]
