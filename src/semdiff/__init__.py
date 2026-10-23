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
from semdiff.parse import PARSER_ID, PARSER_VERSION, ParsedDoc, parse, parser_fingerprint

__version__ = "0.1.0"  # the one source; Hatchling reads it at build time (D-050)

__all__ = [
    "PARSER_ID",
    "PARSER_VERSION",
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
    "parser_fingerprint",
]
