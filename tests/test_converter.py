"""
Tests for the shfmt-JSON to typed-AST conversion boundary.

What the nodes look like once built is covered by ``test_ast.py`` and
``test_parser.py``; this covers the act of conversion - absent input, and a
node type the converter does not know.
"""

from lovely_bash_permissions.converter import _convert_word, _parse_position, node_from_json


class TestNoneInputIsTolerated:
    """Absent input yields None rather than raising.

    shfmt omits keys for nodes it has no data for, so every converter has to
    treat a missing key as "no node here" instead of failing.
    """

    def test_node_from_json_returns_none_for_none(self) -> None:
        assert node_from_json(None) is None

    def test_word_from_json_returns_none_for_none(self) -> None:
        assert _convert_word(None) is None

    def test_parse_position_returns_none_for_none(self) -> None:
        assert _parse_position(None) is None


class TestUnknownTypeDegradesVisibly:
    """A node type the converter does not know keeps its name and loses its payload.

    The shfmt node types are an upstream enumeration, so a type can appear that
    this converter has no mapping for. The result is a bare ``Node`` carrying
    the type name and its positions: the name survives, so a caller can see
    what it got, and every other field is empty rather than absent, so nothing
    downstream can mistake the node for a populated one.
    """

    def test_type_name_is_preserved(self) -> None:
        node = node_from_json({"Type": "SomethingShfmtAddedLater"})
        assert node is not None
        assert node.type == "SomethingShfmtAddedLater"

    def test_no_field_of_an_unknown_type_is_populated(self) -> None:
        node = node_from_json({"Type": "SomethingShfmtAddedLater", "Stmts": [1, 2, 3]})
        assert node is not None
        assert getattr(node, "stmts", None) is None


class TestConverterParseAstDialect:
    def test_dialect_is_passed_to_the_parser(self) -> None:
        from lovely_bash_permissions.ast import CallExpr, TestClause
        from lovely_bash_permissions.converter import parse_ast

        assert isinstance(parse_ast("[[ -f x ]]").stmts[0].cmd, TestClause)
        assert isinstance(parse_ast("[[ -f x ]]", "posix").stmts[0].cmd, CallExpr)
