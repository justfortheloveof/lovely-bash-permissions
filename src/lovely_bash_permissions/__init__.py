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
    get_commands(tree)  # Returns list of command names: ['ls', 'grep']
"""

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
from .converter import NODE_TYPES, parse_ast
from .inspect import (
    Visitor,
    find_arguments,
    find_commands,
    get_arguments,
    get_commands,
    get_redirections,
    get_target_files,
    has_pipe,
    has_variable,
)
from .parser import ParseError, parse

__version__ = "0.1.0"

__all__ = [
    # Parser
    "parse",
    "parse_ast",
    "ParseError",
    # AST nodes
    "Node",
    "Position",
    "Word",
    "CallExpr",
    "BinaryCmd",
    "Stmt",
    "File",
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
    "FuncDecl",
    "Redir",
    "Subshell",
    "IfClause",
    "ForClause",
    "WhileClause",
    "AndCmd",
    "OrCmd",
    "CaseClause",
    "TestClause",
    "UnaryTest",
    "BinaryTest",
    "ParenTest",
    "ArithmCmd",
    "UnaryArithm",
    "ParenArithm",
    "FlagsArithm",
    "LetClause",
    "TimeClause",
    "CoprocClause",
    "TestDecl",
    "Comment",
    "Assign",
    "CaseItem",
    "WordIter",
    "CStyleLoop",
    "ArrayExpr",
    "ArrayElem",
    "BraceExp",
    "DeclClause",
    "ElifBranch",
    "CaseBranch",
    # Registry
    "NODE_TYPES",
    # Inspection
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
