"""
JSON-to-AST conversion for shfmt output.

This module converts shfmt's JSON AST representation into typed Python
dataclass nodes defined in ``ast.py``. It uses a dispatch table
(``_CONVERTERS``) to map shfmt type strings to converter functions.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

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

NODE_TYPES: dict[str, type] = {
    "File": File,
    "CallExpr": CallExpr,
    "BinaryCmd": BinaryCmd,
    "Word": Word,
    "DeclClause": DeclClause,
    "Subshell": Subshell,
    "IfClause": IfClause,
    "ForClause": ForClause,
    "WhileClause": WhileClause,
    "AndCmd": AndCmd,
    "OrCmd": OrCmd,
    "CaseClause": CaseClause,
    "Lit": Lit,
    "SglQuoted": SglQuoted,
    "ParamExp": ParamExp,
    "DblQuoted": DblQuoted,
    "CmdSubst": CmdSubst,
    "ProcSubst": ProcSubst,
    "ArithmExp": ArithmExp,
    "BraceExp": BraceExp,
    "BinaryArithm": BinaryArithm,
    "ExtGlob": ExtGlob,
    "Block": Block,
    "FuncDecl": FuncDecl,
    "TestClause": TestClause,
    "UnaryTest": UnaryTest,
    "BinaryTest": BinaryTest,
    "ParenTest": ParenTest,
    "ArithmCmd": ArithmCmd,
    "UnaryArithm": UnaryArithm,
    "ParenArithm": ParenArithm,
    "FlagsArithm": FlagsArithm,
    "LetClause": LetClause,
    "TimeClause": TimeClause,
    "CoprocClause": CoprocClause,
    "TestDecl": TestDecl,
    "Comment": Comment,
    "Assign": Assign,
    "CaseItem": CaseItem,
    "WordIter": WordIter,
    "CStyleLoop": CStyleLoop,
    "ArrayExpr": ArrayExpr,
    "ArrayElem": ArrayElem,
}

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


def _lit_from_json(data: dict) -> Lit:
    """Convert shfmt JSON to a Lit node."""
    pos, end = _parse_pos_end(data)
    return Lit(
        type="Lit",
        pos=pos,
        end=end,
        value=data.get("Value", ""),
        value_pos=_parse_position(data.get("ValuePos")),
        value_end=_parse_position(data.get("ValueEnd")),
    )


def _sgl_quoted_from_json(data: dict) -> SglQuoted:
    pos, end = _parse_pos_end(data)
    return SglQuoted(type="SglQuoted", pos=pos, end=end, value=data.get("Value", ""))


def _paramexp_from_json(data: dict) -> ParamExp:
    """Convert shfmt JSON to a ParamExp node."""
    pos, end = _parse_pos_end(data)
    param_data = data.get("Param", {})
    param_value = param_data.get("Value", "") if isinstance(param_data, dict) else ""
    index_data = data.get("Index")
    index_node = word_from_json(index_data) if isinstance(index_data, dict) else None
    exp_data = data.get("Exp")
    exp_value = exp_data if isinstance(exp_data, dict) else None
    return ParamExp(
        type="ParamExp",
        pos=pos,
        end=end,
        param=param_value,
        short=data.get("Short", False),
        exp=exp_value,
        index=index_node,
        length=data.get("Length", False),
        dollar_pos=_parse_position(data.get("Dollar")),
    )


def _cmd_subst_from_json(data: dict) -> CmdSubst:
    pos, end = _parse_pos_end(data)
    return CmdSubst(
        type="CmdSubst",
        pos=pos,
        end=end,
        stmts=[stmt_from_json(s) for s in data.get("Stmts", [])],
        backquotes=data.get("Backquotes", False),
    )


def _proc_subst_from_json(data: dict) -> ProcSubst:
    pos, end = _parse_pos_end(data)
    return ProcSubst(
        type="ProcSubst",
        pos=pos,
        end=end,
        op=data.get("Op", ""),
        op_pos=_parse_position(data.get("OpPos")),
        rparen=_parse_position(data.get("Rparen")),
        stmts=[stmt_from_json(s) for s in data.get("Stmts", [])],
    )


def _arithm_exp_from_json(data: dict) -> ArithmExp:
    pos, end = _parse_pos_end(data)
    return ArithmExp(
        type="ArithmExp",
        pos=pos,
        end=end,
        x=node_from_json(data.get("X")),
    )


def _extglob_from_json(data: dict) -> ExtGlob:
    """Convert shfmt JSON to an ExtGlob node."""
    pos, end = _parse_pos_end(data)
    pattern_data = data.get("Pattern", {})
    return ExtGlob(
        type="ExtGlob",
        pos=pos,
        end=end,
        op=data.get("Op", ""),
        op_pos=_parse_position(data.get("OpPos")),
        pattern=_lit_from_json(pattern_data) if pattern_data else None,
    )


def _dbl_quoted_from_json(data: dict) -> DblQuoted:
    parts = (
        [part_from_json(p) for p in data.get("Parts", [])] if "Parts" in data else None
    )
    value = None
    if parts:
        value = "".join(
            str(p.value) if hasattr(p, "value") and p.value is not None else ""
            for p in parts
        )
    pos, end = _parse_pos_end(data)
    return DblQuoted(type="DblQuoted", pos=pos, end=end, parts=parts, value=value)


# ---------------------------------------------------------------------------
# Statement / Word / Redir / Assign helpers
# ---------------------------------------------------------------------------


def _parse_stmt_list(raw: list | None) -> list[Stmt]:
    """Convert a list of raw JSON statement dicts to typed Stmt objects.

    Filters entries that don't look like statements (no ``Cmd`` key)
    and logs a warning for dropped entries.
    """
    if not raw:
        return []
    result: list[Stmt] = []
    for item in raw:
        if isinstance(item, dict) and "Cmd" in item:
            result.append(stmt_from_json(item))
        else:
            _log.debug("Dropped non-statement entry in stmt list: %s", type(item))
    return result


def assign_from_json(data: dict) -> Assign:
    """Convert shfmt JSON assignment data to a typed Assign object."""
    name_data = data.get("Name", {})
    name_node = _lit_from_json(name_data) if isinstance(name_data, dict) else None

    index_data = data.get("Index")
    index_node = word_from_json(index_data) if isinstance(index_data, dict) else None

    value_data = data.get("Value")
    value_node = word_from_json(value_data) if isinstance(value_data, dict) else None

    array_data = data.get("Array")
    array_node = None
    if isinstance(array_data, dict):
        pos, end = _parse_pos_end(array_data)
        array_node = ArrayExpr(
            type="ArrayExpr",
            pos=pos,
            end=end,
            elems=[_array_elem_from_json(e) for e in array_data.get("Elems", [])],
        )

    pos, end = _parse_pos_end(data)
    return Assign(
        type="Assign",
        pos=pos,
        end=end,
        name=name_node,
        index=index_node,
        value=value_node,
        array=array_node,
        append=data.get("Append", False),
        naked=data.get("Naked", False),
    )


def _array_elem_from_json(data: dict) -> ArrayElem:
    """Convert shfmt JSON array element data to a typed ArrayElem object."""
    index_data = data.get("Index")
    index_node = word_from_json(index_data) if isinstance(index_data, dict) else None

    value_data = data.get("Value")
    value_node = word_from_json(value_data) if isinstance(value_data, dict) else None

    pos, end = _parse_pos_end(data)
    return ArrayElem(
        type="ArrayElem",
        pos=pos,
        end=end,
        index=index_node,
        value=value_node,
    )


def redir_from_json(data: dict) -> Redir:
    """Convert shfmt JSON redirection data to a typed Redir object."""
    pos, end = _parse_pos_end(data)
    return Redir(
        op=data.get("Op", ""),
        word=word_from_json(data.get("Word")),
        pos=pos,
        end=end,
        op_pos=_parse_position(data.get("OpPos")),
    )


def stmt_from_json(data: dict) -> Stmt:
    """Convert shfmt JSON statement data to a typed Stmt object."""
    cmd_json = data.get("Cmd")
    cmd = node_from_json(cmd_json)
    redirs: list[Redir] = []
    if "Redirs" in data:
        redirs = [redir_from_json(r) for r in data.get("Redirs", [])]
    elif isinstance(cmd, BinaryCmd):
        y_json = cmd_json.get("Y") if isinstance(cmd_json, dict) else None
        if isinstance(y_json, dict) and "Redirs" in y_json:
            redirs = [redir_from_json(r) for r in y_json.get("Redirs", [])]
    pos, end = _parse_pos_end(data)
    return Stmt(
        cmd=cmd,
        position=_parse_position(data.get("Position")),
        pos=pos,
        end=end,
        redirs=redirs,
    )


def word_from_json(data: dict | None) -> Word | None:
    """Convert shfmt JSON word data to a typed Word object.

    Returns None when *data* is None (key absent in JSON).
    """
    if data is None:
        return None
    parts = [part_from_json(p) for p in data.get("Parts", [])]
    pos, end = _parse_pos_end(data)
    return Word(
        type="Word",
        pos=pos,
        end=end,
        parts=parts,
    )


def part_from_json(data: dict) -> Node:
    """Convert shfmt JSON part data to a typed Node object.

    Delegates to the same converters used by ``node_from_json`` for all
    known types. Falls back to a generic DblQuoted or Node for unknown types.
    """
    part_type = data.get("Type", "")

    # Use the shared converters for all known part types
    converter = _PART_CONVERTERS.get(part_type)
    if converter is not None:
        return converter(data)

    # DblQuoted (handled specially since it needs computed value)
    if part_type == "DblQuoted":
        return _dbl_quoted_from_json(data)

    # Unknown part type — wrap in a generic Node
    pos, end = _parse_pos_end(data)
    return Node(type=part_type, pos=pos, end=end)


# Part-specific converter dispatch (shared types reuse the same functions)
_PART_CONVERTERS: dict[str, Callable[[dict], Node]] = {
    "Lit": _lit_from_json,
    "SglQuoted": _sgl_quoted_from_json,
    "CmdSubst": _cmd_subst_from_json,
    "ProcSubst": _proc_subst_from_json,
    "ParamExp": _paramexp_from_json,
    "ArithmExp": _arithm_exp_from_json,
    "ExtGlob": _extglob_from_json,
}


# ---------------------------------------------------------------------------
# IfClause conversion (handles nested elif/else structures)
# ---------------------------------------------------------------------------


def _parse_if_clause(data: dict) -> IfClause:
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
        type="IfClause",
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
        type="File",
        pos=pos,
        end=end,
        stmts=[stmt_from_json(s) for s in data.get("Stmts", [])],
    )


def _convert_call_expr(data: dict) -> CallExpr:
    assigns_raw = data.get("Assigns")
    assigns = [assign_from_json(a) for a in assigns_raw] if assigns_raw else None
    pos, end = _parse_pos_end(data)
    return CallExpr(
        type="CallExpr",
        pos=pos,
        end=end,
        args=[word_from_json(a) for a in data.get("Args", [])],
        assigns=assigns,
    )


def _convert_binary_cmd(data: dict) -> BinaryCmd:
    pos, end = _parse_pos_end(data)
    return BinaryCmd(
        type="BinaryCmd",
        pos=pos,
        end=end,
        op=data.get("Op", ""),
        left=node_from_json(data.get("X")),
        right=node_from_json(data.get("Y")),
    )


def _convert_decl_clause(data: dict) -> DeclClause:
    variant = data.get("Variant", {})
    variant_value = variant.get("Value", "") if isinstance(variant, dict) else ""

    assigns: list[Assign] = []
    args: list[Word] = []
    for arg in data.get("Args", []):
        if isinstance(arg, dict):
            assigns.append(assign_from_json(arg))
            # Also extract the value as a Word for backwards compat
            val = arg.get("Value", {})
            if isinstance(val, dict) and val.get("Parts"):
                args.append(word_from_json(val))

    pos, end = _parse_pos_end(data)
    return DeclClause(
        type="DeclClause",
        pos=pos,
        end=end,
        variant=variant_value,
        args=args,
        assigns=assigns,
    )


def _convert_subshell(data: dict) -> Subshell:
    pos, end = _parse_pos_end(data)
    return Subshell(
        type="Subshell",
        pos=pos,
        end=end,
        stmts=[stmt_from_json(s) for s in data.get("Stmts", [])],
    )


def _convert_for_clause(data: dict) -> ForClause:
    loop = data.get("Loop", {})
    var_name: str | None = None
    if isinstance(loop, dict):
        name_info = loop.get("Name", {})
        if isinstance(name_info, dict):
            var_name = name_info.get("Value")

    items: list[Word] = []
    if isinstance(loop, dict):
        for w in loop.get("Items", []):
            if isinstance(w, dict):
                items.append(word_from_json(w))

    body = _parse_stmt_list(data.get("Do", []))

    pos, end = _parse_pos_end(data)
    return ForClause(
        type="ForClause",
        pos=pos,
        end=end,
        var=var_name,
        words=items,
        body=body,
    )


def _convert_while_clause(data: dict) -> WhileClause:
    pos, end = _parse_pos_end(data)
    return WhileClause(
        type="WhileClause",
        pos=pos,
        end=end,
        cond_stmts=[stmt_from_json(s) for s in data.get("Cond", [])],
        body=[stmt_from_json(s) for s in data.get("Do", [])],
    )


def _convert_and_cmd(data: dict) -> AndCmd:
    pos, end = _parse_pos_end(data)
    return AndCmd(
        type="AndCmd",
        pos=pos,
        end=end,
        left=node_from_json(data.get("X")),
        right=node_from_json(data.get("Y")),
    )


def _convert_or_cmd(data: dict) -> OrCmd:
    pos, end = _parse_pos_end(data)
    return OrCmd(
        type="OrCmd",
        pos=pos,
        end=end,
        left=node_from_json(data.get("X")),
        right=node_from_json(data.get("Y")),
    )


def _convert_case_clause(data: dict) -> CaseClause:
    pos, end = _parse_pos_end(data)
    return CaseClause(
        type="CaseClause",
        pos=pos,
        end=end,
        expr=word_from_json(data.get("Word")),
        branches=[
            CaseBranch(
                patterns=[word_from_json(w) for w in b.get("Patterns", [])],
                body=[stmt_from_json(s) for s in b.get("Stmts", [])],
            )
            for b in data.get("Items", [])
        ],
        default=[stmt_from_json(s) for s in data.get("Default", [])],
    )


def _convert_binary_arithm(data: dict) -> BinaryArithm:
    pos, end = _parse_pos_end(data)
    return BinaryArithm(
        type="BinaryArithm",
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
        type="Block",
        pos=pos,
        end=end,
        left_pos=_parse_position(data.get("Lbrace")),
        right_pos=_parse_position(data.get("Rbrace")),
        stmts=[stmt_from_json(s) for s in data.get("Stmts", [])],
    )


def _convert_func_decl(data: dict) -> FuncDecl:
    name_data = data.get("Name", {})
    name_node = _lit_from_json(name_data) if isinstance(name_data, dict) else None

    body_data = data.get("Body")
    body_node = None
    if isinstance(body_data, dict):
        body_node = node_from_json(body_data.get("Cmd", body_data))

    pos, end = _parse_pos_end(data)
    return FuncDecl(
        type="FuncDecl",
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
        type="TestClause",
        pos=pos,
        end=end,
        left_pos=_parse_position(data.get("Left")),
        right_pos=_parse_position(data.get("Right")),
        body=node_from_json(data.get("X")),
    )


def _convert_unary_test(data: dict) -> UnaryTest:
    pos, end = _parse_pos_end(data)
    return UnaryTest(
        type="UnaryTest",
        pos=pos,
        end=end,
        op=data.get("Op", ""),
        op_pos=_parse_position(data.get("OpPos")),
        x=node_from_json(data.get("X")),
    )


def _convert_binary_test(data: dict) -> BinaryTest:
    pos, end = _parse_pos_end(data)
    return BinaryTest(
        type="BinaryTest",
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
        type="ParenTest",
        pos=pos,
        end=end,
        left_pos=_parse_position(data.get("Lparen")),
        right_pos=_parse_position(data.get("Rparen")),
        body=node_from_json(data.get("X")),
    )


def _convert_arithm_cmd(data: dict) -> ArithmCmd:
    pos, end = _parse_pos_end(data)
    return ArithmCmd(
        type="ArithmCmd",
        pos=pos,
        end=end,
        left_pos=_parse_position(data.get("Left")),
        right_pos=_parse_position(data.get("Right")),
        body=node_from_json(data.get("X")),
    )


def _convert_unary_arithm(data: dict) -> UnaryArithm:
    pos, end = _parse_pos_end(data)
    return UnaryArithm(
        type="UnaryArithm",
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
        type="ParenArithm",
        pos=pos,
        end=end,
        left_pos=_parse_position(data.get("Lparen")),
        right_pos=_parse_position(data.get("Rparen")),
        body=node_from_json(data.get("X")),
    )


def _convert_flags_arithm(data: dict) -> FlagsArithm:
    pos, end = _parse_pos_end(data)
    return FlagsArithm(
        type="FlagsArithm",
        pos=pos,
        end=end,
        flags=Lit(type="Lit", value=data.get("Flags", "")),
        x=node_from_json(data.get("X")),
    )


def _convert_let_clause(data: dict) -> LetClause:
    pos, end = _parse_pos_end(data)
    return LetClause(
        type="LetClause",
        pos=pos,
        end=end,
        let_pos=_parse_position(data.get("Let")),
        exprs=[node_from_json(e) for e in data.get("Exprs", [])],
    )


def _convert_time_clause(data: dict) -> TimeClause:
    pos, end = _parse_pos_end(data)
    return TimeClause(
        type="TimeClause",
        pos=pos,
        end=end,
        time_pos=_parse_position(data.get("Time")),
        posix_format=data.get("PosixFormat", False),
        stmt=node_from_json(data.get("Stmt")),
    )


def _convert_coproc_clause(data: dict) -> CoprocClause:
    pos, end = _parse_pos_end(data)
    return CoprocClause(
        type="CoprocClause",
        pos=pos,
        end=end,
        coproc_pos=_parse_position(data.get("Coproc")),
        name=word_from_json(data.get("Name")),
        stmt=node_from_json(data.get("Stmt")),
    )


def _convert_test_decl(data: dict) -> TestDecl:
    pos, end = _parse_pos_end(data)
    return TestDecl(
        type="TestDecl",
        pos=pos,
        end=end,
        description=word_from_json(data.get("Description")),
        body=node_from_json(data.get("Body")),
    )


def _convert_comment(data: dict) -> Comment:
    return Comment(
        type="Comment",
        hash_pos=_parse_position(data.get("Hash")),
        text=data.get("Text", ""),
    )


def _convert_case_item(data: dict) -> CaseItem:
    pos, end = _parse_pos_end(data)
    return CaseItem(
        type="CaseItem",
        pos=pos,
        end=end,
        op=data.get("Op", ""),
        patterns=[word_from_json(w) for w in data.get("Patterns", [])],
        stmts=[stmt_from_json(s) for s in data.get("Stmts", [])],
    )


def _convert_word_iter(data: dict) -> WordIter:
    pos, end = _parse_pos_end(data)
    return WordIter(
        type="WordIter",
        pos=pos,
        end=end,
        name=Lit(type="Lit", value=data.get("Name", "")),
        items=[word_from_json(w) for w in data.get("Items", [])],
    )


def _convert_cstyle_loop(data: dict) -> CStyleLoop:
    pos, end = _parse_pos_end(data)
    return CStyleLoop(
        type="CStyleLoop",
        pos=pos,
        end=end,
        init=node_from_json(data.get("Init")),
        cond=node_from_json(data.get("Cond")),
        post=node_from_json(data.get("Post")),
    )


def _convert_array_expr(data: dict) -> ArrayExpr:
    pos, end = _parse_pos_end(data)
    return ArrayExpr(
        type="ArrayExpr",
        pos=pos,
        end=end,
        elems=[node_from_json(e) for e in data.get("Elems", [])],
    )


def _convert_brace_exp(data: dict) -> BraceExp:
    pos, end = _parse_pos_end(data)
    return BraceExp(
        type="BraceExp",
        pos=pos,
        end=end,
        sequence=data.get("Sequence", False),
        elems=[word_from_json(e) for e in data.get("Elems", [])],
    )


# ---------------------------------------------------------------------------
# Dispatch table mapping shfmt Type strings to converter functions
# ---------------------------------------------------------------------------

_CONVERTERS: dict[str, Callable[[dict], Node]] = {
    "File": _convert_file,
    "CallExpr": _convert_call_expr,
    "BinaryCmd": _convert_binary_cmd,
    "DeclClause": _convert_decl_clause,
    "Subshell": _convert_subshell,
    "IfClause": _parse_if_clause,
    "ForClause": _convert_for_clause,
    "WhileClause": _convert_while_clause,
    "AndCmd": _convert_and_cmd,
    "OrCmd": _convert_or_cmd,
    "CaseClause": _convert_case_clause,
    "ArithmExp": _arithm_exp_from_json,
    "BinaryArithm": _convert_binary_arithm,
    "ExtGlob": _extglob_from_json,
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
    "Assign": assign_from_json,
    "CaseItem": _convert_case_item,
    "WordIter": _convert_word_iter,
    "CStyleLoop": _convert_cstyle_loop,
    "ArrayExpr": _convert_array_expr,
    "ArrayElem": _array_elem_from_json,
    "BraceExp": _convert_brace_exp,
    "Lit": _lit_from_json,
    "SglQuoted": _sgl_quoted_from_json,
    "ParamExp": _paramexp_from_json,
    "DblQuoted": _dbl_quoted_from_json,
    "CmdSubst": _cmd_subst_from_json,
    "ProcSubst": _proc_subst_from_json,
    "Word": lambda data: word_from_json(data),
    "Stmt": lambda data: stmt_from_json(data),
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


def parse_ast(command: str) -> Node:
    """Parse a bash command string into a typed AST node.

    This is the main entry point for parsing bash commands. It invokes
    shfmt via the parser module and converts the resulting JSON into
    a typed Python AST rooted at a File node.

    Args:
        command: Bash command string to parse

    Returns:
        Node: Root File node of the parsed AST tree

    Raises:
        ParseError: If shfmt cannot parse the command
    """
    from .parser import parse

    raw = parse(command)
    return node_from_json(raw)
