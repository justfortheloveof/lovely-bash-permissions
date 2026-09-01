"""
AST inspection and traversal utilities.

This module provides functions for querying parsed bash AST trees, including
command extraction, argument collection, variable detection, and redirection
analysis.

Traversal semantics
-------------------
``get_commands`` and ``find_commands`` recurse into CallExpr arguments *and*
into variable-assignment values (via ``iter_children``), so that commands
inside ``$(...)`` or ``VAR=$(cmd)`` are discovered.

``get_arguments`` and ``find_arguments`` recurse into CallExpr arguments
but do **not** descend into assignment values — they collect the literal
argument words of each call, not nested commands.

``has_variable``, ``has_pipe``, ``get_redirections``, and ``get_target_files``
perform a full traversal including CallExpr arguments but do not
special-case assignment values (variables/pipes/redirections inside
assignments are still found via normal child traversal of Word parts).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Iterator
from typing import TypedDict

from .ast import (
    _POSITION_FIELDS,
    ArithmExp,
    BinaryCmd,
    BraceExp,
    CallExpr,
    CmdSubst,
    DblQuoted,
    ExtGlob,
    Lit,
    Node,
    ParamExp,
    ProcSubst,
    Redir,
    SglQuoted,
    Stmt,
    Word,
)


class RedirectionInfo(TypedDict):
    """Typed dictionary for redirection information returned by :func:`get_redirections`."""

    op: str
    target: str


# ---------------------------------------------------------------------------
# Generic child-node iteration
# ---------------------------------------------------------------------------

# Fields that hold child Node values (single or list).  Used by
# ``iter_children`` to avoid a large isinstance dispatch chain.
# Fields named here are introspected via dataclasses.fields().
_SKIP_FIELDS = _POSITION_FIELDS


def iter_children(node: Node, *, include_call_args: bool = False) -> Iterator[Node]:
    """Yield direct child nodes of *node* via dataclass field introspection.

    This is the shared child-traversal used by every inspection function so
    that the CLI and the inspection layer stay consistent.

    When *include_call_args* is False (default), CallExpr ``args`` are
    skipped so that ``get_commands()`` does not descend into argument
    words.  When True, they are included (including the command-name
    position, so ``$(ls | grep x) arg`` is discovered).

    CallExpr ``assigns`` are always yielded so that variable-assignment
    values are traversed by all visitors.
    """
    if isinstance(node, CallExpr):
        if node.assigns:
            yield from node.assigns
        if include_call_args and node.args:
            yield from node.args
        return

    if not dataclasses.is_dataclass(node):
        return

    for f in dataclasses.fields(node):  # type: ignore[arg-type]
        if f.name in _SKIP_FIELDS:
            continue
        val = getattr(node, f.name, None)
        if val is None:
            continue
        if isinstance(val, Node):
            yield val
        elif isinstance(val, list):
            for item in val:
                if isinstance(item, Node):
                    yield item


def _traverse(
    node: Node,
    visitor: Callable[[Node], None],
    recurse_call_expr_args: bool = False,
) -> None:
    """Iterative AST traversal.

    Calls ``visitor(node)`` on every node using an explicit stack,
    avoiding recursion-depth issues on deeply nested bash ASTs.

    When ``recurse_call_expr_args`` is True, child nodes inside CallExpr
    arguments are also visited.
    """
    stack: list[Node] = [node]
    while stack:
        current = stack.pop()
        visitor(current)
        # Reverse so that children are visited in natural order
        children = list(
            iter_children(current, include_call_args=recurse_call_expr_args)
        )
        stack.extend(reversed(children))


# ---------------------------------------------------------------------------
# Early-termination sentinel
# ---------------------------------------------------------------------------


class _Found(Exception):
    """Raised to short-circuit traversal when a match is found."""


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _collect_redirs(node: Node) -> Iterator[Redir]:
    """Yield Redir objects from Stmt or BinaryCmd nodes.

    Other compound nodes (IfClause, ForClause, etc.) wrap their bodies
    in Stmt nodes, so their redirections are discovered when the
    traversal visits those inner Stmt children — no special handling
    is needed here.
    """
    if isinstance(node, (Stmt, BinaryCmd)) and node.redirs:
        yield from node.redirs


def _word_value(word: Word) -> str:
    """Get the best-effort string value of a word (concatenating all parts).

    Handles Lit, SglQuoted, DblQuoted, ParamExp, CmdSubst, ArithmExp,
    ExtGlob, BraceExp, and ProcSubst parts explicitly.  Unknown part
    types are silently skipped.
    """
    parts: list[str] = []
    for part in word.parts:
        if isinstance(part, (Lit, SglQuoted)):
            parts.append(part.value)
        elif isinstance(part, DblQuoted):
            if part.value is not None:
                parts.append(part.value)
        elif isinstance(part, ParamExp):
            parts.append(f"${part.param}")
        elif isinstance(part, CmdSubst):
            parts.append("$(...)")
        elif isinstance(part, ArithmExp):
            parts.append("$(( ... ))")
        elif isinstance(part, ExtGlob):
            pattern = part.pattern.value if part.pattern else ""
            parts.append(f"{part.op}{pattern})")
        elif isinstance(part, BraceExp):
            parts.append("{...}")
        elif isinstance(part, ProcSubst):
            parts.append(f"{part.op}...)")
    return "".join(parts)


def get_commands(tree: Node) -> list[str]:
    """Extract all command names from the AST.

    Recurses into CallExpr arguments and assignment values to discover
    commands inside ``$(...)`` substitutions.
    """
    commands: list[str] = []

    def visitor(node: Node) -> None:
        if isinstance(node, CallExpr) and node.args:
            cmd_name = _word_value(node.args[0])
            if cmd_name:
                commands.append(cmd_name)

    _traverse(tree, visitor, recurse_call_expr_args=True)
    return commands


def find_commands(tree: Node) -> list[CallExpr]:
    """Find all CallExpr nodes (commands) in the AST.

    Recurses into CallExpr arguments and assignment values to discover
    commands inside ``$(...)`` substitutions.
    """
    commands: list[CallExpr] = []

    def visitor(node: Node) -> None:
        if isinstance(node, CallExpr):
            commands.append(node)

    _traverse(tree, visitor, recurse_call_expr_args=True)
    return commands


def has_variable(tree: Node) -> bool:
    """Check if the command contains any variable references."""

    def visitor(node: Node) -> None:
        if isinstance(node, (ParamExp, CmdSubst)):
            raise _Found

    try:
        _traverse(tree, visitor, recurse_call_expr_args=True)
    except _Found:
        return True
    return False


def get_redirections(tree: Node) -> list[RedirectionInfo]:
    """Extract file redirections from the AST.

    Returns a list of :class:`RedirectionInfo` typed dicts with ``op``
    and ``target`` keys.
    """
    redirs: list[RedirectionInfo] = []

    def visitor(node: Node) -> None:
        for r in _collect_redirs(node):
            if r.word:
                redirs.append(RedirectionInfo(op=r.op, target=_word_value(r.word)))

    _traverse(tree, visitor, recurse_call_expr_args=True)
    return redirs


def get_arguments(tree: Node) -> list[list[str]]:
    """Extract command arguments for each call expression.

    Returns the string values of each CallExpr's arguments (excluding the
    command name).  Does **not** descend into assignment values — use
    ``get_commands`` for that.
    """
    args_list: list[list[str]] = []

    def visitor(node: Node) -> None:
        if isinstance(node, CallExpr) and node.args:
            args_list.append([_word_value(arg) for arg in node.args[1:]])

    _traverse(tree, visitor, recurse_call_expr_args=True)
    return args_list


def find_arguments(tree: Node) -> list[list[Word]]:
    """Find all argument Word lists (excluding command names) for each call.

    Returns the raw Word nodes.  Does **not** descend into assignment
    values — use ``find_commands`` for that.
    """
    args_list: list[list[Word]] = []

    def visitor(node: Node) -> None:
        if isinstance(node, CallExpr) and node.args:
            args_list.append(node.args[1:])

    _traverse(tree, visitor, recurse_call_expr_args=True)
    return args_list


def has_pipe(tree: Node) -> bool:
    """Check if the command contains any pipe operators.

    Only returns True for actual pipe operators (``|`` and ``|&``), not for
    ``&&`` or ``||`` which are represented as AndCmd/OrCmd nodes.
    """

    def visitor(node: Node) -> None:
        if isinstance(node, BinaryCmd) and node.op in ("|", "|&"):
            raise _Found

    try:
        _traverse(tree, visitor, recurse_call_expr_args=True)
    except _Found:
        return True
    return False


def get_target_files(tree: Node) -> list[str]:
    """Extract file targets from redirections."""
    targets: list[str] = []

    def visitor(node: Node) -> None:
        for r in _collect_redirs(node):
            if r.word:
                target = _word_value(r.word)
                if target:
                    targets.append(target)

    _traverse(tree, visitor, recurse_call_expr_args=True)
    return targets
