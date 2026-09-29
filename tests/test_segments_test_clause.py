"""
Tests for which literals inside ``[[ ]]`` are commands and which are values.

Bash's ``[[ ]]`` never executes its operands.  A canary proves it::

    [[ -n x && canary ]]      exit=0  canary ran: NO
    [[ -d /tmp && canary ]]   exit=0  canary ran: NO
    [[ -n x && $(canary) ]]   exit=1  canary ran: YES

So *every* operand of a test is a value: the right operand of ``&&``/``||``
included.  Treating that operand as a command was wrong twice over - it
invented commands that never run (``[[ -d /tmp && /etc/passwd ]]`` reported a
``/etc/passwd`` *command*) and it hid the ones that do run, because suppressing
expansion traversal inside the test body meant a substitution in a
``${...}`` default produced no segments at all and the empty-segment fallback
approved the whole command.

The only real executions inside ``[[ ]]`` come from substitutions, which the
generic traversal finds on its own.

The invariants pinned here are:

1. ``[[ -d /tmp && ls ]]``  -> no segments.
2. ``[[ -d /tmp ]]``        -> no segments.
3. ``[[ ( /etc/passwd ) ]]``-> no segments.
4. ``[[ /etc/passwd ]]``    -> no segments.
5. ``[[ $var =~ pat ]]``    -> no segments.
6. ``[[ -d /tmp && ls && pwd ]]`` -> no segments (both operands are values).
7. ``[[ ${x:-$(cmd)} ]]``   -> ``cmd``: substitutions run in every position.
8. No test operand is a command, left or right, in any operator position.
"""

from lovely_bash_permissions.segments import parse_segments
from tests.conftest import _commands


class TestTestOperandsAreValues:
    """Invariant 1: no ``&&``/``||`` operand is a command."""

    def test_and_right_operand_is_a_value(self) -> None:
        assert _commands("[[ -d /tmp && ls ]]") == []

    def test_or_right_operand_is_a_value(self) -> None:
        assert _commands("[[ -d /tmp || cat ]]") == []

    def test_logical_right_operand_inside_paren_test(self) -> None:
        assert _commands("[[ ( -d /tmp ) && ls ]]") == []

    def test_logical_right_operand_quoted_literal(self) -> None:
        assert _commands('[[ cond && "ls" ]]') == []

    def test_logical_right_operand_single_quoted_literal(self) -> None:
        assert _commands("[[ cond && 'ls' ]]") == []

    def test_chained_and_emits_nothing(self) -> None:
        assert _commands("[[ -d /tmp && ls && pwd ]]") == []

    def test_chained_or_emits_nothing(self) -> None:
        assert _commands("[[ -d /tmp || ls || pwd ]]") == []

    def test_path_in_logical_right_operand_is_not_a_command(self) -> None:
        """The old ``&&`` heuristic reported a path as a command name."""
        assert _commands("[[ -d /tmp && /etc/passwd ]]") == []

    def test_bare_logical_operands_emit_nothing(self) -> None:
        assert _commands("[[ a && b || c ]]") == []


class TestBareValueOperandsAreNotCommands:
    """Invariants 2-5: values under test never become command names."""

    def test_bare_unary_test_no_phantom_command(self) -> None:
        assert parse_segments("[[ -d /tmp ]]") == []

    def test_paren_test_bare_literal_no_phantom_command(self) -> None:
        assert parse_segments("[[ ( /etc/passwd ) ]]") == []

    def test_bare_literal_operand_no_phantom_command(self) -> None:
        assert parse_segments("[[ /etc/passwd ]]") == []

    def test_bare_literal_under_test_no_phantom_command(self) -> None:
        assert parse_segments("[[ foo ]]") == []

    def test_bare_path_operand_after_paren_test(self) -> None:
        assert _commands("[[ ( -d /tmp ) ]]") == []

    def test_regex_rhs_is_not_a_command(self) -> None:
        assert parse_segments("[[ $var =~ pat ]]") == []

    def test_glob_and_equality_rhs_are_not_commands(self) -> None:
        for cmd in ("[[ $a == *.txt ]]", "[[ $a != x ]]", "[[ $n -eq 5 ]]", "[[ x =~ ^a.*$ ]]"):
            assert parse_segments(cmd) == [], cmd

    def test_bare_param_exp_is_not_a_command(self) -> None:
        assert parse_segments("[[ $var ]]") == []
        assert parse_segments('[[ "$var" ]]') == []

    def test_value_operand_before_and_is_not_emitted(self) -> None:
        assert _commands("[[ /etc/passwd && -d /tmp ]]") == []


class TestSubstitutionsInsideTestBodiesExecute:
    """Invariant 7: a substitution runs wherever it appears in the test."""

    def test_logical_right_operand_substitution(self) -> None:
        assert _commands("[[ -f x && $(c2) ]] && echo and") == ["c2", "echo"]

    def test_logical_right_operand_quoted_substitution(self) -> None:
        assert _commands('[[ cond && "$(cmd)" ]]') == ["cmd"]

    def test_chained_and_with_substitution_operands(self) -> None:
        # shfmt nests `&&` right-associatively, so both operands are reached.
        assert _commands("[[ -f x && $(a) && $(b) ]]") == ["a", "b"]

    def test_unary_operand_cmdsubst(self) -> None:
        assert _commands("[[ -d $(pwd) ]]") == ["pwd"]

    def test_param_exp_default_substitution(self) -> None:
        """A substitution in a test body must yield segments.

        Traversal into parameter expansions applies inside a test as elsewhere,
        so the inner command cannot vanish; with zero segments the
        empty-segment fallback applies the wildcard and approves the whole
        command.
        """
        assert _commands("[[ ${x:-$(cmd)} ]]") == ["cmd"]

    def test_equality_rhs_cmdsubst(self) -> None:
        assert _commands("[[ ${x} == $(cmd) ]]") == ["cmd"]

    def test_arithmetic_substitution_inside_test(self) -> None:
        assert _commands("[[ -d $((1+$(cmd))) ]]") == ["cmd"]

    def test_left_operand_cmdsubst(self) -> None:
        assert _commands("[[ $(cat /etc/passwd) == x ]]") == ["cat"]

    def test_both_sides_cmdsubst(self) -> None:
        assert _commands("[[ $(a) == $(b) ]]") == ["a", "b"]

    def test_regex_rhs_cmdsubst(self) -> None:
        assert _commands("[[ $var =~ $(cmd) ]]") == ["cmd"]


class TestNoTestOperandIsACommand:
    """Invariant 8: no operand position emits, whatever the operator."""

    def test_literal_operands_not_emitted(self) -> None:
        assert _commands("[[ -d /tmp && ls ]]") == []
        assert _commands("[[ -d /tmp && ls && pwd ]]") == []

    def test_unary_test_operand_not_emitted(self) -> None:
        assert "passwd" not in _commands("[[ -d /etc/passwd ]]")

    def test_left_operand_of_equality_not_emitted(self) -> None:
        assert _commands("[[ /etc/passwd == other ]]") == []

    def test_quoted_operands_not_emitted(self) -> None:
        assert _commands('[[ cond && "ls" ]]') == []
        assert _commands("[[ cond && 'ls' ]]") == []


class TestTestClauseRedirectionsUnaffected:
    """Statement redirections still ride on the synthetic ``[[`` segment."""

    def test_synthetic_segment_for_empty_body(self) -> None:
        segs = parse_segments("[[ -f file ]] > /tmp/out")
        assert len(segs) == 1
        assert segs[0]["command"] == "[["
        assert segs[0]["redirections"][0]["Op"] == ">"

    def test_redirection_not_scattered_onto_test_operands(self) -> None:
        # The test body yields no segments at all now, so the only thing that
        # can carry the statement redirection is the synthetic `[[` segment.
        segs = parse_segments("[[ -d /tmp && ls ]] > /tmp/out")
        carrying = [s for s in segs if s["redirections"]]
        assert len(carrying) == 1
        assert carrying[0]["command"] == "[["
        assert carrying[0]["redirections"][0]["Op"] == ">"

    def test_redirection_with_nested_substitution(self) -> None:
        segs = parse_segments("[[ -d $(pwd) ]] > /tmp/out")
        assert _commands("[[ -d $(pwd) ]] > /tmp/out") == ["pwd", "[["]
        assert any(s["command"] == "[[" and s["redirections"] for s in segs)
        assert all(s["redirections"] == [] for s in segs if s["command"] == "pwd")

    def test_regex_rhs_redirection_no_phantom(self) -> None:
        segs = parse_segments("[[ $var =~ pat ]] > /tmp/out")
        assert "pat" not in _commands("[[ $var =~ pat ]] > /tmp/out")
        assert any(s["redirections"] for s in segs)

    def test_paren_test_redirection_synthetic_segment(self) -> None:
        segs = parse_segments("[[ ( -d /tmp ) ]] > /tmp/out")
        assert len(segs) == 1
        assert segs[0]["command"] == "[["
        assert segs[0]["redirections"]
