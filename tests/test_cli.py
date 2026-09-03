"""
Tests for CLI output of redirection placement.

The bug being regression-tested: redirections in multi-segment bash pipelines
were being dropped by the CLI renderer. The fix reworked cli.py so each
segment's redirection renders immediately after the command that owns it.
Per-side AST data coverage lives in tests/test_binary_redirs.py.
"""

import pytest

from lovely_bash_permissions.cli import main


def _lines(capsys: pytest.CaptureFixture[str]) -> list[str]:
    """Return captured stdout split into non-empty lines."""
    return [line for line in capsys.readouterr().out.splitlines() if line.strip()]


def _find_line(lines: list[str], substr: str) -> int:
    """Return the index of the first line containing *substr*."""
    for i, line in enumerate(lines):
        if substr in line:
            return i
    raise AssertionError(f"No line containing {substr!r} found in:\n" + "\n".join(lines))


def _assert_adjacent(lines: list[str], cmd_substr: str, redir_substr: str) -> None:
    """Assert the redir line directly follows its owning command line."""
    cmd_idx = _find_line(lines, cmd_substr)
    redir_idx = _find_line(lines, redir_substr)
    assert redir_idx == cmd_idx + 1, (
        f"Expected redirection {redir_substr!r} at index {cmd_idx + 1} "
        f"(right after cmd {cmd_substr!r} at {cmd_idx}), "
        f"but found it at index {redir_idx}. Lines:\n" + "\n".join(lines)
    )


class TestCliRedirections:
    """CLI renderer must place each redirection adjacent to its owning command."""

    def test_repro_multisegment_pipe(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Exact reported repro: all three redirections present and ordered."""
        main(["--string", "echo $PATH | cmd2 > 2 | cmd3 >3 | cmd4 > $(ls) | cmd5"])
        lines = _lines(capsys)

        redir_lines = [line for line in lines if "redirection:" in line]
        assert len(redir_lines) >= 3, f"Expected at least 3 redirection lines, got {len(redir_lines)}:\n" + "\n".join(
            redir_lines
        )

        _assert_adjacent(lines, "cmd: cmd2", "redirection: > 2")
        _assert_adjacent(lines, "cmd: cmd3", "redirection: > 3")
        _assert_adjacent(lines, "cmd: cmd4", "redirection: > $(...)")

        idx_2 = _find_line(lines, "redirection: > 2")
        idx_3 = _find_line(lines, "redirection: > 3")
        idx_cmdsub = _find_line(lines, "redirection: > $(...)")
        assert idx_2 < idx_3 < idx_cmdsub, (
            f"Redirections out of order: > 2 at {idx_2}, > 3 at {idx_3}, > $(...) at {idx_cmdsub}"
        )

    def test_two_segment_both_redirected(self, capsys: pytest.CaptureFixture[str]) -> None:
        """2-segment pipe with both segments redirected."""
        main(["--string", "cmd2 > 2 | cmd3 > 3"])
        lines = _lines(capsys)

        _assert_adjacent(lines, "cmd: cmd2", "redirection: > 2")
        _assert_adjacent(lines, "cmd: cmd3", "redirection: > 3")

        idx_r2 = _find_line(lines, "redirection: > 2")
        idx_r3 = _find_line(lines, "redirection: > 3")
        assert idx_r2 < idx_r3

    def test_three_segment_left_nested_all_redirected(self, capsys: pytest.CaptureFixture[str]) -> None:
        """3-segment left-nested pipe with all segments redirected."""
        main(["--string", "a > 1 | b > 2 | c > 3"])
        lines = _lines(capsys)

        _assert_adjacent(lines, "cmd: a", "redirection: > 1")
        _assert_adjacent(lines, "cmd: b", "redirection: > 2")
        _assert_adjacent(lines, "cmd: c", "redirection: > 3")

        idx_1 = _find_line(lines, "redirection: > 1")
        idx_2 = _find_line(lines, "redirection: > 2")
        idx_3 = _find_line(lines, "redirection: > 3")
        assert idx_1 < idx_2 < idx_3

    def test_middle_segment_redirection(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Middle-segment redirection renders next to its command."""
        main(["--string", "cmd1 | cmd2 > f | cmd3"])
        lines = _lines(capsys)

        _assert_adjacent(lines, "cmd: cmd2", "redirection: > f")

        cmd3_idx = _find_line(lines, "cmd: cmd3")
        redir_after_cmd3 = False
        for i in range(cmd3_idx + 1, min(cmd3_idx + 3, len(lines))):
            if "redirection:" in lines[i]:
                redir_after_cmd3 = True
        assert not redir_after_cmd3, f"cmd3 should have no redirection, but found one at line {i}: {lines[i]}"

    def test_adjacency_helper_contract(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Verify the adjacency helper catches misplacement (self-test)."""
        main(["--string", "x > xout | y > yout"])
        lines = _lines(capsys)

        _assert_adjacent(lines, "cmd: x", "redirection: > xout")
        _assert_adjacent(lines, "cmd: y", "redirection: > yout")
