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
but do **not** descend into assignment values - they collect the literal
argument words of each call, not nested commands.

``has_variable``, ``has_pipe``, ``get_redirections``, and ``get_target_files``
perform a full traversal including CallExpr arguments but do not
special-case assignment values (variables/pipes/redirections inside
assignments are still found via normal child traversal of Word parts).
"""

from __future__ import annotations

import dataclasses
import re
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
    """Typed dictionary for redirection information
    returned by :func:`get_redirections`."""

    op: str
    target: str


# ---------------------------------------------------------------------------
# Generic child-node iteration
# ---------------------------------------------------------------------------

# Fields that hold child Node values (single or list).  Used by
# ``iter_children`` to avoid a large isinstance dispatch chain.
# Fields named here are introspected via dataclasses.fields().
_SKIP_FIELDS = _POSITION_FIELDS | {
    # BinaryCmd per-side redirection lists are already covered by the
    # merged ``redirs`` field; traversing them again would duplicate the
    # redirection subtrees (and any substitutions they contain).
    "left_redirs",
    "right_redirs",
}


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

    for f in dataclasses.fields(node):
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
        children = list(iter_children(current, include_call_args=recurse_call_expr_args))
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
    traversal visits those inner Stmt children - no special handling
    is needed here.
    """
    if isinstance(node, (Stmt, BinaryCmd)) and node.redirs:
        yield from node.redirs


def _slice_operand_text(node: Node | None, render_word: Callable[[Word], str]) -> str:
    """Render one operand of a ``${var:offset:length}`` slice.

    Slice operands are typed as bare ``Node`` (a Word in practice, but shfmt
    also allows an arithmetic expression), so anything that is not a Word
    falls back to the arithmetic placeholder instead of crashing the renderer.
    """
    if isinstance(node, Word):
        return render_word(node)
    if isinstance(node, ArithmExp):
        return "$(( ... ))"
    return ""


def _param_exp_text(part: ParamExp, render_word: Callable[[Word], str]) -> str:
    """Render a parameter expansion, keeping every operator and operand.

    Operand words are rendered by *render_word* - the caller passes its own
    word renderer so nesting, quoting and the opaque ``$(...)`` placeholder
    behave identically to top-level parts (a ``CmdSubst`` operand must keep
    rendering as ``$(...)``, because ``evaluate`` keys off that exact string
    to decide a pattern match is unreliable).

    A bare ``$VAR`` / ``${VAR}`` keeps its simple ``$VAR`` spelling; every
    other form keeps its full text so a pattern matching the argument still
    sees the whole expansion (e.g. ``${BAR:-/etc/passwd}`` rather than
    ``$BAR``, which would hide the literal path from the matcher).

    ``${#VAR}`` keeps its ``#`` sigil, which makes it a braced form even
    though it has no operator - the length of ``$x`` is a different
    expression from ``$x`` itself, and rendering it as ``$x`` would hand the
    matcher the wrong one.
    """
    # `${#x}` (string length) and `${#arr[@]}` (element count) are a *different*
    # expression from `${x}`: dropping the `#` hands the matcher a different
    # expansion than the user wrote, so the sigil must survive rendering.
    sigil = "#" if part.length else ""
    op_text = ""
    exp = part.exp
    if exp is not None and exp.op:
        op_text = f"{exp.op}{render_word(exp.word) if exp.word is not None else ''}"
    if part.orig is not None or part.replacement is not None:
        # `${var/pat/rep}` and `${var//pat/rep}` - ``all`` is set for the ``//``
        # (replace-all) spelling.
        op_text += "//" if part.all else "/"
        if part.orig is not None:
            op_text += render_word(part.orig)
        op_text += "/"
        if part.replacement is not None:
            op_text += render_word(part.replacement)
    suffix = ""
    if part.index is not None:
        suffix += f"[{render_word(part.index)}]"
    if part.slice is not None:
        offset = _slice_operand_text(part.slice.offset, render_word)
        length = _slice_operand_text(part.slice.length, render_word)
        # An absent length is the offset-only spelling `${var:offset}`.
        suffix += f":{offset}:{length}" if part.slice.length is not None else f":{offset}"
    if not op_text and not suffix:
        if sigil:
            return "${" + sigil + part.param + "}"
        return f"${part.param}"
    return "${" + sigil + part.param + op_text + suffix + "}"


def _value_part(part: Node) -> str:
    """Render one word part in best-effort *value* form (quotes removed).

    Split out of :func:`_word_value` so that the per-part dispatch can be
    reused when recursing into a ``"..."`` region's parts.

    :class:`DblQuoted` deliberately does *not* short-circuit on its own
    ``value`` field: that field is lossy (``converter._convert_dbl_quoted``
    splices every non-literal part out of it), so ``"pre${x}y"`` would render as
    the string ``"prey"`` - text the user never typed, which a restrictive
    allowed pattern could then be fooled by.  Recursing keeps the expansion
    visible.  ``DblQuoted.parts`` is a strict sub-tree, so the recursion is
    finite.
    """
    if isinstance(part, (Lit, SglQuoted)):
        return part.value
    if isinstance(part, DblQuoted):
        if part.parts:
            return "".join(_value_part(p) for p in part.parts)
        # No parts (shfmt produced none): fall back to the stored value.
        return part.value or ""
    if isinstance(part, ParamExp):
        return _param_exp_text(part, _word_value)
    if isinstance(part, CmdSubst):
        return "$(...)"
    if isinstance(part, ArithmExp):
        return "$(( ... ))"
    if isinstance(part, ExtGlob):
        return f"{part.op}{part.pattern.value if part.pattern else ''})"
    if isinstance(part, BraceExp):
        return "{...}"
    if isinstance(part, ProcSubst):
        return f"{part.op}...)"
    return ""


def _word_value(word: Word) -> str:
    """Get the best-effort string value of a word (concatenating all parts).

    Handles Lit, SglQuoted, DblQuoted, ParamExp, CmdSubst, ArithmExp,
    ExtGlob, BraceExp, and ProcSubst parts explicitly (see
    :func:`_value_part`).  Unknown part types render as the empty string.
    """
    return "".join(_value_part(part) for part in word.parts)


_UNESCAPE_UNQUOTED = re.compile(r"\\([^\n])")
_UNESCAPE_DBLQUOTED = re.compile(r"\\([$`\"\\])")


def _unescape_lit(value: str, *, in_double_quotes: bool) -> str:
    """Bash-style backslash unescaping for a Lit value.

    Unquoted: a backslash drops the next character (bash rule).
    Double-quoted: a backslash is only special before $, `, ", \\ (and
    newline); elsewhere it is literal.
    """
    if in_double_quotes:
        return _UNESCAPE_DBLQUOTED.sub(r"\1", value)
    return _UNESCAPE_UNQUOTED.sub(r"\1", value)


def _raw_part(part: Node) -> str:
    """Render one word part in its *raw* form, preserving quote characters.

    Split out of :func:`_word_raw` so that the per-part dispatch can be
    reused when recursing into a ``"..."`` region's parts.

    A ``DblQuoted`` recurses into its parts for the same fidelity reason as
    :func:`_value_part` (``DblQuoted.value`` is lossy), wrapping the result in
    the quote characters so the region still reads as quoted - a
    quote-preserving pattern like ``^echo\\s+"\\$\\{x\\}"$`` can then match it.

    Unlike :func:`_exec_part` this does *not* switch backslash handling for
    parts inside ``"..."``: the raw form is the text as written, and
    unescaping is the executed form's job.  A nested ``"..."`` region is just
    another ``DblQuoted``, so it renders recursively and terminates.
    """
    if isinstance(part, Lit):
        return part.value
    if isinstance(part, SglQuoted):
        return f"'{part.value}'"
    if isinstance(part, DblQuoted):
        if part.parts:
            return '"' + "".join(_raw_part(p) for p in part.parts) + '"'
        # No parts (shfmt produced none): fall back to the stored value.
        return f'"{part.value}"' if part.value is not None else ""
    if isinstance(part, ParamExp):
        return _param_exp_text(part, _word_raw)
    if isinstance(part, CmdSubst):
        return "$(...)"
    if isinstance(part, ArithmExp):
        return "$(( ... ))"
    if isinstance(part, ExtGlob):
        return f"{part.op}{part.pattern.value if part.pattern else ''})"
    if isinstance(part, BraceExp):
        return "{...}"
    if isinstance(part, ProcSubst):
        return f"{part.op}...)"
    return ""


def _word_raw(word: Word) -> str:
    """Get the raw text of a word, preserving quotes.

    Unlike :func:`_word_value`, this includes quote characters for quoted
    parts, so patterns like ``^echo\\s+'hello'`` can match quoted arguments.
    A ``DblQuoted`` containing an expansion still keeps its quotes *and* the
    expansion text (see :func:`_raw_part`).
    """
    return "".join(_raw_part(part) for part in word.parts)


def _exec_part(part: Node, in_double_quotes: bool) -> str:
    """Render one word part in its executed form.

    *in_double_quotes* is True when the part occurs inside a ``"..."``
    region (including nested double-quoted regions), which changes how
    backslashes in :class:`Lit` values are unescaped.
    """
    if isinstance(part, Lit):
        return _unescape_lit(part.value, in_double_quotes=in_double_quotes)
    if isinstance(part, SglQuoted):
        if in_double_quotes:
            # Quote characters are literal inside "..."; the content follows
            # double-quote-context backslash rules.
            return _unescape_lit(part.value, in_double_quotes=True)
        return part.value
    if isinstance(part, DblQuoted):
        if part.parts:
            return "".join(_exec_part(p, True) for p in part.parts)
        return _unescape_lit(part.value or "", in_double_quotes=True)
    if isinstance(part, ParamExp):
        return _param_exp_text(part, _word_exec)
    if isinstance(part, CmdSubst):
        return "$(...)"
    if isinstance(part, ArithmExp):
        return "$(( ... ))"
    if isinstance(part, ExtGlob):
        return part.pattern.value if part.pattern else ""
    if isinstance(part, BraceExp):
        return "{...}"
    if isinstance(part, ProcSubst):
        return f"{part.op}...)"
    return ""


def _word_exec(word: Word) -> str:
    """Best-effort *executed* form of a word: the string bash would produce
    after quote removal and backslash unescaping (placeholders kept for
    expansions). Used for security pattern matching so quote-split or
    backslash-escaped spellings of a path/flag cannot bypass the raw form.
    """
    return "".join(_exec_part(part, False) for part in word.parts)


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
    command name).  Does **not** descend into assignment values - use
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
    values - use ``find_commands`` for that.
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
