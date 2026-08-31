"""
AST inspection and traversal utilities.

This module provides functions for querying parsed bash AST trees, including
command extraction, argument collection, variable detection, redirection
analysis, and the AST visitor pattern for custom traversal.
"""

from collections.abc import Callable

from .ast import (
    AndCmd,
    ArithmCmd,
    BinaryCmd,
    Block,
    CallExpr,
    CaseClause,
    CmdSubst,
    CoprocClause,
    File,
    ForClause,
    FuncDecl,
    IfClause,
    LetClause,
    Lit,
    Node,
    OrCmd,
    ParamExp,
    Part,
    Redir,
    Stmt,
    Subshell,
    TestClause,
    TimeClause,
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
        if node.redirs:
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
        if node.redirs:
            for redir in node.redirs:
                _traverse(redir, visitor, recurse_call_expr_args)
    elif isinstance(node, Word):
        if node.parts:
            for part in node.parts:
                _traverse(part, visitor, recurse_call_expr_args)
    elif isinstance(node, Redir):
        if node.word:
            _traverse(node.word, visitor, recurse_call_expr_args)
    elif isinstance(node, Lit):
        pass  # leaf
    elif isinstance(node, CmdSubst):
        if node.stmts:
            for stmt in node.stmts:
                _traverse(stmt, visitor, recurse_call_expr_args)
    elif isinstance(node, Part):
        if node.parts:
            for subpart in node.parts:
                _traverse(subpart, visitor, recurse_call_expr_args)
    elif isinstance(node, Subshell):
        if node.stmts:
            for stmt in node.stmts:
                _traverse(stmt, visitor, recurse_call_expr_args)
    elif isinstance(node, IfClause):
        for stmt in node.cond_stmts:
            _traverse(stmt, visitor, recurse_call_expr_args)
        for stmt in node.then_stmts:
            _traverse(stmt, visitor, recurse_call_expr_args)
        for branch in node.elif_branches:
            for stmt in branch["cond"]:
                _traverse(stmt, visitor, recurse_call_expr_args)
            for stmt in branch["body"]:
                _traverse(stmt, visitor, recurse_call_expr_args)
        if node.else_stmts:
            for stmt in node.else_stmts:
                _traverse(stmt, visitor, recurse_call_expr_args)
    elif isinstance(node, ForClause):
        if node.var:
            _traverse(node.var, visitor, recurse_call_expr_args)
        if node.words:
            for word in node.words:
                _traverse(word, visitor, recurse_call_expr_args)
        if node.body:
            for stmt in node.body:
                _traverse(stmt, visitor, recurse_call_expr_args)
    elif isinstance(node, WhileClause):
        if node.cond_stmts:
            for stmt in node.cond_stmts:
                _traverse(stmt, visitor, recurse_call_expr_args)
        if node.body:
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
            for pattern in branch["patterns"]:
                _traverse(pattern, visitor, recurse_call_expr_args)
            for stmt in branch["body"]:
                _traverse(stmt, visitor, recurse_call_expr_args)
        if node.default:
            for stmt in node.default:
                _traverse(stmt, visitor, recurse_call_expr_args)
    # --- Issue #9: missing traversal branches for container node types ---
    elif isinstance(node, Block):
        if node.stmts:
            for stmt in node.stmts:
                _traverse(stmt, visitor, recurse_call_expr_args)
    # --- Container node types with body/stmt fields ---
    elif isinstance(node, (FuncDecl, TestClause, ArithmCmd)):
        if node.body:
            _traverse(node.body, visitor, recurse_call_expr_args)
    elif isinstance(node, (TimeClause, CoprocClause)):
        if node.stmt:
            _traverse(node.stmt, visitor, recurse_call_expr_args)
    elif isinstance(node, LetClause):
        if node.exprs:
            for expr in node.exprs:
                _traverse(expr, visitor, recurse_call_expr_args)
    elif hasattr(node, "type") and node.type == "DeclClause" and node.args:
        for a in node.args:
            _traverse(a, visitor, recurse_call_expr_args)


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

    def visit(self, node: Node):
        """Visit a node and dispatch to the appropriate method."""
        if isinstance(node, File):
            return self.visit_file(node)
        elif isinstance(node, Stmt):
            return self.visit_stmt(node)
        elif isinstance(node, CallExpr):
            return self.visit_call_expr(node)
        elif isinstance(node, BinaryCmd):
            return self.visit_binary_cmd(node)
        elif isinstance(node, Word):
            return self.visit_word(node)
        elif isinstance(node, Redir):
            return self.visit_redir(node)
        elif isinstance(node, Lit):
            return self.visit_lit(node)
        elif isinstance(node, (ParamExp, Part)):
            return self.visit_part(node)
        elif isinstance(node, Subshell):
            return self.visit_subshell(node)
        elif isinstance(node, CmdSubst):
            return self.visit_cmd_subst(node)
        elif isinstance(node, IfClause):
            return self.visit_if_clause(node)
        elif isinstance(node, ForClause):
            return self.visit_for_clause(node)
        elif isinstance(node, WhileClause):
            return self.visit_while_clause(node)
        elif isinstance(node, AndCmd):
            return self.visit_and_cmd(node)
        elif isinstance(node, OrCmd):
            return self.visit_or_cmd(node)
        elif isinstance(node, CaseClause):
            return self.visit_case_clause(node)
        elif isinstance(node, Block):
            return self.visit_block(node)
        elif isinstance(node, FuncDecl):
            return self.visit_func_decl(node)
        elif isinstance(node, TestClause):
            return self.visit_test_clause(node)
        elif isinstance(node, ArithmCmd):
            return self.visit_arithm_cmd(node)
        elif isinstance(node, TimeClause):
            return self.visit_time_clause(node)
        elif isinstance(node, CoprocClause):
            return self.visit_coproc_clause(node)
        elif hasattr(node, "type") and node.type == "DeclClause":
            return self.visit_decl_clause(node)
        else:
            return self.visit_node(node)

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

    def visit_part(self, node: Part) -> None:
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

    def visit_decl_clause(self, node: Node) -> None:
        pass

    def walk(self, node: Node):
        """Walk the entire AST tree, visiting all nodes recursively."""
        _traverse(node, self.visit, recurse_call_expr_args=True)


class VariableVisitor(Visitor):
    """Visitor that detects whether the tree contains any variable references."""

    def __init__(self):
        super().__init__()
        self.found = False

    def visit_part(self, node: Part) -> None:
        if self.found:
            return
        if isinstance(node, (ParamExp, CmdSubst)):
            self.found = True
        elif node.type == "DblQuoted" and node.parts:
            for p in node.parts:
                _traverse(p, self.visit)

    def visit_word(self, node: Word) -> None:
        if self.found:
            return
        for part in node.parts:
            _traverse(part, self.visit)

    def visit_call_expr(self, node: CallExpr) -> None:
        if self.found:
            return
        for arg in node.args:
            _traverse(arg, self.visit)

    def visit_decl_clause(self, node: Node) -> None:
        if self.found:
            return
        if hasattr(node, "args") and node.args:
            for a in node.args:
                _traverse(a, self.visit)

    def visit_cmd_subst(self, node: CmdSubst) -> None:
        self.found = True
        if node.stmts:
            for stmt in node.stmts:
                _traverse(stmt, self.visit, recurse_call_expr_args=True)


def get_commands(tree: Node) -> list[str]:
    """Extract all command names from the AST."""
    commands: list[str] = []

    def visitor(node):
        if isinstance(node, CallExpr):
            if node.args:
                cmd_name = _word_value(node.args[0])
                if cmd_name:
                    commands.append(cmd_name)
            if node.assigns:
                for assign in node.assigns:
                    val = assign.value if hasattr(assign, "value") else None
                    if val is None:
                        continue
                    for p in getattr(val, "parts", []):
                        _traverse(p, visitor)

    _traverse(tree, visitor, recurse_call_expr_args=True)
    return commands


def find_commands(tree: Node) -> list[CallExpr]:
    """Find all CallExpr nodes (commands) in the AST."""
    commands: list[CallExpr] = []

    def visitor(node):
        if isinstance(node, CallExpr):
            commands.append(node)
            if node.assigns:
                for assign in node.assigns:
                    val = assign.value if hasattr(assign, "value") else None
                    if val is None:
                        continue
                    for p in getattr(val, "parts", []):
                        _traverse(p, visitor)

    _traverse(tree, visitor, recurse_call_expr_args=True)
    return commands


def _word_value(word: Word) -> str:
    """Get the value of a word (concatenate all parts)."""
    parts = []
    for part in word.parts:
        if part.value:
            parts.append(part.value)
    return "".join(parts)


def has_variable(tree: Node) -> bool:
    """Check if the command contains any variable references."""
    visitor = VariableVisitor()
    _traverse(tree, visitor.visit, recurse_call_expr_args=True)
    return visitor.found


def get_redirections(tree: Node) -> list[dict]:
    """Extract file redirections from the AST."""
    redirs: list[dict] = []

    def visitor(node):
        if (isinstance(node, (Stmt, BinaryCmd))) and node.redirs:
            for r in node.redirs:
                redirs.append({"op": r.op, "target": _word_value(r.word)})

    _traverse(tree, visitor)
    return redirs


def get_arguments(tree: Node) -> list[list[str]]:
    """Extract command arguments for each call expression."""
    args_list: list[list[str]] = []

    def visitor(node):
        if isinstance(node, CallExpr) and node.args:
            args_list.append([_word_value(arg) for arg in node.args[1:]])

    _traverse(tree, visitor)
    return args_list


def find_arguments(tree: Node) -> list[list[Word]]:
    """Find all argument lists (excluding command names) for each call."""
    args_list: list[list[Word]] = []

    def visitor(node):
        if isinstance(node, CallExpr) and node.args:
            args_list.append(node.args[1:])

    _traverse(tree, visitor)
    return args_list


def has_pipe(tree: Node) -> bool:
    """Check if the command contains any pipes."""
    found = False

    def visitor(n: Node):
        nonlocal found
        if found:
            return
        if isinstance(n, BinaryCmd):
            found = True

    _traverse(tree, visitor, recurse_call_expr_args=True)
    return found


def get_target_files(tree: Node) -> list[str]:
    """Extract file targets from redirections."""
    targets: list[str] = []

    def visitor(node):
        if (isinstance(node, (Stmt, BinaryCmd))) and node.redirs:
            for r in node.redirs:
                target = _word_value(r.word)
                if target:
                    targets.append(target)

    _traverse(tree, visitor)
    return targets
