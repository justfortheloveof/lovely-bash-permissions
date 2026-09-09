"""Tests for redirection inheritance in declaration builtin commands.

This module verifies that declaration builtins (export, declare, readonly,
local, typeset) correctly inherit redirections from their parent statement.
The test pattern follows test_segments_redirs.py for consistency.
"""

from lovely_bash_permissions.segments import parse_segments


class TestDeclClauseRedirectionInheritance:
    """Verify that declaration builtins inherit redirections from parent statements."""

    def test_export_with_output_redirection(self) -> None:
        """export with output redirection should carry the redirection in its segment."""
        segs = parse_segments("export FOO=\"bar\" > /tmp/out.txt")
        assert len(segs) >= 1
        found = False
        for seg in segs:
            if seg["command"] == "export" and seg["redirections"]:
                assert seg["redirections"][0]["Op"] == ">"
                assert seg["redirections"][0]["Word"]["Parts"][0]["Value"] == "/tmp/out.txt"
                found = True
        assert found

    def test_readonly_with_output_redirection(self) -> None:
        """readonly with output redirection should carry the redirection in its segment."""
        segs = parse_segments("readonly FOO=\"bar\" > /tmp/out.txt")
        assert len(segs) >= 1
        found = False
        for seg in segs:
            if seg["command"] == "readonly" and seg["redirections"]:
                assert seg["redirections"][0]["Op"] == ">"
                found = True
        assert found

    def test_declare_with_output_redirection(self) -> None:
        """declare -x with output redirection should carry the redirection in its segment."""
        segs = parse_segments("declare -x FOO=\"bar\" > /tmp/out.txt")
        assert len(segs) >= 1
        found = False
        for seg in segs:
            if seg["command"] == "declare" and seg["redirections"]:
                assert seg["redirections"][0]["Op"] == ">"
                found = True
        assert found

    def test_local_with_output_redirection(self) -> None:
        """local with output redirection should carry the redirection in its segment."""
        segs = parse_segments("local FOO=\"bar\" > /tmp/out.txt")
        assert len(segs) >= 1
        found = False
        for seg in segs:
            if seg["command"] == "local" and seg["redirections"]:
                assert seg["redirections"][0]["Op"] == ">"
                found = True
        assert found

    def test_typeset_with_output_redirection(self) -> None:
        """typeset with output redirection should carry the redirection in its segment."""
        segs = parse_segments("typeset FOO=\"bar\" > /tmp/out.txt")
        assert len(segs) >= 1
        found = False
        for seg in segs:
            if seg["command"] == "typeset" and seg["redirections"]:
                assert seg["redirections"][0]["Op"] == ">"
                found = True
        assert found

    def test_export_with_fd_redirection(self) -> None:
        """export with fd redirection (2>) should carry the redirection in its segment."""
        segs = parse_segments("export FOO=\"bar\" 2> /tmp/err.txt")
        assert len(segs) >= 1
        found = False
        for seg in segs:
            if seg["command"] == "export" and seg["redirections"]:
                assert seg["redirections"][0]["Op"] == ">"
                assert seg["redirections"][0]["N"] == {"Value": "2"}
                found = True
        assert found

    def test_callexpr_regression_still_works(self) -> None:
        """CallExpr should still carry redirections (regression test)."""
        segs = parse_segments("echo hi > /tmp/test.txt")
        assert len(segs) == 1
        r = segs[0]["redirections"]
        assert len(r) == 1
        assert r[0]["Op"] == ">"
        assert r[0]["Word"]["Parts"][0]["Value"] == "/tmp/test.txt"

    def test_export_nested_cmdsubst_still_detected(self) -> None:
        """export with nested CmdSubst in value should still be extracted (regression)."""
        segs = parse_segments("export FOO=$(echo bar > /tmp/out.txt)")
        found_nested = False
        for seg in segs:
            if seg["command"] == "echo" and seg["redirections"]:
                assert seg["redirections"][0]["Op"] == ">"
                found_nested = True
        assert found_nested

    def test_export_no_redirection(self) -> None:
        """export without redirection should have empty redirections list."""
        segs = parse_segments("export FOO=\"bar\"")
        found = False
        for seg in segs:
            if seg["command"] == "export":
                assert seg["redirections"] == []
                found = True
        assert found

    def test_declclause_multiple_redirs(self) -> None:
        """export with multiple redirections should carry all of them."""
        segs = parse_segments("export FOO=\"bar\" > /tmp/out.txt 2> /tmp/err.txt")
        found = False
        for seg in segs:
            if seg["command"] == "export" and len(seg["redirections"]) == 2:
                found = True
        assert found

    def test_declclause_in_block_inherits_block_redirs(self) -> None:
        """DeclClause in a block should inherit the block's redirections."""
        segs = parse_segments("{ export FOO=\"bar\"; } > /tmp/out.txt")
        found = False
        for seg in segs:
            if seg["command"] == "export" and seg["redirections"]:
                found = True
        assert found

    def test_export_multiple_values_redir(self) -> None:
        """export with multiple assignments and redirection should carry the redirection."""
        segs = parse_segments("export A=\"x\" B=\"y\" > /tmp/out.txt")
        found = False
        for seg in segs:
            if seg["command"] == "export" and seg["redirections"]:
                found = True
        assert found

    def test_decl_clause_recurses_into_cmdsubst_in_value(self) -> None:
        """DeclClause should still recurse into CmdSubst in its value expressions."""
        segs = parse_segments("export FOO=$(rm -rf /tmp/x)")
        found_nested = False
        for seg in segs:
            if seg["command"] == "rm":
                found_nested = True
        assert found_nested

    def test_decl_clause_recurses_into_cmdsubst_in_redir_target(self) -> None:
        """DeclClause should recurse into CmdSubst in its redirection target word."""
        segs = parse_segments("export FOO=\"bar\" > $(mktemp)")
        found_nested = False
        for seg in segs:
            if seg["command"] == "mktemp":
                found_nested = True
        assert found_nested