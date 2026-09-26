"""Command line interface (T-20, FR-29): ``semdiff normalize file.html``.

A thin shell over the T-19 API. stdout carries normalized HTML and nothing else, so it
can always be redirected into a file; diagnostics and the ``--report`` summary go to
stderr. Every typed error from T-02 maps to its own exit code, so a script can tell an
oversized input from a parse failure without reading the message.

Rule provenance comes from ``apply_rules`` as D-033 anticipated — there is no second
reporting model.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from collections.abc import Callable
from pathlib import Path

from semdiff import Config, NormalizationConfig, SemDiffError, __version__
from semdiff.normalize import BUILTIN_RULES, NormalizedDoc, apply_rules
from semdiff.parse import parse

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2  # argparse's own code for a bad command line
EXIT_PARSE = 3
EXIT_TOO_LARGE = 4
EXIT_CONFIG = 5
EXIT_IO = 6

_EXIT_BY_ERROR_TYPE = {"parse_error": EXIT_PARSE, "input_too_large": EXIT_TOO_LARGE}


def _read_stdin() -> bytes:
    """Raw bytes, so the parser's encoding detection (T-10) still applies."""
    return sys.stdin.buffer.read()


def _write_stdout(text: str) -> None:
    """Always UTF-8, whatever the console claims to be: the output is a document."""
    sys.stdout.buffer.write(text.encode("utf-8"))
    sys.stdout.buffer.flush()


def _fail(message: str, code: int) -> int:
    print(f"semdiff: {message}", file=sys.stderr)
    return code


def _load_config(args: argparse.Namespace) -> Config:
    config = Config()
    if args.config is not None:
        config = Config.from_json(Path(args.config).read_text(encoding="utf-8"))
    normalization = NormalizationConfig(
        disabled_rules=config.normalization.disabled_rules | frozenset(args.disable_rule),
        enabled_rules=config.normalization.enabled_rules | frozenset(args.enable_rule),
    )
    return config.model_copy(update={"normalization": normalization})


def _report(result: NormalizedDoc) -> str:
    """One line per rule that fired, in the order the rules ran, with application counts."""
    counts = Counter(application.rule_id for application in result.applied_rules)
    if not counts:
        return "no rules fired\n"
    width = max(len(rule_id) for rule_id in counts)
    lines = [f"{len(counts)} rules fired, {sum(counts.values())} applications"]
    lines += [f"  {rule_id:<{width}}  {count}" for rule_id, count in counts.items()]
    return "\n".join(lines) + "\n"


def _normalize(args: argparse.Namespace) -> int:
    try:
        config = _load_config(args)
    except OSError as exc:
        return _fail(f"cannot read config: {exc}", EXIT_IO)
    except (ValueError, TypeError) as exc:
        return _fail(f"invalid config: {exc}", EXIT_CONFIG)

    try:
        source = _read_stdin() if args.file in (None, "-") else Path(args.file).read_bytes()
    except OSError as exc:
        return _fail(f"cannot read input: {exc}", EXIT_IO)

    try:
        doc = parse(source, encoding=args.encoding, config=config)
        result = apply_rules(doc, BUILTIN_RULES, config.normalization)
    except SemDiffError as exc:
        return _fail(f"{exc.type_id}: {exc.message}", _EXIT_BY_ERROR_TYPE.get(exc.type_id, EXIT_ERROR))
    except ValueError as exc:  # unknown rule id in a toggle
        return _fail(f"invalid config: {exc}", EXIT_CONFIG)

    html = result.tree.html or ""
    try:
        if args.output is None:
            _write_stdout(html)
        else:
            Path(args.output).write_bytes(html.encode("utf-8"))
    except OSError as exc:
        return _fail(f"cannot write output: {exc}", EXIT_IO)

    if args.report:
        sys.stderr.write(_report(result))
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="semdiff", description="Semantic HTML change detection.")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)

    normalize_parser = commands.add_parser(
        "normalize",
        help="strip presentational noise from an HTML document and canonicalize it",
        description="Write the normalized document to stdout, or to --output.",
    )
    normalize_parser.add_argument("file", nargs="?", help="input file; omit or pass - to read stdin")
    normalize_parser.add_argument("-o", "--output", help="write to this file instead of stdout")
    normalize_parser.add_argument("--report", action="store_true", help="list the rules that fired, on stderr")
    normalize_parser.add_argument("--config", help="JSON config file (see Config.to_canonical_json)")
    normalize_parser.add_argument(
        "--disable-rule", action="append", default=[], metavar="ID", help="turn one rule off; repeatable"
    )
    normalize_parser.add_argument(
        "--enable-rule", action="append", default=[], metavar="ID", help="turn one opt-in rule on; repeatable"
    )
    normalize_parser.add_argument("--encoding", help="override the input encoding instead of detecting it")
    normalize_parser.set_defaults(handler=_normalize)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handler: Callable[[argparse.Namespace], int] = args.handler
    return handler(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
