"""
AST inspection and traversal utilities.
"""

from typing import List, Callable, Any, Dict, Optional
from .ast import Node, CallExpr, BinaryCmd, Word, Part, Stmt, File, Redir, Subshell, IfClause, ForClause, WhileClause, AndCmd, OrCmd, CaseClause, part_from_json, node_from_json


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

    def visit_subshell(self, node: Subshell) -> None:
        """Visit a Subshell node."""
        pass

    def visit_if_clause(self, node: IfClause) -> None:
        """Visit an IfClause node."""
        pass

    def visit_for_clause(self, node: ForClause) -> None:
        """Visit a ForClause node."""
        pass

    def visit_while_clause(self, node: WhileClause) -> None:
        """Visit a WhileClause node."""
        pass

    def visit_and_cmd(self, node: AndCmd) -> None:
        """Visit an AndCmd node (&&)."""
        pass

    def visit_or_cmd(self, node: OrCmd) -> None:
        """Visit an OrCmd node (||)."""
        pass

    def visit_case_clause(self, node: CaseClause) -> None:
        """Visit a CaseClause node."""
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
            # CmdSubst also has Stmts that need to be visited
            if node.type == "CmdSubst" and hasattr(node, 'extra') and node.extra:
                stmts = node.extra.get('stmts', node.extra.get('Stmts', []))
                for stmt in stmts:
                    self.walk(stmt)
        elif isinstance(node, Subshell):
            if node.stmts:
                for stmt in node.stmts:
                    self.walk(stmt)
        elif isinstance(node, IfClause):
            if node.cond:
                for stmt in node.cond:
                    self.walk(stmt)
            if node.then:
                for stmt in node.then:
                    self.walk(stmt)
            for branch in node.elif_branches:
                for stmt in branch["cond"]:
                    self.walk(stmt)
                for stmt in branch["body"]:
                    self.walk(stmt)
            if node.else_branch:
                for stmt in node.else_branch:
                    self.walk(stmt)
        elif isinstance(node, ForClause):
            if node.var:
                self.walk(node.var)
            if node.words:
                for word in node.words:
                    self.walk(word)
            if node.body:
                for stmt in node.body:
                    self.walk(stmt)
        elif isinstance(node, WhileClause):
            if node.cond:
                for stmt in node.cond:
                    self.walk(stmt)
            if node.body:
                for stmt in node.body:
                    self.walk(stmt)
        elif isinstance(node, AndCmd):
            if node.x:
                self.walk(node.x)
            if node.y:
                self.walk(node.y)
        elif isinstance(node, OrCmd):
            if node.x:
                self.walk(node.x)
            if node.y:
                self.walk(node.y)
        elif isinstance(node, CaseClause):
            if node.expr:
                self.walk(node.expr)
            for branch in node.branches:
                for pattern in branch["patterns"]:
                    self.walk(pattern)
                for stmt in branch["body"]:
                    self.walk(stmt)
            if node.default:
                for stmt in node.default:
                    self.walk(stmt)


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
        # Handle Assigns (variable assignments)
        if node.extra and "assigns" in node.extra:
            for assign in node.extra["assigns"]:
                val = assign.get("value", assign.get("Value", {}))
                parts = val.get("parts", val.get("Parts", []))
                for p in parts:
                    if isinstance(p, dict):
                        _find_commands(part_from_json(p), commands)
                    else:
                        _find_commands(p, commands)
    elif isinstance(node, Part) and node.type == "CmdSubst":
        # Descend into command substitution
        if node.parts:
            for p in node.parts:
                _find_commands(p, commands)
    elif isinstance(node, Part):
        # Recurse into nested parts
        if node.parts:
            for p in node.parts:
                _find_commands(p, commands)
    elif hasattr(node, 'assigns') and node.assigns:
        # Handle CallExpr with Assigns
        for assign in node.assigns:
            if hasattr(assign, 'value') and assign.value:
                for part in assign.value:
                    _find_commands(part, commands)
    elif isinstance(node, BinaryCmd):
        _find_commands(node.x, commands)
        _find_commands(node.y, commands)
    elif isinstance(node, File):
        for stmt in node.stmts:
            _find_commands(stmt.cmd, commands)
    elif isinstance(node, Stmt):
        _find_commands(node.cmd, commands)
    elif isinstance(node, Subshell):
        for stmt in node.stmts:
            _find_commands(stmt.cmd, commands)
    elif isinstance(node, IfClause):
        for stmt in node.cond:
            _find_commands(stmt.cmd, commands)
        for stmt in node.then:
            _find_commands(stmt.cmd, commands)
        for branch in node.elif_branches:
            for stmt in branch["cond"]:
                _find_commands(stmt.cmd, commands)
            for stmt in branch["body"]:
                _find_commands(stmt.cmd, commands)
        for stmt in node.else_branch:
            _find_commands(stmt.cmd, commands)
    elif isinstance(node, ForClause):
        for stmt in node.body:
            _find_commands(stmt.cmd, commands)
    elif isinstance(node, WhileClause):
        for stmt in node.cond:
            _find_commands(stmt.cmd, commands)
        for stmt in node.body:
            _find_commands(stmt.cmd, commands)
    elif isinstance(node, AndCmd):
        _find_commands(node.x, commands)
        _find_commands(node.y, commands)
    elif isinstance(node, OrCmd):
        _find_commands(node.x, commands)
        _find_commands(node.y, commands)
    elif isinstance(node, CaseClause):
        for branch in node.branches:
            for stmt in branch["body"]:
                _find_commands(stmt.cmd, commands)
        for stmt in node.default:
            _find_commands(stmt.cmd, commands)


def _collect_commands(node: Node, commands: List[str]):
    """Recursively collect command names."""
    if isinstance(node, CallExpr):
        # First arg is the command name
        if node.args:
            cmd_name = _word_value(node.args[0])
            if cmd_name:
                commands.append(cmd_name)
        # Handle Assigns (variable assignments)
        if node.extra and "assigns" in node.extra:
            for assign in node.extra["assigns"]:
                val = assign.get("value", assign.get("Value", {}))
                parts = val.get("parts", val.get("Parts", []))
                for p in parts:
                    if isinstance(p, dict):
                        _collect_commands(part_from_json(p), commands)
                    else:
                        _collect_commands(p, commands)
    elif isinstance(node, Part) and node.type == "CmdSubst":
        # Descend into command substitution to find nested commands
        if node.extra:
            for stmt in node.extra:
                cmd = stmt.get("Cmd")
                if cmd:
                    _collect_commands(node_from_json(cmd), commands)
    elif isinstance(node, Part):
        # Recurse into nested parts (CmdSubst can be nested)
        if node.parts:
            for p in node.parts:
                _collect_commands(p, commands)
    elif hasattr(node, 'assigns') and node.assigns:
        # Handle CallExpr with Assigns (variable assignments)
        for assign in node.assigns:
            if hasattr(assign, 'value') and assign.value:
                for part in assign.value:
                    _collect_commands(part, commands)
    elif isinstance(node, BinaryCmd):
        _collect_commands(node.x, commands)
        _collect_commands(node.y, commands)
    elif isinstance(node, File):
        for stmt in node.stmts:
            _collect_commands(stmt.cmd, commands)
    elif isinstance(node, Stmt):
        _collect_commands(node.cmd, commands)
    elif isinstance(node, Subshell):
        for stmt in node.stmts:
            _collect_commands(stmt.cmd, commands)
    elif isinstance(node, IfClause):
        for stmt in node.cond:
            _collect_commands(stmt.cmd, commands)
        for stmt in node.then:
            _collect_commands(stmt.cmd, commands)
        for branch in node.elif_branches:
            for stmt in branch["cond"]:
                _collect_commands(stmt.cmd, commands)
            for stmt in branch["body"]:
                _collect_commands(stmt.cmd, commands)
        for stmt in node.else_branch:
            _collect_commands(stmt.cmd, commands)
    elif isinstance(node, ForClause):
        for stmt in node.body:
            _collect_commands(stmt.cmd, commands)
    elif isinstance(node, WhileClause):
        for stmt in node.cond:
            _collect_commands(stmt.cmd, commands)
        for stmt in node.body:
            _collect_commands(stmt.cmd, commands)
    elif isinstance(node, AndCmd):
        _collect_commands(node.x, commands)
        _collect_commands(node.y, commands)
    elif isinstance(node, OrCmd):
        _collect_commands(node.x, commands)
        _collect_commands(node.y, commands)
    elif isinstance(node, CaseClause):
        for branch in node.branches:
            for stmt in branch["body"]:
                _collect_commands(stmt.cmd, commands)
        for stmt in node.default:
            _collect_commands(stmt.cmd, commands)


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
    elif isinstance(node, Subshell):
        return any(_has_variable_recursive(s.cmd) for s in node.stmts)
    elif isinstance(node, IfClause):
        if any(_has_variable_recursive(s.cmd) for s in node.cond):
            return True
        if any(_has_variable_recursive(s.cmd) for s in node.then):
            return True
        for branch in node.elif_branches:
            if any(_has_variable_recursive(s.cmd) for s in branch["cond"]):
                return True
            if any(_has_variable_recursive(s.cmd) for s in branch["body"]):
                return True
        return any(_has_variable_recursive(s.cmd) for s in node.else_branch)
    elif isinstance(node, ForClause):
        if node.var and _has_variable_recursive(node.var):
            return True
        if any(_has_variable_recursive(w) for w in node.words):
            return True
        return any(_has_variable_recursive(s.cmd) for s in node.body)
    elif isinstance(node, WhileClause):
        if any(_has_variable_recursive(s.cmd) for s in node.cond):
            return True
        return any(_has_variable_recursive(s.cmd) for s in node.body)
    elif isinstance(node, AndCmd):
        return _has_variable_recursive(node.x) or _has_variable_recursive(node.y)
    elif isinstance(node, OrCmd):
        return _has_variable_recursive(node.x) or _has_variable_recursive(node.y)
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
    elif isinstance(node, Subshell):
        for stmt in node.stmts:
            _collect_redirections(stmt, redirs)
    elif isinstance(node, IfClause):
        for stmt in node.cond:
            _collect_redirections(stmt, redirs)
        for stmt in node.then:
            _collect_redirections(stmt, redirs)
        for branch in node.elif_branches:
            for stmt in branch["cond"]:
                _collect_redirections(stmt, redirs)
            for stmt in branch["body"]:
                _collect_redirections(stmt, redirs)
        for stmt in node.else_branch:
            _collect_redirections(stmt, redirs)
    elif isinstance(node, ForClause):
        for stmt in node.body:
            _collect_redirections(stmt, redirs)
    elif isinstance(node, WhileClause):
        for stmt in node.cond:
            _collect_redirections(stmt, redirs)
        for stmt in node.body:
            _collect_redirections(stmt, redirs)
    elif isinstance(node, AndCmd):
        _collect_redirections(node.x, redirs)
        _collect_redirections(node.y, redirs)
    elif isinstance(node, OrCmd):
        _collect_redirections(node.x, redirs)
        _collect_redirections(node.y, redirs)
    elif isinstance(node, CaseClause):
        for branch in node.branches:
            for stmt in branch["body"]:
                _collect_redirections(stmt, redirs)
        for stmt in node.default:
            _collect_redirections(stmt, redirs)
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
    elif isinstance(node, Subshell):
        for stmt in node.stmts:
            _collect_arguments(stmt.cmd, args_list)
    elif isinstance(node, IfClause):
        for stmt in node.cond:
            _collect_arguments(stmt.cmd, args_list)
        for stmt in node.then:
            _collect_arguments(stmt.cmd, args_list)
        for branch in node.elif_branches:
            for stmt in branch["cond"]:
                _collect_arguments(stmt.cmd, args_list)
            for stmt in branch["body"]:
                _collect_arguments(stmt.cmd, args_list)
        for stmt in node.else_branch:
            _collect_arguments(stmt.cmd, args_list)
    elif isinstance(node, ForClause):
        for stmt in node.body:
            _collect_arguments(stmt.cmd, args_list)
    elif isinstance(node, WhileClause):
        for stmt in node.cond:
            _collect_arguments(stmt.cmd, args_list)
        for stmt in node.body:
            _collect_arguments(stmt.cmd, args_list)
    elif isinstance(node, AndCmd):
        _collect_arguments(node.x, args_list)
        _collect_arguments(node.y, args_list)
    elif isinstance(node, OrCmd):
        _collect_arguments(node.x, args_list)
        _collect_arguments(node.y, args_list)
    elif isinstance(node, CaseClause):
        for branch in node.branches:
            for stmt in branch["body"]:
                _collect_arguments(stmt.cmd, args_list)
        for stmt in node.default:
            _collect_arguments(stmt.cmd, args_list)


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
    elif isinstance(node, Subshell):
        for stmt in node.stmts:
            _find_arguments(stmt.cmd, args_list)
    elif isinstance(node, IfClause):
        for stmt in node.cond:
            _find_arguments(stmt.cmd, args_list)
        for stmt in node.then:
            _find_arguments(stmt.cmd, args_list)
        for branch in node.elif_branches:
            for stmt in branch["cond"]:
                _find_arguments(stmt.cmd, args_list)
            for stmt in branch["body"]:
                _find_arguments(stmt.cmd, args_list)
        for stmt in node.else_branch:
            _find_arguments(stmt.cmd, args_list)
    elif isinstance(node, ForClause):
        for stmt in node.body:
            _find_arguments(stmt.cmd, args_list)
    elif isinstance(node, WhileClause):
        for stmt in node.cond:
            _find_arguments(stmt.cmd, args_list)
        for stmt in node.body:
            _find_arguments(stmt.cmd, args_list)
    elif isinstance(node, AndCmd):
        _find_arguments(node.x, args_list)
        _find_arguments(node.y, args_list)
    elif isinstance(node, OrCmd):
        _find_arguments(node.x, args_list)
        _find_arguments(node.y, args_list)
    elif isinstance(node, CaseClause):
        for branch in node.branches:
            for stmt in branch["body"]:
                _find_arguments(stmt.cmd, args_list)
        for stmt in node.default:
            _find_arguments(stmt.cmd, args_list)


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
    elif isinstance(node, CallExpr):
        return False
    elif isinstance(node, Subshell):
        return any(_has_pipe_recursive(s.cmd) for s in node.stmts)
    elif isinstance(node, IfClause):
        if any(_has_pipe_recursive(s.cmd) for s in node.cond):
            return True
        if any(_has_pipe_recursive(s.cmd) for s in node.then):
            return True
        for branch in node.elif_branches:
            if any(_has_pipe_recursive(s.cmd) for s in branch["cond"]):
                return True
            if any(_has_pipe_recursive(s.cmd) for s in branch["body"]):
                return True
        return any(_has_pipe_recursive(s.cmd) for s in node.else_branch)
    elif isinstance(node, ForClause):
        return any(_has_pipe_recursive(s.cmd) for s in node.body)
    elif isinstance(node, WhileClause):
        if any(_has_pipe_recursive(s.cmd) for s in node.cond):
            return True
        return any(_has_pipe_recursive(s.cmd) for s in node.body)
    elif isinstance(node, AndCmd):
        return _has_pipe_recursive(node.x) or _has_pipe_recursive(node.y)
    elif isinstance(node, OrCmd):
        return _has_pipe_recursive(node.x) or _has_pipe_recursive(node.y)
    elif isinstance(node, CaseClause):
        for branch in node.branches:
            if any(_has_pipe_recursive(s.cmd) for s in branch["body"]):
                return True
        return any(_has_pipe_recursive(s.cmd) for s in node.default)
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
    # Subshell
    elif isinstance(node, Subshell):
        for stmt in node.stmts:
            _collect_target_files(stmt, targets)
    # IfClause
    elif isinstance(node, IfClause):
        for stmt in node.cond:
            _collect_target_files(stmt, targets)
        for stmt in node.then:
            _collect_target_files(stmt, targets)
        for branch in node.elif_branches:
            for stmt in branch["cond"]:
                _collect_target_files(stmt, targets)
            for stmt in branch["body"]:
                _collect_target_files(stmt, targets)
        for stmt in node.else_branch:
            _collect_target_files(stmt, targets)
    # ForClause
    elif isinstance(node, ForClause):
        for stmt in node.body:
            _collect_target_files(stmt, targets)
    # WhileClause
    elif isinstance(node, WhileClause):
        for stmt in node.cond:
            _collect_target_files(stmt, targets)
        for stmt in node.body:
            _collect_target_files(stmt, targets)
    # AndCmd
    elif isinstance(node, AndCmd):
        _collect_target_files(node.x, targets)
        _collect_target_files(node.y, targets)
    # OrCmd
    elif isinstance(node, OrCmd):
        _collect_target_files(node.x, targets)
        _collect_target_files(node.y, targets)
    # CaseClause
    elif isinstance(node, CaseClause):
        for branch in node.branches:
            for stmt in branch["body"]:
                _collect_target_files(stmt, targets)
        for stmt in node.default:
            _collect_target_files(stmt, targets)
    # CallExpr: check for args that might be files? No, stick to redirections only
