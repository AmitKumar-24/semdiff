"""T-00: package installs, exposes a version, and ships the py.typed marker.

The three dependency tests belong to D-047 and D-048. NFR-2 stopped being a package list and
became a principle — the core install is what the shipped layers actually import, a package is
declared by the release that first imports it, optional layers live in extras (D-047) — and a
principle with nothing enforcing it is exactly how `extruct` came to sit in the v0.1 core
install, pulling an HTTP client behind it, without a single line of `src/semdiff/` importing
it. These read the declaration from `pyproject.toml` rather than from installed metadata, so
they answer for the source of truth and do not need a reinstall to notice a change.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
SOURCE = ROOT / "src" / "semdiff"

# What a shipped layer imports: L0 parses with selectolax, every model is pydantic.
IMPORTED = frozenset({"selectolax", "pydantic"})
# lxml is not one of them. D-047 kept it in the core install as a named exception, declared
# ahead of the second parser backend FR-2 reserves it for; D-048 deferred that backend (T-11)
# out of v0.1, which left the exception without its reason, so lxml moved to the one place
# that does import it — `tests/baseline`, which measures SemDiff against `lxml.html.diff`
# (T-22). It returns to the core install with the release that first imports it.
DEV_ONLY = frozenset({"lxml"})
LXML_IMPORT = re.compile(r"^\s*(?:import|from)\s+lxml\b", re.MULTILINE)
BASELINE = ROOT / "tests" / "baseline"


def test_version() -> None:
    import semdiff

    assert semdiff.__version__ == "0.0.0"


def test_py_typed_marker() -> None:
    import semdiff

    assert (Path(semdiff.__file__).parent / "py.typed").is_file()


def _project() -> dict[str, object]:
    with PYPROJECT.open("rb") as handle:
        project: dict[str, object] = tomllib.load(handle)["project"]
    return project


def _names(requirements: object) -> frozenset[str]:
    """Package names, stripped of versions, extras and environment markers."""
    assert isinstance(requirements, list)
    return frozenset(
        re.split(r"[<>=!~;\[\s]", str(requirement), maxsplit=1)[0].strip()
        for requirement in requirements
    )


def declared_core() -> frozenset[str]:
    """Package names in ``[project.dependencies]``."""
    return _names(_project()["dependencies"])


def declared_dev() -> frozenset[str]:
    """Package names in the ``dev`` extra."""
    extras = _project()["optional-dependencies"]
    assert isinstance(extras, dict)
    return _names(extras["dev"])


def test_the_core_install_is_only_what_the_shipped_layers_import() -> None:
    """NFR-2 as a test (D-047).

    Adding a package to the core install is a change to the dependency budget: it belongs to
    the release that first imports it, with its footprint measured. The failure message says
    so, because the mistake this guards against is a plausible-looking line added in passing —
    which is how a normalization-only release came to install `requests`, `urllib3`, `rdflib`,
    `beautifulsoup4` and `html5lib` (F-001).
    """
    assert declared_core() == IMPORTED, (
        "the declared core install changed. A dependency belongs to the release that first "
        "imports it, with its install footprint measured (NFR-2, D-047); a package an "
        "optional layer needs belongs in an extra, and one only the tests need belongs in "
        "`dev` (D-048)."
    )


def test_lxml_is_a_development_dependency_and_the_baseline_is_why() -> None:
    """Both halves of D-048's dependency move, so neither can rot alone.

    `lxml` is declared in `dev` because `tests/baseline` imports `lxml.html.diff` for the
    published comparison (T-22) — the one thing in this repository that needs it. If that
    import ever goes, the declaration has lost its reason and should go with it, which is
    what the second assertion is for.
    """
    assert DEV_ONLY <= declared_dev(), (
        "lxml is not declared in the `dev` extra, but `tests/baseline` imports it: a fresh "
        '`pip install -e ".[dev]"` would not be able to run the baseline comparison (T-22).'
    )
    importers = sorted(
        path.relative_to(ROOT).as_posix()
        for path in BASELINE.rglob("*.py")
        if LXML_IMPORT.search(path.read_text(encoding="utf-8"))
    )
    assert importers, (
        "nothing under tests/baseline imports lxml any more, so the `dev` declaration has "
        "outlived its reason (D-048)."
    )


def test_nothing_shipped_imports_lxml_so_the_core_install_may_omit_it() -> None:
    """The tripwire that puts lxml back.

    No shipped layer imports lxml today, which is the whole basis for leaving it out of the
    core install (D-048). The day the second parser backend lands (FR-2, T-11), `src/semdiff/`
    imports it, this test fails, and the declaration has to move back into
    `[project.dependencies]` — where the principle in NFR-2 says it belongs the moment a
    shipped layer imports it.
    """
    importers = sorted(
        path.relative_to(ROOT).as_posix()
        for path in SOURCE.rglob("*.py")
        if LXML_IMPORT.search(path.read_text(encoding="utf-8"))
    )
    assert importers == [], (
        f"lxml is now imported by {importers}, so it is no longer a development dependency. "
        "T-11 has landed: move lxml into [project.dependencies] and revisit D-048."
    )
