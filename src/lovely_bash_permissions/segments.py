"""
Bash command segment parser.

This module provides the :func:`parse_segments` function which parses
bash command strings into structured segments. Each segment contains
the command name, arguments, and redirections.

Segment extraction handles:
    - Pipes (|): each side becomes a separate segment
    - And (&&): each side becomes a separate segment
    - Or (||): each side becomes a separate segment
    - Background (&): the command before & is extracted
    - Statements: each sequential command becomes a segment

If parsing fails, an empty list is returned.
"""

from __future__ import annotations

import logging
from typing import Any

from .ast import (
    AndCmd,
    BinaryCmd,
    BinaryTest,
    Block,
    CallExpr,
    CaseClause,
    CmdSubst,
    CStyleLoop,
    DeclClause,
    File,
    ForClause,
    FuncDecl,
    IfClause,
    Lit,
    OrCmd,
    ParenTest,
    ProcSubst,
    Redir,
    Stmt,
    Subshell,
    TestClause,
    WhileClause,
    Word,
)
from .converter import node_from_json
from .inspect import _word_raw, _word_value
from .parser import ParseError, parse

_logger = logging.getLogger(__name__)

#: Default shell dialect used for parsing
DEFAULT_DIALECT = "bash"


def _extract_redirs(node: object) -> list[Redir]:
    """Extract redirections from a typed AST node.

    Handles both wrapped statements (Stmt.redirs) and direct operands whose
    redirections live on the node itself (BinaryCmd left/right_redirs).

    Args:
        node: A typed AST node.

    Returns:
        List of Redir objects found on this node.
    """
    if isinstance(node, Stmt):
        return list(node.redirs)
    elif isinstance(node, BinaryCmd):
        # Per-side split — caller decides how to attribute them
        return []  # handled inline by the caller
    else:
        return []


def _extract_segments(
    node: object, redirs: list[Redir] | None = None, *, _in_test_expr: bool = False
) -> list[dict[str, Any]]:
    """
    Recursively extract command segments from an AST node.

    Args:
        node: An AST node (raw shfmt JSON dict or Python node).
        redirs: Redirections inherited from a parent statement/pipe.

    Returns:
        List of segment dicts, each with:
            - 'command': str - command name
            - 'arguments': list[str] - argument strings
            - 'redirections': list[dict] - redirection info
    """
    segments: list[dict[str, Any]] = []

    # Handle Python AST nodes
    if isinstance(node, BinaryCmd):
        # Pipe commands: each side becomes a separate segment.
        # Redirections live on the BinaryCmd's per-side fields.
        left_redirs = _extract_redirs(node.left) if node.left else []
        right_redirs = _extract_redirs(node.right) if node.right else []
        # If the BinaryCmd itself carries per-side redirs, merge them in
        if node.left_redirs:
            left_redirs = list(node.left_redirs) + left_redirs
        if node.right_redirs:
            right_redirs = list(node.right_redirs) + right_redirs
        segments.extend(_extract_segments(node.left, left_redirs))
        segments.extend(_extract_segments(node.right, right_redirs))

    elif isinstance(node, AndCmd):
        # Logical AND: each side becomes a separate segment
        left_redirs = _extract_redirs(node.left) if node.left else []
        right_redirs = _extract_redirs(node.right) if node.right else []
        segments.extend(_extract_segments(node.left, left_redirs))
        segments.extend(_extract_segments(node.right, right_redirs))

    elif isinstance(node, OrCmd):
        # Logical OR: each side becomes a separate segment
        left_redirs = _extract_redirs(node.left) if node.left else []
        right_redirs = _extract_redirs(node.right) if node.right else []
        segments.extend(_extract_segments(node.left, left_redirs))
        segments.extend(_extract_segments(node.right, right_redirs))

    elif isinstance(node, Stmt):
        # Statement: redirections live on the statement itself.
        # Pass them down so each command segment inherits them.
        inherited = list(node.redirs)
        if node.cmd:
            segments.extend(_extract_segments(node.cmd, inherited))

    elif isinstance(node, CallExpr):
        # Simple command: extract command, arguments, and inherited redirections
        if node.args:

            def _part_value(p: object) -> str:
                """Extract string value from a Word part node."""
                if isinstance(p, Lit):
                    return p.value
                elif hasattr(p, "value"):
                    v = getattr(p, "value", None)
                    return v if isinstance(v, str) else ""
                return ""

            redir_dicts = [
                {
                    "Op": r.op,
                    "N": {"Value": str(r.n)} if r.n is not None else {},
                    "Word": {"Parts": [{"Value": _part_value(p)} for p in (r.word.parts if r.word else [])]},
                }
                for r in (redirs or [])
            ]
            segments.append(
                {
                    "command": _word_value(node.args[0]),
                    "arguments": [_word_raw(arg) for arg in node.args[1:]],
                    "redirections": redir_dicts,
                }
            )
            # Recurse into arguments to find nested CmdSubst/ProcSubst redirections
            for arg in node.args[1:]:
                segments.extend(_extract_segments(arg, redirs))

    elif isinstance(node, DeclClause):
        # export/unset with naked words: those are real command names
        if node.variant in ("export", "unset"):
            naked_assigns = [a for a in (node.assigns or []) if getattr(a, "naked", False)]
            if naked_assigns:
                name = naked_assigns[0].name
                cmd_name = name.value if name else ""
                if cmd_name:
                    segments.append({"command": cmd_name, "arguments": [], "redirections": []})
            elif node.args:
                # Fallback: use first arg value (works for unset without assigns)
                cmd_name = _word_value(node.args[0])
                segments.append({"command": cmd_name, "arguments": [], "redirections": []})
                segments.append({"command": cmd_name, "arguments": [], "redirections": []})
    elif isinstance(node, CaseClause):
        # case/switch: extract commands from each branch body
        if hasattr(node, "branches") and node.branches:
            for branch in node.branches:
                if hasattr(branch, "body") and branch.body:
                    for stmt in branch.body:
                        segments.extend(_extract_segments(stmt))

    elif isinstance(node, (ForClause, CStyleLoop)):
        # Extract commands from loop body
        if hasattr(node, "body") and node.body:
            for stmt in node.body:
                segments.extend(_extract_segments(stmt))

    elif isinstance(node, Subshell):
        # Recurse into subshell body (...)
        if hasattr(node, "stmts") and node.stmts:
            for stmt in node.stmts:
                segments.extend(_extract_segments(stmt))

    elif isinstance(node, TestClause):
        # Recurse into test expression — UnaryTest/BinaryTest may contain commands in args
        if hasattr(node, "body") and node.body:
            segments.extend(_extract_segments(node.body, _in_test_expr=True))

    elif isinstance(node, BinaryTest):
        # Test expression: only right operand of &&/|| is a "command" to check
        if hasattr(node, "right") and node.right:
            segments.extend(_extract_segments(node.right, _in_test_expr=True))

    elif isinstance(node, ParenTest):
        # Parenthesized test: recurse into body with test context
        if hasattr(node, "body") and node.body:
            segments.extend(_extract_segments(node.body, _in_test_expr=True))

    elif isinstance(node, (IfClause, WhileClause)):
        # Handle conditional blocks: extract from each branch.
        # cond_stmts / body are lists of Stmt (each carries its own redirs).
        if hasattr(node, "cond_stmts"):
            for stmt in node.cond_stmts:
                segments.extend(_extract_segments(stmt))
        if hasattr(node, "body") and node.body:
            for stmt in node.body:
                segments.extend(_extract_segments(stmt))
        if hasattr(node, "elif_branch") and node.elif_branch:
            segments.extend(_extract_segments(node.elif_branch))
        if hasattr(node, "else_stmts") and node.else_stmts:
            for stmt in node.else_stmts:
                segments.extend(_extract_segments(stmt))

    elif isinstance(node, Word):
        # Word nodes (arguments) may contain CmdSubst/ProcSubst in their parts.
        # Recurse into each part to find nested redirections (only outside test expr context).
        if not _in_test_expr:
            for part in node.parts:
                segments.extend(_extract_segments(part, _in_test_expr=False))
        # Inside test expressions, word values are command names
        if _in_test_expr:
            segments.append({"command": _word_value(node), "arguments": [], "redirections": []})

    elif isinstance(node, Lit):
        # Literals are command names only inside test expressions
        if _in_test_expr:
            segments.append({"command": node.value, "arguments": [], "redirections": []})

    elif isinstance(node, (CmdSubst, ProcSubst)):
        # Command/process substitution: recurse into each stmt, passing inherited redirs.
        if hasattr(node, "stmts") and node.stmts:
            inherited = list(redirs or [])
            for stmt in node.stmts:
                segments.extend(_extract_segments(stmt, inherited))

    elif isinstance(node, (FuncDecl, Block)):
        # Function body / block: recurse into contained stmts
        if hasattr(node, "body") and node.body:
            segments.extend(_extract_segments(node.body))
        elif hasattr(node, "stmts"):
            for stmt in node.stmts:
                segments.extend(_extract_segments(stmt))

    elif isinstance(node, File):
        # File: extract from all statements
        for stmt in node.stmts:
            segments.extend(_extract_segments(stmt))

    else:
        _logger.warning("Unhandled AST node type '%s' — returning 0 segments", type(node).__name__)

    return segments


def parse_segments(command: str, dialect: str = DEFAULT_DIALECT) -> list[dict[str, Any]]:
    """
    Parse a bash command into segments.

    Each segment represents a command with its name, arguments, and
    redirections. Commands are separated by pipes, logical AND/OR
    operators, background execution, and statement separators.

    Args:
        command: The bash command string to parse.
        dialect: Shell dialect for parsing (default: "bash").

    Returns:
        List of segment dicts. Each dict contains:
            - 'command': str - the command name
            - 'arguments': list[str] - the command's arguments
            - 'redirections': list[dict] - redirection info

        If parsing fails, returns an empty list.
    """
    if not command or not command.strip():
        return []

    try:
        raw_ast = parse(command, dialect)
        ast = node_from_json(raw_ast)
    except (ParseError, FileNotFoundError):
        return []

    if ast is None:
        return []
    return _extract_segments(ast)
