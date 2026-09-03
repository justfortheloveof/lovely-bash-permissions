"""
Library-level tests for per-operand redirection data on BinaryCmd.

Regression coverage for the converter/ast change that splits a BinaryCmd's
redirections into ``left_redirs``/``right_redirs`` (per operand) while keeping
the merged ``redirs`` list for backwards compatibility. This supports the CLI
rendering fix so each pipeline segment's redirection can be attributed to the
command that owns it.
"""

from lovely_bash_permissions import BinaryCmd, parse_ast


class TestBinaryPerSideRedirs:
    """BinaryCmd must carry per-operand redirections in its AST fields."""

    def test_simple_two_segment_per_side(self) -> None:
        """cmd2 > 2 | cmd3 > 3 splits redirs onto left_redirs and right_redirs."""
        tree = parse_ast("cmd2 > 2 | cmd3 > 3")
        stmt = tree.stmts[0]
        bc = stmt.cmd
        assert isinstance(bc, BinaryCmd)

        assert len(bc.left_redirs) == 1
        assert bc.left_redirs[0].word.parts[0].value == "2"

        assert len(bc.right_redirs) == 1
        assert bc.right_redirs[0].word.parts[0].value == "3"

        merged_targets = [r.word.parts[0].value for r in bc.redirs]
        assert merged_targets == ["2", "3"]

    def test_three_segment_left_nested_per_side(self) -> None:
        """a > 1 | b > 2 | c > 3 — redirs split per-side across the nested chain."""
        tree = parse_ast("a > 1 | b > 2 | c > 3")
        stmt = tree.stmts[0]
        outer = stmt.cmd
        assert isinstance(outer, BinaryCmd)

        inner = outer.left
        assert isinstance(inner, BinaryCmd)

        assert len(inner.left_redirs) >= 1
        assert inner.left_redirs[0].word.parts[0].value == "1"

        assert len(inner.right_redirs) >= 1
        assert inner.right_redirs[0].word.parts[0].value == "2"

        merged_targets = [
            r.word.parts[0].value for node in (inner, outer) if isinstance(node, BinaryCmd) for r in node.redirs
        ]
        assert "1" in merged_targets
        assert "2" in merged_targets
        assert "3" in merged_targets
