"""T-00: package installs, exposes a version, and ships the py.typed marker.

The two dependency tests are T-30's. NFR-2 stopped being a package list and became a
principle — the core install is what the shipped layers actually import, a package is
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
# The one package declared ahead of its use. FR-2 names lxml as a second parser backend and
# T-11 has not been built, so nothing imports it yet; D-047 records the exception as
# deliberate rather than as the same drift extruct represented.
RESERVED = frozenset({"lxml"})
LXML_IMPORT = re.compile(r"^\s*(?:import|from)\s+lxml\b", re.MULTILINE)


def test_version() -> None:
    import semdiff

    assert semdiff.__version__ == "0.0.0"


def test_py_typed_marker() -> None:
    import semdiff

    assert (Path(semdiff.__file__).parent / "py.typed").is_file()


def declared_core() -> frozenset[str]:
    """Package names in ``[project.dependencies]``, stripped of versions and markers."""
    with PYPROJECT.open("rb") as handle:
        project: dict[str, object] = tomllib.load(handle)["project"]
    requirements = project["dependencies"]
    assert isinstance(requirements, list)
    return frozenset(
        re.split(r"[<>=!~;\[\s]", str(requirement), maxsplit=1)[0].strip()
        for requirement in requirements
    )


def test_the_core_install_is_only_what_the_shipped_layers_import() -> None:
    """NFR-2 as a test (D-047).

    Adding a package to the core install is a change to the dependency budget: it belongs to
    the release that first imports it, with its footprint measured. The failure message says
    so, because the mistake this guards against is a plausible-looking line added in passing —
    which is how a normalization-only release came to install `requests`, `urllib3`, `rdflib`,
    `beautifulsoup4` and `html5lib` (F-001).
    """
    assert declared_core() == IMPORTED | RESERVED, (
        "the declared core install changed. A dependency belongs to the release that first "
        "imports it, with its install footprint measured (NFR-2, D-047); a package an "
        "optional layer needs belongs in an extra."
    )


def test_lxml_is_declared_ahead_of_its_use_and_nothing_imports_it_yet() -> None:
    """The one exception, and the tripwire that retires it.

    `lxml` is in the core install although no shipped layer imports it, because FR-2 names it
    as a second parser backend (`parser="lxml"`) and T-11 has not been built. The day T-11
    lands, `src/semdiff/` imports lxml, this test fails, and the exception stops being one —
    at which point this becomes a plain assertion that the backend is wired up. Until then it
    keeps a deliberate exception from decaying into the drift D-047 was written to end.
    """
    assert RESERVED <= declared_core(), "lxml is reserved by FR-2; removing it is a T-11 decision"
    importers = sorted(
        path.relative_to(ROOT).as_posix()
        for path in SOURCE.rglob("*.py")
        if LXML_IMPORT.search(path.read_text(encoding="utf-8"))
    )
    assert importers == [], (
        f"lxml is now imported by {importers}, so it is no longer declared ahead of its use. "
        "T-11 has landed: revisit this test and D-047's named exception."
    )
