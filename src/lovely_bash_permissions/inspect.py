"""
AST inspection and traversal utilities.

This module provides functions for querying parsed bash AST trees, including
command extraction, argument collection, variable detection, redirection
analysis, and the AST visitor pattern for custom traversal.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

from .ast import (
    AndCmd,
    ArithmCmd,
    ArithmExp,
    Assign,
    BinaryArithm,
    BinaryCmd,
    BinaryTest,
    Block,
    BraceExp,
    CallExpr,
    CaseClause,
    CmdSubst,
    CoprocClause,
    DblQuoted,
    DeclClause,
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

# ---------------------------------------------------------------------------
# Generic child-node iteration (#6)
# ---------------------------------------------------------------------------


def _iter_children(node: Node, *, include_call_args: bool = False) -> Iterator[Node]:
    """Yield direct child nodes of *node*.

    When *include_call_args* is False (default), CallExpr arguments are
    skipped so that ``get_commands()`` does not descend into argument
    words.  When True, they are included (used by ``Visitor.walk``).
    """
    if isinstance(node, File):
        yield from node.stmts
    elif isinstance(node, Stmt):
        if node.cmd:
            yield node.cmd
        yield from node.redirs
    elif isinstance(node, CallExpr):
        if include_call_args and node.args:
            yield from node.args
    elif isinstance(node, BinaryCmd):
        if node.left:
            yield node.left
        if node.right:
            yield node.right
        yield from node.redirs
    elif isinstance(node, Word):
        yield from node.parts
    elif isinstance(node, Redir):
        if node.word:
            yield node.word
    elif isinstance(node, (Lit, SglQuoted)):
        return  # leaf nodes
    elif isinstance(node, ParamExp):
        if node.index:
            yield node.index
    elif isinstance(node, DblQuoted):
        yield from node.parts
    elif isinstance(node, (CmdSubst, Subshell, ProcSubst)):
        yield from node.stmts
    elif isinstance(node, IfClause):
        yield from node.cond_stmts
        yield from node.then_stmts
        for branch in node.elif_branches:
            yield from branch.cond
            yield from branch.body
        yield from node.else_stmts
    elif isinstance(node, ForClause):
        yield from node.words
        yield from node.body
    elif isinstance(node, WhileClause):
        yield from node.cond_stmts
        yield from node.body
    elif isinstance(node, (AndCmd, OrCmd)):
        if node.left:
            yield node.left
        if node.right:
            yield node.right
    elif isinstance(node, CaseClause):
        if node.expr:
            yield node.expr
        for branch in node.branches:
            yield from branch.patterns
            yield from branch.body
        yield from node.default_body
    elif isinstance(node, Block):
        yield from node.stmts
    elif isinstance(node, (FuncDecl, TestClause, ArithmCmd)):
        if node.body:
            yield node.body
    elif isinstance(node, (TimeClause, CoprocClause)):
        if node.stmt:
            yield node.stmt
    elif isinstance(node, LetClause):
        yield from node.exprs
    elif isinstance(node, DeclClause):
        yield from node.args
        for a in node.assigns:
            if a.value:
                yield a.value
    elif isinstance(node, ArithmExp):
        if node.x:
            yield node.x
    elif isinstance(node, BinaryArithm):
        if node.left:
            yield node.left
        if node.right:
            yield node.right
    elif isinstance(node, (UnaryArithm, UnaryTest)):
        if node.x:
            yield node.x
    elif isinstance(node, BinaryTest):
        if node.left:
            yield node.left
        if node.right:
            yield node.right
    elif isinstance(node, (ParenTest, ParenArithm)):
        if node.body:
            yield node.body
    elif isinstance(node, ExtGlob):
        if node.pattern:
            yield node.pattern
    elif isinstance(node, BraceExp):
        yield from node.elems
    elif isinstance(node, FlagsArithm):
        if node.x:
            yield node.x
    elif isinstance(node, Assign) and node.value:
        yield node.value


def _traverse(
    node: Node,
    visitor: Callable[[Node], None],
    recurse_call_expr_args: bool = False,
) -> None:
    """Shared AST traversal helper.

    Calls ``visitor(node)`` on every node, then recurses into children.

    When ``recurse_call_expr_args`` is True, child nodes inside CallExpr
    arguments are also visited (used by ``walk()``).
    """
    visitor(node)
    for child in _iter_children(node, include_call_args=recurse_call_expr_args):
        _traverse(child, visitor, recurse_call_expr_args)


# ---------------------------------------------------------------------------
# Early-termination sentinel (#11)
# ---------------------------------------------------------------------------


class _Found(Exception):
    """Raised to short-circuit traversal when a match is found."""


# ---------------------------------------------------------------------------
# Shared helpers (#9, #10)
# ---------------------------------------------------------------------------


def _traverse_assigns(node: CallExpr, visitor: Callable[[Node], None]) -> None:
    """Traverse variable-assignment values attached to a CallExpr."""
    if node.assigns:
        for assign in node.assigns:
            if assign.value is not None:
                for part in assign.value.parts:
                    _traverse(part, visitor)


def _collect_redirs(node: Node) -> Iterator[Redir]:
    """Yield Redir objects from Stmt or BinaryCmd nodes."""
    if isinstance(node, (Stmt, BinaryCmd)) and node.redirs:
        yield from node.redirs


class Visitor:
    """AST node visitor pattern for traversing bash AST trees.

    Subclass Visitor and override specific visit methods to process
    particular node types.

    Example:
        class CommandCollector(Visitor):
            def __init__(self):
                super().__init__()
                self.commands = []

            def visit_call_expr(self, node):
                super().visit_call_expr(node)
                cmd_name = _word_value(node.args[0])
                self.commands.append(cmd_name)

        collector = CommandCollector()
        collector.walk(tree)
    """

    # Dispatch table maps type -> method name.
    # Complete for all node types (#7).
    _DISPATCH: dict[type, str] = {
        File: "visit_file",
        Stmt: "visit_stmt",
        CallExpr: "visit_call_expr",
        BinaryCmd: "visit_binary_cmd",
        Word: "visit_word",
        Redir: "visit_redir",
        Lit: "visit_lit",
        SglQuoted: "visit_sgl_quoted",
        ParamExp: "visit_param_exp",
        DblQuoted: "visit_dbl_quoted",
        Subshell: "visit_subshell",
        CmdSubst: "visit_cmd_subst",
        IfClause: "visit_if_clause",
        ForClause: "visit_for_clause",
        WhileClause: "visit_while_clause",
        AndCmd: "visit_and_cmd",
        OrCmd: "visit_or_cmd",
        CaseClause: "visit_case_clause",
        Block: "visit_block",
        FuncDecl: "visit_func_decl",
        TestClause: "visit_test_clause",
        ArithmCmd: "visit_arithm_cmd",
        TimeClause: "visit_time_clause",
        CoprocClause: "visit_coproc_clause",
        DeclClause: "visit_decl_clause",
        LetClause: "visit_let_clause",
        ExtGlob: "visit_ext_glob",
        Assign: "visit_assign",
        ArithmExp: "visit_arithm_exp",
        BinaryArithm: "visit_binary_arithm",
        ProcSubst: "visit_proc_subst",
        # Previously missing types (#7)
        UnaryTest: "visit_unary_test",
        BinaryTest: "visit_binary_test",
        ParenTest: "visit_paren_test",
        UnaryArithm: "visit_unary_arithm",
        ParenArithm: "visit_paren_arithm",
        BraceExp: "visit_brace_exp",
        FlagsArithm: "visit_flags_arithm",
    }

    def visit(self, node: Node) -> None:
        """Visit a node and dispatch to the appropriate method."""
        method_name = self._DISPATCH.get(type(node))
        if method_name is not None:
            getattr(self, method_name)(node)
        else:
            self.visit_node(node)

    def visit_file(self, node: File) -> None:
        pass

    def visit_stmt(self, node: Stmt) -> None:
        pass

    def visit_call_expr(self, node: CallExpr) -> None:
        pass

    def visit_binary_cmd(self, node: BinaryCmd) -> None:
        pass

    def visit_word(self, node: Word) -> None:
        pass

    def visit_redir(self, node: Redir) -> None:
        pass

    def visit_lit(self, node: Lit) -> None:
        pass

    def visit_param_exp(self, node: ParamExp) -> None:
        self.visit_part(node)

    def visit_dbl_quoted(self, node: DblQuoted) -> None:
        pass

    def visit_part(self, node: Node) -> None:
        pass

    def visit_node(self, node: Node) -> None:
        pass

    def visit_subshell(self, node: Subshell) -> None:
        pass

    def visit_cmd_subst(self, node: CmdSubst) -> None:
        pass

    def visit_if_clause(self, node: IfClause) -> None:
        pass

    def visit_for_clause(self, node: ForClause) -> None:
        pass

    def visit_while_clause(self, node: WhileClause) -> None:
        pass

    def visit_and_cmd(self, node: AndCmd) -> None:
        pass

    def visit_or_cmd(self, node: OrCmd) -> None:
        pass

    def visit_case_clause(self, node: CaseClause) -> None:
        pass

    def visit_block(self, node: Block) -> None:
        pass

    def visit_func_decl(self, node: FuncDecl) -> None:
        pass

    def visit_test_clause(self, node: TestClause) -> None:
        pass

    def visit_arithm_cmd(self, node: ArithmCmd) -> None:
        pass

    def visit_time_clause(self, node: TimeClause) -> None:
        pass

    def visit_coproc_clause(self, node: CoprocClause) -> None:
        pass

    def visit_decl_clause(self, node: DeclClause) -> None:
        pass

    def visit_sgl_quoted(self, node: SglQuoted) -> None:
        pass

    def visit_let_clause(self, node: LetClause) -> None:
        pass

    def visit_ext_glob(self, node: ExtGlob) -> None:
        pass

    def visit_assign(self, node: Assign) -> None:
        pass

    def visit_arithm_exp(self, node: ArithmExp) -> None:
        pass

    def visit_binary_arithm(self, node: BinaryArithm) -> None:
        pass

    def visit_proc_subst(self, node: ProcSubst) -> None:
        pass

    # New visit methods for previously missing types (#7)

    def visit_unary_test(self, node: UnaryTest) -> None:
        pass

    def visit_binary_test(self, node: BinaryTest) -> None:
        pass

    def visit_paren_test(self, node: ParenTest) -> None:
        pass

    def visit_unary_arithm(self, node: UnaryArithm) -> None:
        pass

    def visit_paren_arithm(self, node: ParenArithm) -> None:
        pass

    def visit_brace_exp(self, node: BraceExp) -> None:
        pass

    def visit_flags_arithm(self, node: FlagsArithm) -> None:
        pass

    def walk(self, node: Node) -> None:
        """Walk the entire AST tree, visiting all nodes recursively."""
        _traverse(node, self.visit, recurse_call_expr_args=True)


def _word_value(word: Word) -> str:
    """Get the string value of a word (concatenating all parts).

    Handles Lit, SglQuoted, DblQuoted, ParamExp, and CmdSubst parts,
    producing a best-effort string representation.
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
        elif hasattr(part, "value") and part.value is not None:
            parts.append(str(part.value))
    return "".join(parts)


def get_commands(tree: Node) -> list[str]:
    """Extract all command names from the AST."""
    commands: list[str] = []

    def visitor(node: Node) -> None:
        if isinstance(node, CallExpr):
            if node.args:
                cmd_name = _word_value(node.args[0])
                if cmd_name:
                    commands.append(cmd_name)
            _traverse_assigns(node, visitor)

    _traverse(tree, visitor, recurse_call_expr_args=True)
    return commands


def find_commands(tree: Node) -> list[CallExpr]:
    """Find all CallExpr nodes (commands) in the AST."""
    commands: list[CallExpr] = []

    def visitor(node: Node) -> None:
        if isinstance(node, CallExpr):
            commands.append(node)
            _traverse_assigns(node, visitor)

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


def get_redirections(tree: Node) -> list[dict]:
    """Extract file redirections from the AST."""
    redirs: list[dict] = []

    def visitor(node: Node) -> None:
        for r in _collect_redirs(node):
            if r.word:
                redirs.append({"op": r.op, "target": _word_value(r.word)})

    _traverse(tree, visitor)
    return redirs


def get_arguments(tree: Node) -> list[list[str]]:
    """Extract command arguments for each call expression.

    Recurses into CallExpr arguments consistently with ``get_commands``.
    """
    args_list: list[list[str]] = []

    def visitor(node: Node) -> None:
        if isinstance(node, CallExpr) and node.args:
            args_list.append([_word_value(arg) for arg in node.args[1:]])

    _traverse(tree, visitor, recurse_call_expr_args=True)
    return args_list


def find_arguments(tree: Node) -> list[list[Word]]:
    """Find all argument lists (excluding command names) for each call.

    Recurses into CallExpr arguments consistently with ``find_commands``.
    """
    args_list: list[list[Word]] = []

    def visitor(node: Node) -> None:
        if isinstance(node, CallExpr) and node.args:
            args_list.append(node.args[1:])

    _traverse(tree, visitor, recurse_call_expr_args=True)
    return args_list


def has_pipe(tree: Node) -> bool:
    """Check if the command contains any pipe operators.

    Only returns True for actual pipe operators (``|``), not for
    ``&&`` or ``||`` which are also represented as BinaryCmd nodes.
    """

    def visitor(node: Node) -> None:
        if isinstance(node, BinaryCmd) and node.op == "|":
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

    _traverse(tree, visitor)
    return targets
