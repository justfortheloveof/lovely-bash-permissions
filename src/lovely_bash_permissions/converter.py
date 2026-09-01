"""
JSON-to-AST conversion for shfmt output.

This module converts shfmt's JSON AST representation into typed Python
dataclass nodes defined in ``ast.py``. It uses a dispatch table
(``_CONVERTERS``) to map shfmt type strings to converter functions.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable
from typing import Any

from .ast import (
    AndCmd,
    ArithmCmd,
    ArithmExp,
    ArrayElem,
    ArrayExpr,
    Assign,
    BinaryArithm,
    BinaryCmd,
    BinaryTest,
    Block,
    BraceExp,
    CallExpr,
    CaseBranch,
    CaseClause,
    CaseItem,
    CmdSubst,
    Comment,
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
    Node,
    OrCmd,
    ParamExp,
    ParenArithm,
    ParenTest,
    Position,
    ProcSubst,
    Redir,
    SglQuoted,
    Stmt,
    Subshell,
    TestClause,
    TestDecl,
    TimeClause,
    UnaryArithm,
    UnaryTest,
    WhileClause,
    Word,
    WordIter,
)

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Type mapping from shfmt's JSON to our dataclasses
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Position helpers
# ---------------------------------------------------------------------------


def _parse_position(data: dict | None) -> Position | None:
    """Parse source position data from shfmt JSON.

    Returns None when *data* is None (key absent in JSON).
    """
    if data is None:
        return None
    return Position(
        offset=data.get("Offset", 0),
        line=data.get("Line", 0),
        col=data.get("Col", 0),
    )


def _parse_pos_end(data: dict) -> tuple[Position | None, Position | None]:
    """Extract pos/end from a JSON dict."""
    return _parse_position(data.get("Pos")), _parse_position(data.get("End"))


# ---------------------------------------------------------------------------
# Shared leaf converters
# ---------------------------------------------------------------------------


def _convert_lit(data: dict) -> Lit:
    """Convert shfmt JSON to a Lit node."""
    pos, end = _parse_pos_end(data)
    return Lit(
        pos=pos,
        end=end,
        value=data.get("Value", ""),
        value_pos=_parse_position(data.get("ValuePos")),
        value_end=_parse_position(data.get("ValueEnd")),
    )


def _convert_sgl_quoted(data: dict) -> SglQuoted:
    pos, end = _parse_pos_end(data)
    return SglQuoted(pos=pos, end=end, value=data.get("Value", ""))


def _convert_param_exp(data: dict) -> ParamExp:
    """Convert shfmt JSON to a ParamExp node."""
    pos, end = _parse_pos_end(data)
    param_data = data.get("Param", {})
    param_value = param_data.get("Value", "") if isinstance(param_data, dict) else ""
    index_data = data.get("Index")
    index_node = _convert_word(index_data) if isinstance(index_data, dict) else None
    exp_data = data.get("Exp")
    exp_value = exp_data if isinstance(exp_data, dict) else None
    return ParamExp(
        pos=pos,
        end=end,
        param=param_value,
        short=data.get("Short", False),
        exp=exp_value,
        index=index_node,
        length=data.get("Length", False),
        dollar_pos=_parse_position(data.get("Dollar")),
    )


def _convert_cmd_subst(data: dict) -> CmdSubst:
    pos, end = _parse_pos_end(data)
    return CmdSubst(
        pos=pos,
        end=end,
        stmts=[_convert_stmt(s) for s in data.get("Stmts", [])],
        backquotes=data.get("Backquotes", False),
    )


def _convert_proc_subst(data: dict) -> ProcSubst:
    pos, end = _parse_pos_end(data)
    return ProcSubst(
        pos=pos,
        end=end,
        op=data.get("Op", ""),
        op_pos=_parse_position(data.get("OpPos")),
        rparen=_parse_position(data.get("Rparen")),
        stmts=[_convert_stmt(s) for s in data.get("Stmts", [])],
    )


def _convert_arithm_exp(data: dict) -> ArithmExp:
    pos, end = _parse_pos_end(data)
    return ArithmExp(
        pos=pos,
        end=end,
        x=node_from_json(data.get("X")),
    )


def _convert_ext_glob(data: dict) -> ExtGlob:
    """Convert shfmt JSON to an ExtGlob node."""
    pos, end = _parse_pos_end(data)
    pattern_data = data.get("Pattern", {})
    return ExtGlob(
        pos=pos,
        end=end,
        op=data.get("Op", ""),
        op_pos=_parse_position(data.get("OpPos")),
        pattern=_convert_lit(pattern_data) if pattern_data else None,
    )


def _convert_dbl_quoted(data: dict) -> DblQuoted:
    parts = [_convert_part(p) for p in data.get("Parts", [])]
    value = None
    if parts:
        vals: list[str] = []
        for p in parts:
            if isinstance(p, (Lit, SglQuoted)):  # noqa: SIM114
                vals.append(p.value)
            elif isinstance(p, DblQuoted) and p.value is not None:
                vals.append(p.value)
            else:
                vals.append("")
        value = "".join(vals)
    pos, end = _parse_pos_end(data)
    return DblQuoted(pos=pos, end=end, parts=parts, value=value)


# ---------------------------------------------------------------------------
# Statement / Word / Redir / Assign helpers
# ---------------------------------------------------------------------------


def _parse_stmt_list(raw: list | None) -> list[Stmt]:
    """Convert a list of raw JSON statement dicts to typed Stmt objects.

    Entries without a ``Cmd`` key (e.g., comment-only lines) are converted
    to Stmt nodes with ``cmd=None``.  This preserves the statement count
    but lets callers skip empty-cmd statements if they wish.
    """
    if not raw:
        return []
    result: list[Stmt] = []
    for item in raw:
        if isinstance(item, dict):
            result.append(_convert_stmt(item))
        else:
            _log.warning("Dropped non-dict entry in stmt list: %r", item)
    return result


def _convert_assign(data: dict) -> Assign:
    """Convert shfmt JSON assignment data to a typed Assign object."""
    name_data = data.get("Name", {})
    name_node = _convert_lit(name_data) if isinstance(name_data, dict) else None

    index_data = data.get("Index")
    index_node = _convert_word(index_data) if isinstance(index_data, dict) else None

    value_data = data.get("Value")
    value_node = _convert_word(value_data) if isinstance(value_data, dict) else None

    array_data = data.get("Array")
    array_node = None
    if isinstance(array_data, dict):
        pos, end = _parse_pos_end(array_data)
        array_node = ArrayExpr(
            pos=pos,
            end=end,
            elems=[_convert_array_elem(e) for e in array_data.get("Elems", [])],
        )

    pos, end = _parse_pos_end(data)
    return Assign(
        pos=pos,
        end=end,
        name=name_node,
        index=index_node,
        value=value_node,
        array=array_node,
        append=data.get("Append", False),
        naked=data.get("Naked", False),
    )


def _convert_array_elem(data: dict) -> ArrayElem:
    """Convert shfmt JSON array element data to a typed ArrayElem object."""
    index_data = data.get("Index")
    index_node = _convert_word(index_data) if isinstance(index_data, dict) else None

    value_data = data.get("Value")
    value_node = _convert_word(value_data) if isinstance(value_data, dict) else None

    pos, end = _parse_pos_end(data)
    return ArrayElem(
        pos=pos,
        end=end,
        index=index_node,
        value=value_node,
    )


def _convert_redir(data: dict) -> Redir:
    """Convert shfmt JSON redirection data to a typed Redir object."""
    pos, end = _parse_pos_end(data)
    n_raw = data.get("N")
    n_val: int | None = None
    if isinstance(n_raw, int):
        n_val = n_raw
    elif isinstance(n_raw, dict):
        # shfmt encodes N as a Lit-like dict with a "Value" key
        with contextlib.suppress(ValueError, TypeError):
            n_val = int(n_raw.get("Value", ""))
    return Redir(
        op=data.get("Op", ""),
        n=n_val,
        word=_convert_word(data.get("Word")),
        pos=pos,
        end=end,
        op_pos=_parse_position(data.get("OpPos")),
    )


def _convert_stmt(data: dict) -> Stmt:
    """Convert shfmt JSON statement data to a typed Stmt object.

    When the statement has no ``Cmd`` key (e.g., comment-only lines),
    ``cmd`` is set to ``None``.
    """
    cmd_json = data.get("Cmd")
    cmd = node_from_json(cmd_json) if cmd_json is not None else None
    redirs: list[Redir] = []
    if "Redirs" in data:
        redirs = [_convert_redir(r) for r in data.get("Redirs", [])]
    pos, end = _parse_pos_end(data)
    return Stmt(
        cmd=cmd,
        position=_parse_position(data.get("Position")),
        pos=pos,
        end=end,
        redirs=redirs,
    )


def _convert_word(data: dict | None) -> Word | None:
    """Convert shfmt JSON word data to a typed Word object.

    Returns None when *data* is None (key absent in JSON).
    """
    if data is None:
        return None
    parts = [_convert_part(p) for p in data.get("Parts", [])]
    pos, end = _parse_pos_end(data)
    return Word(
        pos=pos,
        end=end,
        parts=parts,
    )


def _convert_part(data: dict) -> Node:
    """Convert shfmt JSON part data to a typed Node object.

    Delegates to ``_CONVERTERS`` for all known types. Falls back to a
    generic Node for unknown types.
    """
    part_type = data.get("Type", "")
    converter = _CONVERTERS.get(part_type)
    if converter is not None:
        result = converter(data)
        if result is not None:
            return result

    # Unknown part type — wrap in a generic Node
    pos, end = _parse_pos_end(data)
    return Node(type=part_type, pos=pos, end=end)


# ---------------------------------------------------------------------------
# IfClause conversion (handles nested elif/else structures)
# ---------------------------------------------------------------------------


def _convert_if_clause(data: dict) -> IfClause:
    """Parse an IfClause from shfmt JSON, handling nested elif/else structures."""
    cond_stmts = _parse_stmt_list(data.get("Cond", []))
    then_stmts = _parse_stmt_list(data.get("Then", []))

    elif_branches: list[ElifBranch] = []
    else_stmts: list[Stmt] = []

    for b in data.get("Elif", []):
        if isinstance(b, dict):
            elif_branches.append(
                ElifBranch(
                    cond=_parse_stmt_list(b.get("Cond", [])),
                    body=_parse_stmt_list(b.get("Then", b.get("Body", []))),
                )
            )

    else_raw = data.get("Else")
    if isinstance(else_raw, dict):
        if "Cond" in else_raw:
            _collect_elif_chain(else_raw, elif_branches, else_stmts)
        else:
            else_stmts = _parse_stmt_list(else_raw.get("Then", []))
    elif isinstance(else_raw, list):
        else_stmts = _parse_stmt_list(else_raw)

    pos, end = _parse_pos_end(data)
    return IfClause(
        pos=pos,
        end=end,
        cond_stmts=cond_stmts,
        then_stmts=then_stmts,
        elif_branches=elif_branches,
        else_stmts=else_stmts,
    )


def _collect_elif_chain(
    data: dict,
    elif_branches: list[ElifBranch],
    else_stmts: list[Stmt],
) -> None:
    """Recursively collect elif branches from nested shfmt Else structures."""
    elif_branches.append(
        ElifBranch(
            cond=_parse_stmt_list(data.get("Cond", [])),
            body=_parse_stmt_list(data.get("Then", [])),
        )
    )

    nested_else = data.get("Else")
    if isinstance(nested_else, dict):
        if "Cond" in nested_else:
            _collect_elif_chain(nested_else, elif_branches, else_stmts)
        else:
            else_stmts.extend(_parse_stmt_list(nested_else.get("Then", [])))
    elif isinstance(nested_else, list):
        else_stmts.extend(_parse_stmt_list(nested_else))


# ---------------------------------------------------------------------------
# Node-level converters
# ---------------------------------------------------------------------------


def _convert_file(data: dict) -> File:
    pos, end = _parse_pos_end(data)
    return File(
        pos=pos,
        end=end,
        stmts=[_convert_stmt(s) for s in data.get("Stmts", [])],
    )


def _convert_call_expr(data: dict) -> CallExpr:
    assigns_raw = data.get("Assigns")
    assigns = [_convert_assign(a) for a in assigns_raw] if assigns_raw else None
    pos, end = _parse_pos_end(data)
    return CallExpr(
        pos=pos,
        end=end,
        args=[w for a in data.get("Args", []) if (w := _convert_word(a)) is not None],
        assigns=assigns,
    )


def _convert_binary_cmd(data: dict) -> BinaryCmd:
    """Convert shfmt BinaryCmd JSON to a typed BinaryCmd node.

    shfmt attaches redirections to the ``Stmt``-shaped ``X``/``Y``
    operands.  Those operands are unwrapped to their ``Cmd`` so that
    ``left``/``right`` point directly at the command; the operands'
    redirections are split here onto :class:`BinaryCmd` per-side fields
    (``left_redirs``/``right_redirs``) so each redirection can be
    attributed to its own operand.  ``redirs`` holds the merged list
    (left then right) for backwards compatibility.
    """
    left_redirs: list[Redir] = []
    right_redirs: list[Redir] = []
    for side, target in (("X", left_redirs), ("Y", right_redirs)):
        operand = data.get(side)
        if isinstance(operand, dict):
            target.extend(_convert_redir(r) for r in operand.get("Redirs", []))
    redirs = left_redirs + right_redirs
    pos, end = _parse_pos_end(data)
    return BinaryCmd(
        pos=pos,
        end=end,
        op=data.get("Op", ""),
        left=node_from_json(data.get("X")),
        right=node_from_json(data.get("Y")),
        left_redirs=left_redirs,
        right_redirs=right_redirs,
        redirs=redirs,
    )


def _convert_decl_clause(data: dict) -> DeclClause:
    """Convert shfmt DeclClause JSON to a typed DeclClause node.

    shfmt represents declaration arguments (e.g., ``export FOO=bar``) as
    Assign-like dicts in the ``Args`` array.  We store these in two fields:

    * ``assigns`` — the full Assign objects with name/value/etc.
    * ``args`` — the *value* portion as Word nodes, so callers that only
      need the word-level view don't have to dig into Assign internals.
    """
    variant = data.get("Variant", {})
    variant_value = variant.get("Value", "") if isinstance(variant, dict) else ""

    assigns: list[Assign] = []
    args: list[Word] = []
    for arg in data.get("Args", []):
        if isinstance(arg, dict):
            assigns.append(_convert_assign(arg))
            # Also extract the value as a Word for backwards compat
            val = arg.get("Value", {})
            if isinstance(val, dict) and val.get("Parts"):
                word = _convert_word(val)
                if word is not None:
                    args.append(word)

    pos, end = _parse_pos_end(data)
    return DeclClause(
        pos=pos,
        end=end,
        variant=variant_value,
        args=args,
        assigns=assigns,
    )


def _convert_subshell(data: dict) -> Subshell:
    pos, end = _parse_pos_end(data)
    return Subshell(
        pos=pos,
        end=end,
        stmts=[_convert_stmt(s) for s in data.get("Stmts", [])],
    )


def _convert_for_clause(data: dict) -> ForClause:
    loop = data.get("Loop", {})
    var_name: str | None = None
    items: list[Word] = []

    if isinstance(loop, dict):
        name_info = loop.get("Name", {})
        if isinstance(name_info, dict):
            var_name = name_info.get("Value")
        for w in loop.get("Items", []):
            if isinstance(w, dict):
                word = _convert_word(w)
                if word is not None:
                    items.append(word)

    body = _parse_stmt_list(data.get("Do", []))

    pos, end = _parse_pos_end(data)
    return ForClause(
        pos=pos,
        end=end,
        var=var_name,
        words=items,
        body=body,
    )


def _convert_while_clause(data: dict) -> WhileClause:
    pos, end = _parse_pos_end(data)
    return WhileClause(
        pos=pos,
        end=end,
        cond_stmts=[_convert_stmt(s) for s in data.get("Cond", [])],
        body=[_convert_stmt(s) for s in data.get("Do", [])],
    )


def _convert_and_cmd(data: dict) -> AndCmd:
    pos, end = _parse_pos_end(data)
    return AndCmd(
        pos=pos,
        end=end,
        left=node_from_json(data.get("X")),
        right=node_from_json(data.get("Y")),
    )


def _convert_or_cmd(data: dict) -> OrCmd:
    pos, end = _parse_pos_end(data)
    return OrCmd(
        pos=pos,
        end=end,
        left=node_from_json(data.get("X")),
        right=node_from_json(data.get("Y")),
    )


def _convert_case_clause(data: dict) -> CaseClause:
    pos, end = _parse_pos_end(data)
    return CaseClause(
        pos=pos,
        end=end,
        expr=_convert_word(data.get("Word")),
        branches=[
            CaseBranch(
                patterns=[
                    w
                    for p in b.get("Patterns", [])
                    if (w := _convert_word(p)) is not None
                ],
                body=[_convert_stmt(s) for s in b.get("Stmts", [])],
            )
            for b in data.get("Items", [])
        ],
    )


def _convert_binary_arithm(data: dict) -> BinaryArithm:
    pos, end = _parse_pos_end(data)
    return BinaryArithm(
        pos=pos,
        end=end,
        op=data.get("Op", ""),
        op_pos=_parse_position(data.get("OpPos")),
        left=node_from_json(data.get("X")),
        right=node_from_json(data.get("Y")),
    )


def _convert_block(data: dict) -> Block:
    pos, end = _parse_pos_end(data)
    return Block(
        pos=pos,
        end=end,
        left_pos=_parse_position(data.get("Lbrace")),
        right_pos=_parse_position(data.get("Rbrace")),
        stmts=[_convert_stmt(s) for s in data.get("Stmts", [])],
    )


def _convert_func_decl(data: dict) -> FuncDecl:
    name_data = data.get("Name", {})
    name_node = _convert_lit(name_data) if isinstance(name_data, dict) else None

    body_data = data.get("Body")
    body_node = None
    if isinstance(body_data, dict):
        body_node = node_from_json(body_data.get("Cmd", body_data))

    pos, end = _parse_pos_end(data)
    return FuncDecl(
        pos=pos,
        end=end,
        rsrv_word=data.get("RsrvWord", False),
        parens=data.get("Parens", False),
        name=name_node,
        body=body_node,
    )


def _convert_test_clause(data: dict) -> TestClause:
    pos, end = _parse_pos_end(data)
    return TestClause(
        pos=pos,
        end=end,
        left_pos=_parse_position(data.get("Left")),
        right_pos=_parse_position(data.get("Right")),
        body=node_from_json(data.get("X")),
    )


def _convert_unary_test(data: dict) -> UnaryTest:
    pos, end = _parse_pos_end(data)
    return UnaryTest(
        pos=pos,
        end=end,
        op=data.get("Op", ""),
        op_pos=_parse_position(data.get("OpPos")),
        x=node_from_json(data.get("X")),
    )


def _convert_binary_test(data: dict) -> BinaryTest:
    pos, end = _parse_pos_end(data)
    return BinaryTest(
        pos=pos,
        end=end,
        op=data.get("Op", ""),
        op_pos=_parse_position(data.get("OpPos")),
        left=node_from_json(data.get("X")),
        right=node_from_json(data.get("Y")),
    )


def _convert_paren_test(data: dict) -> ParenTest:
    pos, end = _parse_pos_end(data)
    return ParenTest(
        pos=pos,
        end=end,
        left_pos=_parse_position(data.get("Lparen")),
        right_pos=_parse_position(data.get("Rparen")),
        body=node_from_json(data.get("X")),
    )


def _convert_arithm_cmd(data: dict) -> ArithmCmd:
    pos, end = _parse_pos_end(data)
    return ArithmCmd(
        pos=pos,
        end=end,
        left_pos=_parse_position(data.get("Left")),
        right_pos=_parse_position(data.get("Right")),
        body=node_from_json(data.get("X")),
    )


def _convert_unary_arithm(data: dict) -> UnaryArithm:
    pos, end = _parse_pos_end(data)
    return UnaryArithm(
        pos=pos,
        end=end,
        op=data.get("Op", ""),
        op_pos=_parse_position(data.get("OpPos")),
        post=data.get("Post", False),
        x=node_from_json(data.get("X")),
    )


def _convert_paren_arithm(data: dict) -> ParenArithm:
    pos, end = _parse_pos_end(data)
    return ParenArithm(
        pos=pos,
        end=end,
        left_pos=_parse_position(data.get("Lparen")),
        right_pos=_parse_position(data.get("Rparen")),
        body=node_from_json(data.get("X")),
    )


def _convert_flags_arithm(data: dict) -> FlagsArithm:
    pos, end = _parse_pos_end(data)
    return FlagsArithm(
        pos=pos,
        end=end,
        flags=Lit(value=data.get("Flags", "")),
        x=node_from_json(data.get("X")),
    )


def _convert_let_clause(data: dict) -> LetClause:
    pos, end = _parse_pos_end(data)
    return LetClause(
        pos=pos,
        end=end,
        let_pos=_parse_position(data.get("Let")),
        exprs=[
            n for e in data.get("Exprs", []) if (n := node_from_json(e)) is not None
        ],
    )


def _convert_time_clause(data: dict) -> TimeClause:
    pos, end = _parse_pos_end(data)
    return TimeClause(
        pos=pos,
        end=end,
        time_pos=_parse_position(data.get("Time")),
        posix_format=data.get("PosixFormat", False),
        stmt=node_from_json(data.get("Stmt")),
    )


def _convert_coproc_clause(data: dict) -> CoprocClause:
    pos, end = _parse_pos_end(data)
    return CoprocClause(
        pos=pos,
        end=end,
        coproc_pos=_parse_position(data.get("Coproc")),
        name=_convert_word(data.get("Name")),
        stmt=node_from_json(data.get("Stmt")),
    )


def _convert_test_decl(data: dict) -> TestDecl:
    pos, end = _parse_pos_end(data)
    return TestDecl(
        pos=pos,
        end=end,
        description=_convert_word(data.get("Description")),
        body=node_from_json(data.get("Body")),
    )


def _convert_comment(data: dict) -> Comment:
    pos, end = _parse_pos_end(data)
    return Comment(
        pos=pos,
        end=end,
        hash_pos=_parse_position(data.get("Hash")),
        text=data.get("Text", ""),
    )


def _convert_case_item(data: dict) -> CaseItem:
    pos, end = _parse_pos_end(data)
    return CaseItem(
        pos=pos,
        end=end,
        op=data.get("Op", ""),
        patterns=[
            w for p in data.get("Patterns", []) if (w := _convert_word(p)) is not None
        ],
        stmts=[_convert_stmt(s) for s in data.get("Stmts", [])],
    )


def _convert_word_iter(data: dict) -> WordIter:
    pos, end = _parse_pos_end(data)
    name_data = data.get("Name")
    name_node = (
        _convert_lit(name_data)
        if isinstance(name_data, dict)
        else Lit(value=str(name_data) if name_data else "")
    )
    return WordIter(
        pos=pos,
        end=end,
        name=name_node,
        items=[w for i in data.get("Items", []) if (w := _convert_word(i)) is not None],
    )


def _convert_cstyle_loop(data: dict) -> CStyleLoop:
    pos, end = _parse_pos_end(data)
    return CStyleLoop(
        pos=pos,
        end=end,
        init=node_from_json(data.get("Init")),
        cond=node_from_json(data.get("Cond")),
        post=node_from_json(data.get("Post")),
    )


def _convert_array_expr(data: dict) -> ArrayExpr:
    pos, end = _parse_pos_end(data)
    return ArrayExpr(
        pos=pos,
        end=end,
        elems=[_convert_array_elem(e) for e in data.get("Elems", [])],
    )


def _convert_brace_exp(data: dict) -> BraceExp:
    pos, end = _parse_pos_end(data)
    return BraceExp(
        pos=pos,
        end=end,
        sequence=data.get("Sequence", False),
        elems=[w for e in data.get("Elems", []) if (w := _convert_word(e)) is not None],
    )


# ---------------------------------------------------------------------------
# Dispatch table mapping shfmt Type strings to converter functions
# ---------------------------------------------------------------------------

_CONVERTERS: dict[str, Callable[[dict[str, Any]], Node | None]] = {
    "File": _convert_file,
    "CallExpr": _convert_call_expr,
    "BinaryCmd": _convert_binary_cmd,
    "DeclClause": _convert_decl_clause,
    "Subshell": _convert_subshell,
    "IfClause": _convert_if_clause,
    "ForClause": _convert_for_clause,
    "WhileClause": _convert_while_clause,
    "AndCmd": _convert_and_cmd,
    "OrCmd": _convert_or_cmd,
    "CaseClause": _convert_case_clause,
    "ArithmExp": _convert_arithm_exp,
    "BinaryArithm": _convert_binary_arithm,
    "ExtGlob": _convert_ext_glob,
    "Block": _convert_block,
    "FuncDecl": _convert_func_decl,
    "TestClause": _convert_test_clause,
    "UnaryTest": _convert_unary_test,
    "BinaryTest": _convert_binary_test,
    "ParenTest": _convert_paren_test,
    "ArithmCmd": _convert_arithm_cmd,
    "UnaryArithm": _convert_unary_arithm,
    "ParenArithm": _convert_paren_arithm,
    "FlagsArithm": _convert_flags_arithm,
    "LetClause": _convert_let_clause,
    "TimeClause": _convert_time_clause,
    "CoprocClause": _convert_coproc_clause,
    "TestDecl": _convert_test_decl,
    "Comment": _convert_comment,
    "Assign": _convert_assign,
    "CaseItem": _convert_case_item,
    "WordIter": _convert_word_iter,
    "CStyleLoop": _convert_cstyle_loop,
    "ArrayExpr": _convert_array_expr,
    "ArrayElem": _convert_array_elem,
    "BraceExp": _convert_brace_exp,
    "Lit": _convert_lit,
    "SglQuoted": _convert_sgl_quoted,
    "ParamExp": _convert_param_exp,
    "DblQuoted": _convert_dbl_quoted,
    "CmdSubst": _convert_cmd_subst,
    "ProcSubst": _convert_proc_subst,
    "Word": _convert_word,
    "Stmt": _convert_stmt,
}


def node_from_json(data: dict | None) -> Node | None:
    """Convert shfmt JSON node data to a typed AST node.

    Returns None when *data* is None (key absent in JSON).

    Uses the ``_CONVERTERS`` dispatch table to map shfmt's ``Type`` field
    to a converter function.
    """
    if data is None:
        return None

    node_type = data.get("Type", "")

    # Handle nodes that have 'Cmd' but no 'Type' (wrapped statements)
    if not node_type and "Cmd" in data:
        return node_from_json(data["Cmd"])

    converter = _CONVERTERS.get(node_type)
    if converter is not None:
        return converter(data)

    # Unknown type — wrap in a generic Node
    pos, end = _parse_pos_end(data)
    return Node(type=node_type, pos=pos, end=end)


def parse_ast(command: str) -> File:
    """Parse a bash command string into a typed AST.

    This is the main entry point for parsing bash commands.  It invokes
    shfmt via :func:`~lovely_bash_permissions.parser.parse` and converts
    the resulting JSON into a typed Python AST rooted at a :class:`File`
    node.  Re-exported from the package root for convenience.

    Args:
        command: Bash command string to parse

    Returns:
        Root File node of the parsed AST tree

    Raises:
        ParseError: If shfmt cannot parse the command
    """
    from .parser import parse

    raw = parse(command)
    result = node_from_json(raw)
    if not isinstance(result, File):
        raise TypeError(f"Expected File node, got {type(result).__name__}")
    return result
