"""
Tests for the CLI's rendering of value-only words.

A statement whose payload is data must render, not read as empty:
``for i in /etc/passwd; do :; done`` shows ``cmd: :`` plus the word list, and
``case /etc/passwd in x) ;; esac`` reports its subject instead of printing
``(no commands found)``.

Three extra lines are emitted for that:

* ``words: a, b, c``   - a ``for`` loop's word list
* ``case: <subject>``  - a ``case`` statement's subject word
* ``pattern: <p>``     - one line per ``case`` branch pattern

Commands nested inside those words (``for i in $(cmd)``) are already
rendered by the generic child descent, so these tests also pin that they are
not rendered twice.

The same file also covers how assignments are rendered.  The CLI delegates to the
renderer ``segments`` uses for permission evaluation, and the tests below pin
that the inspection output agrees with :func:`parse_segments` operand for
operand - that agreement is the whole point, so the two cannot drift.  The
comparison is against
the variable-assignment segment (``command == ""``), which is where both a bare
assignment and a declaration builtin's operands are reported.
"""

import pytest

from lovely_bash_permissions import cli
from lovely_bash_permissions.ast import Assign
from lovely_bash_permissions.cli import main
from lovely_bash_permissions.segments import parse_segments


def _lines(capsys: pytest.CaptureFixture[str]) -> list[str]:
    """Return captured stdout split into non-empty lines."""
    return [line for line in capsys.readouterr().out.splitlines() if line.strip()]


def _payload(lines: list[str]) -> list[str]:
    """Return the indented payload lines (skip headers and the summary)."""
    return [line for line in lines if line.startswith(" ")]


def _assign_operands(lines: list[str], variant: str | None = None) -> list[str]:
    """Return the operands rendered on ``assign:`` lines.

    Args:
        lines: The captured output lines.
        variant: ``None`` (the default) reads bare assignment lines; a keyword
            such as ``"declare"`` reads that declaration's operands, which the
            CLI renders as ``assign: declare <operand>``.

    Returns:
        The operand text of each matching line, without the ``assign:`` prefix.
    """
    prefix = "  assign: " if variant is None else f"  assign: {variant} "
    return [line[len(prefix) :] for line in lines if line.startswith(prefix)]


def _assignment_arguments(source: str) -> list[str]:
    """Return the non-empty arguments of *source*'s variable-assignment segment.

    ``parse_segments`` reports assignment operands on the segment whose command
    is ``""`` - for a bare assignment and for a declaration builtin's operands
    alike - and that is the segment the permission path gates with the
    ``variable_assignment`` policy, so it is the one the rendering has to agree
    with.

    Args:
        source: The bash source to segment.

    Returns:
        The variable-assignment segment's arguments, empty ones dropped.

    Raises:
        AssertionError: If the source produces no such segment.
    """
    for segment in parse_segments(source):
        if segment["command"] == "":
            return [str(argument) for argument in segment["arguments"] if argument]
    raise AssertionError(f"no variable-assignment segment in {parse_segments(source)}")


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
    """A statement made only of values renders instead of 'no commands'."""

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


class TestAssignmentRendering:
    """Assignments render as written, for every shape shfmt produces."""

    def test_declared_array_after_a_flag_keeps_its_elements(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["--string", "declare -a A=(a b)"]) == 0
        assert "  assign: declare A=(a b)" in _lines(capsys)

    def test_array_append_keeps_its_elements(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["--string", "A+=(x y)"]) == 0
        assert "  assign: A+=(x y)" in _lines(capsys)

    def test_subscripted_array_append_keeps_its_elements(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["--string", "A[i]+=(x y)"]) == 0
        assert "  assign: A[i]+=(x y)" in _lines(capsys)

    def test_plain_array_keeps_its_elements(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["--string", "A=(a b)"]) == 0
        assert "  assign: A=(a b)" in _lines(capsys)

    def test_subscripted_scalar_is_unchanged(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["--string", "A[i]=value"]) == 0
        assert "  assign: A[i]=value" in _lines(capsys)

    def test_empty_array_keeps_the_placeholder(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["--string", "A=()"]) == 0
        assert "  assign: A=(...)" in _lines(capsys)

    def test_sparse_array_keeps_its_subscripts(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["--string", "A=([0]=x [2]=y)"]) == 0
        assert "  assign: A=([0]=x [2]=y)" in _lines(capsys)

    def test_naked_flag_gets_no_stray_equals(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["--string", "declare -a"]) == 0
        lines = _lines(capsys)
        assert "  assign: declare -a" in lines
        assert not [line for line in lines if "declare =-a" in line]

    def test_naked_name_gets_no_stray_equals(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["--string", "export FOO"]) == 0
        assert "  assign: export FOO" in _lines(capsys)

    def test_declared_scalar(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["--string", "export FOO=bar"]) == 0
        assert "  assign: export FOO=bar" in _lines(capsys)

    def test_declared_array_keeps_its_elements(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["--string", "export A=(a b)"]) == 0
        assert "  assign: export A=(a b)" in _lines(capsys)

    def test_substitution_element_surfaces_the_nested_command_once(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["--string", "A=($(cmd))"]) == 0
        lines = _lines(capsys)
        assert "  assign: A=($(...))" in lines
        assert [line.strip() for line in lines if "cmd:" in line] == ["cmd: cmd"]

    def test_substitution_in_a_declared_array_surfaces_the_nested_command(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["--string", "export A=($(cmd))"]) == 0
        lines = _lines(capsys)
        assert "  assign: export A=($(...))" in lines
        assert [line.strip() for line in lines if "cmd:" in line] == ["cmd: cmd"]

    def test_nested_command_in_a_value_is_not_double_rendered(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["--string", "A=$(cmd)"]) == 0
        lines = _lines(capsys)
        assert "  assign: A=$(...)" in lines
        assert [line.strip() for line in lines if "cmd:" in line] == ["cmd: cmd"]


def _blank_assign_text(assign: Assign) -> str:
    """Stand-in renderer for an assignment that has nothing to render."""
    return ""


class TestUnrenderableAssignment:
    """An assignment with nothing to render produces no ``assign:`` line."""

    def test_delegating_renderer_reports_empty(self) -> None:
        assert cli._assign_text(Assign()) == ""

    def test_bare_assignment_line_is_omitted(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(cli, "_assign_text", _blank_assign_text)
        assert main(["--string", "A=b"]) == 0
        lines = _lines(capsys)
        assert not [line for line in lines if "assign" in line]

    def test_declared_assignment_line_is_omitted(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(cli, "_assign_text", _blank_assign_text)
        assert main(["--string", "export FOO=bar"]) == 0
        lines = _lines(capsys)
        assert not [line for line in lines if "assign" in line]
        # The statement keeps its header, exactly as an operand-less
        # declaration does, rather than growing a dangling ``assign:`` line.
        assert lines[0].startswith("statement 1 ")


class TestAgreesWithSegments:
    """The rendered operands are the operands ``segments`` reports.

    The CLI renders a declaration builtin's assigns straight from the AST on one
    ``assign: <variant> <operand>`` line, while ``parse_segments`` now splits
    those operands onto the variable-assignment segment (the keyword keeps its
    own, empty, command segment).  So the comparison is against the
    variable-assignment segment: that is the segment the permission path
    evaluates, which is exactly what this test is here to keep honest.
    """

    @pytest.mark.parametrize(
        ("source", "variant"),
        [
            ("A=(a b)", None),
            ("A+=(x y)", None),
            ("A[i]+=(x y)", None),
            ("A=(a b c)", None),
            ("A[i]=value", None),
            ("A=()", None),
            ("A=([0]=x [2]=y)", None),
            ("A=($(cmd))", None),
            ("A=$(cmd)", None),
            ("A=value", None),
            ("A=", None),
            ("declare -a A=(a b)", "declare"),
            ("declare -a", "declare"),
            ("export FOO=bar", "export"),
            ("export A=(a b)", "export"),
            ("export A=($(cmd))", "export"),
        ],
    )
    def test_operands_match_the_segment_arguments(
        self, capsys: pytest.CaptureFixture[str], source: str, variant: str | None
    ) -> None:
        assert main(["--string", source]) == 0
        rendered = _assign_operands(_lines(capsys), variant)
        expected = _assignment_arguments(source)
        assert rendered == expected
