"""T-20: the ``semdiff`` command line (FR-29).

The CLI is a thin shell over the T-19 API: stdout carries normalized HTML and nothing
else, stderr carries diagnostics and the ``--report`` summary, and every typed error from
T-02 maps to its own exit code.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from semdiff import __version__, normalize
from semdiff.cli import (
    EXIT_CONFIG,
    EXIT_IO,
    EXIT_OK,
    EXIT_PARSE,
    EXIT_TOO_LARGE,
    EXIT_USAGE,
    main,
)

NOISY = (
    '<div class="card css-1dbjc4n" id="react-root-7a3b2c">\n'
    "  <!-- build 4a3f -->\n"
    "  <p>Updated 3 minutes ago</p>\n"
    '  <script src="/assets/js/main.3eef80bd.js"></script>\n'
    "</div>\n"
)
CLEAN = normalize(NOISY)


@pytest.fixture
def page(tmp_path: Path) -> Path:
    path = tmp_path / "page.html"
    path.write_bytes(NOISY.encode())
    return path


# ---- input and output ---------------------------------------------------------------------
def test_file_input_writes_html_to_stdout(page: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["normalize", str(page)]) == EXIT_OK
    captured = capsys.readouterr()
    assert captured.out == CLEAN
    assert captured.err == ""


def test_stdin_is_used_when_no_file_is_given(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("semdiff.cli._read_stdin", lambda: NOISY.encode())
    assert main(["normalize"]) == EXIT_OK
    assert capsys.readouterr().out == CLEAN


def test_dash_means_stdin(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr("semdiff.cli._read_stdin", lambda: NOISY.encode())
    assert main(["normalize", "-"]) == EXIT_OK
    assert capsys.readouterr().out == CLEAN


def test_output_file_keeps_stdout_empty(page: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "out.html"
    assert main(["normalize", str(page), "--output", str(out)]) == EXIT_OK
    assert out.read_bytes().decode() == CLEAN
    assert capsys.readouterr().out == ""


def test_output_is_written_as_utf8_whatever_the_console_encoding(tmp_path: Path) -> None:
    source = tmp_path / "in.html"
    source.write_bytes("<p>café — 日本語</p>".encode())
    out = tmp_path / "out.html"
    assert main(["normalize", str(source), "-o", str(out)]) == EXIT_OK
    assert "café — 日本語" in out.read_bytes().decode("utf-8")


def test_cli_output_matches_the_public_api(page: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(["normalize", str(page)])
    assert capsys.readouterr().out == normalize(page.read_bytes())


# ---- --report -----------------------------------------------------------------------------
def test_report_goes_to_stderr_and_leaves_stdout_clean(page: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["normalize", str(page), "--report"]) == EXIT_OK
    captured = capsys.readouterr()
    assert captured.out == CLEAN  # byte-for-byte the same HTML as without --report
    assert "class.emotion" in captured.err
    assert "id.hex_suffix" in captured.err
    assert "timestamp.relative_ago" in captured.err
    assert "asset.dotted_hash" in captured.err
    assert "canonical.comments" in captured.err


def test_report_counts_applications_and_lists_them_in_phase_order(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    source = tmp_path / "in.html"
    source.write_bytes(b'<p class="a css-1dbjc4n">x</p><!-- c --><p class="b css-ios753">y</p>')
    main(["normalize", str(source), "--report"])
    lines = [line for line in capsys.readouterr().err.splitlines() if line.startswith("  ")]
    fired = [line.split()[0] for line in lines]
    assert fired[0] == "class.emotion"
    assert lines[0].split()[1] == "2"  # both class tokens, one rule, one row
    assert fired == sorted(set(fired), key=fired.index)  # no duplicate rows
    assert fired.index("class.emotion") < fired.index("canonical.comments")  # phase order


def test_report_says_so_when_nothing_fires(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = tmp_path / "in.html"
    source.write_bytes(b"<html><head></head><body><p>plain</p></body></html>")
    assert main(["normalize", str(source), "--report"]) == EXIT_OK
    assert "no rules fired" in capsys.readouterr().err


def test_report_and_output_file_can_be_combined(page: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "out.html"
    assert main(["normalize", str(page), "-o", str(out), "--report"]) == EXIT_OK
    captured = capsys.readouterr()
    assert out.read_bytes().decode() == CLEAN
    assert captured.out == ""
    assert "applications" in captured.err


# ---- configuration ---------------------------------------------------------------------------
def test_disable_rule_is_honoured(page: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["normalize", str(page), "--disable-rule", "timestamp.relative_ago"]) == EXIT_OK
    assert "3 minutes ago" in capsys.readouterr().out


def test_disable_rule_repeats(page: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main([
        "normalize", str(page),
        "--disable-rule", "timestamp.relative_ago",
        "--disable-rule", "class.emotion",
    ])
    out = capsys.readouterr().out
    assert code == EXIT_OK
    assert "3 minutes ago" in out and "css-1dbjc4n" in out


def test_config_file_is_read(page: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"normalization": {"disabled_rules": ["class.emotion"]}}), encoding="utf-8")
    assert main(["normalize", str(page), "--config", str(config)]) == EXIT_OK
    assert "css-1dbjc4n" in capsys.readouterr().out


def test_flags_layer_on_top_of_the_config_file(page: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"normalization": {"disabled_rules": ["class.emotion"]}}), encoding="utf-8")
    code = main(["normalize", str(page), "--config", str(config), "--disable-rule", "timestamp.relative_ago"])
    out = capsys.readouterr().out
    assert code == EXIT_OK
    assert "css-1dbjc4n" in out and "3 minutes ago" in out


def test_unknown_rule_id_is_a_config_error(page: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["normalize", str(page), "--disable-rule", "no.such.rule"]) == EXIT_CONFIG
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "no.such.rule" in captured.err


def test_malformed_config_file_is_a_config_error(page: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = tmp_path / "config.json"
    config.write_text("{not json", encoding="utf-8")
    assert main(["normalize", str(page), "--config", str(config)]) == EXIT_CONFIG
    assert capsys.readouterr().out == ""


# ---- failure modes ---------------------------------------------------------------------------
@pytest.mark.parametrize("content", [b"", b"   \n\t "], ids=["empty", "whitespace"])
def test_empty_input_exits_with_the_parse_code(
    content: bytes, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "empty.html"
    source.write_bytes(content)
    assert main(["normalize", str(source)]) == EXIT_PARSE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "parse_error" in captured.err


def test_oversized_input_exits_with_its_own_code(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = tmp_path / "big.html"
    source.write_bytes(b"<p>" + b"x" * 500 + b"</p>")
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"max_input_bytes": 64}), encoding="utf-8")
    assert main(["normalize", str(source), "--config", str(config)]) == EXIT_TOO_LARGE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "input_too_large" in captured.err


def test_missing_file_is_an_io_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["normalize", str(tmp_path / "nope.html")]) == EXIT_IO
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "nope.html" in captured.err


def test_unwritable_output_is_an_io_error(page: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target = tmp_path / "missing-dir" / "out.html"
    assert main(["normalize", str(page), "-o", str(target)]) == EXIT_IO
    assert capsys.readouterr().out == ""


def test_no_subcommand_is_a_usage_error() -> None:
    with pytest.raises(SystemExit) as excinfo:
        main([])
    assert excinfo.value.code == EXIT_USAGE


def test_unknown_option_is_a_usage_error(page: Path) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["normalize", str(page), "--nope"])
    assert excinfo.value.code == EXIT_USAGE


def test_exit_codes_are_distinct() -> None:
    codes = [EXIT_OK, EXIT_USAGE, EXIT_PARSE, EXIT_TOO_LARGE, EXIT_CONFIG, EXIT_IO]
    assert len(set(codes)) == len(codes)


# ---- determinism and the installed command ---------------------------------------------------
def test_repeated_runs_are_identical(page: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(["normalize", str(page), "--report"])
    once = capsys.readouterr()
    main(["normalize", str(page), "--report"])
    twice = capsys.readouterr()
    assert (once.out, once.err) == (twice.out, twice.err)


def test_version_is_reported(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == EXIT_OK
    assert __version__ in capsys.readouterr().out


def test_module_entry_point_runs(page: Path) -> None:
    done = subprocess.run(
        [sys.executable, "-m", "semdiff", "normalize", str(page)],
        capture_output=True,
        check=False,
    )
    assert done.returncode == EXIT_OK
    assert done.stdout.decode("utf-8") == CLEAN
    assert done.stderr == b""
