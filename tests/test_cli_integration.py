"""Integration tests for cli.py entry point (main).

Each test calls ``lovely_bash_permissions.cli.main`` with argv-style
arguments and asserts the exit code plus captured stdout.  Exit codes:

    0  success
    2  usage error (bad or missing arguments)
    3  parse error

Tests are deliberately thin — they verify the *integration* between
argument parsing, input reading, and AST rendering rather than deep
unit behaviour.
"""

import sys
from unittest import mock

import pytest

from lovely_bash_permissions.cli import main


def _stdout(capsys: pytest.CaptureFixture[str]) -> list[str]:
    """Return captured stdout split into non-empty lines (stripped)."""
    return [line.strip() for line in capsys.readouterr().out.splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# 1. test_main_string_basic
# ---------------------------------------------------------------------------


def test_main_string_basic(capsys: pytest.CaptureFixture[str]) -> None:
    """Basic --string invocation succeeds and reports the command."""
    exit_code = main(["--string", "ls -la"])
    assert exit_code == 0
    lines = _stdout(capsys)
    cmd_lines = [l for l in lines if "cmd:" in l]
    assert len(cmd_lines) >= 1, f"No 'cmd:' line found in {lines}"
    assert "ls" in cmd_lines[0]


# ---------------------------------------------------------------------------
# 2. test_main_string_pipe
# ---------------------------------------------------------------------------


def test_main_string_pipe(capsys: pytest.CaptureFixture[str]) -> None:
    """Piped command reports pipes detected."""
    exit_code = main(["--string", "ls | grep test"])
    assert exit_code == 0
    lines = _stdout(capsys)
    pipes_line = [l for l in lines if l.startswith("Pipes:")]
    assert len(pipes_line) >= 1, f"No 'Pipes:' line found in {lines}"
    assert "yes" in pipes_line[0]


# ---------------------------------------------------------------------------
# 3. test_main_empty_string
# ---------------------------------------------------------------------------


def test_main_empty_string(capsys: pytest.CaptureFixture[str]) -> None:
    """Empty string triggers usage error (exit 2)."""
    with pytest.raises(SystemExit) as exc:
        main(["--string", ""])
    assert exc.value.code == 2


# ---------------------------------------------------------------------------
# 4. test_main_parse_error
# ---------------------------------------------------------------------------


def test_main_parse_error(capsys: pytest.CaptureFixture[str]) -> None:
    """Invalid bash syntax triggers parse error (exit 3)."""
    exit_code = main(["--string", "{ invalid"])
    assert exit_code == 3


# ---------------------------------------------------------------------------
# 5. test_main_no_input — stdin is a tty, no --string/--file
# ---------------------------------------------------------------------------


def test_main_no_input(capsys: pytest.CaptureFixture[str]) -> None:
    """No args and stdin is a tty → exit 2 (no input error)."""
    # Mock sys.stdin.isatty() to return True so _read_input hits the tty guard.
    with mock.patch("lovely_bash_permissions.cli.sys.stdin", isatty=mock.Mock(return_value=True)):
        with pytest.raises(SystemExit) as exc:
            main([])
    assert exc.value.code == 2


# ---------------------------------------------------------------------------
# 6. test_main_dialect_arg
# ---------------------------------------------------------------------------


def test_main_dialect_arg(capsys: pytest.CaptureFixture[str]) -> None:
    """--dialect zsh parses without error (exit 0)."""
    exit_code = main(["--string", "ls -la", "--dialect", "zsh"])
    assert exit_code == 0
