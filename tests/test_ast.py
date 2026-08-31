"""
Tests for AST node types — dataclass structure, NODE_TYPES registry,
and node types not covered by test_parser.py.
"""

from lovely_bash_permissions import (
    BraceExp,
    Word,
    parse_ast,
)
from lovely_bash_permissions.ast import NODE_TYPES


class TestBraceExpNode:
    """Tests for the BraceExp node type."""

    def test_brace_exp_dataclass_exists(self):
        assert BraceExp is not None

    def test_brace_exp_type_string(self):
        node = BraceExp()
        assert node.type == "BraceExp"

    def test_brace_exp_sequence_default(self):
        node = BraceExp()
        assert node.sequence is False

    def test_brace_exp_elems_default(self):
        node = BraceExp()
        assert node.elems == []

    def test_brace_exp_registered_in_node_types(self):
        assert "BraceExp" in NODE_TYPES

    def test_brace_exp_instantiation(self):
        node = BraceExp(sequence=True, elems=[Word(parts=[])])
        assert node.sequence is True


class TestNodeTypesRegistry:
    """Verify all expected types are registered in NODE_TYPES."""

    def test_all_core_types_registered(self):
        expected = [
            "File",
            "CallExpr",
            "BinaryCmd",
            "Word",
            "DeclClause",
            "Subshell",
            "IfClause",
            "ForClause",
            "WhileClause",
            "AndCmd",
            "OrCmd",
            "CaseClause",
            "Lit",
            "SglQuoted",
            "ParamExp",
            "DblQuoted",
            "CmdSubst",
            "ProcSubst",
            "ArithmExp",
            "BraceExp",
            "BinaryArithm",
            "ExtGlob",
            "Block",
            "FuncDecl",
            "TestClause",
            "UnaryTest",
            "BinaryTest",
            "ParenTest",
            "ArithmCmd",
            "UnaryArithm",
            "ParenArithm",
            "FlagsArithm",
            "LetClause",
            "TimeClause",
            "CoprocClause",
            "TestDecl",
            "Comment",
            "Assign",
            "CaseItem",
            "WordIter",
            "CStyleLoop",
            "ArrayExpr",
            "ArrayElem",
        ]
        for name in expected:
            assert name in NODE_TYPES, f"{name} missing from NODE_TYPES"


class TestNodeFromJsonNoneGuard:
    """Verify that node_from_json handles None input gracefully."""

    def test_node_from_json_returns_none_for_none(self):
        from lovely_bash_permissions.ast import node_from_json

        assert node_from_json(None) is None

    def test_word_from_json_returns_none_for_none(self):
        from lovely_bash_permissions.ast import word_from_json

        assert word_from_json(None) is None

    def test_parse_position_returns_none_for_none(self):
        from lovely_bash_permissions.ast import _parse_position

        assert _parse_position(None) is None


class TestStmtInheritsNode:
    """Verify Stmt and Redir inherit from Node."""

    def test_stmt_is_node(self):
        from lovely_bash_permissions.ast import Node, Stmt

        s = Stmt()
        assert isinstance(s, Node)

    def test_redir_is_node(self):
        from lovely_bash_permissions.ast import Node, Redir

        r = Redir()
        assert isinstance(r, Node)


class TestConsistentNaming:
    """Verify BinaryArithm, BinaryTest, AndCmd, OrCmd use left/right."""

    def test_binary_arithm_left_right(self):
        tree = parse_ast("echo $((2 + 3))")
        arithm = tree.stmts[0].cmd.args[1].parts[0].x
        assert hasattr(arithm, "left")
        assert hasattr(arithm, "right")

    def test_and_cmd_left_right(self):
        tree = parse_ast("cd /tmp && ls")
        cmd = tree.stmts[0].cmd
        assert hasattr(cmd, "left")
        assert hasattr(cmd, "right")
