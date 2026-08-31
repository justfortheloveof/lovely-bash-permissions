"""
Comprehensive tests for AST node types.

Verifies that all node dataclasses exist, are registered in NODE_TYPES,
and have correct default values. Tests each type by importing it and
checking registration status.
"""

import pytest


class TestBraceExpNode:
    """Tests for the BraceExp node type (Step 9)."""

    def test_brace_exp_dataclass_exists(self):
        """BraceExp dataclass is importable from lovely_bash_permissions."""
        from lovely_bash_permissions import BraceExp
        assert BraceExp is not None

    def test_brace_exp_type_string(self):
        """BraceExp default type string is 'BraceExp'."""
        from lovely_bash_permissions import BraceExp
        node = BraceExp()
        assert node.type == "BraceExp"

    def test_brace_exp_sequence_default(self):
        """BraceExp default sequence is False."""
        from lovely_bash_permissions import BraceExp
        node = BraceExp()
        assert node.sequence is False

    def test_brace_exp_elems_default(self):
        """BraceExp default elems is None."""
        from lovely_bash_permissions import BraceExp
        node = BraceExp()
        assert node.elems is None

    def test_brace_exp_registered_in_node_types(self):
        """BraceExp is registered in ast.NODE_TYPES mapping."""
        from lovely_bash_permissions.ast import NODE_TYPES, BraceExp
        assert "BraceExp" in NODE_TYPES
        assert NODE_TYPES["BraceExp"] is BraceExp

    def test_brace_exp_instantiation_with_values(self):
        """BraceExp can be instantiated with custom values."""
        from lovely_bash_permissions import BraceExp, Word
        node = BraceExp(
            type="BraceExp",
            sequence=True,
            elems=[Word(parts=[])],
        )
        assert node.sequence is True
        assert len(node.elems) == 1
