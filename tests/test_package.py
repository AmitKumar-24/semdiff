"""T-00: package installs, exposes a version, and ships the py.typed marker.

The three dependency tests belong to D-047 and D-048. NFR-2 stopped being a package list and
became a principle — the core install is what the shipped layers actually import, a package is
declared by the release that first imports it, optional layers live in extras (D-047) — and a
principle with nothing enforcing it is exactly how `extruct` came to sit in the v0.1 core
install, pulling an HTTP client behind it, without a single line of `src/semdiff/` importing
it. These read the declaration from `pyproject.toml` rather than from installed metadata, so
they answer for the source of truth and do not need a reinstall to notice a change.

The packaging tests are D-050's, and they work the same way: NFR-9 names things a published
release must carry — a version, an extras surface, classifiers, a licence, `py.typed` — and
every one of them lives in `pyproject.toml`, where it can be asserted without building
anything. What they deliberately do not assert is a version *string*: the version has one
source (`semdiff.__version__`, read by Hatchling at build time), so a test that repeated it
would be a second source of the same truth and the next release would have to update both.
"""

from __future__ import annotations

import importlib.metadata
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
SOURCE = ROOT / "src" / "semdiff"
VERSION_FILE = SOURCE / "__init__.py"
VERSION_LITERAL = re.compile(r'^__version__ = "([^"]+)"(?:\s*#.*)?$', re.MULTILINE)
RELEASE_VERSION = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
# The public extras surface, frozen by the first upload (Q-01, D-050). `all` is the union of
# the feature extras and never carries `dev`.
FEATURE_EXTRAS = frozenset({"content", "ml"})
EXTRAS = FEATURE_EXTRAS | {"all", "dev"}
SELF_REFERENCE = re.compile(r"^semdiff\[([^\]]+)\]$")

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


def test_the_version_has_exactly_one_source() -> None:
    """D-050: Hatchling reads the version out of the package, so `pyproject.toml` must not
    carry one of its own. Two literals is how a release ships a wheel labelled with the
    previous version — this asserts the structure, never the number."""
    project = _project()
    assert "version" not in project, (
        "pyproject.toml declares a static version again. The version lives in "
        f"{VERSION_FILE.relative_to(ROOT).as_posix()} and Hatchling reads it from there (D-050)."
    )
    dynamic = project.get("dynamic", [])
    assert isinstance(dynamic, list)
    assert "version" in dynamic, "`version` is missing from project.dynamic"
    with PYPROJECT.open("rb") as handle:
        hatch_version = tomllib.load(handle)["tool"]["hatch"]["version"]
    assert isinstance(hatch_version, dict)
    assert hatch_version["path"] == VERSION_FILE.relative_to(ROOT).as_posix()


def test_the_version_is_a_release_version_and_the_module_agrees_with_the_file() -> None:
    import semdiff

    literal = VERSION_LITERAL.search(VERSION_FILE.read_text(encoding="utf-8"))
    assert literal is not None, f"no `__version__ = \"...\"` line in {VERSION_FILE.name}"
    assert semdiff.__version__ == literal.group(1)
    assert RELEASE_VERSION.match(semdiff.__version__), (
        f"{semdiff.__version__!r} is not a release version. 0.0.0 was the placeholder a "
        "release has to replace (NFR-9, D-050)."
    )
    assert semdiff.__version__ != "0.0.0"


def test_the_installed_distribution_reports_the_same_version() -> None:
    """The drift this catches is the one that survives a build: a wheel whose metadata says one
    version while the module it contains says another. Install metadata is written once, so
    after bumping `__version__` this needs a reinstall — which is the point."""
    import semdiff

    installed = importlib.metadata.version("semdiff")
    assert installed == semdiff.__version__, (
        f"installed metadata says {installed}, the package says {semdiff.__version__}. "
        'Reinstall (`pip install -e ".[dev]"`) if the version was just bumped; otherwise the '
        "build is picking the version up from somewhere else (D-050)."
    )


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


# ---- what a published release has to carry (NFR-9, D-050) ------------------------------------
def test_the_extras_are_the_decided_public_surface() -> None:
    """Q-01, resolved at D-050. An extra is a public name: `pip install semdiff[content]` in
    someone's requirements file cannot be renamed later without breaking their install, so the
    set is frozen by the first upload rather than discovered after it."""
    extras = _project()["optional-dependencies"]
    assert isinstance(extras, dict)
    assert set(extras) == EXTRAS, f"the published extras surface changed (Q-01, D-050): {set(extras)}"


def test_all_is_the_union_of_the_feature_extras_and_never_carries_dev() -> None:
    """`all` means "everything a user might want", not "everything a contributor needs".
    Pulling pytest and mypy into a user install would be the mistake this forbids."""
    extras = _project()["optional-dependencies"]
    assert isinstance(extras, dict)
    requirements = extras["all"]
    assert isinstance(requirements, list)
    referenced: set[str] = set()
    for requirement in requirements:
        match = SELF_REFERENCE.match(str(requirement).strip())
        assert match is not None, f"`all` should be a self-reference, got {requirement!r}"
        referenced |= {name.strip() for name in match.group(1).split(",")}
    assert referenced == FEATURE_EXTRAS, f"`all` resolves to {sorted(referenced)}"
    assert "dev" not in referenced


def test_the_published_metadata_is_complete() -> None:
    """NFR-9's PyPI clause, as far as a file can answer for it: a reader of the project page
    needs somewhere to click, and a release that still says it is being planned misinforms
    every one of them."""
    project = _project()
    classifiers = project["classifiers"]
    assert isinstance(classifiers, list)
    assert "Development Status :: 3 - Alpha" in classifiers
    assert not any("Development Status :: 1 - Planning" == item for item in classifiers)
    assert "Operating System :: OS Independent" in classifiers
    urls = project["urls"]
    assert isinstance(urls, dict)
    assert {"Homepage", "Repository", "Issues"} <= set(urls)
    assert all(str(url).startswith("https://") for url in urls.values()), urls
    keywords = project["keywords"]
    assert isinstance(keywords, list) and keywords


def test_python_support_matches_the_decision_that_set_it() -> None:
    """D-003 set >=3.11 and says so: "Supersedes NFR-9 / T-00 3.10+"."""
    assert _project()["requires-python"] == ">=3.11"


def test_the_build_backend_is_pinned_so_the_metadata_is_reproducible() -> None:
    """D-050: an unpinned backend makes the emitted `Metadata-Version` a property of the build
    machine. Two builds of one commit should not differ in metadata, so the pin is exact and
    bumping it is a deliberate act with its metadata effect re-checked."""
    with PYPROJECT.open("rb") as handle:
        requires = tomllib.load(handle)["build-system"]["requires"]
    assert isinstance(requires, list)
    pins = [str(item) for item in requires if str(item).startswith("hatchling")]
    assert len(pins) == 1, f"expected exactly one hatchling requirement, got {pins}"
    assert "==" in pins[0], f"hatchling is not pinned exactly: {pins[0]!r} (D-050)"


def test_the_sdist_keeps_the_code_and_the_evidence_the_readme_cites() -> None:
    """F-004, resolved at D-050. The README's limitations section tells readers to follow
    `FINDINGS.md` and `docs/DECISIONS.md`; a source distribution that dropped them would ship a
    README citing files it does not contain. What goes is what is neither code nor evidence."""
    with PYPROJECT.open("rb") as handle:
        sdist = tomllib.load(handle)["tool"]["hatch"]["build"]["targets"]["sdist"]
    excluded = sdist["exclude"]
    assert isinstance(excluded, list)
    excluded_paths = {str(item) for item in excluded}
    for path in (
        "corpus/",
        "tests/",
        ".github/",
        ".gitignore",
        ".gitattributes",
        "scripts/",
        "docs/CLAUDE_CODE_INSTRUCTIONS.md",
    ):
        assert path in excluded_paths, f"{path} is no longer excluded from the sdist (D-050)"
    # This asserts the list, which is a statement of intent; `scripts/check_sdist.py` asserts
    # the artifact. The two disagree about exactly one file: hatchling force-includes the VCS
    # ignore files it used for its own exclusions, so `.gitignore` ships whatever this says.
    for kept in ("FINDINGS.md", "docs/DECISIONS.md", "README.md", "LICENSE"):
        assert kept not in excluded_paths, (
            f"{kept} is cited by the README or required by NFR-9; excluding it from the sdist "
            "would publish a README pointing at files the distribution does not carry (D-050)."
        )
