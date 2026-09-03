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

import sys

from .ast import (
    AndCmd,
    BinaryCmd,
    CallExpr,
    File,
    FuncDecl,
    IfClause,
    OrCmd,
    Stmt,
    WhileClause,
)
from .converter import node_from_json
from .inspect import _word_value
from .parser import ParseError, parse

#: Default shell dialect used for parsing
DEFAULT_DIALECT = "bash"


def _extract_segments(node: object) -> list[dict]:
    """
    Recursively extract command segments from an AST node.

    Args:
        node: An AST node (raw shfmt JSON dict or Python node).

    Returns:
        List of segment dicts, each with:
            - 'command': str - command name
            - 'arguments': list[str] - argument strings
            - 'redirections': list[dict] - redirection info
    """
    segments: list[dict] = []

    # Handle Python AST nodes
    if isinstance(node, BinaryCmd):
        # Pipe commands: process each side separately
        segments.extend(_extract_segments(node.left))
        segments.extend(_extract_segments(node.right))

    elif isinstance(node, AndCmd):
        # Logical AND: process each side separately
        segments.extend(_extract_segments(node.left))
        segments.extend(_extract_segments(node.right))

    elif isinstance(node, OrCmd):
        # Logical OR: process each side separately
        segments.extend(_extract_segments(node.left))
        segments.extend(_extract_segments(node.right))

    elif isinstance(node, Stmt):
        # Statement: extract segments from the cmd
        segments.extend(_extract_segments(node.cmd))

    elif isinstance(node, CallExpr):
        # Simple command: extract command and arguments
        if node.args:
            segments.append(
                {
                    "command": _word_value(node.args[0]),
                    "arguments": [_word_value(arg) for arg in node.args[1:]],
                    "redirections": [],
                }
            )

    elif isinstance(node, (IfClause, WhileClause)):
        # Handle conditional blocks: extract from each branch
        if hasattr(node, "cond"):
            segments.extend(_extract_segments(node.cond))
        if hasattr(node, "body") and node.body:
            for stmt in node.body:
                segments.extend(_extract_segments(stmt))
        if hasattr(node, "elif_branch") and node.elif_branch:
            segments.extend(_extract_segments(node.elif_branch))
        if hasattr(node, "else_branch") and node.else_branch:
            for stmt in node.else_branch:
                segments.extend(_extract_segments(stmt))

    elif isinstance(node, FuncDecl):
        # Function: extract from the body
        if node.body:
            segments.extend(_extract_segments(node.body))

    elif isinstance(node, File):
        # File: extract from all statements
        for stmt in node.stmts:
            segments.extend(_extract_segments(stmt))

    # Handle raw shfmt JSON nodes
    elif isinstance(node, dict):
        node_type = node.get("Type", "")
        if (
            node_type == "BinaryCmd"
            and node.get("Op") in ("|", "|&")
            or node_type == "AndCmd"
            or node_type == "OrCmd"
        ):
            segments.extend(_extract_segments(node.get("X")))
            segments.extend(_extract_segments(node.get("Y")))
        elif node_type == "CallExpr":
            args = node.get("Args", [])
            if args:
                segments.append(
                    {
                        "command": _word_value(args[0]),
                        "arguments": [_word_value(arg) for arg in args[1:]],
                        "redirections": [],
                    }
                )
        else:
            # Fall back to converting to Python node
            try:
                converted = node_from_json(node)
                if converted is not None:
                    return _extract_segments(converted)
            except Exception as e:  # noqa: BLE001
                print(f"error: {e}", file=sys.stderr)

    return segments


def parse_segments(command: str, dialect: str = DEFAULT_DIALECT) -> list[dict]:
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
