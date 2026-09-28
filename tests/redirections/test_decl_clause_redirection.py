"""Tests for redirection handling in declaration builtin commands.

A declaration builtin (``export``/``readonly``/``declare``/``local``/``typeset``)
produces **two** segments: the operands become a variable-assignment segment
(command ``""``, no redirections) and the keyword becomes a bare command segment
that carries the statement's redirections. That split is what lets the
``variable_assignment`` policy apply to ``export FOO=bar``, so these tests assert
the exact segment list -- both the operands and *which* segment owns the
redirection -- rather than scanning for a segment that happens to match.
"""

from typing import Any

from lovely_bash_permissions.segments import parse_segments

Shape = list[tuple[str, list[str], list[str]]]


def shape_of(command: str) -> Shape:
    """Reduce parse_segments output to (command, arguments, [redirection Op]) tuples.

    Comparing full shapes pins segment count, segment order, the arguments of each
    segment, and the segment that owns each redirection -- a scan-and-set-found
    loop cannot distinguish any of those.
    """
    return [(s["command"], s["arguments"], [r["Op"] for r in s["redirections"]]) for s in parse_segments(command)]


def first_value(word: dict[str, Any]) -> str:
    """Return the first literal Value of a redirection target word."""
    return str(word["Parts"][0]["Value"])


class TestDeclClauseRedirectionInheritance:
    """Verify declaration builtins emit an assignment segment plus a keyword segment."""

    def test_export_with_output_redirection(self) -> None:
        """export splits into an assignment segment and a redirect-bearing export segment."""
        segs = parse_segments('export FOO="bar" > /tmp/out.txt')
        assert shape_of('export FOO="bar" > /tmp/out.txt') == [("", ['FOO="bar"'], []), ("export", [], [">"])]
        # the redirection rides on the keyword segment, and names /tmp/out.txt
        assert first_value(segs[1]["redirections"][0]["Word"]) == "/tmp/out.txt"

    def test_readonly_with_output_redirection(self) -> None:
        """readonly splits the same way; the operand stays on the assignment segment."""
        assert shape_of('readonly FOO="bar" > /tmp/out.txt') == [("", ['FOO="bar"'], []), ("readonly", [], [">"])]

    def test_declare_with_output_redirection(self) -> None:
        """declare -x: the option flag is an assignment-segment operand, not a declare argument."""
        assert shape_of('declare -x FOO="bar" > /tmp/out.txt') == [
            ("", ["-x", 'FOO="bar"'], []),
            ("declare", [], [">"]),
        ]

    def test_local_with_output_redirection(self) -> None:
        """local splits into an assignment segment and a redirect-bearing local segment."""
        assert shape_of('local FOO="bar" > /tmp/out.txt') == [("", ['FOO="bar"'], []), ("local", [], [">"])]

    def test_typeset_with_output_redirection(self) -> None:
        """typeset splits into an assignment segment and a redirect-bearing typeset segment."""
        assert shape_of('typeset FOO="bar" > /tmp/out.txt') == [("", ['FOO="bar"'], []), ("typeset", [], [">"])]

    def test_export_with_fd_redirection(self) -> None:
        """export's keyword segment carries the fd-prefixed redirection and its fd number."""
        segs = parse_segments('export FOO="bar" 2> /tmp/err.txt')
        assert shape_of('export FOO="bar" 2> /tmp/err.txt') == [("", ['FOO="bar"'], []), ("export", [], [">"])]
        # Op alone cannot distinguish `2>` from `>`; pin the fd and the target.
        assert segs[1]["redirections"][0]["N"] == {"Value": "2"}
        assert first_value(segs[1]["redirections"][0]["Word"]) == "/tmp/err.txt"
        # the fd redirection must not be duplicated onto the assignment segment
        assert segs[0]["redirections"] == []

    def test_callexpr_regression_still_works(self) -> None:
        """A plain CallExpr is still a single segment owning its redirection."""
        segs = parse_segments("echo hi > /tmp/test.txt")
        assert shape_of("echo hi > /tmp/test.txt") == [("echo", ["hi"], [">"])]
        assert first_value(segs[0]["redirections"][0]["Word"]) == "/tmp/test.txt"

    def test_export_nested_cmdsubst_still_detected(self) -> None:
        """The CmdSubst value yields a third segment that owns its own inner redirection."""
        assert shape_of("export FOO=$(echo bar > /tmp/out.txt)") == [
            ("", ["FOO=$(...)"], []),
            ("export", [], []),
            ("echo", ["bar"], [">"]),
        ]

    def test_export_no_redirection(self) -> None:
        """Without a redirection the keyword segment is bare and the assignment segment still exists."""
        segs = parse_segments('export FOO="bar"')
        assert shape_of('export FOO="bar"') == [("", ['FOO="bar"'], []), ("export", [], [])]
        assert segs[1]["redirections"] == []
        assert segs[0]["command"] == ""
        assert segs[0]["arguments"] == ['FOO="bar"']

    def test_declclause_multiple_redirs(self) -> None:
        """Both redirections land on the keyword segment; the assignment segment keeps none."""
        segs = parse_segments('export FOO="bar" > /tmp/out.txt 2> /tmp/err.txt')
        assert shape_of('export FOO="bar" > /tmp/out.txt 2> /tmp/err.txt') == [
            ("", ['FOO="bar"'], []),
            ("export", [], [">", ">"]),
        ]
        keyword_redirs = segs[1]["redirections"]
        assert len(keyword_redirs) == 2
        assert segs[0]["redirections"] == []
        # order and fd attribution, not just the count of two
        assert [r["Op"] for r in keyword_redirs] == [">", ">"]
        assert first_value(keyword_redirs[0]["Word"]) == "/tmp/out.txt"
        assert first_value(keyword_redirs[1]["Word"]) == "/tmp/err.txt"
        # the first is an implicit-fd `>`, the second an explicit `2>`
        assert keyword_redirs[0]["N"] == {}
        assert keyword_redirs[1]["N"] == {"Value": "2"}

    def test_declclause_in_block_inherits_block_redirs(self) -> None:
        """A block's redirection is inherited by the keyword segment, not the assignment segment."""
        assert shape_of('{ export FOO="bar"; } > /tmp/out.txt') == [("", ['FOO="bar"'], []), ("export", [], [">"])]

    def test_export_multiple_values_redir(self) -> None:
        """All assignments share one assignment segment, in source order."""
        assert shape_of('export A="x" B="y" > /tmp/out.txt') == [
            ("", ['A="x"', 'B="y"'], []),
            ("export", [], [">"]),
        ]

    def test_decl_clause_recurses_into_cmdsubst_in_value(self) -> None:
        """The CmdSubst inside the assignment value is recursed into as its own segment."""
        assert shape_of("export FOO=$(rm -rf /tmp/x)") == [
            ("", ["FOO=$(...)"], []),
            ("export", [], []),
            ("rm", ["-rf", "/tmp/x"], []),
        ]

    def test_decl_clause_recurses_into_cmdsubst_in_redir_target(self) -> None:
        """The CmdSubst in the redirection target is a third segment; the redirect stays on export."""
        assert shape_of('export FOO="bar" > $(mktemp)') == [
            ("", ['FOO="bar"'], []),
            ("export", [], [">"]),
            ("mktemp", [], []),
        ]


class TestDeclClauseOperandShape:
    """Pin the operand/keyword split itself, not just per-variant redirection behavior."""

    def test_every_declaration_variant_emits_variable_assignment_segment(self) -> None:
        """export/readonly/local/declare/typeset all emit a separate "" assignment segment."""
        for keyword, operands in [
            ("export", ['FOO="bar"']),
            ("readonly", ['FOO="bar"']),
            ("local", ['FOO="bar"']),
            ("declare", ["-x", 'FOO="bar"']),
            ("typeset", ['FOO="bar"']),
        ]:
            assert shape_of(f"{keyword} {' '.join(operands)}") == [("", operands, []), (keyword, [], [])], keyword

    def test_bare_keyword_has_no_operands_and_no_segments(self) -> None:
        """A declaration with no operands yields no assignment segment and no keyword segment."""
        assert shape_of("export") == []
        for keyword in ("readonly", "local", "declare", "typeset"):
            assert shape_of(keyword) == [], keyword

    def test_non_assignment_operands_still_land_on_assignment_segment(self) -> None:
        """Operands that are not NAME=value (names, flags, arrays) also go to the "" segment."""
        assert shape_of("export FOO bar") == [("", ["FOO", "bar"], []), ("export", [], [])]
        assert shape_of("export BOGUS=true bogus") == [("", ["BOGUS=true", "bogus"], []), ("export", [], [])]
        assert shape_of("export -f foo") == [("", ["-f", "foo"], []), ("export", [], [])]
        assert shape_of("declare -a A=(a b)") == [("", ["-a", "A=(a b)"], []), ("declare", [], [])]
        assert shape_of("export A=()") == [("", ["A=(...)"], []), ("export", [], [])]

    def test_operand_shape_matches_callexpr_assignment_prefix(self) -> None:
        """A declaration operand is attributed exactly like a CallExpr assignment prefix."""
        decl = shape_of('export FOO="bar" > /tmp/out')
        call = shape_of("FOO=bar ls > /tmp/out")
        assert decl == [("", ['FOO="bar"'], []), ("export", [], [">"])]
        assert call == [("", ["FOO=bar"], []), ("ls", [], [">"])]

        # same two-segment contract in both, with only the command name and operand spelling differing
        for form, command_name in ((decl, "export"), (call, "ls")):
            assert len(form) == 2, command_name
            assert form[0][0] == "", command_name
            assert form[1][0] == command_name
            assert form[0][2] == [], command_name
            assert form[1][2] == [">"], command_name

    def test_lone_assignment_without_command_keeps_its_redirection(self) -> None:
        """A bare `FOO=bar > /tmp/out` has no command segment, so the redirect stays on the assignment."""
        # pre-existing CallExpr behavior, pinned here so the DeclClause rule above is not
        # over-generalized into "assignment segments never carry redirections".
        assert shape_of("FOO=bar > /tmp/out") == [("", ["FOO=bar"], [">"])]
