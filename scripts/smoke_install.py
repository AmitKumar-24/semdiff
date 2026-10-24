"""Assert that an *installed* semdiff-html behaves, from outside its own source tree (D-050).

The CI packaging job and the release workflow both install the built artifacts into a clean
environment, and what they need to know is what a user needs: that the distribution is
``semdiff-html``, that the import package and the console script are both ``semdiff``, that the
version is real and agrees everywhere it is written, that ``py.typed`` shipped, that
normalization works through the API and through the command, and that a core install carries no
development dependency. One script, so the two workflows cannot drift apart and so the same
checks can be run by hand against a venv.

Run it with the interpreter of the environment under test, never the development one::

    /tmp/clean/bin/python scripts/smoke_install.py
    SEMDIFF_EXPECT_VERSION=0.1.0 /tmp/clean/bin/python scripts/smoke_install.py

``SEMDIFF_EXPECT_VERSION`` adds one assertion: the installed distribution reports exactly that
version. The release workflow passes the pushed tag, which is how the tag is validated against
the artifact that is about to be published.

Two things make it refuse an environment on purpose, and neither is a bug to work
around. Run with a development interpreter it reports that ``semdiff`` resolved to the
working tree and stops, because then it would be testing the checkout and not the
artifact; build and install first. Run against a virtualenv that holds development
packages for unrelated reasons and the dev-dependency check fails, since in CI that is
exactly the defect it exists to catch. ``--allow-dev-extras`` downgrades *that one check*
to a printed note for a hand-run; nothing passes it in CI, where the script is invoked
with no arguments at all.

Exits 0 and prints what it found, or exits 1 naming every violation.
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import os
import subprocess
import sys
import sysconfig
from pathlib import Path

#: The distribution name is the one name that differs from the import name (D-050).
DISTRIBUTION = "semdiff-html"
IMPORT_PACKAGE = "semdiff"
CONSOLE_SCRIPT = "semdiff"
#: What a build that lost `[tool.hatch.version]` would emit.
PLACEHOLDER = "0.0.0"
SAMPLE = "<p>x</p>"
CANONICAL = "<html><head></head><body><p>x</p></body></html>"
#: Declared in `[dev]` and imported by nothing under `src/` (D-048), so a core install that
#: drags one of these in has a dependency the library does not need.
DEV_ONLY = ("lxml",)
#: The one check a hand-run may waive, because a development virtualenv legitimately
#: carries these. CI passes no arguments, so CI cannot waive it by accident.
ALLOW_DEV = "--allow-dev-extras"
#: This file's repository, so a run against the working tree fails loudly instead of passing
#: for the wrong reason -- an editable install left behind is exactly how that happens.
REPOSITORY = Path(__file__).resolve().parent.parent


def command_path() -> Path:
    """Where the console script landed in *this* interpreter's environment."""
    name = CONSOLE_SCRIPT + (".exe" if sys.platform == "win32" else "")
    return Path(sysconfig.get_path("scripts")) / name


def main(argv: list[str]) -> int:
    allow_dev = ALLOW_DEV in argv
    unknown = [argument for argument in argv if argument != ALLOW_DEV]
    if unknown:
        print(f"unexpected argument(s): {' '.join(unknown)}", file=sys.stderr)
        print(__doc__, file=sys.stderr)
        return 2

    try:
        import semdiff
    except Exception as error:
        print(f"FAIL cannot import {IMPORT_PACKAGE}: {error!r}", file=sys.stderr)
        return 1

    module = Path(semdiff.__file__ or "").resolve()
    if REPOSITORY in module.parents:
        print(
            f"FAIL {IMPORT_PACKAGE} resolved to the working tree ({module}), not to an installed"
            " distribution: run this with the interpreter of the environment under test",
            file=sys.stderr,
        )
        return 1

    try:
        version = importlib.metadata.version(DISTRIBUTION)
    except importlib.metadata.PackageNotFoundError:
        print(f"FAIL no installed distribution named {DISTRIBUTION}", file=sys.stderr)
        return 1

    problems: list[str] = []
    if version == PLACEHOLDER:
        problems.append(f"the placeholder version shipped: {version}")
    if semdiff.__version__ != version:
        problems.append(
            f"{IMPORT_PACKAGE}.__version__ is {semdiff.__version__}, the distribution says {version}"
        )
    expected = os.environ.get("SEMDIFF_EXPECT_VERSION")
    if expected is not None and expected != version:
        problems.append(f"expected version {expected}, installed {version}")

    if not (module.parent / "py.typed").is_file():
        problems.append("py.typed is missing, so the annotations never reach a type checker")

    produced = semdiff.normalize(SAMPLE)
    if produced != CANONICAL:
        problems.append(f"normalize({SAMPLE!r}) returned {produced!r}")

    entry_points = importlib.metadata.distribution(DISTRIBUTION).entry_points
    console = {entry.name: entry.value for entry in entry_points if entry.group == "console_scripts"}
    if console != {CONSOLE_SCRIPT: f"{IMPORT_PACKAGE}.cli:main"}:
        problems.append(f"the console_scripts entry point is {console}")

    command = command_path()
    if not command.is_file():
        problems.append(f"the {CONSOLE_SCRIPT} command was not installed at {command}")
    else:
        wanted = f"{version} ({semdiff.parser_fingerprint()})"
        printed = subprocess.run([str(command), "--version"], capture_output=True, text=True)
        if printed.returncode != 0 or printed.stdout.strip() != wanted:
            problems.append(
                f"{CONSOLE_SCRIPT} --version exited {printed.returncode} and printed"
                f" {printed.stdout.strip()!r}, wanted {wanted!r}"
            )
        # stdout carries the document and nothing else, so this compares bytes, not lines.
        piped = subprocess.run(
            [str(command), "normalize", "-"], input=SAMPLE.encode("utf-8"), capture_output=True
        )
        if piped.returncode != 0 or piped.stdout != CANONICAL.encode("utf-8"):
            problems.append(
                f"{CONSOLE_SCRIPT} normalize - exited {piped.returncode} and wrote {piped.stdout!r}"
            )

    notes: list[str] = []
    for name in DEV_ONLY:
        if importlib.util.find_spec(name) is not None:
            complaint = f"{name} is importable: a core install must not carry a dev dependency"
            (notes if allow_dev else problems).append(complaint)

    print(f"{DISTRIBUTION} {version} at {module.parent}")
    print(f"  {IMPORT_PACKAGE}.__version__ {semdiff.__version__}, {semdiff.parser_fingerprint()}")
    print(f"  {CONSOLE_SCRIPT} at {command}")
    for note in notes:
        print(f"  NOTE {note} -- waived by {ALLOW_DEV}")
    for problem in problems:
        print(f"FAIL {problem}", file=sys.stderr)
    if problems:
        print(f"\n{len(problems)} problem(s) in the installed distribution", file=sys.stderr)
        return 1
    print("\nthe installed distribution behaves")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
