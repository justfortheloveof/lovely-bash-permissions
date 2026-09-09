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
    ArithmCmd,
    BinaryCmd,
    BinaryTest,
    Block,
    CallExpr,
    CaseClause,
    CmdSubst,
    CoprocClause,
    CStyleLoop,
    DeclClause,
    ElifBranch,
    File,
    ForClause,
    FuncDecl,
    IfClause,
    LetClause,
    Lit,
    OrCmd,
    ParenTest,
    ProcSubst,
    Redir,
    Stmt,
    Subshell,
    TestClause,
    TimeClause,
    UnaryTest,
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
        # Declaration builtins (export/unset). Only *naked* names are real
        # symbols being declared; `export NAME=value` is an assignment, not a
        # command invocation. Recurse into assignment values so command
        # substitutions inside them are still extracted (export FOO=$(rm x)).
        if node.variant in ("export", "unset"):
            for assign in node.assigns or []:
                if getattr(assign, "naked", False) and assign.name is not None and assign.name.value:
                    segments.append({"command": assign.name.value, "arguments": [], "redirections": []})
                if assign.value is not None:
                    segments.extend(_extract_segments(assign.value))
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

    elif isinstance(node, UnaryTest):
        # Unary test op (-d/-n/-z ...): the operand is a path/variable, not a
        # command. Recurse WITHOUT test-expr context so nested command
        # substitutions are still extracted (e.g. [[ -d $(pwd) ]]) but the
        # operand itself is not emitted as a segment.
        if node.x is not None:
            segments.extend(_extract_segments(node.x, _in_test_expr=False))

    elif isinstance(node, ParenTest):
        # Parenthesized test: recurse into body with test context
        if hasattr(node, "body") and node.body:
            segments.extend(_extract_segments(node.body, _in_test_expr=True))

    elif isinstance(node, TimeClause):
        # time <cmd> — extract the command from inside
        if hasattr(node, "stmt") and node.stmt:
            segments.extend(_extract_segments(node.stmt))

    elif isinstance(node, (ArithmCmd, LetClause)):
        # (( expr )) and let — arithmetic-only, skip (no real command)
        pass

    elif isinstance(node, CoprocClause):
        # coprocess — extract command if present
        if hasattr(node, "stmt") and node.stmt:
            segments.extend(_extract_segments(node.stmt))

    elif isinstance(node, IfClause):
        # Conditions and every branch body are real executions.
        for stmt in node.cond_stmts:
            segments.extend(_extract_segments(stmt))
        for stmt in node.then_stmts:
            segments.extend(_extract_segments(stmt))
        for elif_branch in node.elif_branches:
            segments.extend(_extract_segments(elif_branch))
        for stmt in node.else_stmts:
            segments.extend(_extract_segments(stmt))

    elif isinstance(node, ElifBranch):
        for stmt in node.cond:
            segments.extend(_extract_segments(stmt))
        for stmt in node.body:
            segments.extend(_extract_segments(stmt))

    elif isinstance(node, WhileClause):
        for stmt in node.cond_stmts:
            segments.extend(_extract_segments(stmt))
        for stmt in node.body:
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
