"""
lovely-bash-permissions: Bash command parser using shfmt-py.

Parse bash commands and inspect their AST structure.
"""

from .parser import parse, ParseError
from .ast import parse_ast, Node, Position, Word, CallExpr, BinaryCmd, Stmt, File, Part, Redir
from .inspect import get_commands, get_arguments, has_variable, get_redirections, find_commands, find_arguments, has_pipe, get_target_files, Visitor

__version__ = "0.1.0"

__all__ = [
    "parse",
    "parse_ast",
    "ParseError",
    "Node",
    "Position",
    "Word",
    "CallExpr",
    "BinaryCmd",
    "Stmt",
    "File",
    "Part",
    "Redir",
    "get_commands",
    "get_arguments",
    "has_variable",
    "get_redirections",
    "find_commands",
    "find_arguments",
    "has_pipe",
    "get_target_files",
    "Visitor",
]

def main() -> None:
    print("Hello from lovely-bash-permissions!")
