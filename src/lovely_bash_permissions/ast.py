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
    - Part: Atomic part of a word (literal, variable, expansion)
    - Redir: Redirection (file > output.txt)
    - Subshell: Parenthesized command group
    - IfClause, ForClause, WhileClause: Control flow
    - AndCmd, OrCmd: Logical operators (&&, ||)
    - CaseClause: Case/switch statements

JSON node types not explicitly mapped are stored in generic Node objects.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Position:
    """Source position information for AST nodes."""

    offset: int = 0
    line: int = 0
    col: int = 0


@dataclass
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
        args: Command arguments as a list of Word nodes
    """

    type: str = ""
    pos: Position | None = None
    end: Position | None = None
    extra: dict | None = None
    args: list[Word] | None = None


@dataclass
class Word(Node):
    """A bash word composed of parts.

    Words are the basic unit of bash syntax — simple literals,
    variable expansions, command substitutions, or complex combinations.

    Attributes:
        parts: List of Part objects that make up this word
    """

    parts: list[Part] = field(default_factory=list)


@dataclass
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


@dataclass
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


@dataclass
class SglQuoted(Node):
    """A single-quoted shell string.

    Content is taken literally — no variable expansion or special character
    interpretation.

    Attributes:
        value: The string content without the surrounding quotes
    """

    type: str = "SglQuoted"
    value: str = ""


@dataclass
class DblQuoted(Node):
    """A double-quoted shell string with nested parts.

    Allows variable expansion, command substitution, and escape sequences,
    but protects words from splitting and globbing.

    Attributes:
        parts: List of Part objects that make up the quoted content
    """

    type: str = "DblQuoted"
    parts: list[Part] | None = None


@dataclass
class CmdSubst(Node):
    """A command substitution ($(...) or backticks).

    Attributes:
        stmts: List of Stmt objects representing commands in the substitution
        backquotes: True if backtick syntax, False for $(...)
    """

    type: str = "CmdSubst"
    stmts: list[Stmt] = field(default_factory=list)
    backquotes: bool = False


@dataclass
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


@dataclass
class ArithmExp(Node):
    """An arithmetic expansion ($((...)))

    Attributes:
        x: The inner arithmetic expression
    """

    type: str = "ArithmExp"
    x: Node | None = None


@dataclass
class BraceExp(Node):
    """Brace expansion: {a,b} or {1..10}.

    Attributes:
        sequence: True for {1..10} style, False for {a,b}
        elems: List of Word nodes representing expansion elements
    """

    type: str = "BraceExp"
    sequence: bool = False
    elems: list[Word] = field(default_factory=list)


@dataclass
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


@dataclass
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


@dataclass
class Part:
    """An atomic part of a bash word.

    Represents a single syntactic element within a word. Parts can be
    literals, variable references, expansions, or nested parts.

    Attributes:
        type: shfmt part type name
        pos: Starting source position
        end: Ending source position
        value: Literal string value (for Lit and some other types)
        parts: Nested parts (for DblQuoted, SglQuoted, etc.)
        extra: Additional context (for CmdSubst, contains inner statements)
    """

    type: str = ""
    pos: Position | None = None
    end: Position | None = None
    value: str | None = None
    parts: list[Part] | None = None
    extra: dict | None = None


@dataclass
class CallExpr(Node):
    """A command invocation with its arguments.

    The first argument in the args list is the command name.

    Attributes:
        args: List of Word objects — first is the command name, rest are arguments
        assigns: Variable assignments before the command (e.g., "x=1 ls")
    """

    args: list[Word] = field(default_factory=list)
    assigns: list[Assign] | None = None


@dataclass
class Block(Node):
    """A block of statements enclosed in curly braces.

    Commands run in the current shell (unlike subshells).

    Attributes:
        left_pos: Position of the opening brace
        right_pos: Position of the closing brace
        stmts: List of Stmt objects representing commands in the block
    """

    type: str = "Block"
    left_pos: Position | None = None
    right_pos: Position | None = None
    stmts: list[Stmt] = field(default_factory=list)


@dataclass
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


@dataclass
class BinaryCmd(Node):
    """A binary command operation (primarily pipes).

    Attributes:
        op: Operator symbol ("|" for pipe, "&&", "||", etc.)
        left: Left operand (a command or nested expression)
        right: Right operand (a command or nested expression)
        redirs: Redirections applied at the pipe level
    """

    op: str = ""
    left: Node | None = None
    right: Node | None = None
    redirs: list[Redir] | None = None


@dataclass
class Subshell(Node):
    """A parenthesized command group (subshell).

    Attributes:
        stmts: List of Stmt objects executed within the subshell
    """

    stmts: list[Stmt] = field(default_factory=list)


@dataclass
class IfClause(Node):
    """An if/elif/else conditional statement.

    Attributes:
        cond_stmts: List of Stmt objects for the if condition
        then_stmts: List of Stmt objects for the true branch
        elif_branches: List of dicts with "cond" and "body" keys
        else_stmts: List of Stmt objects for the else branch
    """

    cond_stmts: list[Stmt] = field(default_factory=list)
    then_stmts: list[Stmt] = field(default_factory=list)
    elif_branches: list[dict] = field(default_factory=list)
    else_stmts: list[Stmt] = field(default_factory=list)


@dataclass
class ForClause(Node):
    """A for loop statement.

    Attributes:
        var: Word representing the loop variable name
        words: List of Word objects to iterate over
        body: List of Stmt objects executed in each iteration
    """

    var: Word | None = None
    words: list[Word] = field(default_factory=list)
    body: list[Stmt] = field(default_factory=list)


@dataclass
class WhileClause(Node):
    """A while loop statement.

    Attributes:
        cond_stmts: List of Stmt objects evaluated as the loop condition
        body: List of Stmt objects executed in each iteration
    """

    cond_stmts: list[Stmt] = field(default_factory=list)
    body: list[Stmt] = field(default_factory=list)


@dataclass
class AndCmd(Node):
    """Logical AND operator (&&).

    Attributes:
        left: Left operand (command or expression)
        right: Right operand (command or expression)
    """

    left: Node | None = None
    right: Node | None = None


@dataclass
class OrCmd(Node):
    """Logical OR operator (||).

    Attributes:
        left: Left operand (command or expression)
        right: Right operand (command or expression)
    """

    left: Node | None = None
    right: Node | None = None


@dataclass
class CaseClause(Node):
    """A case/switch statement.

    Attributes:
        expr: Word expression to evaluate for matching
        branches: List of dicts with "patterns" (Words) and "body" (Stmts)
        default: List of Stmt objects for the default (*) branch
    """

    expr: Word | None = None
    branches: list[dict] = field(default_factory=list)
    default: list[Stmt] = field(default_factory=list)


@dataclass
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


@dataclass
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


@dataclass
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


@dataclass
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


@dataclass
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


@dataclass
class ArithmCmd(Node):
    """Arithmetic command: (( expr ))."""

    type: str = "ArithmCmd"
    left_pos: Position | None = None
    right_pos: Position | None = None
    body: Node | None = None


@dataclass
class UnaryArithm(Node):
    """Unary arithmetic: -x, !x, x++, x--."""

    type: str = "UnaryArithm"
    op: str = ""
    op_pos: Position | None = None
    post: bool = False
    x: Node | None = None


@dataclass
class ParenArithm(Node):
    """Parenthesized arithmetic: (expr)."""

    type: str = "ParenArithm"
    left_pos: Position | None = None
    right_pos: Position | None = None
    body: Node | None = None


@dataclass
class FlagsArithm(Node):
    """Zsh subscript flags: ${array[(flags)expr]}."""

    type: str = "FlagsArithm"
    flags: Lit | None = None
    x: Node | None = None


@dataclass
class LetClause(Node):
    """Let statement: let expr."""

    type: str = "LetClause"
    let_pos: Position | None = None
    exprs: list[Node] = field(default_factory=list)


@dataclass
class TimeClause(Node):
    """Time-prefixed command: time cmd."""

    type: str = "TimeClause"
    time_pos: Position | None = None
    posix_format: bool = False
    stmt: Node | None = None


@dataclass
class CoprocClause(Node):
    """Coprocess: coproc NAME { cmd }."""

    type: str = "CoprocClause"
    coproc_pos: Position | None = None
    name: Word | None = None
    stmt: Node | None = None


@dataclass
class TestDecl(Node):
    """Bats test: @test "description" { body }."""

    type: str = "TestDecl"
    description: Word | None = None
    body: Node | None = None


@dataclass
class Comment(Node):
    """Shell comment: # text."""

    type: str = "Comment"
    hash_pos: Position | None = None
    text: str = ""


@dataclass
class Assign(Node):
    """Variable assignment: var=val, arr[i]=val, var+=val."""

    type: str = "Assign"
    name: Lit | None = None
    index: Node | None = None
    value: Word | None = None
    array: Node | None = None
    append: bool = False
    naked: bool = False


@dataclass
class CaseItem(Node):
    """Case statement branch: patterns) stmts;;"""

    type: str = "CaseItem"
    op: str = ""
    patterns: list[Word] = field(default_factory=list)
    stmts: list[Node] = field(default_factory=list)


@dataclass
class WordIter(Node):
    """For-loop word iteration: for var in words."""

    type: str = "WordIter"
    name: Lit | None = None
    items: list[Word] = field(default_factory=list)


@dataclass
class CStyleLoop(Node):
    """C-style for loop: for (init; cond; post)."""

    type: str = "CStyleLoop"
    init: Node | None = None
    cond: Node | None = None
    post: Node | None = None


@dataclass
class ArrayExpr(Node):
    """Array expression: ( elem1 elem2 )."""

    type: str = "ArrayExpr"
    elems: list[Node] = field(default_factory=list)


@dataclass
class ArrayElem(Node):
    """Array element: index=value or just value."""

    type: str = "ArrayElem"
    index: Node | None = None
    value: Word | None = None


@dataclass
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
    redirs: list[Redir] | None = None


@dataclass
class File(Node):
    """Top-level file node wrapping all statements.

    Attributes:
        stmts: List of Stmt objects representing all commands
    """

    stmts: list[Stmt] = field(default_factory=list)


# ---------------------------------------------------------------------------
# JSON → AST conversion
# ---------------------------------------------------------------------------


def _parse_position(data: dict | None) -> Position | None:
    """Parse source position data from shfmt JSON.

    Returns None when *data* is None (key absent in JSON).
    """
    if data is None:
        return None
    return Position(
        offset=data.get("Offset", 0),
        line=data.get("Line", 0),
        col=data.get("Col", 0),
    )


def _parse_pos_end(data: dict) -> tuple[Position | None, Position | None]:
    """Extract pos/end from a JSON dict."""
    return _parse_position(data.get("Pos")), _parse_position(data.get("End"))


def _parse_stmt_list(raw: list | None) -> list[Stmt]:
    """Convert a list of raw JSON statement dicts to typed Stmt objects.

    Filters entries that don't look like statements (no ``Cmd`` key).
    """
    if not raw:
        return []
    return [
        stmt_from_json(item) for item in raw if isinstance(item, dict) and "Cmd" in item
    ]


def _lit_from_json(data: dict) -> Lit:
    """Convert shfmt JSON to a Lit node."""
    pos, end = _parse_pos_end(data)
    return Lit(
        type="Lit",
        pos=pos,
        end=end,
        value=data.get("Value", ""),
        value_pos=_parse_position(data.get("ValuePos")),
        value_end=_parse_position(data.get("ValueEnd")),
    )


def _extglob_from_json(data: dict) -> ExtGlob:
    """Convert shfmt JSON to an ExtGlob node."""
    pos, end = _parse_pos_end(data)
    pattern_data = data.get("Pattern", {})
    return ExtGlob(
        type="ExtGlob",
        pos=pos,
        end=end,
        op=data.get("Op", ""),
        op_pos=_parse_position(data.get("OpPos")),
        pattern=_lit_from_json(pattern_data) if pattern_data else None,
    )


def _paramexp_from_json(data: dict) -> ParamExp:
    """Convert shfmt JSON to a ParamExp node."""
    pos, end = _parse_pos_end(data)
    param_data = data.get("Param", {})
    param_value = param_data.get("Value", "") if isinstance(param_data, dict) else ""
    index_data = data.get("Index")
    index_node = word_from_json(index_data) if isinstance(index_data, dict) else None
    exp_data = data.get("Exp")
    exp_value = exp_data if isinstance(exp_data, dict) else None
    return ParamExp(
        type="ParamExp",
        pos=pos,
        end=end,
        param=param_value,
        short=data.get("Short", False),
        exp=exp_value,
        index=index_node,
        length=data.get("Length", False),
        dollar_pos=_parse_position(data.get("Dollar")),
    )


def assign_from_json(data: dict) -> Assign:
    """Convert shfmt JSON assignment data to a typed Assign object."""
    name_data = data.get("Name", {})
    name_node = _lit_from_json(name_data) if isinstance(name_data, dict) else None

    index_data = data.get("Index")
    index_node = word_from_json(index_data) if isinstance(index_data, dict) else None

    value_data = data.get("Value")
    value_node = word_from_json(value_data) if isinstance(value_data, dict) else None

    array_data = data.get("Array")
    array_node = None
    if isinstance(array_data, dict):
        pos, end = _parse_pos_end(array_data)
        array_node = ArrayExpr(
            type="ArrayExpr",
            pos=pos,
            end=end,
            elems=[array_elem_from_json(e) for e in array_data.get("Elems", [])],
        )

    pos, end = _parse_pos_end(data)
    return Assign(
        type="Assign",
        pos=pos,
        end=end,
        name=name_node,
        index=index_node,
        value=value_node,
        array=array_node,
        append=data.get("Append", False),
        naked=data.get("Naked", False),
    )


def array_elem_from_json(data: dict) -> ArrayElem:
    """Convert shfmt JSON array element data to a typed ArrayElem object."""
    index_data = data.get("Index")
    index_node = word_from_json(index_data) if isinstance(index_data, dict) else None

    value_data = data.get("Value")
    value_node = word_from_json(value_data) if isinstance(value_data, dict) else None

    pos, end = _parse_pos_end(data)
    return ArrayElem(
        type="ArrayElem",
        pos=pos,
        end=end,
        index=index_node,
        value=value_node,
    )


def redir_from_json(data: dict) -> Redir:
    """Convert shfmt JSON redirection data to a typed Redir object."""
    pos, end = _parse_pos_end(data)
    return Redir(
        op=data.get("Op", ""),
        word=word_from_json(data.get("Word")),
        pos=pos,
        end=end,
        op_pos=_parse_position(data.get("OpPos")),
    )


def stmt_from_json(data: dict) -> Stmt:
    """Convert shfmt JSON statement data to a typed Stmt object."""
    cmd_json = data.get("Cmd")
    cmd = node_from_json(cmd_json)
    redirs = None
    if "Redirs" in data:
        redirs = [redir_from_json(r) for r in data.get("Redirs", [])]
    elif isinstance(cmd, BinaryCmd):
        y_json = cmd_json.get("Y") if isinstance(cmd_json, dict) else None
        if isinstance(y_json, dict) and "Redirs" in y_json:
            redirs = [redir_from_json(r) for r in y_json.get("Redirs", [])]
    pos, end = _parse_pos_end(data)
    return Stmt(
        cmd=cmd,
        position=_parse_position(data.get("Position")),
        pos=pos,
        end=end,
        redirs=redirs,
    )


def word_from_json(data: dict | None) -> Word | None:
    """Convert shfmt JSON word data to a typed Word object.

    Returns None when *data* is None (key absent in JSON).
    """
    if data is None:
        return None
    parts = [part_from_json(p) for p in data.get("Parts", [])]
    pos, end = _parse_pos_end(data)
    return Word(
        type="Word",
        pos=pos,
        end=end,
        parts=parts,
    )


def part_from_json(data: dict) -> Part | Node:
    """Convert shfmt JSON part data to a typed Part or Node object.

    Delegates to the same converters used by ``node_from_json`` for shared
    types (Lit, SglQuoted, CmdSubst, ProcSubst, ParamExp, ArithmExp, ExtGlob).
    """
    part_type = data.get("Type", "")

    if part_type == "Lit":
        return _lit_from_json(data)
    if part_type == "SglQuoted":
        pos, end = _parse_pos_end(data)
        return SglQuoted(
            type="SglQuoted", pos=pos, end=end, value=data.get("Value", "")
        )
    if part_type == "CmdSubst":
        pos, end = _parse_pos_end(data)
        return CmdSubst(
            type="CmdSubst",
            pos=pos,
            end=end,
            stmts=[stmt_from_json(s) for s in data.get("Stmts", [])],
            backquotes=data.get("Backquotes", False),
        )
    if part_type == "ProcSubst":
        pos, end = _parse_pos_end(data)
        return ProcSubst(
            type="ProcSubst",
            pos=pos,
            end=end,
            op=data.get("Op", ""),
            op_pos=_parse_position(data.get("OpPos")),
            rparen=_parse_position(data.get("Rparen")),
            stmts=[stmt_from_json(s) for s in data.get("Stmts", [])],
        )
    if part_type == "ParamExp":
        return _paramexp_from_json(data)
    if part_type == "ArithmExp":
        pos, end = _parse_pos_end(data)
        return ArithmExp(
            type="ArithmExp",
            pos=pos,
            end=end,
            x=node_from_json(data.get("X")),
        )
    if part_type == "ExtGlob":
        return _extglob_from_json(data)

    # DblQuoted and other generic part types
    parts = None
    if "Parts" in data:
        parts = [part_from_json(p) for p in data.get("Parts", [])]

    value = data.get("Value")
    if part_type == "DblQuoted" and parts:
        value = "".join(
            str(p.value) if hasattr(p, "value") and p.value is not None else ""
            for p in parts
        )

    pos, end = _parse_pos_end(data)
    return Part(
        type=part_type,
        pos=pos,
        end=end,
        value=value,
        parts=parts,
        extra=data.get("Stmts") if part_type == "CmdSubst" else None,
    )


def _parse_if_clause(data: dict) -> IfClause:
    """Parse an IfClause from shfmt JSON, handling nested elif/else structures."""
    cond_stmts = _parse_stmt_list(data.get("Cond", []))
    then_stmts = _parse_stmt_list(data.get("Then", []))

    elif_branches: list[dict] = []
    else_stmts: list[Stmt] = []

    # Process Elif array (if present)
    for b in data.get("Elif", []):
        if isinstance(b, dict):
            elif_branches.append(
                {
                    "cond": _parse_stmt_list(b.get("Cond", [])),
                    "body": _parse_stmt_list(b.get("Then", b.get("Body", []))),
                }
            )

    # Process Else field
    else_raw = data.get("Else")
    if isinstance(else_raw, dict):
        if "Cond" in else_raw:
            # elif represented as nested structure
            _collect_elif_chain(else_raw, elif_branches, else_stmts)
        else:
            else_stmts = _parse_stmt_list(else_raw.get("Then", []))
    elif isinstance(else_raw, list):
        else_stmts = _parse_stmt_list(else_raw)

    pos, end = _parse_pos_end(data)
    return IfClause(
        type="IfClause",
        pos=pos,
        end=end,
        cond_stmts=cond_stmts,
        then_stmts=then_stmts,
        elif_branches=elif_branches,
        else_stmts=else_stmts,
    )


def _collect_elif_chain(
    data: dict,
    elif_branches: list[dict],
    else_stmts: list[Stmt],
) -> None:
    """Recursively collect elif branches from nested shfmt Else structures."""
    elif_branches.append(
        {
            "cond": _parse_stmt_list(data.get("Cond", [])),
            "body": _parse_stmt_list(data.get("Then", [])),
        }
    )

    nested_else = data.get("Else")
    if isinstance(nested_else, dict):
        if "Cond" in nested_else:
            _collect_elif_chain(nested_else, elif_branches, else_stmts)
        else:
            else_stmts.extend(_parse_stmt_list(nested_else.get("Then", [])))
    elif isinstance(nested_else, list):
        else_stmts.extend(_parse_stmt_list(nested_else))


# ---------------------------------------------------------------------------
# Node type registry and dispatch
# ---------------------------------------------------------------------------

# Type mapping from shfmt's JSON to our dataclasses
NODE_TYPES = {
    "File": File,
    "CallExpr": CallExpr,
    "BinaryCmd": BinaryCmd,
    "Word": Word,
    "DeclClause": Node,
    "Subshell": Subshell,
    "IfClause": IfClause,
    "ForClause": ForClause,
    "WhileClause": WhileClause,
    "AndCmd": AndCmd,
    "OrCmd": OrCmd,
    "CaseClause": CaseClause,
    "Lit": Lit,
    "SglQuoted": SglQuoted,
    "ParamExp": ParamExp,
    "DblQuoted": DblQuoted,
    "CmdSubst": CmdSubst,
    "ProcSubst": ProcSubst,
    "ArithmExp": ArithmExp,
    "BraceExp": BraceExp,
    "BinaryArithm": BinaryArithm,
    "ExtGlob": ExtGlob,
    "Block": Block,
    "FuncDecl": FuncDecl,
    "TestClause": TestClause,
    "UnaryTest": UnaryTest,
    "BinaryTest": BinaryTest,
    "ParenTest": ParenTest,
    "ArithmCmd": ArithmCmd,
    "UnaryArithm": UnaryArithm,
    "ParenArithm": ParenArithm,
    "FlagsArithm": FlagsArithm,
    "LetClause": LetClause,
    "TimeClause": TimeClause,
    "CoprocClause": CoprocClause,
    "TestDecl": TestDecl,
    "Comment": Comment,
    "Assign": Assign,
    "CaseItem": CaseItem,
    "WordIter": WordIter,
    "CStyleLoop": CStyleLoop,
    "ArrayExpr": ArrayExpr,
    "ArrayElem": ArrayElem,
}


def _convert_file(data: dict) -> File:
    pos, end = _parse_pos_end(data)
    return File(
        type="File",
        pos=pos,
        end=end,
        stmts=[stmt_from_json(s) for s in data.get("Stmts", [])],
    )


def _convert_call_expr(data: dict) -> CallExpr:
    assigns_raw = data.get("Assigns")
    assigns = [assign_from_json(a) for a in assigns_raw] if assigns_raw else None
    pos, end = _parse_pos_end(data)
    return CallExpr(
        type="CallExpr",
        pos=pos,
        end=end,
        args=[word_from_json(a) for a in data.get("Args", [])],
        assigns=assigns,
    )


def _convert_binary_cmd(data: dict) -> BinaryCmd:
    pos, end = _parse_pos_end(data)
    return BinaryCmd(
        type="BinaryCmd",
        pos=pos,
        end=end,
        op=data.get("Op", ""),
        left=node_from_json(data.get("X")),
        right=node_from_json(data.get("Y")),
        redirs=None,
    )


def _convert_decl_clause(data: dict) -> Node:
    words = []
    for arg in data.get("Args", []):
        if isinstance(arg, dict):
            val = arg.get("value", arg.get("Value", {}))
            if val:
                w = Word(
                    type="Word",
                    pos=_parse_position(val.get("Pos")),
                    end=_parse_position(val.get("End")),
                    parts=[part_from_json(p) for p in val.get("Parts", [])],
                )
                words.append(w)
    pos, end = _parse_pos_end(data)
    return Node(type="DeclClause", pos=pos, end=end, args=words)


def _convert_subshell(data: dict) -> Subshell:
    pos, end = _parse_pos_end(data)
    return Subshell(
        type="Subshell",
        pos=pos,
        end=end,
        stmts=[stmt_from_json(s) for s in data.get("Stmts", [])],
    )


def _convert_for_clause(data: dict) -> ForClause:
    loop = data.get("Loop", {})
    var_name = None
    if isinstance(loop, dict):
        name_info = loop.get("Name", {})
        if isinstance(name_info, dict):
            var_name = name_info.get("Value")

    items = []
    if isinstance(loop, dict):
        for w in loop.get("Items", []):
            if isinstance(w, dict):
                items.append(word_from_json(w))

    body = _parse_stmt_list(data.get("Do", []))

    pos, end = _parse_pos_end(data)
    return ForClause(
        type="ForClause",
        pos=pos,
        end=end,
        var=None
        if var_name is None
        else Word(type="Word", parts=[Part(type="Lit", value=var_name)]),
        words=items,
        body=body,
    )


def _convert_while_clause(data: dict) -> WhileClause:
    pos, end = _parse_pos_end(data)
    return WhileClause(
        type="WhileClause",
        pos=pos,
        end=end,
        cond_stmts=[stmt_from_json(s) for s in data.get("Cond", [])],
        body=[stmt_from_json(s) for s in data.get("Do", [])],
    )


def _convert_and_cmd(data: dict) -> AndCmd:
    pos, end = _parse_pos_end(data)
    return AndCmd(
        type="AndCmd",
        pos=pos,
        end=end,
        left=node_from_json(data.get("X")),
        right=node_from_json(data.get("Y")),
    )


def _convert_or_cmd(data: dict) -> OrCmd:
    pos, end = _parse_pos_end(data)
    return OrCmd(
        type="OrCmd",
        pos=pos,
        end=end,
        left=node_from_json(data.get("X")),
        right=node_from_json(data.get("Y")),
    )


def _convert_case_clause(data: dict) -> CaseClause:
    pos, end = _parse_pos_end(data)
    return CaseClause(
        type="CaseClause",
        pos=pos,
        end=end,
        expr=word_from_json(data.get("Word")),
        branches=[
            {
                "patterns": [word_from_json(w) for w in b.get("Patterns", [])],
                "body": [stmt_from_json(s) for s in b.get("Stmts", [])],
            }
            for b in data.get("Items", [])
        ],
        default=[stmt_from_json(s) for s in data.get("Default", [])],
    )


def _convert_arithm_exp(data: dict) -> ArithmExp:
    pos, end = _parse_pos_end(data)
    return ArithmExp(
        type="ArithmExp", pos=pos, end=end, x=node_from_json(data.get("X"))
    )


def _convert_binary_arithm(data: dict) -> BinaryArithm:
    pos, end = _parse_pos_end(data)
    return BinaryArithm(
        type="BinaryArithm",
        pos=pos,
        end=end,
        op=data.get("Op", ""),
        op_pos=_parse_position(data.get("OpPos")),
        left=node_from_json(data.get("X")),
        right=node_from_json(data.get("Y")),
    )


def _convert_block(data: dict) -> Block:
    pos, end = _parse_pos_end(data)
    return Block(
        type="Block",
        pos=pos,
        end=end,
        left_pos=_parse_position(data.get("Lbrace")),
        right_pos=_parse_position(data.get("Rbrace")),
        stmts=[stmt_from_json(s) for s in data.get("Stmts", [])],
    )


def _convert_func_decl(data: dict) -> FuncDecl:
    name_data = data.get("Name", {})
    name_node = _lit_from_json(name_data) if isinstance(name_data, dict) else None

    body_data = data.get("Body")
    body_node = None
    if isinstance(body_data, dict):
        body_node = node_from_json(body_data.get("Cmd", body_data))

    pos, end = _parse_pos_end(data)
    return FuncDecl(
        type="FuncDecl",
        pos=pos,
        end=end,
        rsrv_word=data.get("RsrvWord", False),
        parens=data.get("Parens", False),
        name=name_node,
        body=body_node,
    )


def _convert_test_clause(data: dict) -> TestClause:
    pos, end = _parse_pos_end(data)
    return TestClause(
        type="TestClause",
        pos=pos,
        end=end,
        left_pos=_parse_position(data.get("Left")),
        right_pos=_parse_position(data.get("Right")),
        body=node_from_json(data.get("X")),
    )


def _convert_unary_test(data: dict) -> UnaryTest:
    pos, end = _parse_pos_end(data)
    return UnaryTest(
        type="UnaryTest",
        pos=pos,
        end=end,
        op=data.get("Op", ""),
        op_pos=_parse_position(data.get("OpPos")),
        x=node_from_json(data.get("X")),
    )


def _convert_binary_test(data: dict) -> BinaryTest:
    pos, end = _parse_pos_end(data)
    return BinaryTest(
        type="BinaryTest",
        pos=pos,
        end=end,
        op=data.get("Op", ""),
        op_pos=_parse_position(data.get("OpPos")),
        left=node_from_json(data.get("X")),
        right=node_from_json(data.get("Y")),
    )


def _convert_paren_test(data: dict) -> ParenTest:
    pos, end = _parse_pos_end(data)
    return ParenTest(
        type="ParenTest",
        pos=pos,
        end=end,
        left_pos=_parse_position(data.get("Lparen")),
        right_pos=_parse_position(data.get("Rparen")),
        body=node_from_json(data.get("X")),
    )


def _convert_arithm_cmd(data: dict) -> ArithmCmd:
    pos, end = _parse_pos_end(data)
    return ArithmCmd(
        type="ArithmCmd",
        pos=pos,
        end=end,
        left_pos=_parse_position(data.get("Left")),
        right_pos=_parse_position(data.get("Right")),
        body=node_from_json(data.get("X")),
    )


def _convert_unary_arithm(data: dict) -> UnaryArithm:
    pos, end = _parse_pos_end(data)
    return UnaryArithm(
        type="UnaryArithm",
        pos=pos,
        end=end,
        op=data.get("Op", ""),
        op_pos=_parse_position(data.get("OpPos")),
        post=data.get("Post", False),
        x=node_from_json(data.get("X")),
    )


def _convert_paren_arithm(data: dict) -> ParenArithm:
    pos, end = _parse_pos_end(data)
    return ParenArithm(
        type="ParenArithm",
        pos=pos,
        end=end,
        left_pos=_parse_position(data.get("Lparen")),
        right_pos=_parse_position(data.get("Rparen")),
        body=node_from_json(data.get("X")),
    )


def _convert_flags_arithm(data: dict) -> FlagsArithm:
    pos, end = _parse_pos_end(data)
    return FlagsArithm(
        type="FlagsArithm",
        pos=pos,
        end=end,
        flags=Lit(type="Lit", value=data.get("Flags", "")),
        x=node_from_json(data.get("X")),
    )


def _convert_let_clause(data: dict) -> LetClause:
    pos, end = _parse_pos_end(data)
    return LetClause(
        type="LetClause",
        pos=pos,
        end=end,
        let_pos=_parse_position(data.get("Let")),
        exprs=[node_from_json(e) for e in data.get("Exprs", [])],
    )


def _convert_time_clause(data: dict) -> TimeClause:
    pos, end = _parse_pos_end(data)
    return TimeClause(
        type="TimeClause",
        pos=pos,
        end=end,
        time_pos=_parse_position(data.get("Time")),
        posix_format=data.get("PosixFormat", False),
        stmt=node_from_json(data.get("Stmt")),
    )


def _convert_coproc_clause(data: dict) -> CoprocClause:
    pos, end = _parse_pos_end(data)
    return CoprocClause(
        type="CoprocClause",
        pos=pos,
        end=end,
        coproc_pos=_parse_position(data.get("Coproc")),
        name=word_from_json(data.get("Name")),
        stmt=node_from_json(data.get("Stmt")),
    )


def _convert_test_decl(data: dict) -> TestDecl:
    pos, end = _parse_pos_end(data)
    return TestDecl(
        type="TestDecl",
        pos=pos,
        end=end,
        description=word_from_json(data.get("Description")),
        body=node_from_json(data.get("Body")),
    )


def _convert_comment(data: dict) -> Comment:
    return Comment(
        type="Comment",
        hash_pos=_parse_position(data.get("Hash")),
        text=data.get("Text", ""),
    )


def _convert_assign(data: dict) -> Assign:
    pos, end = _parse_pos_end(data)
    return Assign(
        type="Assign",
        pos=pos,
        end=end,
        name=Lit(type="Lit", value=data.get("Name", "")),
        index=node_from_json(data.get("Index")),
        value=word_from_json(data.get("Value")),
        array=node_from_json(data.get("Array")),
        append=data.get("Append", False),
        naked=data.get("Naked", False),
    )


def _convert_case_item(data: dict) -> CaseItem:
    pos, end = _parse_pos_end(data)
    return CaseItem(
        type="CaseItem",
        pos=pos,
        end=end,
        op=data.get("Op", ""),
        patterns=[word_from_json(w) for w in data.get("Patterns", [])],
        stmts=[stmt_from_json(s) for s in data.get("Stmts", [])],
    )


def _convert_word_iter(data: dict) -> WordIter:
    pos, end = _parse_pos_end(data)
    return WordIter(
        type="WordIter",
        pos=pos,
        end=end,
        name=Lit(type="Lit", value=data.get("Name", "")),
        items=[word_from_json(w) for w in data.get("Items", [])],
    )


def _convert_cstyle_loop(data: dict) -> CStyleLoop:
    pos, end = _parse_pos_end(data)
    return CStyleLoop(
        type="CStyleLoop",
        pos=pos,
        end=end,
        init=node_from_json(data.get("Init")),
        cond=node_from_json(data.get("Cond")),
        post=node_from_json(data.get("Post")),
    )


def _convert_array_expr(data: dict) -> ArrayExpr:
    pos, end = _parse_pos_end(data)
    return ArrayExpr(
        type="ArrayExpr",
        pos=pos,
        end=end,
        elems=[node_from_json(e) for e in data.get("Elems", [])],
    )


def _convert_array_elem(data: dict) -> ArrayElem:
    pos, end = _parse_pos_end(data)
    return ArrayElem(
        type="ArrayElem",
        pos=pos,
        end=end,
        index=node_from_json(data.get("Index")),
        value=word_from_json(data.get("Value")),
    )


def _convert_brace_exp(data: dict) -> BraceExp:
    pos, end = _parse_pos_end(data)
    return BraceExp(
        type="BraceExp",
        pos=pos,
        end=end,
        sequence=data.get("Sequence", False),
        elems=[word_from_json(e) for e in data.get("Elems", [])],
    )


def _convert_sgl_quoted(data: dict) -> SglQuoted:
    pos, end = _parse_pos_end(data)
    return SglQuoted(type="SglQuoted", pos=pos, end=end, value=data.get("Value", ""))


def _convert_cmd_subst(data: dict) -> CmdSubst:
    pos, end = _parse_pos_end(data)
    return CmdSubst(
        type="CmdSubst",
        pos=pos,
        end=end,
        stmts=[stmt_from_json(s) for s in data.get("Stmts", [])],
        backquotes=data.get("Backquotes", False),
    )


def _convert_proc_subst(data: dict) -> ProcSubst:
    pos, end = _parse_pos_end(data)
    return ProcSubst(
        type="ProcSubst",
        pos=pos,
        end=end,
        op=data.get("Op", ""),
        op_pos=_parse_position(data.get("OpPos")),
        rparen=_parse_position(data.get("Rparen")),
        stmts=[stmt_from_json(s) for s in data.get("Stmts", [])],
    )


def _convert_dbl_quoted(data: dict) -> DblQuoted:
    parts = (
        [part_from_json(p) for p in data.get("Parts", [])] if "Parts" in data else None
    )
    pos, end = _parse_pos_end(data)
    return DblQuoted(type="DblQuoted", pos=pos, end=end, parts=parts)


# Dispatch table mapping shfmt Type strings to converter functions
_CONVERTERS: dict[str, callable] = {
    "File": _convert_file,
    "CallExpr": _convert_call_expr,
    "BinaryCmd": _convert_binary_cmd,
    "DeclClause": _convert_decl_clause,
    "Subshell": _convert_subshell,
    "IfClause": _parse_if_clause,
    "ForClause": _convert_for_clause,
    "WhileClause": _convert_while_clause,
    "AndCmd": _convert_and_cmd,
    "OrCmd": _convert_or_cmd,
    "CaseClause": _convert_case_clause,
    "ArithmExp": _convert_arithm_exp,
    "BinaryArithm": _convert_binary_arithm,
    "ExtGlob": _extglob_from_json,
    "Block": _convert_block,
    "FuncDecl": _convert_func_decl,
    "TestClause": _convert_test_clause,
    "UnaryTest": _convert_unary_test,
    "BinaryTest": _convert_binary_test,
    "ParenTest": _convert_paren_test,
    "ArithmCmd": _convert_arithm_cmd,
    "UnaryArithm": _convert_unary_arithm,
    "ParenArithm": _convert_paren_arithm,
    "FlagsArithm": _convert_flags_arithm,
    "LetClause": _convert_let_clause,
    "TimeClause": _convert_time_clause,
    "CoprocClause": _convert_coproc_clause,
    "TestDecl": _convert_test_decl,
    "Comment": _convert_comment,
    "Assign": _convert_assign,
    "CaseItem": _convert_case_item,
    "WordIter": _convert_word_iter,
    "CStyleLoop": _convert_cstyle_loop,
    "ArrayExpr": _convert_array_expr,
    "ArrayElem": _convert_array_elem,
    "BraceExp": _convert_brace_exp,
    "Lit": _lit_from_json,
    "SglQuoted": _convert_sgl_quoted,
    "ParamExp": _paramexp_from_json,
    "DblQuoted": _convert_dbl_quoted,
    "CmdSubst": _convert_cmd_subst,
    "ProcSubst": _convert_proc_subst,
    "Word": lambda data: word_from_json(data),
    "Stmt": lambda data: stmt_from_json(data),
}


def node_from_json(data: dict | None) -> Node | None:
    """Convert shfmt JSON node data to a typed AST node.

    Returns None when *data* is None (key absent in JSON).

    Uses the ``_CONVERTERS`` dispatch table to map shfmt's ``Type`` field
    to a converter function, eliminating the previous 530-line if/elif chain.
    """
    if data is None:
        return None

    node_type = data.get("Type", "")

    # Handle nodes that have 'Cmd' but no 'Type' (wrapped statements)
    if not node_type and "Cmd" in data:
        return node_from_json(data["Cmd"])

    converter = _CONVERTERS.get(node_type)
    if converter is not None:
        return converter(data)

    # Unknown type — wrap in a generic Node
    pos, end = _parse_pos_end(data)
    return Node(type=node_type, pos=pos, end=end)


def parse_ast(command: str) -> Node:
    """Parse a bash command string into a typed AST node.

    This is the main entry point for parsing bash commands. It invokes
    shfmt via the parser module and converts the resulting JSON into
    a typed Python AST rooted at a File node.

    Args:
        command: Bash command string to parse

    Returns:
        Node: Root File node of the parsed AST tree

    Raises:
        ParseError: If shfmt cannot parse the command
    """
    from .parser import parse

    raw = parse(command)
    return node_from_json(raw)
