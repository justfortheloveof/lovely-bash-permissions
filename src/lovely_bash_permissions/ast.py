"""
AST node types for bash commands.

This module defines the typed AST representation for parsed bash commands,
based on shfmt's JSON node types. Each shfmt node type maps to a Python
dataclass with appropriate fields.

Node types:
    - File: Top-level container with statements
    - Stmt: Individual statement with optional redirections
    - CallExpr: Command invocation (e.g., "ls -la")
    - BinaryCmd: Pipe operations (cmd1 | cmd2)
    - Word: A word composed of parts
    - Redir: Redirection (file > output.txt)
    - Subshell: Parenthesized command group
    - IfClause, ForClause, WhileClause: Control flow
    - AndCmd, OrCmd: Logical operators (&&, ||)
    - CaseClause: Case/switch statements
    - DeclClause: Declaration builtins (export, local, readonly, etc.)
    - ElifBranch, CaseBranch: Typed branch structures

JSON node types not explicitly mapped are stored in generic Node objects.
"""

from __future__ import annotations

from dataclasses import dataclass, field


def _node_repr(obj: object, depth: int = 1) -> str:
    """Depth-limited repr for AST nodes.

    Shows field names and values up to *depth* levels deep. Beyond that,
    nested nodes are shown as ``<Type ...>``.
    """
    if depth <= 0:
        type_val = getattr(obj, "type", obj.__class__.__name__)
        return f"<{type_val} ...>"
    cls = type(obj)
    fields = getattr(cls, "__dataclass_fields__", {})
    parts: list[str] = []
    for name in fields:
        val = getattr(obj, name, None)
        if val is None or val == "" or val == []:
            continue
        if isinstance(val, list):
            items = ", ".join(
                _node_repr(v, depth - 1)
                if hasattr(v, "__dataclass_fields__")
                else repr(v)
                for v in val
            )
            parts.append(f"{name}=[{items}]")
        elif hasattr(val, "__dataclass_fields__"):
            parts.append(f"{name}={_node_repr(val, depth - 1)}")
        else:
            parts.append(f"{name}={val!r}")
    return f"{cls.__name__}({', '.join(parts)})"


@dataclass(slots=True)
class Position:
    """Source position information for AST nodes."""

    offset: int = 0
    line: int = 0
    col: int = 0


@dataclass(slots=True, repr=False)
class Node:
    """Base AST node for all bash syntax elements.

    Every node in the AST inherits from this base class. Unknown or
    unmapped shfmt node types are represented as Node objects with
    their original type name preserved in the ``type`` field.

    Attributes:
        type: shfmt node type name (e.g., "File", "CallExpr", "Word")
        pos: Starting source position
        end: Ending source position
        extra: Additional context or metadata (parser-specific)
    """

    type: str = ""
    pos: Position | None = None
    end: Position | None = None
    extra: dict | None = None

    def __repr__(self) -> str:
        return _node_repr(self)


@dataclass(slots=True, repr=False)
class Word(Node):
    """A bash word composed of parts.

    Words are the basic unit of bash syntax — simple literals,
    variable expansions, command substitutions, or complex combinations.

    Attributes:
        parts: List of Node objects that make up this word
    """

    parts: list[Node] = field(default_factory=list)


@dataclass(slots=True, repr=False)
class Lit(Node):
    """A shell literal string without any special characters.

    Represents a plain, unquoted bash word. Examples: ``hello``, ``file.txt``,
    ``ls``, ``42``.

    Attributes:
        value: The literal string value
        value_pos: Source position of the value's start
        value_end: Source position of the value's end
    """

    type: str = "Lit"
    value: str = ""
    value_pos: Position | None = None
    value_end: Position | None = None


@dataclass(slots=True, repr=False)
class ParamExp(Node):
    """A shell parameter expansion ($VAR, ${VAR}, ${VAR:-default}, etc.).

    Attributes:
        param: The parameter name (e.g., "HOME", "@", "0")
        short: True for $VAR form, False for ${VAR} form
        exp: Expansion expression dict with Op/Word fields
        index: Array index Word node (for ${arr[0]})
        length: True for ${#VAR} length expansion
        dollar_pos: Position of the $ character
    """

    type: str = "ParamExp"
    param: str = ""
    short: bool = False
    exp: dict | None = None
    index: Word | None = None
    length: bool = False
    dollar_pos: Position | None = None


@dataclass(slots=True, repr=False)
class SglQuoted(Node):
    """A single-quoted shell string.

    Content is taken literally — no variable expansion or special character
    interpretation.

    Attributes:
        value: The string content without the surrounding quotes
    """

    type: str = "SglQuoted"
    value: str = ""


@dataclass(slots=True, repr=False)
class DblQuoted(Node):
    """A double-quoted shell string with nested parts.

    Allows variable expansion, command substitution, and escape sequences,
    but protects words from splitting and globbing.

    Attributes:
        parts: List of Node objects that make up the quoted content
        value: Computed string value (concatenation of part values)
    """

    type: str = "DblQuoted"
    parts: list[Node] = field(default_factory=list)
    value: str | None = None


@dataclass(slots=True, repr=False)
class CmdSubst(Node):
    """A command substitution ($(...) or backticks).

    Attributes:
        stmts: List of Stmt objects representing commands in the substitution
        backquotes: True if backtick syntax, False for $(...)
    """

    type: str = "CmdSubst"
    stmts: list[Stmt] = field(default_factory=list)
    backquotes: bool = False


@dataclass(slots=True, repr=False)
class ProcSubst(Node):
    """A process substitution (<(cmd) or >(cmd)).

    Attributes:
        op: The operator string ("<(" or ">(")
        op_pos: Position of the opening operator
        rparen: Position of the closing parenthesis
        stmts: List of Stmt objects representing commands to execute
    """

    type: str = "ProcSubst"
    op: str = ""
    op_pos: Position | None = None
    rparen: Position | None = None
    stmts: list[Stmt] = field(default_factory=list)


@dataclass(slots=True, repr=False)
class ArithmExp(Node):
    """An arithmetic expansion ($((...)))

    Attributes:
        x: The inner arithmetic expression
    """

    type: str = "ArithmExp"
    x: Node | None = None


@dataclass(slots=True, repr=False)
class BraceExp(Node):
    """Brace expansion: {a,b} or {1..10}.

    Attributes:
        sequence: True for {1..10} style, False for {a,b}
        elems: List of Word nodes representing expansion elements
    """

    type: str = "BraceExp"
    sequence: bool = False
    elems: list[Word] = field(default_factory=list)


@dataclass(slots=True, repr=False)
class ExtGlob(Node):
    """Extended glob pattern (@(pat|pat), +(pat|pat), etc.).

    Attributes:
        op: Extended glob operator string ("@(", "+(", "*(", "?(", "!(")
        op_pos: Source position of the operator character
        pattern: Pattern specification as a Lit node
    """

    type: str = "ExtGlob"
    op: str = ""
    op_pos: Position | None = None
    pattern: Lit | None = None


@dataclass(slots=True, repr=False)
class BinaryArithm(Node):
    """A binary arithmetic operation within an arithmetic expression.

    Attributes:
        op: The operator string (+, -, *, /, %, ==, etc.)
        op_pos: Position of the operator character
        left: Left operand
        right: Right operand
    """

    type: str = "BinaryArithm"
    op: str = ""
    op_pos: Position | None = None
    left: Node | None = None
    right: Node | None = None


@dataclass(slots=True, repr=False)
class CallExpr(Node):
    """A command invocation with its arguments.

    The first argument in the args list is the command name.

    Attributes:
        args: List of Word objects — first is the command name, rest are arguments
        assigns: Variable assignments before the command (e.g., "x=1 ls")
    """

    type: str = "CallExpr"
    args: list[Word] = field(default_factory=list)
    assigns: list[Assign] | None = None


@dataclass(slots=True, repr=False)
class Block(Node):
    """A block of statements enclosed in curly braces.

    Commands run in the current shell environment (unlike subshells).

    Attributes:
        left_pos: Position of the opening brace
        right_pos: Position of the closing brace
        stmts: List of Stmt objects representing commands in the block
    """

    type: str = "Block"
    left_pos: Position | None = None
    right_pos: Position | None = None
    stmts: list[Stmt] = field(default_factory=list)


@dataclass(slots=True, repr=False)
class FuncDecl(Node):
    """A bash function declaration.

    Attributes:
        rsrv_word: True if the ``function`` keyword was used
        parens: True if the function uses () syntax
        name: Lit node containing the function name
        body: Block node containing the function body statements
    """

    type: str = "FuncDecl"
    rsrv_word: bool = False
    parens: bool = False
    name: Lit | None = None
    body: Node | None = None


@dataclass(slots=True, repr=False)
class BinaryCmd(Node):
    """A binary command operation (primarily pipes).

    Attributes:
        op: Operator symbol ("|" for pipe, "&&", "||", etc.)
        left: Left operand (a command or nested expression)
        right: Right operand (a command or nested expression)
        redirs: Redirections applied at the pipe level
    """

    type: str = "BinaryCmd"
    op: str = ""
    left: Node | None = None
    right: Node | None = None
    redirs: list[Redir] = field(default_factory=list)


@dataclass(slots=True, repr=False)
class Subshell(Node):
    """A parenthesized command group (subshell).

    Attributes:
        stmts: List of Stmt objects executed within the subshell
    """

    type: str = "Subshell"
    stmts: list[Stmt] = field(default_factory=list)


@dataclass(slots=True)
class ElifBranch:
    """A typed elif branch in an IfClause.

    Attributes:
        cond: List of Stmt objects for the elif condition
        body: List of Stmt objects for the elif body
    """

    cond: list[Stmt]
    body: list[Stmt]

    def __getitem__(self, key: str) -> list[Stmt]:
        """Dict-like access for backwards compatibility."""
        if key == "cond":
            return self.cond
        if key == "body":
            return self.body
        raise KeyError(key)


@dataclass(slots=True, repr=False)
class IfClause(Node):
    """An if/elif/else conditional statement.

    Attributes:
        cond_stmts: List of Stmt objects for the if condition
        then_stmts: List of Stmt objects for the true branch
        elif_branches: List of ElifBranch objects
        else_stmts: List of Stmt objects for the else branch
    """

    cond_stmts: list[Stmt] = field(default_factory=list)
    then_stmts: list[Stmt] = field(default_factory=list)
    elif_branches: list[ElifBranch] = field(default_factory=list)
    else_stmts: list[Stmt] = field(default_factory=list)


@dataclass(slots=True, repr=False)
class ForClause(Node):
    """A for loop statement.

    Attributes:
        var: The loop variable name as a string
        words: List of Word objects to iterate over
        body: List of Stmt objects executed in each iteration
    """

    var: str | None = None
    words: list[Word] = field(default_factory=list)
    body: list[Stmt] = field(default_factory=list)


@dataclass(slots=True, repr=False)
class WhileClause(Node):
    """A while loop statement.

    Attributes:
        cond_stmts: List of Stmt objects evaluated as the loop condition
        body: List of Stmt objects executed in each iteration
    """

    cond_stmts: list[Stmt] = field(default_factory=list)
    body: list[Stmt] = field(default_factory=list)


@dataclass(slots=True, repr=False)
class AndCmd(Node):
    """Logical AND operator (&&).

    Attributes:
        left: Left operand (command or expression)
        right: Right operand (command or expression)
    """

    left: Node | None = None
    right: Node | None = None


@dataclass(slots=True, repr=False)
class OrCmd(Node):
    """Logical OR operator (||).

    Attributes:
        left: Left operand (command or expression)
        right: Right operand (command or expression)
    """

    left: Node | None = None
    right: Node | None = None


@dataclass(slots=True)
class CaseBranch:
    """A typed case branch in a CaseClause.

    Attributes:
        patterns: List of Word nodes for the patterns
        body: List of Stmt objects for the branch body
    """

    patterns: list[Word]
    body: list[Stmt]

    def __getitem__(self, key: str) -> list:
        """Dict-like access for backwards compatibility."""
        if key == "patterns":
            return self.patterns
        if key == "body":
            return self.body
        raise KeyError(key)


@dataclass(slots=True, repr=False)
class CaseClause(Node):
    """A case/switch statement.

    Attributes:
        expr: Word expression to evaluate for matching
        branches: List of CaseBranch objects
        default: List of Stmt objects for the default (*) branch
    """

    expr: Word | None = None
    branches: list[CaseBranch] = field(default_factory=list)
    default: list[Stmt] = field(default_factory=list)


@dataclass(slots=True, repr=False)
class Redir(Node):
    """A file redirection operation.

    Attributes:
        op: Redirection operator string (e.g., ">", ">>", "<", "2>")
        word: Word specifying the file target
        op_pos: Source position of the redirection operator itself
    """

    op: str = ""
    word: Word | None = None
    op_pos: Position | None = None


@dataclass(slots=True, repr=False)
class TestClause(Node):
    """Extended test: [[ condition ]].

    Attributes:
        left_pos: Position of the opening [[
        right_pos: Position of the closing ]]
        body: The test expression node
    """

    type: str = "TestClause"
    left_pos: Position | None = None
    right_pos: Position | None = None
    body: Node | None = None


@dataclass(slots=True, repr=False)
class UnaryTest(Node):
    """Unary test: -f file, -z str, etc.

    Attributes:
        op: The operator string ("-f", "-d", "-r", etc.)
        op_pos: Position of the operator
        x: The test operand
    """

    type: str = "UnaryTest"
    op: str = ""
    op_pos: Position | None = None
    x: Node | None = None


@dataclass(slots=True, repr=False)
class BinaryTest(Node):
    """Binary test: a -eq b, a == b, a && b, etc.

    Attributes:
        op: The operator string
        op_pos: Position of the operator
        left: Left operand
        right: Right operand
    """

    type: str = "BinaryTest"
    op: str = ""
    op_pos: Position | None = None
    left: Node | None = None
    right: Node | None = None


@dataclass(slots=True, repr=False)
class ParenTest(Node):
    """Parenthesized test: ( expr ).

    Attributes:
        left_pos: Position of the opening parenthesis
        right_pos: Position of the closing parenthesis
        body: The inner test expression
    """

    type: str = "ParenTest"
    left_pos: Position | None = None
    right_pos: Position | None = None
    body: Node | None = None


@dataclass(slots=True, repr=False)
class ArithmCmd(Node):
    """Arithmetic command: (( expr ))."""

    type: str = "ArithmCmd"
    left_pos: Position | None = None
    right_pos: Position | None = None
    body: Node | None = None


@dataclass(slots=True, repr=False)
class UnaryArithm(Node):
    """Unary arithmetic: -x, !x, x++, x--."""

    type: str = "UnaryArithm"
    op: str = ""
    op_pos: Position | None = None
    post: bool = False
    x: Node | None = None


@dataclass(slots=True, repr=False)
class ParenArithm(Node):
    """Parenthesized arithmetic: (expr)."""

    type: str = "ParenArithm"
    left_pos: Position | None = None
    right_pos: Position | None = None
    body: Node | None = None


@dataclass(slots=True, repr=False)
class FlagsArithm(Node):
    """Zsh subscript flags: ${array[(flags)expr]}."""

    type: str = "FlagsArithm"
    flags: Lit | None = None
    x: Node | None = None


@dataclass(slots=True, repr=False)
class LetClause(Node):
    """Let statement: let expr."""

    type: str = "LetClause"
    let_pos: Position | None = None
    exprs: list[Node] = field(default_factory=list)


@dataclass(slots=True, repr=False)
class TimeClause(Node):
    """Time-prefixed command: time cmd."""

    type: str = "TimeClause"
    time_pos: Position | None = None
    posix_format: bool = False
    stmt: Node | None = None


@dataclass(slots=True, repr=False)
class CoprocClause(Node):
    """Coprocess: coproc NAME { cmd }."""

    type: str = "CoprocClause"
    coproc_pos: Position | None = None
    name: Word | None = None
    stmt: Node | None = None


@dataclass(slots=True, repr=False)
class TestDecl(Node):
    """Bats test: @test "description" { body }."""

    type: str = "TestDecl"
    description: Word | None = None
    body: Node | None = None


@dataclass(slots=True, repr=False)
class Comment(Node):
    """Shell comment: # text."""

    type: str = "Comment"
    hash_pos: Position | None = None
    text: str = ""


@dataclass(slots=True, repr=False)
class Assign(Node):
    """Variable assignment: var=val, arr[i]=val, var+=val."""

    type: str = "Assign"
    name: Lit | None = None
    index: Node | None = None
    value: Word | None = None
    array: Node | None = None
    append: bool = False
    naked: bool = False


@dataclass(slots=True, repr=False)
class CaseItem(Node):
    """Case statement branch: patterns) stmts;;"""

    type: str = "CaseItem"
    op: str = ""
    patterns: list[Word] = field(default_factory=list)
    stmts: list[Node] = field(default_factory=list)


@dataclass(slots=True, repr=False)
class WordIter(Node):
    """For-loop word iteration: for var in words."""

    type: str = "WordIter"
    name: Lit | None = None
    items: list[Word] = field(default_factory=list)


@dataclass(slots=True, repr=False)
class CStyleLoop(Node):
    """C-style for loop: for (init; cond; post)."""

    type: str = "CStyleLoop"
    init: Node | None = None
    cond: Node | None = None
    post: Node | None = None


@dataclass(slots=True, repr=False)
class ArrayExpr(Node):
    """Array expression: ( elem1 elem2 )."""

    type: str = "ArrayExpr"
    elems: list[Node] = field(default_factory=list)


@dataclass(slots=True, repr=False)
class ArrayElem(Node):
    """Array element: index=value or just value."""

    type: str = "ArrayElem"
    index: Node | None = None
    value: Word | None = None


@dataclass(slots=True, repr=False)
class DeclClause(Node):
    """Declaration builtin (export, local, readonly, declare, typeset).

    Attributes:
        variant: The declaration command name (e.g., "export", "local")
        args: Declaration arguments as Word nodes
        assigns: Variable assignments in the declaration
    """

    type: str = "DeclClause"
    variant: str = ""
    args: list[Word] = field(default_factory=list)
    assigns: list[Assign] = field(default_factory=list)


@dataclass(slots=True, repr=False)
class Stmt(Node):
    """A bash statement.

    Wraps a command with its associated position and optional redirections.

    Attributes:
        cmd: The command node (CallExpr, BinaryCmd, Subshell, etc.)
        position: shfmt's position field (alternative to pos)
        redirs: List of Redir objects applied to this statement
    """

    cmd: Node | None = None
    position: Position | None = None
    redirs: list[Redir] = field(default_factory=list)


@dataclass(slots=True, repr=False)
class File(Node):
    """Top-level file node wrapping all statements.

    Attributes:
        stmts: List of Stmt objects representing all commands
    """

    stmts: list[Stmt] = field(default_factory=list)
