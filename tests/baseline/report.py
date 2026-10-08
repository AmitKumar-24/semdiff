"""T-22 benchmark: run every baseline over every noise_only pair and print the table.

    python -m tests.baseline.report              # markdown table
    python -m tests.baseline.report --json       # machine-readable
    python -m tests.baseline.report --repeat 5   # best-of-5 timings

Deterministic and offline: it reads the committed corpus and calls nothing but the differs.
Timings are best-of-N wall clock over the whole pair (both snapshots), per tool.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import time
from collections.abc import Callable
from dataclasses import dataclass

from tests.baseline.metrics import (
    changed_line_bytes,
    difflib_raw_lines,
    difflib_raw_words,
    difflib_text_words,
    lxml_html_diff_marks,
    semdiff_changes,
)
from tests.corpus.labels import Category
from tests.corpus.loader import Pair, load_pairs

Metric = Callable[[bytes, bytes], int]

TOOLS: tuple[tuple[str, Metric], ...] = (
    ("difflib_lines", difflib_raw_lines),
    ("difflib_words", difflib_raw_words),
    ("difflib_text", difflib_text_words),
    ("lxml_htmldiff", lxml_html_diff_marks),
    ("semdiff", semdiff_changes),
)


@dataclass(frozen=True)
class Row:
    id: str
    families: list[str]
    bytes: int
    changed_line_bytes: int
    counts: dict[str, int]
    millis: dict[str, float]


def measure(metric: Metric, pair: Pair, repeat: int) -> tuple[int, float]:
    """Return the metric's count and its best-of-``repeat`` wall clock in milliseconds."""
    best = float("inf")
    count = 0
    for _ in range(repeat):
        start = time.perf_counter()
        count = metric(pair.old_bytes, pair.new_bytes)
        best = min(best, time.perf_counter() - start)
    return count, best * 1000


def run(repeat: int = 3) -> list[Row]:
    rows: list[Row] = []
    for pair in load_pairs(category=Category.NOISE_ONLY):
        counts: dict[str, int] = {}
        millis: dict[str, float] = {}
        for name, metric in TOOLS:
            counts[name], millis[name] = measure(metric, pair, repeat)
        rows.append(
            Row(
                id=pair.id,
                families=[family.value for family in (pair.label.noise_families or [])],
                bytes=len(pair.old_bytes),
                changed_line_bytes=changed_line_bytes(pair.old_bytes, pair.new_bytes),
                counts=counts,
                millis={name: round(value, 1) for name, value in millis.items()},
            )
        )
    return rows


def markdown(rows: list[Row]) -> str:
    names = [name for name, _ in TOOLS]
    lines = [
        "| pair | family | KiB | " + " | ".join(names) + " |",
        "|---|---|---:|" + "---:|" * len(names),
    ]
    for row in rows:
        counts = " | ".join(str(row.counts[name]) for name in names)
        lines += [f"| {row.id} | {','.join(row.families)} | {row.bytes / 1024:.0f} | {counts} |"]

    lines += ["", f"| tool | pairs flagged of {len(rows)} | total units | median ms |", "|---|---:|---:|---:|"]
    for name in names:
        flagged = sum(1 for row in rows if row.counts[name] > 0)
        total = sum(row.counts[name] for row in rows)
        times = sorted(row.millis[name] for row in rows)
        lines += [f"| {name} | {flagged} | {total} | {times[len(times) // 2]:.1f} |"]

    shown = sum(row.changed_line_bytes for row in rows)
    whole = sum(row.bytes for row in rows)
    lines += [
        "",
        f"difflib_lines reports {len(rows)} changed lines totalling {shown / 1024:.0f} KiB out of "
        f"{whole / 1024:.0f} KiB of document: {100 * shown / whole:.0f}% of the corpus sits inside "
        f"a line it calls changed.",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    parser.add_argument("--repeat", type=int, default=3, help="timing repetitions (default 3)")
    args = parser.parse_args()
    rows = run(args.repeat)
    print(json.dumps([dataclasses.asdict(row) for row in rows], indent=2) if args.json else markdown(rows))


if __name__ == "__main__":
    main()
