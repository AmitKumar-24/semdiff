"""Assert what a built source distribution carries (F-004, resolved at D-050).

The rule D-050 chose is *the code, plus the evidence the README cites*. The README's
limitations section sends readers to ``FINDINGS.md`` and ``docs/DECISIONS.md``, so a
distribution without them would publish a README pointing at files it does not contain; and
everything that is neither code nor evidence is left out. ``pyproject.toml`` holds the exclude
list and ``tests/test_package.py`` asserts that list, but a list is a statement of intent --
this checks the artifact it actually produced.

Usage::

    python scripts/check_sdist.py dist/semdiff_html-*.tar.gz

Exits 0 and prints what it found, or exits 1 naming every violation.
"""

from __future__ import annotations

import sys
import tarfile
from pathlib import Path

#: Present or the distribution is not usable, or not honest about its own citations.
REQUIRED = (
    "PKG-INFO",
    "pyproject.toml",
    "README.md",
    "LICENSE",
    "FINDINGS.md",
    "docs/DECISIONS.md",
    "docs/ARCHITECTURE.md",
    "src/semdiff/__init__.py",
    "src/semdiff/py.typed",
)
#: Absent, each for its own reason -- see D-050.
FORBIDDEN = (
    "tests/",
    "corpus/",
    ".github/",
    "scripts/",
    ".gitattributes",
    "docs/CLAUDE_CODE_INSTRUCTIONS.md",
)
#: Shipped although `pyproject.toml` excludes it, because the backend puts it back: hatchling's
#: sdist builder force-includes the VCS ignore files it used for its own exclusions, and a
#: force-include outranks the exclude list. Tolerated by name so that any *other* stray file
#: still fails, and so this stops being tolerated the day the backend stops doing it.
BACKEND_FORCED = (".gitignore",)


def members(archive: Path) -> list[str]:
    """Every file in the tarball, with the ``semdiff-<version>/`` prefix stripped."""
    with tarfile.open(archive) as tar:
        names = [member.name for member in tar.getmembers() if member.isfile()]
    return sorted(name.split("/", 1)[1] for name in names if "/" in name)


def check(archive: Path) -> list[str]:
    paths = members(archive)
    problems = [f"missing: {name}" for name in REQUIRED if name not in paths]
    for prefix in FORBIDDEN:
        found = [name for name in paths if name.startswith(prefix)]
        if found:
            shown = ", ".join(found[:4]) + (" …" if len(found) > 4 else "")
            problems.append(f"should not ship ({len(found)}): {shown}")
    stray = sorted(
        name
        for name in paths
        if name.startswith(".") and name not in BACKEND_FORCED
    )
    if stray:
        problems.append(f"unexpected dotfile(s): {', '.join(stray)}")
    print(f"{archive.name}: {len(paths)} files")
    for name in paths:
        if "/" not in name:
            print(f"  {name}")
    for top in sorted({name.split('/')[0] for name in paths if "/" in name}):
        print(f"  {top}/ ({sum(1 for name in paths if name.startswith(top + '/'))} files)")
    return problems


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    archives = [Path(item) for item in argv]
    missing = [str(path) for path in archives if not path.is_file()]
    if missing:
        print(f"no such file: {', '.join(missing)}", file=sys.stderr)
        return 2
    problems = [problem for archive in archives for problem in check(archive)]
    for problem in problems:
        print(f"FAIL {problem}", file=sys.stderr)
    if problems:
        print(f"\n{len(problems)} problem(s) — see D-050 for what the sdist carries", file=sys.stderr)
        return 1
    print("\nsdist contents match D-050")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
