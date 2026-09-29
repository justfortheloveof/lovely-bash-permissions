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
    ArrayElem,
    ArrayExpr,
    Assign,
    BinaryCmd,
    CallExpr,
    CaseBranch,
    CaseClause,
    CmdSubst,
    DeclClause,
    File,
    ForClause,
    Node,
    ProcSubst,
    Redir,
    Stmt,
    Word,
)
from .converter import parse_ast
from .errors import ShfmtError
from .inspect import _word_value, has_pipe, has_variable, iter_children
from .segments import _assign_operand_text

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
        return str(args.string)
    if not sys.stdin.isatty():
        return str(sys.stdin.read())
    _die("no input provided: pass --file, --string, or pipe data via stdin")
    raise AssertionError("unreachable")


def _die(message: str) -> NoReturn:
    print(f"{PROG}: error: {message}", file=sys.stderr)
    raise SystemExit(2)


# ---------------------------------------------------------------------------
# Node-to-string helpers
# ---------------------------------------------------------------------------


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
    """Reconstruct a variable assignment as written.

    Delegates to :func:`lovely_bash_permissions.segments._assign_operand_text`
    so the inspection output and the permission-evaluation path share a single
    renderer.  That renderer covers every shape shfmt produces - scalar,
    subscripted, array, ``+=`` combined with either, and naked declaration
    operands (a bare name or a flag such as ``declare -a``) - where an
    earlier copy here dropped array elements and appended a stray ``=`` to a
    name-less flag.

    Args:
        assign: The ``Assign`` node to render.

    Returns:
        The assignment as written, or ``""`` when there is nothing to render.
        Callers omit the ``assign:`` line for the empty result rather than
        printing it with nothing after the colon.
    """
    return _assign_operand_text(assign)


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
    * ``("words", node, redirs)`` for value words that are not commands:
      a ``ForClause`` loop list (``for i in a b c``) or a ``CaseClause``
      subject (``case $x in``).  These carry no redirection of their own.
    * ``("pattern", node, redirs)`` for a ``CaseBranch``'s match patterns.

    Only ``("cmd", ...)`` items own redirections; the value-word kinds
    never disturb the command/redirection pairing computed by
    :func:`_render_statement`.
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
        # Value words: surfaced so a statement is not opaque when its only
        # content is data (`for i in /etc/passwd; do :; done`, `case $x in`).
        # Yielded here, at the point the node pops, so they render before
        # the commands nested in them.  The generic child descent below
        # still walks those words, which is what renders the commands
        # embedded in substitutions such as `for i in $(cmd)`.
        if isinstance(current, ForClause):
            if current.words:
                yield "words", current, seg
        elif isinstance(current, CaseClause) and current.expr is not None:
            yield "words", current, seg
        elif isinstance(current, CaseBranch) and current.patterns:
            yield "pattern", current, seg
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


def _render_statement(command: Node, redirs: list[Redir], report: _Report, indent: int = 1) -> bool:
    """Render a statement group: its commands plus any nested statements.

    *redirs* apply to the group's trailing command.  A ``BinaryCmd``'s
    redirections are attached to the operand (``X``/``Y``) that owns them,
    so each redirection renders immediately after its own command instead of
    being collected at the end of the pipeline.  Nested ``Stmt`` nodes
    (inside functions, loops, cases, subshells, ...) carry their own
    redirections and are rendered as deeper groups.  Value words that are
    not commands (a ``for`` loop list, a ``case`` subject and its patterns)
    are rendered in place, in source order.
    """
    items = list(_iter_items(command))
    if not items:
        return False

    # Only "cmd" items own the group's trailing redirections, so the
    # value-word items never shift where those redirections land.
    last_cmd = max((i for i, (kind, _, _) in enumerate(items) if kind == "cmd"), default=-1)

    for i, (kind, node, seg_redirs) in enumerate(items):
        if kind == "cmd":
            _render_command_or_decl(node, indent, report)
            if seg_redirs:
                _render_redirs(seg_redirs, indent, report)
            if i == last_cmd and redirs:
                _render_redirs(redirs, indent, report)
            continue
        if kind == "words":
            _render_value_words(node, indent, report)
            continue
        if kind == "pattern":
            _render_patterns(node, indent, report)
            continue

        # Nested statement: when this group has no direct commands of its
        # own, its trailing redirections apply to the final nested group.
        if isinstance(node, Stmt):
            nested_redirs = _redirs_of(node)
            inherited = seg_redirs
            if last_cmd == -1 and i == len(items) - 1:
                inherited = inherited + redirs
            nested_redirs = nested_redirs + inherited
            if node.cmd is not None:
                _render_statement(node.cmd, nested_redirs, report, indent)
    return True


def _render_value_words(node: Node, indent: int, report: _Report) -> None:
    """Render the value words of a ``for`` loop or a ``case`` subject.

    These words are plain data, not commands, so they get their own lines
    (``words: a, b, c`` / ``case: $x``).  Commands nested inside them (e.g.
    ``for i in $(cmd)``) are rendered separately by the traversal that
    descends into the same words - do not render them again here.
    """
    if isinstance(node, ForClause):
        rendered = [_word_value(w) for w in node.words]
        rendered = [w for w in rendered if w]
        if rendered:
            report.add(indent, f"words: {', '.join(rendered)}")
    elif isinstance(node, CaseClause) and node.expr is not None:
        subject = _word_value(node.expr)
        if subject:
            report.add(indent, f"case: {subject}")


def _render_patterns(node: Node, indent: int, report: _Report) -> None:
    """Render a ``case`` branch's match patterns (one line per pattern)."""
    if not isinstance(node, CaseBranch):
        return
    for pattern in node.patterns:
        text = _word_value(pattern)
        if text:
            report.add(indent, f"pattern: {text}")


def _render_command_or_decl(node: Node, indent: int, report: _Report) -> None:
    """Render a single command or declaration node."""
    if isinstance(node, DeclClause):
        _render_declared(node, indent, report)
    elif isinstance(node, CallExpr):
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
        text = _assign_text(assign)
        # An assignment with nothing renderable (see ``_assign_text``) would
        # otherwise leave a dangling ``assign:`` line.
        if text:
            report.add(indent, f"assign: {text}")
        _render_assign_subs(assign, indent, report)


def _render_declared(decl: DeclClause, indent: int, report: _Report) -> None:
    """Render a declaration clause (e.g. ``export FOO=$(...)``).

    Each operand is a separate ``assign:`` line prefixed with the declaration
    keyword, so ``declare -a A=(a b)`` reads as ``declare -a`` plus
    ``declare A=(a b)`` - the operands ``segments`` reports as the
    declaration's arguments.

    This one-line form is deliberately *not* 1:1 with the segment list. The
    permission path splits a declaration into a variable-assignment segment for
    the operands plus a separate segment for the variant keyword
    (``export FOO=bar`` -> ``[('', ['FOO=bar']), ('export', [])]``), because
    ``variable_assignment`` only applies to segments whose ``command`` is
    ``""``; leaving the operands as the variant segment's arguments meant
    ``export FOO=bar`` was approved even under ``"variable_assignment": "deny"``.
    The split exists so a policy key can reach the operands, not to shape the
    display. Emitting both would print ``assign: export FOO=bar`` *and*
    ``assign: export``, duplicating the variant keyword and losing the
    association between the keyword and its operand, so do not "fix" the
    rendering to match the segment list. ``TestAgreesWithSegments`` in
    ``tests/test_cli_words_output.py`` cross-checks this
    output against the ``command == ""`` segment, which is why it already
    tolerates the difference.
    """
    for assign in decl.assigns or []:
        text = _assign_text(assign)
        if text:
            report.add(indent, f"assign: {decl.variant} {text}")
        _render_assign_subs(assign, indent, report)


def _render_assign_subs(assign: Assign, indent: int, report: _Report) -> None:
    """Render commands nested in substitutions inside an assignment.

    Covers the subscript, the plain value, and every array element's value and
    subscript, so ``A=($(cmd))`` surfaces ``cmd`` just as ``A=$(cmd)`` does.
    The node owning the assignment is a renderable leaf, so the generic child
    descent does not visit these words again and nothing is rendered twice.
    """
    words: list[Word] = []
    if isinstance(assign.index, Word):
        words.append(assign.index)
    if assign.value is not None:
        words.append(assign.value)
    if isinstance(assign.array, ArrayExpr):
        for elem in assign.array.elems:
            if isinstance(elem, ArrayElem):
                if isinstance(elem.index, Word):
                    words.append(elem.index)
                if elem.value is not None:
                    words.append(elem.value)
    _render_word_subs(words, indent, report)


def _render_redirs(redirs: list[Redir], indent: int, report: _Report) -> None:
    """Render a command's trailing redirections.

    Commands nested inside a redirection target (e.g. ``> $(ls)``) are also
    rendered, as plain commands at the same indentation.
    """
    for redir in redirs:
        if redir.word:
            report.add(indent, f"redirection: {_redir_text(redir)}")
            for subst in _iter_substs(redir.word):
                if isinstance(subst, (CmdSubst, ProcSubst)):
                    for stmt in subst.stmts:
                        if stmt.cmd is not None:
                            _render_statement(stmt.cmd, _redirs_of(stmt), report, indent + 1)


def _render_word_subs(words: list[Word], indent: int, report: _Report) -> bool:
    """Render commands nested inside substitutions found in *words*."""
    rendered = False
    for word in words:
        for subst in _iter_substs(word):
            if isinstance(subst, (CmdSubst, ProcSubst)):
                rendered = True
                for stmt in subst.stmts:
                    if stmt.cmd is not None:
                        _render_statement(stmt.cmd, _redirs_of(stmt), report, indent + 1)
    return rendered


def _stmt_snippet(stmt: Stmt, source: str) -> str:
    """Extract the raw source text for a statement.

    shfmt reports positions as **byte** offsets into the UTF-8 source, while
    *source* is a ``str`` indexed by code point.  Slicing the ``str`` with a
    byte offset is wrong as soon as the command contains a non-ASCII
    character anywhere before the statement, so the slice is taken on the
    encoded form and decoded afterwards.  The bounds check has to compare
    against the encoded length for the same reason - a byte offset can exceed
    ``len(source)`` on multibyte input without being out of range.
    """
    if stmt.pos is None or stmt.end is None:
        return ""
    start = stmt.pos.offset
    end = stmt.end.offset
    encoded = source.encode("utf-8", errors="replace")
    if start < 0 or end < 0 or start > len(encoded) or end > len(encoded):
        return ""
    return encoded[start:end].decode("utf-8", errors="replace").strip()


def _redirs_of(stmt: Stmt) -> list[Redir]:
    """Return the statement's redirections, when present."""
    return stmt.redirs or []


def _render(tree: File, source: str) -> None:
    report = _Report()
    rendered_any = False

    for stmt_no, stmt in enumerate(tree.stmts, start=1):
        if stmt.cmd is None:
            continue
        statement_report = _Report()
        if _render_statement(stmt.cmd, _redirs_of(stmt), statement_report):
            snippet = _stmt_snippet(stmt, source)
            report.add(0, f"statement {stmt_no} `{snippet}`:")
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
    except ShfmtError as exc:
        print(f"{PROG}: error: failed to parse input: {exc}", file=sys.stderr)
        return 3

    _render(tree, source)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
