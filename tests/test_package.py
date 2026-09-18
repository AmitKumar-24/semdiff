"""T-00: package installs, exposes a version, and ships the py.typed marker."""

from pathlib import Path


def test_version() -> None:
    import semdiff

    assert semdiff.__version__ == "0.0.0"


def test_py_typed_marker() -> None:
    import semdiff

    assert (Path(semdiff.__file__).parent / "py.typed").is_file()
