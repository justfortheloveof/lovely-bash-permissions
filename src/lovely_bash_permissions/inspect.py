"""
AST inspection and traversal utilities.

This module provides functions for querying parsed bash AST trees, including
command extraction, argument collection, variable detection, redirection
analysis, and the AST visitor pattern for custom traversal.
"""

from __future__ import annotations

from collections.abc import Callable

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


def _traverse(
    node: Node,
    visitor: Callable[[Node], None],
    recurse_call_expr_args: bool = False,
) -> None:
    """Shared AST traversal helper.

    Calls ``visitor(node)`` on every node, then recurses into children
    based on node type.

    When ``recurse_call_expr_args`` is True, child nodes inside CallExpr
    arguments are also visited (used by ``walk()``). When False (default),
    CallExpr arguments are skipped to preserve the original behavior where
    ``get_commands()`` does not extract nested commands.
    """
    visitor(node)

    if isinstance(node, File):
        for stmt in node.stmts:
            _traverse(stmt, visitor, recurse_call_expr_args)
    elif isinstance(node, Stmt):
        if node.cmd:
            _traverse(node.cmd, visitor, recurse_call_expr_args)
        for redir in node.redirs:
            _traverse(redir, visitor, recurse_call_expr_args)
    elif isinstance(node, CallExpr):
        if recurse_call_expr_args and node.args:
            for arg in node.args:
                _traverse(arg, visitor, recurse_call_expr_args)
    elif isinstance(node, BinaryCmd):
        if node.left:
            _traverse(node.left, visitor, recurse_call_expr_args)
        if node.right:
            _traverse(node.right, visitor, recurse_call_expr_args)
        for redir in node.redirs:
            _traverse(redir, visitor, recurse_call_expr_args)
    elif isinstance(node, Word):
        for part in node.parts:
            _traverse(part, visitor, recurse_call_expr_args)
    elif isinstance(node, Redir):
        if node.word:
            _traverse(node.word, visitor, recurse_call_expr_args)
    elif isinstance(node, (Lit, SglQuoted)):
        pass  # leaf
    elif isinstance(node, ParamExp):
        if node.index:
            _traverse(node.index, visitor, recurse_call_expr_args)
    elif isinstance(node, DblQuoted):
        for part in node.parts:
            _traverse(part, visitor, recurse_call_expr_args)
    elif isinstance(node, (CmdSubst, Subshell, ProcSubst)):
        for stmt in node.stmts:
            _traverse(stmt, visitor, recurse_call_expr_args)
    elif isinstance(node, IfClause):
        for stmt in node.cond_stmts:
            _traverse(stmt, visitor, recurse_call_expr_args)
        for stmt in node.then_stmts:
            _traverse(stmt, visitor, recurse_call_expr_args)
        for branch in node.elif_branches:
            for stmt in branch.cond:
                _traverse(stmt, visitor, recurse_call_expr_args)
            for stmt in branch.body:
                _traverse(stmt, visitor, recurse_call_expr_args)
        for stmt in node.else_stmts:
            _traverse(stmt, visitor, recurse_call_expr_args)
    elif isinstance(node, ForClause):
        for word in node.words:
            _traverse(word, visitor, recurse_call_expr_args)
        for stmt in node.body:
            _traverse(stmt, visitor, recurse_call_expr_args)
    elif isinstance(node, WhileClause):
        for stmt in node.cond_stmts:
            _traverse(stmt, visitor, recurse_call_expr_args)
        for stmt in node.body:
            _traverse(stmt, visitor, recurse_call_expr_args)
    elif isinstance(node, (AndCmd, OrCmd)):
        if node.left:
            _traverse(node.left, visitor, recurse_call_expr_args)
        if node.right:
            _traverse(node.right, visitor, recurse_call_expr_args)
    elif isinstance(node, CaseClause):
        if node.expr:
            _traverse(node.expr, visitor, recurse_call_expr_args)
        for branch in node.branches:
            for pattern in branch.patterns:
                _traverse(pattern, visitor, recurse_call_expr_args)
            for stmt in branch.body:
                _traverse(stmt, visitor, recurse_call_expr_args)
        for stmt in node.default:
            _traverse(stmt, visitor, recurse_call_expr_args)
    elif isinstance(node, Block):
        for stmt in node.stmts:
            _traverse(stmt, visitor, recurse_call_expr_args)
    elif isinstance(node, (FuncDecl, TestClause, ArithmCmd)):
        if node.body:
            _traverse(node.body, visitor, recurse_call_expr_args)
    elif isinstance(node, (TimeClause, CoprocClause)):
        if node.stmt:
            _traverse(node.stmt, visitor, recurse_call_expr_args)
    elif isinstance(node, LetClause):
        for expr in node.exprs:
            _traverse(expr, visitor, recurse_call_expr_args)
    elif isinstance(node, DeclClause):
        for a in node.args:
            _traverse(a, visitor, recurse_call_expr_args)
        for a in node.assigns:
            if a.value:
                _traverse(a.value, visitor, recurse_call_expr_args)
    elif isinstance(node, ArithmExp):
        if node.x:
            _traverse(node.x, visitor, recurse_call_expr_args)
    elif isinstance(node, BinaryArithm):
        if node.left:
            _traverse(node.left, visitor, recurse_call_expr_args)
        if node.right:
            _traverse(node.right, visitor, recurse_call_expr_args)
    elif isinstance(node, (UnaryArithm, UnaryTest)):
        if node.x:
            _traverse(node.x, visitor, recurse_call_expr_args)
    elif isinstance(node, BinaryTest):
        if node.left:
            _traverse(node.left, visitor, recurse_call_expr_args)
        if node.right:
            _traverse(node.right, visitor, recurse_call_expr_args)
    elif isinstance(node, (ParenTest, ParenArithm)):
        if node.body:
            _traverse(node.body, visitor, recurse_call_expr_args)
    elif isinstance(node, ExtGlob):
        if node.pattern:
            _traverse(node.pattern, visitor, recurse_call_expr_args)
    elif isinstance(node, Assign) and node.value:
        _traverse(node.value, visitor, recurse_call_expr_args)


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

    # Dispatch table built once per class (maps type -> method name)
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
    }

    def visit(self, node: Node) -> None:
        """Visit a node and dispatch to the appropriate method."""
        method_name = self._DISPATCH.get(type(node))
        if method_name is not None:
            getattr(self, method_name)(node)
        else:
            # Check for ParamExp-like nodes dispatched via visit_part for
            # backwards compatibility
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
        # Default: delegate to visit_part for backwards compatibility
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
            if node.assigns:
                for assign in node.assigns:
                    val = assign.value
                    if val is None:
                        continue
                    for p in val.parts:
                        _traverse(p, visitor)

    _traverse(tree, visitor, recurse_call_expr_args=True)
    return commands


def find_commands(tree: Node) -> list[CallExpr]:
    """Find all CallExpr nodes (commands) in the AST."""
    commands: list[CallExpr] = []

    def visitor(node: Node) -> None:
        if isinstance(node, CallExpr):
            commands.append(node)
            if node.assigns:
                for assign in node.assigns:
                    val = assign.value
                    if val is None:
                        continue
                    for p in val.parts:
                        _traverse(p, visitor)

    _traverse(tree, visitor, recurse_call_expr_args=True)
    return commands


def has_variable(tree: Node) -> bool:
    """Check if the command contains any variable references."""
    found = False

    def visitor(node: Node) -> None:
        nonlocal found
        if found:
            return
        if isinstance(node, (ParamExp, CmdSubst)):
            found = True

    _traverse(tree, visitor, recurse_call_expr_args=True)
    return found


def get_redirections(tree: Node) -> list[dict]:
    """Extract file redirections from the AST."""
    redirs: list[dict] = []

    def visitor(node: Node) -> None:
        if isinstance(node, (Stmt, BinaryCmd)) and node.redirs:
            for r in node.redirs:
                if r.word:
                    redirs.append({"op": r.op, "target": _word_value(r.word)})

    _traverse(tree, visitor)
    return redirs


def get_arguments(tree: Node) -> list[list[str]]:
    """Extract command arguments for each call expression."""
    args_list: list[list[str]] = []

    def visitor(node: Node) -> None:
        if isinstance(node, CallExpr) and node.args:
            args_list.append([_word_value(arg) for arg in node.args[1:]])

    _traverse(tree, visitor)
    return args_list


def find_arguments(tree: Node) -> list[list[Word]]:
    """Find all argument lists (excluding command names) for each call."""
    args_list: list[list[Word]] = []

    def visitor(node: Node) -> None:
        if isinstance(node, CallExpr) and node.args:
            args_list.append(node.args[1:])

    _traverse(tree, visitor)
    return args_list


def has_pipe(tree: Node) -> bool:
    """Check if the command contains any pipe operators.

    Only returns True for actual pipe operators (``|``), not for
    ``&&`` or ``||`` which are also represented as BinaryCmd nodes.
    """
    found = False

    def visitor(n: Node) -> None:
        nonlocal found
        if found:
            return
        if isinstance(n, BinaryCmd) and n.op == "|":
            found = True

    _traverse(tree, visitor, recurse_call_expr_args=True)
    return found


def get_target_files(tree: Node) -> list[str]:
    """Extract file targets from redirections."""
    targets: list[str] = []

    def visitor(node: Node) -> None:
        if isinstance(node, (Stmt, BinaryCmd)) and node.redirs:
            for r in node.redirs:
                if r.word:
                    target = _word_value(r.word)
                    if target:
                        targets.append(target)

    _traverse(tree, visitor)
    return targets
