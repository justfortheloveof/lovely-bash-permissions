"""
Tests for AST node types — dataclass structure and node types
not covered by test_parser.py.
"""

from lovely_bash_permissions import (
    BraceExp,
    DeclClause,
    Word,
    parse_ast,
)


class TestBraceExpNode:
    """Tests for the BraceExp node type."""

    def test_brace_exp_dataclass_exists(self) -> None:
        assert BraceExp is not None

    def test_brace_exp_type_string(self) -> None:
        node = BraceExp()
        assert node.type == "BraceExp"

    def test_brace_exp_sequence_default(self) -> None:
        node = BraceExp()
        assert node.sequence is False

    def test_brace_exp_elems_default(self) -> None:
        node = BraceExp()
        assert node.elems == []

    def test_brace_exp_instantiation(self) -> None:
        node = BraceExp(sequence=True, elems=[Word(parts=[])])
        assert node.sequence is True


class TestNodeFromJsonNoneGuard:
    """Verify that node_from_json handles None input gracefully."""

    def test_node_from_json_returns_none_for_none(self) -> None:
        from lovely_bash_permissions.converter import node_from_json

        assert node_from_json(None) is None

    def test_word_from_json_returns_none_for_none(self) -> None:
        from lovely_bash_permissions.converter import _convert_word

        assert _convert_word(None) is None

    def test_parse_position_returns_none_for_none(self) -> None:
        from lovely_bash_permissions.converter import _parse_position

        assert _parse_position(None) is None


class TestStmtInheritsNode:
    """Verify Stmt and Redir inherit from Node."""

    def test_stmt_is_node(self) -> None:
        from lovely_bash_permissions.ast import Node, Stmt

        s = Stmt()
        assert isinstance(s, Node)

    def test_redir_is_node(self) -> None:
        from lovely_bash_permissions.ast import Node, Redir

        r = Redir()
        assert isinstance(r, Node)


class TestConsistentNaming:
    """Verify BinaryArithm, BinaryTest, AndCmd, OrCmd use left/right."""

    def test_binary_arithm_left_right(self) -> None:
        tree = parse_ast("echo $((2 + 3))")
        arithm = tree.stmts[0].cmd.args[1].parts[0].x
        assert hasattr(arithm, "left")
        assert hasattr(arithm, "right")

    def test_and_cmd_left_right(self) -> None:
        tree = parse_ast("cd /tmp && ls")
        cmd = tree.stmts[0].cmd
        assert hasattr(cmd, "left")
        assert hasattr(cmd, "right")


class TestDeclClauseNode:
    """Tests for the DeclClause dataclass."""

    def test_decl_clause_is_proper_type(self) -> None:
        assert DeclClause is not None
        node = DeclClause()
        assert node.type == "DeclClause"

    def test_decl_clause_isinstance(self) -> None:
        tree = parse_ast("export FOO=bar")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, DeclClause)
        assert cmd.type == "DeclClause"


class TestNodeRepr:
    """Test depth-limited __repr__ on nodes."""

    def test_repr_does_not_raise(self) -> None:
        tree = parse_ast("ls -la | grep txt")
        r = repr(tree)
        assert "File" in r

    def test_repr_is_depth_limited(self) -> None:
        tree = parse_ast("ls -la | grep txt")
        r = repr(tree)
        assert "..." in r


class TestAllExports:
    """Validate that __all__ stays in sync with actual module exports."""

    def test_all_matches_namespace(self) -> None:
        import types

        import lovely_bash_permissions

        all_set = set(lovely_bash_permissions.__all__)
        namespace = {
            name
            for name in dir(lovely_bash_permissions)
            if not name.startswith("_") and not isinstance(getattr(lovely_bash_permissions, name), types.ModuleType)
        }
        missing_from_all = namespace - all_set
        extra_in_all = all_set - namespace
        assert not missing_from_all, f"In namespace but not __all__: {missing_from_all}"
        assert not extra_in_all, f"In __all__ but not namespace: {extra_in_all}"
