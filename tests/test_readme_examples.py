"""The README's worked examples, executed rather than reviewed.

v0.1.0 shipped a documented output that no version has ever produced: the example showed a
dynamic class vanishing, when a hash is *replaced* by ``__semdiff__`` and always was
(``tests/normalize/test_assets.py`` pins the behaviour, so only the prose had drifted). Every
other claim in that file is asserted somewhere -- the limitations catalogue, the corpus counts,
the guarantees -- and the one worked example was not, so it drifted unnoticed into the
repository and from there onto the PyPI project page, which renders the same README.

The extractor is deliberately narrow. It runs a call to ``semdiff.normalize`` whose arguments
are all literals, and nothing else, so a README can never become a way to execute arbitrary
code inside the suite. Anything it does not understand it skips, and
``test_the_readme_still_carries_a_worked_example`` fails if the example it does understand is
deleted -- otherwise skipping everything would read as passing.

What it does not check is the parser build printed in the ``--report`` sample or named in the
guarantees: that is whatever selectolax the reader installed, so pinning it here would only
move the staleness from the README into a test.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

import semdiff

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
#: A fenced ``python`` block, captured whole.
BLOCK = re.compile(r"^```python\n(.*?)^```", re.DOTALL | re.MULTILINE)
#: A call on one line, with its documented result on the next as a quoted literal.
WORKED = re.compile(r"^(semdiff\.normalize\(.*\))\n# (['\"].*)$", re.MULTILINE)


def examples() -> list[tuple[str, str]]:
    """Every (call, documented output) pair the README states and this test can run."""
    found: list[tuple[str, str]] = []
    for block in BLOCK.findall(README.read_text(encoding="utf-8")):
        found.extend(WORKED.findall(block))
    return found


def test_the_readme_still_carries_a_worked_example() -> None:
    """Without this, deleting the example would turn the test below into a silent no-op."""
    assert examples(), "no README example is being checked any more"


@pytest.mark.parametrize("call, documented", examples())
def test_the_documented_output_is_what_normalize_returns(call: str, documented: str) -> None:
    """The README is a published artifact: its output lines are claims about this code."""
    node = ast.parse(call, mode="eval").body
    assert isinstance(node, ast.Call), call
    assert ast.unparse(node.func) == "semdiff.normalize", call
    arguments = [ast.literal_eval(argument) for argument in node.args]
    keywords = {
        keyword.arg: ast.literal_eval(keyword.value)
        for keyword in node.keywords
        if keyword.arg is not None
    }
    produced = semdiff.normalize(*arguments, **keywords)
    assert produced == ast.literal_eval(documented), (
        f"README.md documents\n  {ast.literal_eval(documented)!r}\nbut normalize returns\n"
        f"  {produced!r}\n({semdiff.parser_fingerprint()})"
    )
