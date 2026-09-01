"""Command-line interface for pretty-printing bash inspection results.

The CLI accepts bash code from a ``--file``, an inline ``--string``, or
standard input, parses it into an AST, then prints a per-statement summary
grouping each command with its arguments, assignments, and redirections.
It also reports the boolean checks (variables, pipes).

Exit codes:
    0  success (parsing and inspection succeeded)
    2  usage error (bad or missing arguments)
    3  parse error (shfmt could not parse the input)
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterator
from typing import NoReturn

from .ast import (
    ArithmExp,
    Assign,
    BinaryCmd,
    BraceExp,
    CallExpr,
    CmdSubst,
    DblQuoted,
    DeclClause,
    ExtGlob,
    File,
    Lit,
    Node,
    ParamExp,
    ProcSubst,
    Redir,
    SglQuoted,
    Stmt,
    Word,
)
from .converter import parse_ast
from .inspect import has_pipe, has_variable, iter_children
from .parser import ParseError

PROG = "lovely-bash-inspection"
INDENT = "  "

# Nodes rendered as a leaf (never descended into).
_RENDERABLE = (CallExpr, DeclClause)


# ---------------------------------------------------------------------------
# Input handling
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Parse bash code and print a per-command inspection summary.",
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--file",
        metavar="PATH",
        help="Path to a file containing bash code to inspect.",
    )
    source.add_argument(
        "--string",
        metavar="BASH",
        help="Inline bash code string to inspect.",
    )
    parser.add_argument(
        "--dialect",
        default="bash",
        help="Shell dialect for parsing (default: bash).",
    )
    return parser


def _read_input(args: argparse.Namespace) -> str:
    """Read bash source from the chosen input mode."""
    if args.file is not None:
        try:
            with open(args.file, encoding="utf-8") as fh:
                return fh.read()
        except OSError as exc:
            _die(f"cannot read {args.file!r}: {exc.strerror or exc}")
    if args.string is not None:
        return args.string
    if not sys.stdin.isatty():
        return sys.stdin.read()
    _die("no input provided: pass --file, --string, or pipe data via stdin")
    raise AssertionError("unreachable")


def _die(message: str) -> NoReturn:
    print(f"{PROG}: error: {message}", file=sys.stderr)
    raise SystemExit(2)


# ---------------------------------------------------------------------------
# Node-to-string helpers
# ---------------------------------------------------------------------------


def _word_value(word: Word) -> str:
    """Reconstruct a best-effort string value for a Word node."""
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


def _redir_text(redir: Redir) -> str:
    """Format a redirection as ``OP TARGET``.

    File-target redirections (``> file``, ``2>> file``) get a separating
    space; fd-duplication redirections (``>&1``, ``2>&1``) do not.
    """
    target = _word_value(redir.word) if redir.word else ""
    op = f"{redir.n}{redir.op}" if redir.n is not None else redir.op
    if redir.op in ("<&", ">&"):
        return f"{op}{target}"
    return f"{op} {target}" if target else op


def _assign_text(assign: Assign) -> str:
    """Reconstruct a best-effort string for an assignment's left-hand side."""
    name = (
        assign.name.value
        if isinstance(assign.name, Lit)
        else (assign.name.value if assign.name else "?")
    )
    if assign.index is not None and isinstance(assign.index, Word):
        name += f"[{_word_value(assign.index)}]"
    op = "+=" if assign.append else "="
    if assign.value is not None:
        return f"{name}{op}{_word_value(assign.value)}"
    if assign.array is not None:
        return f"{name}{op}(...)"
    return name + op


# ---------------------------------------------------------------------------
# Traversal
# ---------------------------------------------------------------------------
# Child traversal is shared with the inspection layer via
# ``inspect.iter_children`` so the CLI and the inspection API stay
# consistent.  The CLI walks every child (including CallExpr arguments)
# to discover nested commands and statements.


def _iter_items(node: Node) -> Iterator[tuple[str, Node, list[Redir]]]:
    """Yield renderable commands and nested statements in source order.

    Each item is a tuple ``(kind, node, redirs)``:

    * ``("cmd", node, redirs)`` for a command/declaration, where *redirs*
      are the redirections attached to that specific command (via its
      pipeline/``&&``/``||`` segment).
    * ``("stmt", node, redirs)`` for a nested ``Stmt``, where *redirs* are
      the incoming segment redirections to thread into that deeper group.
    """
    # Stack entries carry the redirections that trail the subtree rooted at
    # the node.  For a BinaryCmd these come from the per-operand redirection
    # fields, so each redirection renders adjacent to the command that owns
    # it.  For compound nodes the segment redirections are passed to the
    # final child so they reach the last command of the group.
    stack: list[tuple[Node, list[Redir]]] = [(node, [])]
    while stack:
        current, seg = stack.pop()
        if isinstance(current, _RENDERABLE):
            yield "cmd", current, seg
            continue
        if isinstance(current, Stmt):
            yield "stmt", current, seg
            continue
        if isinstance(current, BinaryCmd):
            # Push the right operand first so the left pops (and renders)
            # first, preserving source order.
            if current.right is not None:
                stack.append((current.right, list(current.right_redirs)))
            if current.left is not None:
                stack.append((current.left, list(current.left_redirs)))
            continue
        # Compound node (subshell, block, control flow, ...): descend into
        # its children, threading the segment redirections to the last one.
        children = list(iter_children(current, include_call_args=True))
        pushed: list[tuple[Node, list[Redir]]] = []
        for i, child in enumerate(children):
            child_seg = seg if i == len(children) - 1 else []
            pushed.append((child, child_seg))
        stack.extend(reversed(pushed))


def _iter_substs(word: Word) -> Iterator[Node]:
    """Yield CmdSubst/ProcSubst nodes found in a Word's parts."""
    for part in word.parts:
        if isinstance(part, (CmdSubst, ProcSubst)):
            yield part


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


class _Report:
    """Accumulates indented lines for one bash statement."""

    def __init__(self) -> None:
        self._lines: list[str] = []

    def __bool__(self) -> bool:
        return bool(self._lines)

    def add(self, indent: int, text: str) -> None:
        self._lines.append(INDENT * indent + text)

    def lines(self) -> list[str]:
        return list(self._lines)


def _render_statement(
    command: Node, redirs: list[Redir], report: _Report, indent: int = 1
) -> bool:
    """Render a statement group: its commands plus any nested statements.

    *redirs* apply to the group's trailing command.  A ``BinaryCmd``'s
    redirections are attached to the operand (``X``/``Y``) that owns them,
    so each redirection renders immediately after its own command instead of
    being collected at the end of the pipeline.  Nested ``Stmt`` nodes
    (inside functions, loops, cases, subshells, ...) carry their own
    redirections and are rendered as deeper groups.
    """
    items = list(_iter_items(command))
    if not items:
        return False

    last_cmd = max(
        (i for i, (kind, _, _) in enumerate(items) if kind == "cmd"), default=-1
    )

    for i, (kind, node, seg_redirs) in enumerate(items):
        if kind == "cmd":
            _render_command_or_decl(node, indent, report)
            if seg_redirs:
                _render_redirs(seg_redirs, indent, report)
            if i == last_cmd and redirs:
                _render_redirs(redirs, indent, report)
            continue

        # Nested statement: when this group has no direct commands of its
        # own, its trailing redirections apply to the final nested group.
        nested_redirs = _redirs_of(node)
        inherited = seg_redirs
        if last_cmd == -1 and i == len(items) - 1:
            inherited = inherited + redirs
        nested_redirs = nested_redirs + inherited
        if node.cmd is not None:
            _render_statement(node.cmd, nested_redirs, report, indent)
    return True


def _render_command_or_decl(node: Node, indent: int, report: _Report) -> None:
    """Render a single command or declaration node."""
    if isinstance(node, DeclClause):
        _render_declared(node, indent, report)
    else:
        _render_command(node, indent, report)


def _render_command(call: CallExpr, indent: int, report: _Report) -> None:
    """Render a single command, its assigns, and nested substitutions."""
    if call.args:
        name = _word_value(call.args[0])
        args = [_word_value(a) for a in call.args[1:]]
        report.add(indent, f"cmd: {name}")
        if args:
            report.add(indent, f"args: {', '.join(args)}")
        _render_word_subs(call.args, indent, report)
    for assign in call.assigns or []:
        report.add(indent, f"assign: {_assign_text(assign)}")
        if assign.value:
            _render_word_subs([assign.value], indent, report)


def _render_declared(decl: DeclClause, indent: int, report: _Report) -> None:
    """Render a declaration clause (e.g. ``export FOO=$(...)``)."""
    for assign in decl.assigns or []:
        report.add(indent, f"assign: {decl.variant} {_assign_text(assign)}")
        if assign.value:
            _render_word_subs([assign.value], indent, report)


def _render_redirs(redirs: list[Redir], indent: int, report: _Report) -> None:
    """Render a command's trailing redirections.

    Commands nested inside a redirection target (e.g. ``> $(ls)``) are also
    rendered, as plain commands at the same indentation.
    """
    for redir in redirs:
        if redir.word:
            report.add(indent, f"redirection: {_redir_text(redir)}")
            for subst in _iter_substs(redir.word):
                for stmt in subst.stmts:
                    if stmt.cmd is not None:
                        _render_statement(
                            stmt.cmd, _redirs_of(stmt), report, indent + 1
                        )


def _render_word_subs(words: list[Word], indent: int, report: _Report) -> bool:
    """Render commands nested inside substitutions found in *words*."""
    rendered = False
    for word in words:
        for subst in _iter_substs(word):
            rendered = True
            for stmt in subst.stmts:
                if stmt.cmd is not None:
                    _render_statement(stmt.cmd, _redirs_of(stmt), report, indent + 1)
    return rendered


def _redirs_of(stmt: Stmt) -> list[Redir]:
    """Return the statement's redirections, when present."""
    return stmt.redirs or []


def _render(tree: File) -> None:
    report = _Report()
    rendered_any = False

    for stmt_no, stmt in enumerate(tree.stmts, start=1):
        if stmt.cmd is None:
            continue
        statement_report = _Report()
        if _render_statement(stmt.cmd, _redirs_of(stmt), statement_report):
            report.add(0, f"statement {stmt_no}:")
            for line in statement_report.lines():
                report.add(0, line)
            report.add(0, "")
            rendered_any = True

    if not rendered_any:
        print("(no commands found)")
        print()
    else:
        for line in report.lines():
            print(line)

    print(f"Variables: {'yes' if has_variable(tree) else 'no'}")
    print(f"Pipes:     {'yes' if has_pipe(tree) else 'no'}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    source = _read_input(args)
    if not source.strip():
        _die("input is empty")

    try:
        tree = parse_ast(source)
    except (ParseError, FileNotFoundError) as exc:
        print(f"{PROG}: error: failed to parse input: {exc}", file=sys.stderr)
        return 3

    _render(tree)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
