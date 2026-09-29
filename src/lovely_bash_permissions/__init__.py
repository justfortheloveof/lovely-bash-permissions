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

from importlib.metadata import version as _metadata_version

from .ast import (
    ArithmCmd,
    ArithmExp,
    ArrayElem,
    ArrayExpr,
    Assign,
    BinaryArithm,
    BinaryCmd,
    BinaryTest,
    Block,
    CallExpr,
    CaseBranch,
    CaseClause,
    CmdSubst,
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
    ParamExp,
    ParamExpExp,
    ParamExpSlice,
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
    structurally_equal,
)
from .converter import parse_ast
from .errors import ShfmtError
from .inspect import (
    RedirectionInfo,
    find_arguments,
    find_commands,
    get_arguments,
    get_commands,
    get_redirections,
    get_target_files,
    has_pipe,
    has_variable,
    iter_children,
)
from .parser import ParseError, parse

__version__ = _metadata_version("lovely-bash-permissions")

__all__ = [
    # AST nodes
    "ArithmCmd",
    "ArithmExp",
    "ArrayElem",
    "ArrayExpr",
    "Assign",
    "BinaryArithm",
    "BinaryCmd",
    "BinaryTest",
    "Block",
    "CStyleLoop",
    "CallExpr",
    "CaseBranch",
    "CaseClause",
    "CmdSubst",
    "CoprocClause",
    "DblQuoted",
    "DeclClause",
    "ElifBranch",
    "ExtGlob",
    "File",
    "FlagsArithm",
    "ForClause",
    "FuncDecl",
    "IfClause",
    "LetClause",
    "Lit",
    "Node",
    "ParamExp",
    "ParamExpExp",
    "ParamExpSlice",
    "ParenArithm",
    "ParenTest",
    "ParseError",
    "Position",
    "ProcSubst",
    "Redir",
    "RedirectionInfo",
    "SglQuoted",
    "ShfmtError",
    "Stmt",
    "Subshell",
    "TestClause",
    "TestDecl",
    "TimeClause",
    "UnaryArithm",
    "UnaryTest",
    "WhileClause",
    "Word",
    # Inspection
    "find_arguments",
    "find_commands",
    "get_arguments",
    "get_commands",
    "get_redirections",
    "get_target_files",
    "has_pipe",
    "has_variable",
    "iter_children",
    # Parser
    "parse",
    "parse_ast",
    "structurally_equal",
]
