"""T-29: the public path opens no outbound connection (FR-4, NFR-8).

FR-4 says there is no network I/O during a diff and that the engine "must not silently retry
over the network"; NFR-8 says no outbound requests. Both were true by inspection and untested,
which is the weakest form of a safety claim — the README states it to users.

**Why this is not a check on imports.** ``import semdiff`` already pulls in ``socket`` and
``urllib.parse``, because pydantic imports them (and until D-047 a full install also carried
``requests`` and ``urllib3`` through ``extruct``, which that decision removed from the core
install; that changes the install rather than this reasoning). Asserting that no networking
module is loaded would therefore fail today while proving nothing: a module that is imported
and never called opens no connection, and a module that is *not* imported can still be
imported later by the code under test. So the guard watches the only thing that matters —
the moment a socket is pointed at an address.

**What the guard intercepts.** Every entry point through which the standard library reaches
the network: ``socket.socket.connect``, ``connect_ex``, ``sendto`` and ``sendmsg`` (where the
platform has it), plus ``socket.create_connection``, ``socket.getaddrinfo`` and
``socket.gethostbyname``. Name resolution counts: a DNS lookup is already an outbound packet,
and it is what an accidental fetch does first. Creating a socket object is *not* intercepted,
because it touches nothing.

**Why an attempt is recorded as well as raised.** The refusal is a ``BaseException`` subclass
and every blocked call appends to a list before raising. A guard that only raised could be
defeated by an ``except Exception`` anywhere in the call path, turning a broken guarantee into
a green test; the recorded list is checked after the call returns, so swallowing the exception
cannot hide the attempt.

**Scope.** This is evidence over the inputs exercised, not a proof over every input or every
execution path. The patches are Python-level, so a call straight into ``_socket``, a shell-out
through ``os``/``subprocess``, or a socket opened inside a C extension would not be seen; and
NFR-8's clause about extruct paths has nothing to exercise while ``extruct`` is neither in the
core install nor imported (D-047). F-033 records both gaps with the measurements behind them,
and separates them from
any evidence that SemDiff actually does these things — there is none.
"""

from __future__ import annotations

import re
import socket
import subprocess
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import NoReturn

import pytest

import semdiff
from semdiff.cli import main
from tests.corpus.labels import Category
from tests.corpus.loader import Pair, load_pairs

PAIRS = load_pairs(category=Category.NOISE_ONLY)
SNAPSHOTS = [
    pytest.param(pair, which, id=f"{pair.id}-{which}")
    for pair in PAIRS
    for which in ("old", "new")
]

# RFC 5737 TEST-NET-1 and RFC 2606 .invalid: addresses reserved so they can never route, so a
# guard that failed open would still not reach a real host.
UNROUTABLE = "192.0.2.1"
UNRESOLVABLE = "semdiff-t29.invalid"

# Markup that invites a fetch at every point a browser would make one, plus an external entity.
# None of it may produce a connection: FR-4's "simply absent", not "fetched quietly".
BAIT = f"""<!DOCTYPE html [<!ENTITY xxe SYSTEM "http://{UNROUTABLE}/entity">]>
<html><head>
<meta http-equiv="refresh" content="0;url=http://{UNROUTABLE}/refresh">
<base href="http://{UNROUTABLE}/">
<link rel="stylesheet" href="http://{UNROUTABLE}/a.css">
<link rel="preload" as="font" href="http://{UNRESOLVABLE}/f.woff2" crossorigin>
<style>@import url("http://{UNROUTABLE}/b.css");</style>
<script src="http://{UNROUTABLE}/c.js"></script>
<script type="application/ld+json">{{"@context":"http://{UNROUTABLE}/schema"}}</script>
</head><body>
<img src="http://{UNROUTABLE}/p.png" srcset="http://{UNROUTABLE}/p2.png 2x">
<iframe src="http://{UNROUTABLE}/f.html"></iframe>
<object data="http://{UNROUTABLE}/o.bin"></object>
<embed src="http://{UNRESOLVABLE}/e.bin">
<video poster="http://{UNROUTABLE}/v.jpg"><source src="http://{UNROUTABLE}/v.mp4"></video>
<p>&xxe;</p>
</body></html>
"""


class NetworkAttempt(BaseException):
    """A blocked outbound call.

    Deliberately not an ``Exception``: a bare ``except Exception`` in the code under test must
    not be able to turn a violated guarantee into a passing test.
    """


# ``(owner, attribute)`` pairs. The first four are unbound methods, so their first argument is
# the socket itself and is dropped from the record; ``sendmsg`` is absent on Windows.
def _targets() -> list[tuple[object, str, bool]]:
    methods = [
        (socket.socket, name, True)
        for name in ("connect", "connect_ex", "sendto", "sendmsg")
        if hasattr(socket.socket, name)
    ]
    functions = [
        (socket, name, False)
        for name in ("create_connection", "getaddrinfo", "gethostbyname")
        if hasattr(socket, name)
    ]
    return [*methods, *functions]


@contextmanager
def no_network() -> Iterator[list[str]]:
    """Block every outbound entry point for the duration, yielding the attempts recorded."""
    attempts: list[str] = []
    saved: list[tuple[object, str, object, bool]] = []

    def refusal(label: str, drop_self: bool) -> Callable[..., NoReturn]:
        def refuse(*args: object, **kwargs: object) -> NoReturn:
            shown = args[1:] if drop_self else args
            attempts.append(f"{label}{shown!r}")
            raise NetworkAttempt(f"{label} was called with {shown!r}")

        return refuse

    for owner, name, drop_self in _targets():
        # Whether the name is the owner's *own* attribute or inherited. ``socket.socket``
        # inherits ``connect`` from ``_socket.socket``, so putting the original back with
        # setattr would leave an own attribute behind that was never there — equivalent in
        # behaviour, but this guard patches a class the whole process shares, so it restores
        # the shape as well as the value.
        saved.append((owner, name, getattr(owner, name), name in vars(owner)))
        label = f"socket.socket.{name}" if drop_self else f"socket.{name}"
        setattr(owner, name, refusal(label, drop_self))
    try:
        yield attempts
    finally:
        for owner, name, original, owned in reversed(saved):
            if owned:
                setattr(owner, name, original)
            else:
                delattr(owner, name)


# ---- the guard is armed (without this, every test below could pass vacuously) ----------------
def test_the_guard_catches_a_connection() -> None:
    with no_network() as attempts:
        with pytest.raises(NetworkAttempt):
            socket.create_connection((UNROUTABLE, 80), timeout=0.01)
    assert len(attempts) == 1 and attempts[0].startswith("socket.create_connection")


def test_the_guard_catches_a_raw_socket_connect() -> None:
    with no_network() as attempts:
        with pytest.raises(NetworkAttempt):
            socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((UNROUTABLE, 80))
    assert len(attempts) == 1 and attempts[0].startswith("socket.socket.connect")


def test_the_guard_catches_a_name_lookup() -> None:
    """A DNS query is already an outbound packet, and it is the first thing a stray fetch does."""
    with no_network() as attempts:
        with pytest.raises(NetworkAttempt):
            socket.getaddrinfo(UNRESOLVABLE, 80)
    assert len(attempts) == 1 and attempts[0].startswith("socket.getaddrinfo")


def test_the_guard_survives_being_swallowed() -> None:
    """The reason the refusal is a ``BaseException`` and the attempt is also recorded."""
    with no_network() as attempts:
        try:
            socket.create_connection((UNROUTABLE, 80))
        except Exception:  # noqa: BLE001 - the point of the test
            pytest.fail("an except Exception caught the refusal")
        except NetworkAttempt:
            pass
    assert len(attempts) == 1


def test_the_guard_leaves_no_trace() -> None:
    """It patches a class every module in the process shares, so it must put that class back as
    it found it — the same objects, and the same ones inherited rather than owned."""
    import _socket

    methods = ("connect", "connect_ex", "sendto")
    functions = ("create_connection", "getaddrinfo", "gethostbyname")
    owned = {name: name in vars(socket.socket) for name in methods}
    descriptors = {name: getattr(socket.socket, name) for name in methods}
    originals = {name: getattr(socket, name) for name in functions}

    with no_network():
        assert socket.socket.connect is not descriptors["connect"], "the patch did not apply"

    assert {name: name in vars(socket.socket) for name in methods} == owned
    assert {name: getattr(socket.socket, name) for name in methods} == descriptors
    assert {name: getattr(socket, name) for name in functions} == originals
    assert socket.socket.connect is _socket.socket.connect


def test_the_guard_ignores_imports_and_unopened_sockets() -> None:
    """The distinction the whole design rests on: a module that is imported, and a socket that
    is created but never pointed anywhere, are not network I/O and must not register."""
    with no_network() as attempts:
        import urllib.parse

        assert urllib.parse.urlparse("http://example.com/a").netloc == "example.com"
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.settimeout(0.01)
        assert probe.family is socket.AF_INET
        probe.close()
        assert "socket" in __import__("sys").modules
    assert attempts == []


# ---- the guarantee itself ---------------------------------------------------------------------
@pytest.mark.parametrize(("pair", "which"), SNAPSHOTS)
def test_normalize_opens_no_connection_on_the_corpus(pair: Pair, which: str) -> None:
    """All 40 parser-contract snapshots, through the public API, under the guard."""
    raw = pair.old_bytes if which == "old" else pair.new_bytes
    with no_network() as attempts:
        output = semdiff.normalize(raw)
    assert attempts == [], f"{pair.id}-{which} attempted {attempts}"
    assert output


def test_normalize_opens_no_connection_on_markup_that_invites_one() -> None:
    """Every fetchable reference a browser would follow, and an external entity besides."""
    with no_network() as attempts:
        output = semdiff.normalize(BAIT)
    assert attempts == []
    assert "&amp;xxe;" in output or "&xxe;" in output, "the entity was resolved, not left inert"
    assert UNROUTABLE in output, "the URLs survive as text; they are simply never followed"


def test_parse_opens_no_connection() -> None:
    """L0 is where a fetch would be cheapest to add by accident, so it is checked on its own."""
    with no_network() as attempts:
        doc = semdiff.parse(BAIT.encode("utf-8"), url=f"http://{UNROUTABLE}/page.html")
    assert attempts == []
    assert doc.url == f"http://{UNROUTABLE}/page.html", "a url is provenance, never a fetch"


def test_the_cli_opens_no_connection(tmp_path: Path) -> None:
    """The other public surface. ``--report`` is on, so the reporting path is covered too."""
    source = tmp_path / "bait.html"
    source.write_bytes(BAIT.encode("utf-8"))
    destination = tmp_path / "out.html"
    with no_network() as attempts:
        code = main(["normalize", str(source), "-o", str(destination), "--report"])
    assert attempts == []
    assert code == 0 and destination.read_bytes()


def test_the_whole_corpus_is_covered() -> None:
    """A gate that quietly stopped covering a snapshot would pass without testing it."""
    assert len(SNAPSHOTS) == len(PAIRS) * 2 == 40


# ---- the scope of the guarantee, kept honest ---------------------------------------------------
def test_the_findings_this_module_cites_exist() -> None:
    """The scope note above points at FINDINGS rows. A citation that resolves to nothing reads
    as evidence and is not."""
    findings = (Path(__file__).resolve().parents[1] / "FINDINGS.md").read_text(encoding="utf-8")
    rows = set(re.findall(r"^\|\s*(F-\d{3})\s*\|", findings, re.M))
    cited = set(re.findall(r"\bF-\d{3}\b", __doc__ or ""))
    assert cited, "the module docstring states no scope"
    assert cited <= rows, f"cited but defined nowhere: {sorted(cited - rows)}"


def test_extruct_is_not_on_the_public_path_yet() -> None:
    """A tripwire for the one NFR-8 clause this module cannot exercise (F-033).

    This is *not* the fallacy the rest of the file avoids — it does not infer "no network"
    from "no import". It asserts the opposite direction: NFR-8 requires no outbound request
    from extruct paths, and while ``extruct`` is unimported there is no such path to put under
    the guard, so the clause is vacuously satisfied rather than verified. The day T-38 wires
    extruct in, this fails, and the guard above has to be extended over the extraction path.

    Run in a subprocess so the answer is about the public path alone, not about whatever the
    rest of the test session has imported into ``sys.modules``.
    """
    probe = (
        "import sys, semdiff; semdiff.normalize('<p>x</p>'); "
        "print(sorted(m for m in ('extruct', 'requests', 'urllib3') if m in sys.modules))"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-c", probe], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "[]", (
        f"{result.stdout.strip()} is now reachable from the public path. NFR-8's extruct "
        "clause has become live: extend the guard in this module over the extraction path "
        "and revisit F-033 (T-38)."
    )
