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
    ArithmExp,
    BinaryArithm,
    BinaryCmd,
    BinaryTest,
    Block,
    BraceExp,
    CallExpr,
    CaseClause,
    CmdSubst,
    CoprocClause,
    CStyleLoop,
    DblQuoted,
    DeclClause,
    ElifBranch,
    ExtGlob,
    File,
    FlagsArithm,
    ForClause,
    FuncDecl,
    IfClause,
    LetClause,
    Lit,
    OrCmd,
    ParamExp,
    ParenArithm,
    ParenTest,
    ProcSubst,
    Redir,
    SglQuoted,
    Stmt,
    Subshell,
    TestClause,
    TimeClause,
    UnaryArithm,
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
        # Redirections live on the BinaryCmd's per-side fields; also inherit
        # any redirections from a parent compound (e.g. `{ a | b; } > file`).
        left_redirs = list(redirs or [])
        right_redirs = list(redirs or [])
        left_redirs += _extract_redirs(node.left) if node.left else []
        right_redirs += _extract_redirs(node.right) if node.right else []
        if node.left_redirs:
            left_redirs = left_redirs + list(node.left_redirs)
        if node.right_redirs:
            right_redirs = right_redirs + list(node.right_redirs)
        segments.extend(_extract_segments(node.left, left_redirs))
        segments.extend(_extract_segments(node.right, right_redirs))

    elif isinstance(node, AndCmd):
        # Logical AND: each side becomes a separate segment
        left_redirs = list(redirs or [])
        right_redirs = list(redirs or [])
        left_redirs += _extract_redirs(node.left) if node.left else []
        right_redirs += _extract_redirs(node.right) if node.right else []
        segments.extend(_extract_segments(node.left, left_redirs))
        segments.extend(_extract_segments(node.right, right_redirs))

    elif isinstance(node, OrCmd):
        # Logical OR: each side becomes a separate segment
        left_redirs = list(redirs or [])
        right_redirs = list(redirs or [])
        left_redirs += _extract_redirs(node.left) if node.left else []
        right_redirs += _extract_redirs(node.right) if node.right else []
        segments.extend(_extract_segments(node.left, left_redirs))
        segments.extend(_extract_segments(node.right, right_redirs))

    elif isinstance(node, Stmt):
        # Statement: merge redirections inherited from a parent compound
        # command (e.g. `{ ...; } > file`) with the statement's own.
        inherited = list(redirs or []) + list(node.redirs)
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
            # Recurse into redirection target words so nested command/process
            # substitutions are extracted (e.g. `cmd > $(generate_name)`).
            for r in redirs or []:
                if r.word is not None:
                    segments.extend(_extract_segments(r.word))

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
                        segments.extend(_extract_segments(stmt, redirs))

    elif isinstance(node, (ForClause, CStyleLoop)):
        # Extract commands from loop body
        if hasattr(node, "body") and node.body:
            for stmt in node.body:
                segments.extend(_extract_segments(stmt, redirs))

    elif isinstance(node, Subshell):
        # Recurse into subshell body (...)
        if hasattr(node, "stmts") and node.stmts:
            for stmt in node.stmts:
                segments.extend(_extract_segments(stmt, redirs))

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
            segments.extend(_extract_segments(stmt, redirs))
        for stmt in node.then_stmts:
            segments.extend(_extract_segments(stmt, redirs))
        for elif_branch in node.elif_branches:
            segments.extend(_extract_segments(elif_branch, redirs))
        for stmt in node.else_stmts:
            segments.extend(_extract_segments(stmt, redirs))

    elif isinstance(node, ElifBranch):
        for stmt in node.cond:
            segments.extend(_extract_segments(stmt, redirs))
        for stmt in node.body:
            segments.extend(_extract_segments(stmt, redirs))

    elif isinstance(node, WhileClause):
        for stmt in node.cond_stmts:
            segments.extend(_extract_segments(stmt, redirs))
        for stmt in node.body:
            segments.extend(_extract_segments(stmt, redirs))

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

    elif isinstance(node, SglQuoted):
        # Single-quoted literal: no substitutions possible inside. It is a
        # command name only inside test expressions (like a bare literal).
        if _in_test_expr and node.value:
            segments.append({"command": node.value, "arguments": [], "redirections": []})

    elif isinstance(node, DblQuoted):
        # Double-quoted text may embed CmdSubst/ProcSubst/ParamExp parts.
        if _in_test_expr:
            if node.value:
                segments.append({"command": node.value, "arguments": [], "redirections": []})
        else:
            for part in node.parts:
                segments.extend(_extract_segments(part))

    elif isinstance(node, ParamExp):
        # Parameter expansion (${x:-default}, ${arr[i]}, ...) may embed nested
        # command substitutions in its default-value or index expressions.
        if not _in_test_expr:
            if node.index is not None:
                segments.extend(_extract_segments(node.index))
            exp = node.exp
            if isinstance(exp, dict):
                inner_word = exp.get("Word")
                if isinstance(inner_word, dict):
                    for part_raw in inner_word.get("Parts", []):
                        raw_part_node = node_from_json(part_raw)
                        if raw_part_node is not None:
                            segments.extend(_extract_segments(raw_part_node))

    elif isinstance(node, ArithmExp):
        # Arithmetic expansion ($(( ... ))) may embed a command substitution
        # (bash runs $( cmd ) inside $(( ))).
        if node.x is not None:
            segments.extend(_extract_segments(node.x))

    elif isinstance(node, (BinaryArithm, UnaryArithm, ParenArithm, FlagsArithm)):
        # Arithmetic sub-expressions: recurse into operands so command
        # substitutions such as `$(( N + $(cmd) ))` are still extracted.
        if not _in_test_expr:
            for child in (
                getattr(node, "left", None),
                getattr(node, "right", None),
                getattr(node, "x", None),
                getattr(node, "body", None),
            ):
                if child is not None:
                    segments.extend(_extract_segments(child))

    elif isinstance(node, BraceExp):
        # Brace expansion elements may contain substitutions ({a,$(cmd)}).
        if not _in_test_expr:
            for elem in node.elems:
                segments.extend(_extract_segments(elem))

    elif isinstance(node, ExtGlob):
        # Extended glob pattern is a literal pattern — no substitutions inside.
        pass

    elif isinstance(node, (CmdSubst, ProcSubst)):
        # Command/process substitution: recurse into each stmt, passing inherited redirs.
        if hasattr(node, "stmts") and node.stmts:
            inherited = list(redirs or [])
            for stmt in node.stmts:
                segments.extend(_extract_segments(stmt, inherited))

    elif isinstance(node, FuncDecl):
        # Function body / block: recurse into contained stmts, inheriting any
        # redirections that apply to the whole block (e.g. `f() { ...; } > file`).
        segments.extend(_extract_segments(node.body, redirs))

    elif isinstance(node, Block):
        # Curly-brace block: redirections apply to every contained statement.
        for stmt in node.stmts:
            segments.extend(_extract_segments(stmt, redirs))

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
