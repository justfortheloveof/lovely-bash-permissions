"""
Tests for which literals inside ``[[ ]]`` are commands and which are values.

Only the right operand of ``&&``/``||`` inside a test body is a command.
Every other literal in a test body is the value under test, so it must not
be emitted as a command name - otherwise a path like ``/etc/passwd`` shows
up as a bogus ``"/etc/passwd" command does not match allowed patterns``.

The invariants pinned here are:

1. ``[[ -d /tmp && ls ]]``  -> ``ls`` is still emitted.
2. ``[[ -d /tmp ]]``        -> no segments.
3. ``[[ ( /etc/passwd ) ]]``-> no segments.
4. ``[[ /etc/passwd ]]``    -> no segments.
5. ``[[ $var =~ pat ]]``    -> no segments.
6. ``[[ -d /tmp && ls && pwd ]]`` -> characterization test, see below.
7. ``[[ $(cat /etc/passwd) == x ]]`` -> the inner ``cat`` is a real command.
8. UnaryTest / BinaryTest LEFT operands never emit commands.
"""

from lovely_bash_permissions.segments import parse_segments


def _commands(command: str) -> list[str]:
    """Return the command names extracted from *command*."""
    return [s["command"] for s in parse_segments(command)]


class TestLogicalOperandIsACommand:
    """Invariant 1: the right operand of ``&&``/``||`` is a command."""

    def test_and_right_operand(self) -> None:
        assert _commands("[[ -d /tmp && ls ]]") == ["ls"]

    def test_or_right_operand(self) -> None:
        assert "cat" in _commands("[[ -d /tmp || cat ]]")

    def test_logical_right_operand_inside_paren_test(self) -> None:
        assert _commands("[[ ( -d /tmp ) && ls ]]") == ["ls"]

    def test_logical_right_operand_quoted_literal(self) -> None:
        assert _commands('[[ cond && "ls" ]]') == ["ls"]

    def test_logical_right_operand_single_quoted_literal(self) -> None:
        assert _commands("[[ cond && 'ls' ]]") == ["ls"]

    def test_logical_right_operand_substitution(self) -> None:
        assert _commands("[[ -f x && $(c2) ]] && echo and") == ["c2", "echo"]

    def test_logical_right_operand_quoted_substitution(self) -> None:
        assert _commands('[[ cond && "$(cmd)" ]]') == ["cmd"]


class TestBareValueOperandsAreNotCommands:
    """Invariants 2-5: values under test never become command names."""

    def test_bare_unary_test_no_phantom_command(self) -> None:
        assert parse_segments("[[ -d /tmp ]]") == []

    def test_paren_test_bare_literal_no_phantom_command(self) -> None:
        assert parse_segments("[[ ( /etc/passwd ) ]]") == []

    def test_bare_literal_operand_no_phantom_command(self) -> None:
        assert parse_segments("[[ /etc/passwd ]]") == []

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


class TestChainedLogicalOperands:
    """Invariant 6: characterization of ``[[ -d /tmp && ls && pwd ]]``.

    shfmt nests ``&&`` right-associatively, so the node is
    ``&&(-d /tmp, &&(ls, pwd))``: ``pwd`` is the right operand of a logical
    operator (a command) while ``ls`` is the *left* operand of the inner
    one, i.e. a comparison subject, which invariant 8 forbids from being
    emitted.  Only ``pwd`` is emitted - before and after the two-flag split.
    """

    def test_chained_and_emits_only_the_outer_right_operand(self) -> None:
        assert _commands("[[ -d /tmp && ls && pwd ]]") == ["pwd"]

    def test_chained_or_emits_only_the_outer_right_operand(self) -> None:
        assert _commands("[[ -d /tmp || ls || pwd ]]") == ["pwd"]

    def test_chained_and_with_substitution_right_operands(self) -> None:
        # Both right operands run substitutions, so both surface.
        assert _commands("[[ -d /tmp && $(a) && $(b) ]]") == ["a", "b"]


class TestNestedSubstitutionsAreRealCommands:
    """Invariant 7: substitutions inside test operands are real commands."""

    def test_left_operand_cmdsubst(self) -> None:
        assert _commands("[[ $(cat /etc/passwd) == x ]]") == ["cat"]

    def test_both_sides_cmdsubst(self) -> None:
        assert _commands("[[ $(a) == $(b) ]]") == ["a", "b"]

    def test_unary_operand_cmdsubst(self) -> None:
        assert _commands("[[ -d $(pwd) ]]") == ["pwd"]

    def test_regex_rhs_cmdsubst(self) -> None:
        assert _commands("[[ $var =~ $(cmd) ]]") == ["cmd"]

    def test_equality_rhs_cmdsubst(self) -> None:
        assert _commands("[[ a == $(cmd) ]]") == ["cmd"]


class TestLeftOperandsNeverCommands:
    """Invariant 8: only a logical right operand is command position."""

    def test_literal_left_operand_not_emitted(self) -> None:
        commands = _commands("[[ -d /tmp && ls ]]")
        assert "ls" in commands
        assert "d" not in commands and "tmp" not in commands

    def test_unary_test_operand_not_emitted(self) -> None:
        assert "passwd" not in _commands("[[ -d /etc/passwd ]]")

    def test_left_operand_of_chained_and_not_emitted(self) -> None:
        assert "ls" not in _commands("[[ -d /tmp && ls && pwd ]]")

    def test_left_operand_of_equality_not_emitted(self) -> None:
        assert _commands("[[ /etc/passwd == other ]]") == []

    def test_logical_left_operands_not_emitted(self) -> None:
        assert _commands("[[ a && -d b || c ]]") == ["c"]

    def test_known_limitation_path_as_and_right_operand(self) -> None:
        """The ``&&`` heuristic has no way to tell a command from a value.

        A path sitting in the right operand of ``&&`` (``[[ -d /tmp &&
        /etc/passwd ]]``) is still reported as a command - that is the
        documented cost of invariant 1 and is unchanged here.
        """
        assert _commands("[[ -d /tmp && /etc/passwd ]]") == ["/etc/passwd"]


class TestTestClauseRedirectionsUnaffected:
    """Statement redirections still ride on the synthetic ``[[`` segment."""

    def test_synthetic_segment_for_empty_body(self) -> None:
        segs = parse_segments("[[ -f file ]] > /tmp/out")
        assert len(segs) == 1
        assert segs[0]["command"] == "[["
        assert segs[0]["redirections"][0]["Op"] == ">"

    def test_redirection_not_scattered_onto_inner_command(self) -> None:
        segs = parse_segments("[[ -d /tmp && ls ]] > /tmp/out")
        carrying = [s for s in segs if s["redirections"]]
        assert len(carrying) == 1
        assert carrying[0]["command"] == "[["
        assert any(s["command"] == "ls" and s["redirections"] == [] for s in segs)

    def test_regex_rhs_redirection_no_phantom(self) -> None:
        segs = parse_segments("[[ $var =~ pat ]] > /tmp/out")
        assert "pat" not in _commands("[[ $var =~ pat ]] > /tmp/out")
        assert any(s["redirections"] for s in segs)

    def test_paren_test_redirection_synthetic_segment(self) -> None:
        segs = parse_segments("[[ ( -d /tmp ) ]] > /tmp/out")
        assert len(segs) == 1
        assert segs[0]["command"] == "[["
        assert segs[0]["redirections"]
