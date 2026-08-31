"""
lovely-bash-permissions: Bash command parser using shfmt-py.

Parse bash command strings into structured AST trees and inspect them
for commands, arguments, variables, pipes, redirections, and more.

The library uses shfmt-py's `--to-json` flag as its parsing backend,
converting shfmt's typed JSON output into Python dataclasses for
easy inspection and traversal.

Quick start:
    from lovely_bash_permissions import parse_ast, get_commands
    tree = parse_ast('ls -la | grep txt')
    print(get_commands(tree))  # ['ls', 'grep']

Exported symbols:
    Parser: parse, parse_ast, ParseError
    AST nodes: Node, Position, Word, CallExpr, BinaryCmd, Stmt, File,
              Part, Redir, Subshell, IfClause, ForClause, WhileClause,
              AndCmd, OrCmd, CaseClause
    Inspection: get_commands, get_arguments, has_variable,
               get_redirections, find_commands, find_arguments,
               has_pipe, get_target_files, Visitor
"""

from .parser import parse, ParseError
from .ast import parse_ast, Node, Position, Word, CallExpr, BinaryCmd, Stmt, File, Part, Lit, SglQuoted, ParamExp, DblQuoted, CmdSubst, ProcSubst, Redir, Subshell, IfClause, ForClause, WhileClause, AndCmd, OrCmd, CaseClause, ArithmExp, BinaryArithm, ExtGlob, Block
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
    "Lit",
    "SglQuoted",
    "ParamExp",
    "DblQuoted",
    "CmdSubst",
    "ProcSubst",
    "ArithmExp",
    "BinaryArithm",
    "ExtGlob",
    "Block",
    "Redir",
    "Subshell",
    "IfClause",
    "ForClause",
    "WhileClause",
    "AndCmd",
    "OrCmd",
    "CaseClause",
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
