"""
Library-level tests for per-operand redirection data on BinaryCmd.

Regression coverage for the converter/ast change that splits a BinaryCmd's
redirections into ``left_redirs``/``right_redirs`` (per operand) while keeping
the merged ``redirs`` list for backwards compatibility. This supports the CLI
rendering fix so each pipeline segment's redirection can be attributed to the
command that owns it.
"""

from lovely_bash_permissions import BinaryCmd, Lit, parse_ast


class TestBinaryPerSideRedirs:
    """BinaryCmd must carry per-operand redirections in its AST fields."""

    def test_simple_two_segment_per_side(self) -> None:
        """cmd2 > left.txt | cmd3 > right.txt splits redirs onto left_redirs and right_redirs."""
        tree = parse_ast("cmd2 > left.txt | cmd3 > right.txt")
        stmt = tree.stmts[0]
        bc = stmt.cmd
        assert isinstance(bc, BinaryCmd)

        assert len(bc.left_redirs) == 1
        left_word = bc.left_redirs[0].word
        assert left_word is not None
        left_part = left_word.parts[0]
        assert left_part is not None
        assert isinstance(left_part, Lit)
        assert left_part.value == "left.txt"

        assert len(bc.right_redirs) == 1
        right_word = bc.right_redirs[0].word
        assert right_word is not None
        right_part = right_word.parts[0]
        assert right_part is not None
        assert isinstance(right_part, Lit)
        assert right_part.value == "right.txt"

        merged_targets = []
        for r in bc.redirs:
            rw = r.word
            assert rw is not None
            rp = rw.parts[0]
            assert rp is not None
            assert isinstance(rp, Lit)
            merged_targets.append(rp.value)
        assert merged_targets == ["left.txt", "right.txt"]

    def test_three_segment_left_nested_per_side(self) -> None:
        """a > 1 | b > 2 | c > 3 - redirs split per-side across the nested chain."""
        tree = parse_ast("a > 1 | b > 2 | c > 3")
        stmt = tree.stmts[0]
        outer = stmt.cmd
        assert isinstance(outer, BinaryCmd)

        inner = outer.left
        assert isinstance(inner, BinaryCmd)

        assert len(inner.left_redirs) >= 1
        left_word2 = inner.left_redirs[0].word
        assert left_word2 is not None
        left_part2 = left_word2.parts[0]
        assert left_part2 is not None
        assert isinstance(left_part2, Lit)
        assert left_part2.value == "1"

        assert len(inner.right_redirs) >= 1
        right_word2 = inner.right_redirs[0].word
        assert right_word2 is not None
        right_part2 = right_word2.parts[0]
        assert right_part2 is not None
        assert isinstance(right_part2, Lit)
        assert right_part2.value == "2"

        merged_targets = []
        for node in (inner, outer):
            if isinstance(node, BinaryCmd):
                for r in node.redirs:
                    rw2 = r.word
                    assert rw2 is not None
                    rp2 = rw2.parts[0]
                    assert rp2 is not None
                    assert isinstance(rp2, Lit)
                    merged_targets.append(rp2.value)
        assert "1" in merged_targets
        assert "2" in merged_targets
        assert "3" in merged_targets
