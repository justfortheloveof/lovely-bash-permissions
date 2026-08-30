"""
AST inspection and traversal utilities.
"""

from typing import List, Callable, Any, Dict, Optional
from .ast import Node, CallExpr, BinaryCmd, Word, Part, Stmt, File, Redir


class Visitor:
    """
    AST node visitor pattern. Subclass and override visit methods
    to process specific node types.
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
        elif isinstance(node, Part):
            return self.visit_part(node)
        else:
            return self.visit_node(node)

    def visit_file(self, node: File) -> None:
        """Visit a File node."""
        pass

    def visit_stmt(self, node: Stmt) -> None:
        """Visit a Stmt node."""
        pass

    def visit_call_expr(self, node: CallExpr) -> None:
        """Visit a CallExpr node."""
        pass

    def visit_binary_cmd(self, node: BinaryCmd) -> None:
        """Visit a BinaryCmd node."""
        pass

    def visit_word(self, node: Word) -> None:
        """Visit a Word node."""
        pass

    def visit_redir(self, node: Redir) -> None:
        """Visit a Redir node."""
        pass

    def visit_part(self, node: Part) -> None:
        """Visit a Part node."""
        pass

    def visit_node(self, node: Node) -> None:
        """Visit a generic Node."""
        pass

    def walk(self, node: Node):
        """
        Walk the entire AST tree, visiting all nodes.
        """
        self.visit(node)
        # Recursively visit children based on node type
        if isinstance(node, File):
            for stmt in node.stmts:
                self.walk(stmt)
        elif isinstance(node, Stmt):
            if node.cmd:
                self.walk(node.cmd)
            if node.redirs:
                for redir in node.redirs:
                    self.walk(redir)
        elif isinstance(node, CallExpr):
            if node.args:
                for arg in node.args:
                    self.walk(arg)
        elif isinstance(node, BinaryCmd):
            if node.x:
                self.walk(node.x)
            if node.y:
                self.walk(node.y)
            if node.redirs:
                for redir in node.redirs:
                    self.walk(redir)
        elif isinstance(node, Word):
            if node.parts:
                for part in node.parts:
                    self.walk(part)
        elif isinstance(node, Redir):
            if node.word:
                self.walk(node.word)
        elif isinstance(node, Part):
            if node.parts:
                for subpart in node.parts:
                    self.walk(subpart)


def get_commands(tree: Node) -> List[str]:
    """
    Extract all command names from the AST.
    
    Args:
        tree: The AST tree
    
    Returns:
        List of command names
    """
    commands = []
    _collect_commands(tree, commands)
    return commands


def find_commands(tree: Node) -> List[CallExpr]:
    """
    Find all CallExpr nodes (commands) in the AST.
    
    Args:
        tree: The AST tree
    
    Returns:
        List of CallExpr nodes
    """
    commands = []
    _find_commands(tree, commands)
    return commands


def _find_commands(node: Node, commands: List[CallExpr]):
    """Recursively find CallExpr nodes."""
    if isinstance(node, CallExpr):
        commands.append(node)
    elif isinstance(node, BinaryCmd):
        _find_commands(node.x, commands)
        _find_commands(node.y, commands)
    elif isinstance(node, File):
        for stmt in node.stmts:
            _find_commands(stmt.cmd, commands)
    elif isinstance(node, Stmt):
        _find_commands(node.cmd, commands)


def _collect_commands(node: Node, commands: List[str]):
    """Recursively collect command names."""
    if isinstance(node, CallExpr):
        # First arg is the command name
        if node.args:
            cmd_name = _word_value(node.args[0])
            if cmd_name:
                commands.append(cmd_name)
    elif isinstance(node, BinaryCmd):
        _collect_commands(node.x, commands)
        _collect_commands(node.y, commands)
    elif isinstance(node, File):
        for stmt in node.stmts:
            _collect_commands(stmt.cmd, commands)
    elif isinstance(node, Stmt):
        _collect_commands(node.cmd, commands)


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
    
    Args:
        tree: The AST tree
    
    Returns:
        True if any variables are present
    """
    return _has_variable_recursive(tree)


def _has_variable_recursive(node: Node) -> bool:
    """Recursively check for variables."""
    if isinstance(node, Part):
        if node.type in ("Var", "ParamExp", "CmdSubst"):
            return True
        # Recurse into DblQuoted parts
        if node.type == "DblQuoted" and node.parts:
            return any(_has_variable_recursive(p) for p in node.parts)
        return False
    elif isinstance(node, Word):
        return any(_has_variable_recursive(p) for p in node.parts)
    elif isinstance(node, CallExpr):
        return any(_has_variable_recursive(a) for a in node.args)
    elif node.type == "DeclClause":
        # Handle export/declare/readonly commands
        if hasattr(node, 'args') and node.args:
            for a in node.args:
                # Args are objects with 'name' and 'value' fields
                if isinstance(a, dict):
                    if 'value' in a and _has_variable_recursive(a['value']):
                        return True
                elif isinstance(a, (Word, Part)):
                    if _has_variable_recursive(a):
                        return True
                # Otherwise ignore
    elif isinstance(node, BinaryCmd):
        return _has_variable_recursive(node.x) or _has_variable_recursive(node.y)
    elif isinstance(node, File):
        return any(_has_variable_recursive(s.cmd) for s in node.stmts)
    elif isinstance(node, Stmt):
        return _has_variable_recursive(node.cmd)
    elif isinstance(node, Node):
        # Handle other node types with args
        if hasattr(node, 'args') and node.args:
            return any(_has_variable_recursive(a) for a in node.args)
    return False


def get_redirections(tree: Node) -> List[dict]:
    """
    Extract redirections from the AST.
    
    Args:
        tree: The AST tree
    
    Returns:
        List of redirection dicts with 'op' and 'target'
    """
    redirs = []
    _collect_redirections(tree, redirs)
    return redirs


def _collect_redirections(node: Node, redirs: List[dict]):
    """Recursively collect redirections."""
    # File has stmts
    if isinstance(node, File):
        for stmt in node.stmts:
            _collect_redirections(stmt, redirs)
    # Stmt has redirs directly
    elif isinstance(node, Stmt):
        if node.redirs:
            for r in node.redirs:
                redirs.append({
                    'op': r.op,
                    'target': _word_value(r.word)
                })
        _collect_redirections(node.cmd, redirs)
    # BinaryCmd: X and Y may have redirs on their inner nodes
    elif isinstance(node, BinaryCmd):
        _collect_redirections(node.x, redirs)
        _collect_redirections(node.y, redirs)
        # Redirections on the pipe itself
        if node.redirs:
            for r in node.redirs:
                redirs.append({
                    'op': r.op,
                    'target': _word_value(r.word)
                })
    # Recurse into other nodes
    elif isinstance(node, CallExpr):
        pass
    elif isinstance(node, Node):
        pass


def get_arguments(tree: Node) -> List[List[str]]:
    """
    Extract command arguments for each call expression.
    
    Args:
        tree: The AST tree
    
    Returns:
        List of argument lists (excluding command name)
    """
    args_list = []
    _collect_arguments(tree, args_list)
    return args_list


def _collect_arguments(node: Node, args_list: List[List[str]]):
    """Recursively collect command arguments."""
    if isinstance(node, CallExpr):
        # Skip command name (first arg), collect the rest
        args = []
        for arg in node.args[1:]:
            args.append(_word_value(arg))
        args_list.append(args)
    elif isinstance(node, BinaryCmd):
        _collect_arguments(node.x, args_list)
        _collect_arguments(node.y, args_list)
    elif isinstance(node, File):
        for stmt in node.stmts:
            _collect_arguments(stmt.cmd, args_list)
    elif isinstance(node, Stmt):
        _collect_arguments(node.cmd, args_list)


def find_arguments(tree: Node) -> List[List[Word]]:
    """
    Find all argument lists (excluding command names) for each call.
    
    Args:
        tree: The AST tree
    
    Returns:
        List of argument lists (Word objects)
    """
    args_list = []
    _find_arguments(tree, args_list)
    return args_list


def _find_arguments(node: Node, args_list: List[List[Word]]):
    """Recursively find argument lists."""
    if isinstance(node, CallExpr):
        # Skip command name (first arg), collect the rest
        if node.args:
            args_list.append(node.args[1:])
    elif isinstance(node, BinaryCmd):
        _find_arguments(node.x, args_list)
        _find_arguments(node.y, args_list)
    elif isinstance(node, File):
        for stmt in node.stmts:
            _find_arguments(stmt.cmd, args_list)
    elif isinstance(node, Stmt):
        _find_arguments(node.cmd, args_list)


def has_pipe(tree: Node) -> bool:
    """
    Check if the command contains any pipes.
    
    Args:
        tree: The AST tree
    
    Returns:
        True if any pipes are present
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
    elif isinstance(node, BinaryCmd):
        return True
    elif isinstance(node, CallExpr):
        return False
    elif isinstance(node, Node):
        if hasattr(node, 'x') and node.x:
            return _has_pipe_recursive(node.x)
        if hasattr(node, 'y') and node.y:
            return _has_pipe_recursive(node.y)
    return False


def get_target_files(tree: Node) -> List[str]:
    """
    Extract file targets from redirections.
    
    Args:
        tree: The AST tree
    
    Returns:
        List of file target names
    """
    targets = []
    _collect_target_files(tree, targets)
    return targets


def _collect_target_files(node: Node, targets: List[str]):
    """Recursively collect file targets from redirections."""
    # File has stmts
    if isinstance(node, File):
        for stmt in node.stmts:
            _collect_target_files(stmt, targets)
    # Stmt has redirs directly
    elif isinstance(node, Stmt):
        if node.redirs:
            for r in node.redirs:
                target = _word_value(r.word)
                if target:
                    targets.append(target)
        _collect_target_files(node.cmd, targets)
    # BinaryCmd: X and Y may have redirs on their inner nodes
    elif isinstance(node, BinaryCmd):
        _collect_target_files(node.x, targets)
        _collect_target_files(node.y, targets)
        # Redirections on the pipe itself
        if node.redirs:
            for r in node.redirs:
                target = _word_value(r.word)
                if target:
                    targets.append(target)
    # CallExpr: check for args that might be files? No, stick to redirections only
