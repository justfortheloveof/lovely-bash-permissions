"""
AST inspection and traversal utilities.
"""

from typing import List
from .ast import Node, CallExpr, BinaryCmd, Word, Part, Stmt, File, Redir


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
        return node.type in ("Var", "ParamExp")
    elif isinstance(node, Word):
        return any(_has_variable_recursive(p) for p in node.parts)
    elif isinstance(node, CallExpr):
        return any(_has_variable_recursive(a) for a in node.args)
    elif isinstance(node, BinaryCmd):
        return _has_variable_recursive(node.x) or _has_variable_recursive(node.y)
    elif isinstance(node, File):
        return any(_has_variable_recursive(s.cmd) for s in node.stmts)
    elif isinstance(node, Stmt):
        return _has_variable_recursive(node.cmd)
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
