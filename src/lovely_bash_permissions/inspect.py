"""
AST inspection and traversal utilities.

This module provides functions for querying parsed bash AST trees, including
command extraction, argument collection, variable detection, redirection
analysis, and the AST visitor pattern for custom traversal.

Key functions:
    - get_commands(): Extract command names
    - get_arguments(): Extract arguments for each command
    - find_commands(): Get CallExpr nodes
    - find_arguments(): Get argument lists
    - has_variable(): Detect variable usage
    - get_redirections(): Find file redirections
    - has_pipe(): Check for pipe operators
    - get_target_files(): Extract redirection file targets
    - Visitor: Custom AST traversal pattern
"""

from typing import List, Callable, Any, Dict, Optional
from .ast import Node, CallExpr, BinaryCmd, Word, Part, Lit, SglQuoted, ParamExp, DblQuoted, CmdSubst, Stmt, File, Redir, Subshell, IfClause, ForClause, WhileClause, AndCmd, OrCmd, CaseClause, part_from_json, node_from_json


def _traverse(
    node: Node,
    visitor: Callable[[Node], None],
    recurse_call_expr_args: bool = False,
) -> None:
    """Shared AST traversal helper.

    Calls ``visitor(node)`` on every node, then recurses into children
    based on node type.  Visitor functions for leaf types (CallExpr, Redir)
    extract data; visitor functions for container types are no-ops —
    recursion is handled uniformly here.

    When ``recurse_call_expr_args`` is True, child nodes inside CallExpr
    arguments are also visited (used by ``walk()`` so visitors reach words
    and variables inside command arguments).  When False (the default),
    CallExpr arguments are skipped — this preserves the original behavior
    where ``get_commands()`` does not extract commands nested inside
    arguments (e.g. ``echo $(date)`` returns only ``['echo']``).

    This replaces the near-duplicate traversal logic previously spread
    across ``_collect_commands``, ``_find_commands``, ``_collect_arguments``,
    ``_find_arguments``, ``_collect_redirections``, and ``_collect_target_files``.

    Args:
        node:  AST node to visit (typically the root File).
        visitor: Callable invoked on every node; may mutate a captured list.
    """
    visitor(node)

    # --- recursion into children (shared across all callers) -----
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
        # Recurse into args only when recurse_call_expr_args is True
        # (walk() needs it; get_commands intentionally skips nested commands).
        if recurse_call_expr_args and node.args:
            for arg in node.args:
                _traverse(arg, visitor)
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
        pass  # leaf — no children
    elif isinstance(node, Part):
        if node.parts:
            for subpart in node.parts:
                _traverse(subpart, visitor, recurse_call_expr_args)
    elif isinstance(node, CmdSubst):
        # Command substitution ($() or backtick) — recurse into stmts
        if node.stmts:
            for stmt in node.stmts:
                _traverse(stmt, visitor, recurse_call_expr_args)
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
    elif isinstance(node, AndCmd):
        if node.left:
            _traverse(node.left, visitor, recurse_call_expr_args)
        if node.right:
            _traverse(node.right, visitor, recurse_call_expr_args)
    elif isinstance(node, OrCmd):
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


class Visitor:
    """
    AST node visitor pattern for traversing bash AST trees.

    Subclass Visitor and override specific visit methods to process
    particular node types. The visit() method dispatches each node
    to the appropriate handler based on its type.

    Use walk() to traverse the entire tree, calling visit() on each
    node and recursively visiting all child nodes.

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
        commands = collector.commands  # List of command names found

    Visitor methods:
        visit(node) - Dispatch to type-specific handler
        visit_file(node) - Handle File nodes
        visit_stmt(node) - Handle Stmt nodes
        visit_call_expr(node) - Handle CallExpr nodes
        visit_binary_cmd(node) - Handle BinaryCmd nodes
        visit_word(node) - Handle Word nodes
        visit_redir(node) - Handle Redir nodes
        visit_part(node) - Handle Part nodes
        visit_node(node) - Handle generic Node objects
        visit_subshell(node) - Handle Subshell nodes
        visit_if_clause(node) - Handle IfClause nodes
        visit_for_clause(node) - Handle ForClause nodes
        visit_while_clause(node) - Handle WhileClause nodes
        visit_and_cmd(node) - Handle AndCmd nodes (&&)
        visit_or_cmd(node) - Handle OrCmd nodes (||)
        visit_case_clause(node) - Handle CaseClause nodes
        walk(node) - Recursively visit all nodes in the tree
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
        elif isinstance(node, ParamExp):
            return self.visit_part(node)
        elif isinstance(node, Part):
            return self.visit_part(node)
        elif isinstance(node, Subshell):
            return self.visit_subshell(node)
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
        else:
            return self.visit_node(node)

    def visit_file(self, node: File) -> None:
        """Visit a File node. Override to process top-level AST files."""
        pass

    def visit_stmt(self, node: Stmt) -> None:
        """Visit a Stmt node. Override to process individual statements."""
        pass

    def visit_call_expr(self, node: CallExpr) -> None:
        """Visit a CallExpr node. Override to process command invocations."""
        pass

    def visit_binary_cmd(self, node: BinaryCmd) -> None:
        """Visit a BinaryCmd node. Override to process pipes."""
        pass

    def visit_word(self, node: Word) -> None:
        """Visit a Word node. Override to process bash words."""
        pass

    def visit_redir(self, node: Redir) -> None:
        """Visit a Redir node. Override to process file redirections."""
        pass

    def visit_lit(self, node: Lit) -> None:
        """Visit a Lit node. Override to process literal values.

        Lit nodes are simple literal parts of a Word. They inherit from
        Node (not Part) and represent unquoted literal strings.

        By default, Lit nodes are forwarded to visit_part() for
        compatibility with existing visitor code that treats all word
        parts uniformly. Override visit_part() to handle both Part
        and Lit nodes, or override visit_lit() for Lit-specific processing.
        """
        pass

    def visit_part(self, node: Part) -> None:
        """Visit a Part node. Override to process word parts."""
        pass

    def visit_node(self, node: Node) -> None:
        """Visit a generic Node. Override to process unmapped node types."""
        pass

    def visit_subshell(self, node: Subshell) -> None:
        """Visit a Subshell node. Override to process subshell commands."""
        pass

    def visit_if_clause(self, node: IfClause) -> None:
        """Visit an IfClause node. Override to process if/elif/else branches."""
        pass

    def visit_for_clause(self, node: ForClause) -> None:
        """Visit a ForClause node. Override to process for loops."""
        pass

    def visit_while_clause(self, node: WhileClause) -> None:
        """Visit a WhileClause node. Override to process while loops."""
        pass

    def visit_and_cmd(self, node: AndCmd) -> None:
        """Visit an AndCmd node. Override to process && logical AND."""
        pass

    def visit_or_cmd(self, node: OrCmd) -> None:
        """Visit an OrCmd node. Override to process || logical OR."""
        pass

    def visit_case_clause(self, node: CaseClause) -> None:
        """Visit a CaseClause node. Override to process case/switch statements."""
        pass

    def walk(self, node: Node):
        """Walk the entire AST tree, visiting all nodes recursively."""
        _traverse(node, self.visit, recurse_call_expr_args=True)


def get_commands(tree: Node) -> List[str]:
    """
    Extract all command names from the AST.

    Traverses the entire tree and collects the names of all commands
    that would be executed, including commands within pipes, subshells,
    conditionals, and loops.

    Args:
        tree: The AST tree (typically root File node)

    Returns:
        List[str]: Names of all commands in execution order

    Example:
        tree = parse_ast('cat file.txt | grep pattern | sort -u')
        get_commands(tree)  # ['cat', 'grep', 'sort']
    """
    commands: List[str] = []

    def visitor(node):
        if isinstance(node, CallExpr):
            # First arg is the command name
            if node.args:
                cmd_name = _word_value(node.args[0])
                if cmd_name:
                    commands.append(cmd_name)
            # Handle Assigns (variable assignments) — recurse into their parts,
            # which may contain CmdSubst with nested commands.
            if node.assigns:
                for assign in node.assigns:
                    val = assign.value if hasattr(assign, 'value') else None
                    if val is None:
                        continue
                    for p in getattr(val, 'parts', []):
                        _traverse(p, visitor)

    _traverse(tree, visitor)
    return commands


def find_commands(tree: Node) -> List[CallExpr]:
    """
    Find all CallExpr nodes (commands) in the AST.

    Unlike get_commands(), this returns the full CallExpr node objects
    rather than just command names. Use this when you need to inspect
    command arguments or node positions.

    Args:
        tree: The AST tree (typically root File node)

    Returns:
        List[CallExpr]: All command invocation nodes

    Example:
        tree = parse_ast('ls -la | grep txt')
        commands = find_commands(tree)
        commands  # List of CallExpr nodes
        len(commands)              # 2
        commands[0].args[0]        # Word node for 'ls'
    """
    commands: List[CallExpr] = []

    def visitor(node):
        if isinstance(node, CallExpr):
            commands.append(node)
            # Handle Assigns (variable assignments) — recurse into their parts.
            if node.assigns:
                for assign in node.assigns:
                    val = assign.value if hasattr(assign, 'value') else None
                    if val is None:
                        continue
                    for p in getattr(val, 'parts', []):
                        _traverse(p, visitor)

    _traverse(tree, visitor)
    return commands


def _word_value(word: Word) -> str:
    """Get the value of a word (concatenate all parts)."""
    parts = []
    for part in word.parts:
        if part.value:
            parts.append(part.value)
    return "".join(parts)


def has_variable(tree: Node) -> bool:
    """
    Check if the command contains any variable references.

    Detects variable references ($VAR), parameter expansions (${VAR}),
    and command substitutions ($() or backticks). Also handles variables
    within quoted strings and nested expressions.

    Args:
        tree: The AST tree (typically root File node)

    Returns:
        bool: True if any variables are referenced in the command

    Example:
        has_variable(parse_ast('ls -la'))      # False
        has_variable(parse_ast('echo $HOME'))  # True
        has_variable(parse_ast('cat /tmp/x'))  # False (path, not variable)
    """
    return _has_variable_recursive(tree)


def _has_variable_recursive(node: Node) -> bool:
    """Recursively check for variables."""
    if isinstance(node, Lit):
        return False
    elif isinstance(node, Part):
        if node.type in ("Var", "ParamExp", "CmdSubst"):
            return True
        if node.type == "DblQuoted" and node.parts:
            return any(_has_variable_recursive(p) for p in node.parts)
        return False
    elif hasattr(node, 'type') and node.type in ("Var", "ParamExp", "CmdSubst"):
        return True
    elif isinstance(node, Word):
        return any(_has_variable_recursive(p) for p in node.parts)
    elif isinstance(node, CallExpr):
        return any(_has_variable_recursive(a) for a in node.args)
    elif node.type == "DeclClause":
        if hasattr(node, 'args') and node.args:
            for a in node.args:
                if isinstance(a, dict):
                    if 'value' in a and _has_variable_recursive(a['value']):
                        return True
                elif isinstance(a, (Word, Part)):
                    if _has_variable_recursive(a):
                        return True
    elif isinstance(node, BinaryCmd):
        return _has_variable_recursive(node.left) or _has_variable_recursive(node.right)
    elif isinstance(node, File):
        return any(_has_variable_recursive(s.cmd) for s in node.stmts)
    elif isinstance(node, Stmt):
        return _has_variable_recursive(node.cmd)
    elif isinstance(node, Subshell):
        return any(_has_variable_recursive(s.cmd) for s in node.stmts)
    elif isinstance(node, IfClause):
        if any(_has_variable_recursive(s.cmd) for s in node.cond_stmts):
            return True
        if any(_has_variable_recursive(s.cmd) for s in node.then_stmts):
            return True
        for branch in node.elif_branches:
            if any(_has_variable_recursive(s.cmd) for s in branch["cond"]):
                return True
            if any(_has_variable_recursive(s.cmd) for s in branch["body"]):
                return True
        return any(_has_variable_recursive(s.cmd) for s in node.else_stmts)
    elif isinstance(node, ForClause):
        if node.var and _has_variable_recursive(node.var):
            return True
        if any(_has_variable_recursive(w) for w in node.words):
            return True
        return any(_has_variable_recursive(s.cmd) for s in node.body)
    elif isinstance(node, WhileClause):
        if any(_has_variable_recursive(s.cmd) for s in node.cond_stmts):
            return True
        return any(_has_variable_recursive(s.cmd) for s in node.body)
    elif isinstance(node, AndCmd):
        return _has_variable_recursive(node.left) or _has_variable_recursive(node.right)
    elif isinstance(node, OrCmd):
        return _has_variable_recursive(node.left) or _has_variable_recursive(node.right)
    elif isinstance(node, CaseClause):
        if node.expr and _has_variable_recursive(node.expr):
            return True
        for branch in node.branches:
            for pattern in branch["patterns"]:
                if _has_variable_recursive(pattern):
                    return True
            for stmt in branch["body"]:
                if _has_variable_recursive(stmt.cmd):
                    return True
        return any(_has_variable_recursive(s.cmd) for s in node.default)
    elif isinstance(node, Node):
        if hasattr(node, 'args') and node.args:
            return any(_has_variable_recursive(a) for a in node.args)
    return False


def get_redirections(tree: Node) -> List[dict]:
    """
    Extract file redirections from the AST.

    Finds all redirection operations in the tree and returns them as
    dictionaries containing the redirection operator and target file.

    Args:
        tree: The AST tree (typically root File node)

    Returns:
        List[dict]: Each dict has 'op' (operator string like ">", ">>", "<")
            and 'target' (the file path as a string)

    Example:
        tree = parse_ast('cat file.txt > output.txt')
        redirs = get_redirections(tree)
        redirs[0]['op']            # '>'
        redirs[0]['target']        # 'output.txt'
    """
    redirs: List[dict] = []

    def visitor(node):
        if isinstance(node, Stmt) and node.redirs:
            for r in node.redirs:
                redirs.append({'op': r.op, 'target': _word_value(r.word)})
        elif isinstance(node, BinaryCmd) and node.redirs:
            for r in node.redirs:
                redirs.append({'op': r.op, 'target': _word_value(r.word)})

    _traverse(tree, visitor)
    return redirs


def get_arguments(tree: Node) -> List[List[str]]:
    """
    Extract command arguments for each call expression.

    For each command in the AST, returns its arguments (excluding the
    command name itself). The result is a list of argument lists, in
    the same order as the commands appear in the tree.

    Args:
        tree: The AST tree (typically root File node)

    Returns:
        List[List[str]]: Outer list has one entry per command; inner lists
            contain the argument strings for that command

    Example:
        tree = parse_ast('cp file1.txt file2.txt')
        get_arguments(tree)  # [['file1.txt', 'file2.txt']]

        tree2 = parse_ast('ls -la | grep -i txt')
        get_arguments(tree2)  # [['-la'], ['-i', 'txt']]
    """
    args_list: List[List[str]] = []

    def visitor(node):
        if isinstance(node, CallExpr) and node.args:
            args_list.append([_word_value(arg) for arg in node.args[1:]])

    _traverse(tree, visitor)
    return args_list


def find_arguments(tree: Node) -> List[List[Word]]:
    """
    Find all argument lists (excluding command names) for each call.

    Unlike get_arguments(), this returns the full Word node objects
    rather than just the argument strings. Use this when you need
    access to word parts or node positions.

    Args:
        tree: The AST tree (typically root File node)

    Returns:
        List[List[Word]]: Outer list has one entry per command; inner lists
            contain Word objects for each argument
    """
    args_list: List[List[Word]] = []

    def visitor(node):
        if isinstance(node, CallExpr) and node.args:
            args_list.append(node.args[1:])

    _traverse(tree, visitor)
    return args_list


def has_pipe(tree: Node) -> bool:
    """
    Check if the command contains any pipes.

    Traverses the tree looking for BinaryCmd nodes with pipe operators,
    including pipes nested within subshells, conditionals, and loops.

    Args:
        tree: The AST tree (typically root File node)

    Returns:
        bool: True if any pipe operators are present

    Example:
        has_pipe(parse_ast('ls -la'))          # False
        has_pipe(parse_ast('ls | grep txt'))   # True
        has_pipe(parse_ast('ls > file.txt'))   # False (redirect, not pipe)
    """
    return _has_pipe_recursive(tree)


def _has_pipe_recursive(node: Node) -> bool:
    """Recursively check for pipes."""
    if isinstance(node, BinaryCmd):
        return True
    elif isinstance(node, File):
        return any(_has_pipe_recursive(s.cmd) for s in node.stmts)
    elif isinstance(node, Stmt):
        return _has_pipe_recursive(node.cmd)
    elif isinstance(node, CallExpr):
        return False
    elif isinstance(node, Subshell):
        return any(_has_pipe_recursive(s.cmd) for s in node.stmts)
    elif isinstance(node, IfClause):
        if any(_has_pipe_recursive(s.cmd) for s in node.cond_stmts):
            return True
        if any(_has_pipe_recursive(s.cmd) for s in node.then_stmts):
            return True
        for branch in node.elif_branches:
            if any(_has_pipe_recursive(s.cmd) for s in branch["cond"]):
                return True
            if any(_has_pipe_recursive(s.cmd) for s in branch["body"]):
                return True
        return any(_has_pipe_recursive(s.cmd) for s in node.else_stmts)
    elif isinstance(node, ForClause):
        return any(_has_pipe_recursive(s.cmd) for s in node.body)
    elif isinstance(node, WhileClause):
        if any(_has_pipe_recursive(s.cmd) for s in node.cond_stmts):
            return True
        return any(_has_pipe_recursive(s.cmd) for s in node.body)
    elif isinstance(node, AndCmd):
        return _has_pipe_recursive(node.left) or _has_pipe_recursive(node.right)
    elif isinstance(node, OrCmd):
        return _has_pipe_recursive(node.left) or _has_pipe_recursive(node.right)
    elif isinstance(node, CaseClause):
        for branch in node.branches:
            if any(_has_pipe_recursive(s.cmd) for s in branch["body"]):
                return True
        return any(_has_pipe_recursive(s.cmd) for s in node.default)
    return False


def get_target_files(tree: Node) -> List[str]:
    """
    Extract file targets from redirections.

    Finds all redirections in the tree and returns only the target
    file paths. Useful for identifying which files will be modified
    or read by the command.

    Args:
        tree: The AST tree (typically root File node)

    Returns:
        List[str]: Names of all files targeted by redirections

    Example:
        tree = parse_ast('cat file.txt > output.txt')
        get_target_files(tree)  # ['output.txt']
    """
    targets: List[str] = []

    def visitor(node):
        if isinstance(node, Stmt) and node.redirs:
            for r in node.redirs:
                target = _word_value(r.word)
                if target:
                    targets.append(target)
        elif isinstance(node, BinaryCmd) and node.redirs:
            for r in node.redirs:
                target = _word_value(r.word)
                if target:
                    targets.append(target)

    _traverse(tree, visitor)
    return targets
