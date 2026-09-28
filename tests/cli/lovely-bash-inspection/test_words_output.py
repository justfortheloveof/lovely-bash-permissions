"""
Tests for the CLI's rendering of value-only words.

``lovely-bash-inspection`` used to render only commands, declarations,
redirections and assignments, so statements whose payload is data looked
empty: ``for i in /etc/passwd; do :; done`` showed just ``cmd: :`` and
``case /etc/passwd in x) ;; esac`` printed ``(no commands found)``.

The renderer now emits three extra lines:

* ``words: a, b, c``   - a ``for`` loop's word list
* ``case: <subject>``  - a ``case`` statement's subject word
* ``pattern: <p>``     - one line per ``case`` branch pattern

Commands nested inside those words (``for i in $(cmd)``) are already
rendered by the generic child descent, so these tests also pin that they are
not rendered twice.
"""

import pytest

from lovely_bash_permissions.cli import main


def _lines(capsys: pytest.CaptureFixture[str]) -> list[str]:
    """Return captured stdout split into non-empty lines."""
    return [line for line in capsys.readouterr().out.splitlines() if line.strip()]


def _payload(lines: list[str]) -> list[str]:
    """Return the indented payload lines (skip headers and the summary)."""
    return [line for line in lines if line.startswith(" ")]


class TestForLoopWords:
    """A ``for`` loop's word list is rendered as ``words:``."""

    def test_single_loop_word(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["--string", "for i in /etc/passwd; do :; done"]) == 0
        assert "  words: /etc/passwd" in _lines(capsys)

    def test_multiple_loop_words(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["--string", "for i in a b c; do :; done"]) == 0
        assert "  words: a, b, c" in _lines(capsys)

    def test_words_line_precedes_the_body_command(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["--string", "for i in a b; do echo hi; done"]) == 0
        payload = _payload(_lines(capsys))
        assert payload.index("  words: a, b") < payload.index("  cmd: echo")

    def test_empty_word_list_is_omitted(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["--string", "for i in; do echo x; done"]) == 0
        lines = _lines(capsys)
        assert not [line for line in lines if "words:" in line]
        assert "  cmd: echo" in lines

    def test_cstyle_loop_has_no_word_list(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["--string", "for ((i=0; i<3; i++)); do :; done"]) == 0
        lines = _lines(capsys)
        assert not [line for line in lines if "words:" in line]
        assert "  cmd: :" in lines

    def test_nested_loops_render_each_word_list(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["--string", "for i in a b; do for j in c; do :; done; done"]) == 0
        lines = _lines(capsys)
        assert "  words: a, b" in lines
        assert "  words: c" in lines


class TestCaseSubjectAndPatterns:
    """A ``case`` subject and its branch patterns are rendered."""

    def test_subject_only(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["--string", "case /etc/passwd in x) ;; esac"]) == 0
        lines = _lines(capsys)
        assert "  case: /etc/passwd" in lines
        assert "  pattern: x" in lines

    def test_variable_subject(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["--string", "case $x in a) echo m;; esac"]) == 0
        lines = _lines(capsys)
        assert "  case: $x" in lines
        assert "  pattern: a" in lines

    def test_one_pattern_line_per_alternative(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["--string", "case $x in a|b) echo m;; *) echo d;; esac"]) == 0
        lines = _lines(capsys)
        assert "  pattern: a" in lines
        assert "  pattern: b" in lines
        assert "  pattern: *" in lines

    def test_pattern_precedes_its_branch_command(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["--string", "case $x in a) echo m;; esac"]) == 0
        payload = _payload(_lines(capsys))
        assert payload.index("  pattern: a") < payload.index("  cmd: echo")


class TestNestedCommandsNotDuplicated:
    """Commands inside value words are rendered exactly once."""

    def test_cmdsubst_in_loop_words(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["--string", "for i in a b $(cmd); do echo hi; done"]) == 0
        lines = _lines(capsys)
        assert "  words: a, b, $(...)" in lines
        assert [line.strip() for line in lines if "cmd:" in line] == ["cmd: cmd", "cmd: echo"]

    def test_cmdsubst_in_case_pattern(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["--string", "case $x in $(evil)) echo hit;; esac"]) == 0
        lines = _lines(capsys)
        assert "  pattern: $(...)" in lines
        assert [line.strip() for line in lines if "cmd:" in line] == ["cmd: evil", "cmd: echo"]

    def test_cmdsubst_in_case_subject(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["--string", "case $(evil) in a) echo 1;; esac"]) == 0
        lines = _lines(capsys)
        assert "  case: $(...)" in lines
        assert [line.strip() for line in lines if "cmd:" in line] == ["cmd: evil", "cmd: echo"]


class TestValueOnlyStatements:
    """A statement made only of values now renders instead of 'no commands'."""

    def test_empty_case_branch_body_is_reported(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["--string", "case /etc/passwd in x) ;; esac"]) == 0
        lines = _lines(capsys)
        assert "(no commands found)" not in "\n".join(lines)
        assert lines[0].startswith("statement 1 ")

    def test_statement_without_any_command_or_value_reports_none(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["--string", "# just a comment"]) == 0
        assert "(no commands found)" in _lines(capsys)


class TestRedirectionPlacementUnaffected:
    """The new kinds must not shift where trailing redirections render."""

    def test_loop_redirection_follows_the_body_command(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["--string", "for i in a; do :; done > /tmp/out"]) == 0
        lines = _lines(capsys)
        assert lines.index("  cmd: :") + 1 == lines.index("  redirection: > /tmp/out")

    def test_loop_word_list_does_not_swallow_the_redirection(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["--string", "for i in a b; do :; done 2>> /tmp/err"]) == 0
        lines = _lines(capsys)
        assert len([line for line in lines if "redirection:" in line]) == 1
        assert lines.index("  cmd: :") + 1 == lines.index("  redirection: 2>> /tmp/err")
