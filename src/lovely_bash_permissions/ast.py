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

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Position:
    """Source position information for AST nodes.
    
    Tracks the location of a node in the original source text.
    """
    offset: int
    line: int
    col: int


@dataclass
class Range:
    """Source range with start and end positions.
    
    Defines a span of text in the source from pos to end.
    """
    pos: Position
    end: Position


@dataclass
class Node:
    """Base AST node for all bash syntax elements.
    
    Every node in the AST inherits from this base class. Unknown or
    unmapped shfmt node types are represented as Node objects with
    their original type name preserved in the `type` field.
    
    Attributes:
        type: shfmt node type name (e.g., "File", "CallExpr", "Word")
        pos: Starting source position
        end: Ending source position
        extra: Additional context or metadata (parser-specific)
        args: Command arguments as a list of Word nodes
    """
    type: str = None
    pos: Position = None
    end: Position = None
    extra: Optional[dict] = None
    args: Optional[List['Word']] = None


@dataclass
class Word(Node):
    """A bash word composed of parts.
    
    Words are the basic unit of bash syntax. They can be simple literals,
    variable expansions, command substitutions, or complex combinations.
    For example, "hello", "$HOME", "$(date)", or "$HOME/file.txt" are all
    words made up of one or more parts.
    
    Attributes:
        parts: List of Part objects that make up this word
    """
    parts: List['Part'] = None


@dataclass
class Lit(Node):
    """A shell literal string without any special characters.
    
    Represents a plain, unquoted bash word. This is the simplest word part
    type, containing just a literal value with no expansions, variables,
    or special characters. Examples: "hello", "file.txt", "ls", "42".
    
    Lit nodes appear within Words as their parts, or can appear as
    standalone nodes in certain contexts.
    
    Attributes:
        type: Always "Lit"
        pos: Starting source position
        end: Ending source position
        value: The literal string value
        value_pos: Source position of the value's start
        value_end: Source position of the value's end
    """
    type: str = "Lit"
    value: str = ""
    value_pos: Position = None
    value_end: Position = None


@dataclass
class ParamExp(Node):
    """A shell parameter expansion.

    Represents $VAR, ${VAR}, ${VAR:-default}, ${arr[0]}, ${#VAR}, and
    all other bash parameter expansion forms.

    shfmt's JSON representation includes:
        - Type: "ParamExp"
        - Param: The parameter name (Value is the name)
        - Short: true if $VAR form (no braces), false if ${VAR} form
        - Exp: Expansion info (Op, Word) for default/substituted value expressions
        - Index: Array index (Word node) for ${arr[0]} style
        - Length: true for ${#VAR} length expansion
        - Pos/End: Position of the entire expansion
        - Dollar: Position of the $ character

    Attributes:
        type: Always "ParamExp"
        pos: Starting source position of the entire expansion
        end: Ending source position of the entire expansion
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
    exp: Optional[dict] = None
    index: Optional['Word'] = None
    length: bool = False
    dollar_pos: Position = None


@dataclass
class SglQuoted(Node):
    """A single-quoted shell string.
    
    Represents a single-quoted bash string where the content is taken
    literally with no variable expansion, command substitution, or
    special character interpretation. Single-quoted strings are the
    simplest way to quote strings in bash.
    
    Unlike Lit, the value is wrapped in single quotes in the source,
    which means no expansion occurs. For example, in 'echo $HOME',
    the argument would be SglQuoted with value="$HOME" (the variable
    is not expanded).
    
    shfmt's JSON representation for SglQuoted includes:
        - Type: "SglQuoted"
        - Value: The string content without quotes
        - Pos/End: Position of the entire quoted string
        - Left/Right: Position of the opening/closing quote characters
    
    Attributes:
        type: Always "SglQuoted"
        pos: Starting source position of the entire quoted string
        end: Ending source position of the entire quoted string
        value: The string content without the surrounding quotes
    """
    type: str = "SglQuoted"
    value: str = ""


@dataclass
class DblQuoted(Node):
    """A double-quoted shell string with nested parts.
    
    Represents a double-quoted bash string where the content is parsed as
    a list of parts. Unlike single-quoted strings, double-quoted strings
    allow variable expansion, command substitution, and escape sequences,
    but protect words from splitting and globbing.
    
    shfmt's JSON representation for DblQuoted includes:
        - Type: "DblQuoted"
        - Pos/End: Position of the entire quoted string
        - Left/Right: Position of the opening/closing quote characters
        - Parts: Nested parts (Lit, ParamExp, CmdSubst, Esc, etc.)
    
    Attributes:
        type: Always "DblQuoted"
        pos: Starting source position of the entire quoted string
        end: Ending source position of the entire quoted string
        parts: List of Part objects that make up the quoted content
    """
    type: str = "DblQuoted"
    parts: List['Part'] = None


@dataclass
class CmdSubst(Node):
    """A command substitution. 

    Represents bash command substitution using either $(...) or backticks.
    The inner command(s) are parsed as full statements and executed, with
    their output substituted back into the original command.
    
    Examples: 
        echo $(date)           -> Modern $(...) syntax
        echo `date`            -> Legacy backtick syntax
        echo "Hello $(whoami)" -> Command substitution in double quotes
    
    shfmt's JSON representation for CmdSubst includes:
        - Type: "CmdSubst"
        - Pos/End: Position of the entire substitution
        - Left/Right: Position of opening/closing delimiter characters
        - Stmts: List of statements contained in the substitution
        - Backquotes: True if backtick syntax is used, false for $(...)
    
    Attributes:
        type: Always "CmdSubst"
        pos: Starting source position of the entire substitution
        end: Ending source position of the entire substitution
        stmts: List of Stmt objects representing commands in the substitution
        backquotes: True if backtick syntax, False for $(...)
    """
    type: str = "CmdSubst"
    stmts: List['Stmt'] = None
    backquotes: bool = False


@dataclass
class ProcSubst(Node):
    """A process substitution.

    Represents bash process substitution using <(cmd) or >(cmd). These
    create temporary file-like interfaces where a command's output is
    made available as a named pipe (FIFO) or /dev/fd reference.

    Examples:
        cat <(echo 'hi')          -> Read from process output as a file
        diff <(echo 'hi') <(echo 'there') -> Compare two process outputs
        sort < input > >(cat)     -> Write to a process as an output file

    shfmt's JSON representation for ProcSubst includes:
        - Type: "ProcSubst"
        - Pos/End: Position of the entire substitution
        - OpPos: Position of the opening operator (<( or >()
        - Rparen: Position of the closing parenthesis
        - Op: Operator string ("<(" or ">(")
        - Stmts: List of statements to execute

    Attributes:
        type: Always "ProcSubst"
        pos: Starting source position of the entire substitution
        end: Ending source position of the entire substitution
        op: The operator string ("<(" or ">(")
        op_pos: Position of the opening operator
        rparen: Position of the closing parenthesis
        stmts: List of Stmt objects representing commands to execute
    """
    type: str = "ProcSubst"
    op: str = ""
    op_pos: Position = None
    rparen: Position = None
    stmts: List['Stmt'] = None


@dataclass
class ArithmExp(Node):
    """An arithmetic expansion.

    Represents bash arithmetic expansion using $((...)). The inner expression
    is evaluated arithmetically and the result is substituted into the command.

    Examples:
        echo $((2 + 2))        -> Simple arithmetic operation
        echo $((x * y))        -> Variable arithmetic
        echo $((x + y))        -> Addition with variables
    
    shfmt's JSON representation for ArithmExp includes:
        - Type: "ArithmExp"
        - Pos/End: Position of the entire expansion
        - Left/Right: Position of opening/closing delimiter characters
        - X: The inner arithmetic expression (BinaryArithm, Word, etc.)
    
    Attributes:
        type: Always "ArithmExp"
        pos: Starting source position of the entire expansion
        end: Ending source position of the entire expansion
        x: The inner arithmetic expression (Node with type "BinaryArithm", "Word", etc.)
    """
    type: str = "ArithmExp"
    x: Optional['Node'] = None


@dataclass
class ExtGlob(Node):
    """Extended glob pattern.

    Represents bash extended globbing with the `extglob` shell option.
    Matches files/directories against complex patterns using special
    operators. Extended globs must be enabled with `shopt -s extglob`
    in bash.

    Extended glob operators:
        @(pattern)     - Match exactly one occurrence of any pattern
        +(pattern)     - Match one or more occurrences of any pattern
        *(pattern)     - Match zero or more occurrences of any pattern
        ?(pattern)     - Match zero or one occurrence of any pattern
        !(pattern)     - Match anything except the specified patterns

    Patterns are separated by the pipe character (|) within the parentheses.
    Extended globs can be combined with regular globs and file paths.

    Examples:
        ls *.@(txt|md)          -> Match files ending in .txt or .md
        rm -rf *.+(js|css)      -> Match files ending in .js, .css, etc.
        cp *?(bak|orig) dest/   -> Match files with no extension or .bak/.orig
        echo *.!(zip|tar)       -> Match files except .zip or .tar
        find . -name *@(exe|so) -> Find executable/shared library files
    
    shfmt's JSON representation for ExtGlob includes:
        - Type: "ExtGlob"
        - Pos/End: Position of the entire extended glob expression
        - OpPos: Position of the extended glob operator character
        - Op: Extended glob operator string ("@(", "+(", "*(", "?(", "!(")
        - Pattern: Pattern specification as a Lit node (pipe-separated patterns)
    
    Attributes:
        type: Always "ExtGlob"
        pos: Starting source position of the extended glob
        end: Ending source position of the extended glob
        op: Extended glob operator string ("@(", "+(", "*(", "?(", "!(")
        op_pos: Source position of the extended glob operator character
        pattern: Pattern specification as a Lit node
    """
    type: str = "ExtGlob"
    op: str = ""
    op_pos: Position = None
    pattern: Optional['Lit'] = None


@dataclass
class BinaryArithm(Node):
    """A binary arithmetic operation.

    Represents a binary arithmetic operation within an arithmetic expression.
    These appear as the inner expression of ArithmExp nodes.

    Examples:
        $((2 + 2))      -> Op="+", X=Word("2"), Y=Word("2")
        $((x * y))      -> Op="*", X=Word("x"), Y=Word("y")
        $((x = x + 1))  -> Nested: Op="=", Y contains another BinaryArithm
    
    shfmt's JSON representation for BinaryArithm includes:
        - Type: "BinaryArithm"
        - Pos/End: Position of the operation
        - OpPos: Position of the operator character
        - Op: The operator string (+, -, *, /, %, ==, !=, <, >, <=, >=, &&, ||, =, etc.)
        - X: Left operand (Node)
        - Y: Right operand (Node)
    
    Attributes:
        type: Always "BinaryArithm"
        pos: Starting source position
        end: Ending source position
        op: The operator string
        op_pos: Position of the operator character
        x: Left operand
        y: Right operand
    """
    type: str = "BinaryArithm"
    op: str = None
    op_pos: Position = None
    x: Optional['Node'] = None
    y: Optional['Node'] = None


@dataclass
class Part:
    """An atomic part of a bash word.
    
    Represents a single syntactic element within a word. Parts can be
    literals, variable references, expansions, or nested parts.
    
    Common part types:
        - "Lit": Simple literal string value
        - "Var": Variable reference ($VAR)
        - "ParamExp": Parameter expansion (${VAR}, ${VAR-default}, etc.)
        - "CmdSubst": Command substitution ($() or backticks)
        - "DblQuoted": Double-quoted string containing nested parts
        - "SglQuoted": Single-quoted string
    
    Attributes:
        type: shfmt part type name
        pos: Starting source position
        end: Ending source position
        value: Literal string value (for Lit and some other types)
        parts: Nested parts (for DblQuoted, SglQuoted, etc.)
        extra: Additional context (for CmdSubst, contains inner statements)
    """
    type: str = None
    pos: Position = None
    end: Position = None
    value: Optional[str] = None
    parts: Optional[List['Part']] = None
    extra: Optional[dict] = None


@dataclass
class CallExpr(Node):
    """A command invocation with its arguments.
    
    Represents a simple bash command invocation, e.g., "ls -la", "echo hello",
    or "python script.py". The first argument in the args list is the command
    name, followed by its arguments.
    
    For example, in "ls -la /tmp", CallExpr has three args:
        [Word("ls"), Word("-la"), Word("/tmp")]
    
    Attributes:
        args: List of Word objects - first is the command name, rest are arguments
    """
    args: List['Word'] = None


@dataclass
class Block(Node):
    """A block of statements enclosed in curly braces.

    Represents bash block syntax where commands are grouped in curly braces
    and executed in the current shell environment. Unlike subshells (which
    use parentheses and create a new shell), blocks run commands in the
    same shell, so variable changes persist.

    Examples:
        { echo 'a'; echo 'b'; }          -> Two statements in a block
        if true; then { cmd1; cmd2; }; fi -> Block in if-then
        { cmd & }                        -> Background the entire block

    shfmt's JSON representation for Block includes:
        - Type: "Block"
        - Pos/End: Position of the entire block
        - Lbrace: Position of the opening brace
        - Rbrace: Position of the closing brace
        - Stmts: List of statements contained in the block

    Attributes:
        type: Always "Block"
        pos: Starting source position of the entire block
        end: Ending source position of the entire block
        lbrace: Position of the opening brace
        rbrace: Position of the closing brace
        stmts: List of Stmt objects representing commands in the block
    """
    type: str = "Block"
    lbrace: Position = None
    rbrace: Position = None
    stmts: List['Stmt'] = None


@dataclass
class FuncDecl(Node):
    """A bash function declaration.

    Represents bash function definitions in both forms:
        - name() { body }          (traditional, with parentheses)
        - function name { body }    (POSIX-style, with 'function' keyword)

    shfmt's JSON representation for FuncDecl includes:
        - Type: "FuncDecl"
        - Pos/End: Position of the entire function declaration
        - Parens: True if () is used (absent or false for 'function name' form)
        - Name: Lit node containing the function name
        - Body: Statement wrapping the function body block

    Attributes:
        type: Always "FuncDecl"
        pos: Starting source position of the entire declaration
        end: Ending source position of the entire declaration
        parens: True if the function uses () syntax
        name: Lit node containing the function name
        body: Block node containing the function body statements
    """
    type: str = "FuncDecl"
    rsrv_word: bool = False
    parens: bool = False
    name: Optional['Lit'] = None
    body: Optional['Node'] = None


@dataclass
class BinaryCmd(Node):
    """A binary command operation (primarily pipes).
    
    Represents bash binary operators, most commonly pipes (|). The operator
    takes two command operands: x (left) and y (right).
    
    Example: "ls | grep txt" becomes:
        BinaryCmd(op="|", x=CallExpr("ls"), y=CallExpr("grep txt"))
    
    Attributes:
        op: Operator symbol ("|" for pipe)
        x: Left operand (a command or nested expression)
        y: Right operand (a command or nested expression)
        redirs: Redirections applied at the pipe level
    """
    op: str = None
    x: 'Node' = None
    y: 'Node' = None
    redirs: Optional[List['Redir']] = None


@dataclass
class Subshell(Node):
    """A parenthesized command group (subshell).
    
    Represents bash subshell syntax where commands are grouped in parentheses
    and executed in a separate shell environment. For example:
        (cd /tmp && ls)
    
    Attributes:
        stmts: List of Stmt objects executed within the subshell
    """
    stmts: List['Stmt'] = None


@dataclass
class IfClause(Node):
    """An if/elif/else conditional statement.
    
    Represents bash conditional branching. The cond field contains the
    test command, then contains the true branch, elif_branches contains
    additional elif conditions, and else_branch contains the final fallback.
    
    Example: "if test -f file; then cat file; else echo missing; fi"
    
    Attributes:
        cond: List of Stmt objects for the if condition
        then: List of Stmt objects for the true branch
        elif_branches: List of dicts with "cond" and "body" keys
        else_branch: List of Stmt objects for the else branch
    """
    cond: List['Stmt'] = None
    then: List['Stmt'] = None
    elif_branches: List[dict] = None
    else_branch: List['Stmt'] = None


@dataclass
class ForClause(Node):
    """A for loop statement.
    
    Represents bash's C-style for loop: for var in words; do body; done
    
    Example: "for f in *.txt; do echo $f; done"
    
    Attributes:
        var: Word representing the loop variable name
        words: List of Word objects to iterate over
        body: List of Stmt objects executed in each iteration
    """
    var: 'Word' = None
    words: List['Word'] = None
    body: List['Stmt'] = None


@dataclass
class WhileClause(Node):
    """A while loop statement.
    
    Represents bash's while loop: while condition; do body; done
    
    Example: "while true; do sleep 1; done"
    
    Attributes:
        cond: List of Stmt objects evaluated as the loop condition
        body: List of Stmt objects executed in each iteration
    """
    cond: List['Stmt'] = None
    body: List['Stmt'] = None


@dataclass
class AndCmd(Node):
    """Logical AND operator (&&).
    
    Represents bash's short-circuit AND: command1 && command2
    Executes y only if x succeeds (exit code 0).
    
    Example: "test -f file && cat file"
    
    Attributes:
        x: Left operand (command or expression)
        y: Right operand (command or expression)
    """
    x: 'Node' = None
    y: 'Node' = None


@dataclass
class OrCmd(Node):
    """Logical OR operator (||).
    
    Represents bash's short-circuit OR: command1 || command2
    Executes y only if x fails (non-zero exit code).
    
    Example: "ping -c1 host || echo unreachable"
    
    Attributes:
        x: Left operand (command or expression)
        y: Right operand (command or expression)
    """
    x: 'Node' = None
    y: 'Node' = None


@dataclass
class CaseClause(Node):
    """A case/switch statement.
    
    Represents bash's case statement: case expr in patterns) body;; esac
    Matches expr against patterns and executes the first matching branch.
    
    Example: "case $color in red) echo warm;; green) echo natural;; esac"
    
    Attributes:
        expr: Word expression to evaluate for matching
        branches: List of dicts with "patterns" (Words) and "body" (Stmts)
        default: List of Stmt objects for the default (*) branch
    """
    expr: 'Word' = None
    branches: List[dict] = None
    default: List['Stmt'] = None


@dataclass
class Redir:
    """A file redirection operation.
    
    Represents bash's file redirections that connect commands to files.
    Common redirection operators include > (output), >> (append), < (input),
    and 2> (stderr output).
    
    Example: "cat file.txt > output.txt" has a Redir with op='>' and
    word containing 'output.txt'.
    
    Attributes:
        op: Redirection operator string (e.g., ">", ">>", "<", "2>")
        word: Word specifying the file target
        pos: Starting source position of the entire redirection
        end: Ending source position
        op_pos: Source position of the redirection operator itself
    """
    op: str = None
    word: 'Word' = None
    pos: Position = None
    end: Position = None
    op_pos: Position = None

@dataclass
@dataclass
class TestClause(Node):
    """Extended test: [[ condition ]].

    Represents bash's extended test expression, which provides additional
    operators over the POSIX single-bracket test. The test expression is
    stored in the x field and can be a complex expression involving
    UnaryTest, BinaryTest, ParenTest nodes.

    Examples:
        [[ -f file.txt ]]                   -> UnaryTest(-f, file.txt)
        [[ -f file && -r file ]]            -> BinaryTest(&&, UnaryTest(-f, file), UnaryTest(-r, file))
        [[ "$name" == "alx" || "$name" == "bob" ]] -> BinaryTest(||, BinaryTest(...), ...)
        [[ ( $x -gt 0 ) && ( $y -lt 10 ) ]] -> BinaryTest(&&, ParenTest(...), ParenTest(...))

    shfmt's JSON representation includes:
        - Type: "TestClause"
        - Pos/End: Position of the entire test
        - Left/Right: Position of the opening/closing brackets
        - X: The test expression (TestExpr type)

    Attributes:
        type: Always "TestClause"
        pos: Starting source position
        end: Ending source position
        left: Position of the opening [[
        right: Position of the closing ]]
        x: The test expression (Node with type UnaryTest, BinaryTest, ParenTest, etc.)
    """
    type: str = "TestClause"
    left: Position = None
    right: Position = None
    x: Optional['Node'] = None


@dataclass
class UnaryTest(Node):
    """Unary test: -f file, -z str, -n str, -d dir.

    Represents a unary test operation where a single operator tests
    one operand. Common operators include -f (file exists), -d (dir exists),
    -r (readable), -w (writable), -x (executable), -z (string empty),
    -n (string not empty).

    Attributes:
        type: Always "UnaryTest"
        pos: Starting source position
        end: Ending source position
        op: The operator string ("-f", "-d", "-r", etc.)
        op_pos: Position of the operator
        x: The test operand
    """
    type: str = "UnaryTest"
    op: str = None
    op_pos: Position = None
    x: Optional['Node'] = None


@dataclass
class BinaryTest(Node):
    """Binary test: a -eq b, a && b, a || b, a == b, a != b.

    Represents a binary test operation that compares two operands using
    an operator. Comparison operators include -eq (equal), -ne (not equal),
    -lt (less than), -gt (greater than), -le, -ge, == (string equal),
    != (string not equal), && (logical and), || (logical or).

    Attributes:
        type: Always "BinaryTest"
        pos: Starting source position
        end: Ending source position
        op: The operator string
        op_pos: Position of the operator
        x: Left operand
        y: Right operand
    """
    type: str = "BinaryTest"
    op: str = None
    op_pos: Position = None
    x: Optional['Node'] = None
    y: Optional['Node'] = None


@dataclass
class ParenTest(Node):
    """Parenthesized test: ( expr ).

    Represents a test expression wrapped in parentheses to control
    evaluation order in complex test conditions.

    Attributes:
        type: Always "ParenTest"
        pos: Starting source position
        end: Ending source position
        lparen: Position of the opening parenthesis
        rparen: Position of the closing parenthesis
        x: The inner test expression
    """
    type: str = "ParenTest"
    lparen: Position = None
    rparen: Position = None
    x: Optional['Node'] = None


@dataclass
class ArithmCmd(Node):
    """Arithmetic command: (( expr ))."""
    type: str = "ArithmCmd"
    left: Position = None
    right: Position = None
    x: Optional['Node'] = None


@dataclass
class UnaryArithm(Node):
    """Unary arithmetic: -x, !x, x++, x--."""
    type: str = "UnaryArithm"
    op: str = None
    op_pos: Position = None
    post: bool = False
    x: Optional['Node'] = None


@dataclass
class ParenArithm(Node):
    """Parenthesized arithmetic: (expr)."""
    type: str = "ParenArithm"
    lparen: Position = None
    rparen: Position = None
    x: Optional['Node'] = None


@dataclass
class FlagsArithm(Node):
    """Zsh subscript flags: ${array[(flags)expr]}."""
    type: str = "FlagsArithm"
    flags: Optional['Lit'] = None
    x: Optional['Node'] = None


@dataclass
class LetClause(Node):
    """Let statement: let expr."""
    type: str = "LetClause"
    let_pos: Position = None
    exprs: List['Node'] = None


@dataclass
class TimeClause(Node):
    """Time-prefixed command: time cmd."""
    type: str = "TimeClause"
    time_pos: Position = None
    posix_format: bool = False
    stmt: Optional['Node'] = None


@dataclass
class CoprocClause(Node):
    """Coprocess: coproc NAME { cmd }."""
    type: str = "CoprocClause"
    coproc_pos: Position = None
    name: Optional['Word'] = None
    stmt: Optional['Node'] = None


@dataclass
class TestDecl(Node):
    """Bats test: @test "description" { body }."""
    type: str = "TestDecl"
    description: Optional['Word'] = None
    body: Optional['Node'] = None


@dataclass
class Comment(Node):
    """Shell comment: # text."""
    type: str = "Comment"
    hash_pos: Position = None
    text: str = ""


@dataclass
class Assign(Node):
    """Variable assignment: var=val, arr[i]=val, var+=val."""
    type: str = "Assign"
    name: Optional['Lit'] = None
    index: Optional['Node'] = None
    value: Optional['Word'] = None
    array: Optional['Node'] = None
    append: bool = False
    naked: bool = False


@dataclass
class CaseItem(Node):
    """Case statement branch: patterns) stmts;;"""
    type: str = "CaseItem"
    op: str = None
    patterns: List['Word'] = None
    stmts: List['Node'] = None


@dataclass
class WordIter(Node):
    """For-loop word iteration: for var in words."""
    type: str = "WordIter"
    name: Optional['Lit'] = None
    items: List['Word'] = None


@dataclass
class CStyleLoop(Node):
    """C-style for loop: for (init; cond; post)."""
    type: str = "CStyleLoop"
    init: Optional['Node'] = None
    cond: Optional['Node'] = None
    post: Optional['Node'] = None


@dataclass
class ArrayExpr(Node):
    """Array expression: ( elem1 elem2 )."""
    type: str = "ArrayExpr"
    elems: List['Node'] = None


@dataclass
class ArrayElem(Node):
    """Array element: index=value or just value."""
    type: str = "ArrayElem"
    index: Optional['Node'] = None
    value: Optional['Word'] = None


def redir_from_json(data: dict) -> Redir:
    """Convert shfmt JSON redirection data to a typed Redir object.
    
    Args:
        data: shfmt JSON object representing a redirection
    
    Returns:
        Redir: Typed redirection object with operator and target word
    """
    return Redir(
        op=data.get("Op", ""),
        word=word_from_json(data.get("Word")),
        pos=_parse_position(data.get("Pos")),
        end=_parse_position(data.get("End")),
        op_pos=_parse_position(data.get("OpPos")),
    )

@dataclass
class Stmt:
    """A bash statement.
    
    A statement wraps a command with its associated position and optional
    file redirections. Each statement in a script corresponds to one line
    of execution (or a multi-line logical unit).
    
    Example: "cat file.txt > output.txt" has a Stmt with cmd=CallExpr
    and redirs=[Redir(op='>', word='output.txt')]
    
    Attributes:
        cmd: The command node (CallExpr, BinaryCmd, Subshell, etc.)
        position: shfmt's position field (alternative to pos)
        pos: Starting source position
        end: Ending source position
        redirs: List of Redir objects applied to this statement
    """
    cmd: 'Node' = None
    position: Position = None
    pos: Position = None
    end: Position = None
    redirs: Optional[List['Redir']] = None


@dataclass
class File(Node):
    """Top-level file node wrapping all statements.
    
    The root of every parsed bash command tree. Contains a list of
    statements representing all commands in the input.
    
    Example: "ls -la; echo done" produces a File node with two
    statements in the stmts list.
    
    Attributes:
        stmts: List of Stmt objects representing all commands
    """
    stmts: List['Stmt'] = None


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


def node_from_json(data: dict) -> Node:
    """Convert shfmt JSON node data to a typed AST node.
    
    Maps shfmt's node type names to appropriate Python dataclasses using
    the NODE_TYPES mapping. Unknown types are wrapped in generic Node
    objects with their type name preserved.
    
    Args:
        data: shfmt JSON object representing a single node
    
    Returns:
        Node: Appropriately typed AST node (File, CallExpr, BinaryCmd, etc.)
    """
    node_type = data.get("Type", "")
    
    # Handle nodes that have 'Cmd' but no 'Type' (wrapped statements)
    if not node_type and "Cmd" in data:
        return node_from_json(data["Cmd"])
    
    if node_type not in NODE_TYPES:
        return Node(
            type=node_type,
            pos=_parse_position(data.get("Pos")),
            end=_parse_position(data.get("End")),
        )
    
    cls = NODE_TYPES[node_type]
    
    if node_type == "File":
        return File(
            type=node_type,
            pos=_parse_position(data.get("Pos")),
            end=_parse_position(data.get("End")),
            stmts=[stmt_from_json(s) for s in data.get("Stmts", [])],
        )
    elif node_type == "Stmt":
        return stmt_from_json(data)
    elif node_type == "CallExpr":
        # Capture Assigns separately (variable assignments like files=$(...))
        assigns_raw = data.get("Assigns")
        extra = None
        if assigns_raw:
            extra = {"assigns": assigns_raw}
        return CallExpr(
            type=node_type,
            pos=_parse_position(data.get("Pos")),
            end=_parse_position(data.get("End")),
            args=[word_from_json(a) for a in data.get("Args", [])],
            extra=extra,
        )
    elif node_type == "BinaryCmd":
        x = data.get("X")
        y = data.get("Y")
        x_node = node_from_json(x)
        y_node = node_from_json(y)
        return BinaryCmd(
            type=node_type,
            pos=_parse_position(data.get("Pos")),
            end=_parse_position(data.get("End")),
            op=data.get("Op", ""),
            x=x_node,
            y=y_node,
            redirs=None,
        )
    elif node_type == "DeclClause":
        # Export/declare/readonly: convert Arg objects (with name/value) to Words
        words = []
        for arg in data.get("Args", []):
            if isinstance(arg, dict):
                # Extract the value part as a Word-like structure
                val = arg.get("value", arg.get("Value", {}))
                # Build a minimal Word from the value
                if val:
                    w = Word(
                        type="Word",
                        pos=_parse_position(val.get("Pos")),
                        end=_parse_position(val.get("End")),
                        parts=[],
                    )
                    if "Parts" in val:
                        for p in val["Parts"]:
                            w.parts.append(part_from_json(p))
                    words.append(w)
        return Node(
            type=node_type,
            pos=_parse_position(data.get("Pos")),
            end=_parse_position(data.get("End")),
            args=words,
        )
    elif node_type == "Word":
        return word_from_json(data)
    elif node_type == "Lit":
        return Lit(
            type=node_type,
            pos=_parse_position(data.get("Pos")),
            end=_parse_position(data.get("End")),
            value=data.get("Value", ""),
            value_pos=_parse_position(data.get("ValuePos")),
            value_end=_parse_position(data.get("ValueEnd")),
        )
    elif node_type == "Subshell":
        return Subshell(
            type=node_type,
            pos=_parse_position(data.get("Pos")),
            end=_parse_position(data.get("End")),
            stmts=[stmt_from_json(s) for s in data.get("Stmts", [])],
        )
    elif node_type == "IfClause":
        # Cond/Then/Else may be a string field name (e.g. "Pos") or dict/list
        cond_raw = data.get("Cond", [])
        then_raw = data.get("Then", [])
        else_raw = data.get("Else")
        
        cond = []
        if isinstance(cond_raw, list):
            for item in cond_raw:
                if isinstance(item, dict) and "Cmd" in item:
                    cond.append(stmt_from_json(item))
        
        then = []
        if isinstance(then_raw, list):
            for item in then_raw:
                if isinstance(item, dict) and "Cmd" in item:
                    then.append(stmt_from_json(item))
        
        elif_branches = []
        for b in data.get("Elif", []):
            if isinstance(b, dict):
                b_cond = []
                b_body = []
                c_raw = b.get("Cond", [])
                if isinstance(c_raw, list):
                    for item in c_raw:
                        if isinstance(item, dict) and "Cmd" in item:
                            b_cond.append(stmt_from_json(item))
                body_raw = b.get("Then", b.get("Body", []))
                if isinstance(body_raw, list):
                    for item in body_raw:
                        if isinstance(item, dict) and "Cmd" in item:
                            b_body.append(stmt_from_json(item))
                elif_branches.append({"cond": b_cond, "body": b_body})
        
        else_branch = []
        if isinstance(else_raw, dict):
            # Check if it's an elif (nested if) or a plain else body
            # shfmt represents elif as a nested structure in Else without a Type field,
            # but with a Cond field indicating an elif condition.
            if "Cond" in else_raw:
                # elif branch: has Cond, Then, and possibly nested Else
                nested_cond_raw = else_raw.get("Cond", [])
                nested_then_raw = else_raw.get("Then", [])
                nested_else_raw = else_raw.get("Else")
                
                nested_cond = []
                if isinstance(nested_cond_raw, list):
                    for item in nested_cond_raw:
                        if isinstance(item, dict) and "Cmd" in item:
                            nested_cond.append(stmt_from_json(item))
                
                nested_then = []
                if isinstance(nested_then_raw, list):
                    for item in nested_then_raw:
                        if isinstance(item, dict) and "Cmd" in item:
                            nested_then.append(stmt_from_json(item))
                
                elif_branches.append({"cond": nested_cond, "body": nested_then})
                
                # Process nested else recursively
                if isinstance(nested_else_raw, dict):
                    if "Cond" in nested_else_raw:
                        # Another elif - convert recursively
                        nested_nested = node_from_json(nested_else_raw)
                        elif_branches.extend(nested_nested.elif_branches)
                        else_branch = nested_nested.else_branch
                    else:
                        # Plain else body
                        nested_nested_then = nested_else_raw.get("Then", [])
                        if isinstance(nested_nested_then, list):
                            for item in nested_nested_then:
                                if isinstance(item, dict) and "Cmd" in item:
                                    else_branch.append(stmt_from_json(item))
                elif isinstance(nested_else_raw, list):
                    for item in nested_else_raw:
                        if isinstance(item, dict) and "Cmd" in item:
                            else_branch.append(stmt_from_json(item))
            else:
                # Plain else body
                nested_then = else_raw.get("Then", [])
                if isinstance(nested_then, list):
                    for item in nested_then:
                        if isinstance(item, dict) and "Cmd" in item:
                            else_branch.append(stmt_from_json(item))
        elif isinstance(else_raw, list):
            for item in else_raw:
                if isinstance(item, dict) and "Cmd" in item:
                    else_branch.append(stmt_from_json(item))
        
        return IfClause(
            type=node_type,
            pos=_parse_position(data.get("Pos")),
            end=_parse_position(data.get("End")),
            cond=cond,
            then=then,
            elif_branches=elif_branches,
            else_branch=else_branch,
        )
    elif node_type == "ForClause":
        # ForClause has "Loop" field with "Type": "WordIter"
        # Name is a simple value dict with "Value"
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
        
        body = []
        do_raw = data.get("Do", [])
        if isinstance(do_raw, list):
            for s in do_raw:
                if isinstance(s, dict) and "Cmd" in s:
                    body.append(stmt_from_json(s))
        
        return ForClause(
            type=node_type,
            pos=_parse_position(data.get("Pos")),
            end=_parse_position(data.get("End")),
            var=None if var_name is None else Word(
                type="Word",
                parts=[Part(type="Lit", value=var_name)],
            ),
            words=items,
            body=body,
        )
    elif node_type == "WhileClause":
        return WhileClause(
            type=node_type,
            pos=_parse_position(data.get("Pos")),
            end=_parse_position(data.get("End")),
            cond=[stmt_from_json(s) for s in data.get("Cond", [])],
            body=[stmt_from_json(s) for s in data.get("Do", [])],
        )
    elif node_type == "AndCmd":
        return AndCmd(
            type=node_type,
            pos=_parse_position(data.get("Pos")),
            end=_parse_position(data.get("End")),
            x=node_from_json(data.get("X")),
            y=node_from_json(data.get("Y")),
        )
    elif node_type == "OrCmd":
        return OrCmd(
            type=node_type,
            pos=_parse_position(data.get("Pos")),
            end=_parse_position(data.get("End")),
            x=node_from_json(data.get("X")),
            y=node_from_json(data.get("Y")),
        )
    elif node_type == "CaseClause":
        return CaseClause(
            type=node_type,
            pos=_parse_position(data.get("Pos")),
            end=_parse_position(data.get("End")),
            expr=word_from_json(data.get("Expr")),
            branches=[
                {
                    "patterns": [word_from_json(w) for w in b.get("Patterns", [])],
                    "body": [stmt_from_json(s) for s in b.get("Body", [])],
                }
                for b in data.get("Branches", [])
            ],
            default=[stmt_from_json(s) for s in data.get("Default", [])],
        )
    elif node_type == "ArithmExp":
        return ArithmExp(
            type=node_type,
            pos=_parse_position(data.get("Pos")),
            end=_parse_position(data.get("End")),
            x=node_from_json(data.get("X")),
        )
    elif node_type == "BinaryArithm":
        return BinaryArithm(
            type=node_type,
            pos=_parse_position(data.get("Pos")),
            end=_parse_position(data.get("End")),
            op=data.get("Op", ""),
            op_pos=_parse_position(data.get("OpPos")),
            x=node_from_json(data.get("X")),
            y=node_from_json(data.get("Y")),
        )
    elif node_type == "ExtGlob":
        pattern_data = data.get("Pattern", {})
        return ExtGlob(
            type=node_type,
            pos=_parse_position(data.get("Pos")),
            end=_parse_position(data.get("End")),
            op=data.get("Op", ""),
            op_pos=_parse_position(data.get("OpPos")),
            pattern=Lit(
                type="Lit",
                pos=_parse_position(pattern_data.get("Pos")),
                end=_parse_position(pattern_data.get("End")),
                value=pattern_data.get("Value", ""),
                value_pos=_parse_position(pattern_data.get("ValuePos")),
                value_end=_parse_position(pattern_data.get("ValueEnd")),
            ),
        )
    elif node_type == "Block":
        return Block(
            type=node_type,
            pos=_parse_position(data.get("Pos")),
            end=_parse_position(data.get("End")),
            lbrace=_parse_position(data.get("Lbrace")),
            rbrace=_parse_position(data.get("Rbrace")),
            stmts=[stmt_from_json(s) for s in data.get("Stmts", [])],
        )
    elif node_type == "FuncDecl":
        # Name is a Lit node
        name_data = data.get("Name", {})
        name_node = Lit(
            type="Lit",
            pos=_parse_position(name_data.get("Pos")),
            end=_parse_position(name_data.get("End")),
            value=name_data.get("Value", ""),
            value_pos=_parse_position(name_data.get("ValuePos")),
            value_end=_parse_position(name_data.get("ValueEnd")),
        )
        # Body is a Stmt that wraps a Block (cmd field inside Body contains the Block)
        body_data = data.get("Body")
        body_node = None
        if isinstance(body_data, dict):
            # Body has a "Cmd" field that wraps the Block
            if "Cmd" in body_data:
                body_node = node_from_json(body_data["Cmd"])
            else:
                body_node = node_from_json(body_data)
        return FuncDecl(
            type=node_type,
            pos=_parse_position(data.get("Pos")),
            end=_parse_position(data.get("End")),
            rsrv_word=data.get("RsrvWord", False),
            parens=data.get("Parens", False),
            name=name_node,
            body=body_node,
        )
    elif node_type == "TestClause":
        return TestClause(
            type=node_type,
            pos=_parse_position(data.get("Pos")),
            end=_parse_position(data.get("End")),
            left=_parse_position(data.get("Left")),
            right=_parse_position(data.get("Right")),
            x=node_from_json(data.get("X")),
        )
    elif node_type == "UnaryTest":
        return UnaryTest(
            type=node_type,
            pos=_parse_position(data.get("Pos")),
            end=_parse_position(data.get("End")),
            op=data.get("Op", ""),
            op_pos=_parse_position(data.get("OpPos")),
            x=node_from_json(data.get("X")),
        )
    elif node_type == "BinaryTest":
        return BinaryTest(
            type=node_type,
            pos=_parse_position(data.get("Pos")),
            end=_parse_position(data.get("End")),
            op=data.get("Op", ""),
            op_pos=_parse_position(data.get("OpPos")),
            x=node_from_json(data.get("X")),
            y=node_from_json(data.get("Y")),
        )
    elif node_type == "ParenTest":
        return ParenTest(
            type=node_type,
            pos=_parse_position(data.get("Pos")),
            end=_parse_position(data.get("End")),
            lparen=_parse_position(data.get("Lparen")),
            rparen=_parse_position(data.get("Rparen")),
            x=node_from_json(data.get("X")),
        )
    elif node_type == "ArithmCmd":
        return ArithmCmd(
            type=node_type,
            pos=_parse_position(data.get("Pos")),
            end=_parse_position(data.get("End")),
            left=_parse_position(data.get("Left")),
            right=_parse_position(data.get("Right")),
            x=node_from_json(data.get("X")),
        )
    elif node_type == "UnaryArithm":
        return UnaryArithm(
            type=node_type,
            pos=_parse_position(data.get("Pos")),
            end=_parse_position(data.get("End")),
            op=data.get("Op", ""),
            op_pos=_parse_position(data.get("OpPos")),
            post=data.get("Post", False),
            x=node_from_json(data.get("X")),
        )
    elif node_type == "ParenArithm":
        return ParenArithm(
            type=node_type,
            pos=_parse_position(data.get("Pos")),
            end=_parse_position(data.get("End")),
            lparen=_parse_position(data.get("Lparen")),
            rparen=_parse_position(data.get("Rparen")),
            x=node_from_json(data.get("X")),
        )
    elif node_type == "FlagsArithm":
        return FlagsArithm(
            type=node_type,
            pos=_parse_position(data.get("Pos")),
            end=_parse_position(data.get("End")),
            flags=Lit(type="Lit", value=data.get("Flags", "")),
            x=node_from_json(data.get("X")),
        )
    elif node_type == "LetClause":
        return LetClause(
            type=node_type,
            pos=_parse_position(data.get("Pos")),
            end=_parse_position(data.get("End")),
            let_pos=_parse_position(data.get("Let")),
            exprs=[node_from_json(e) for e in data.get("Exprs", [])],
        )
    elif node_type == "TimeClause":
        return TimeClause(
            type=node_type,
            pos=_parse_position(data.get("Pos")),
            end=_parse_position(data.get("End")),
            time_pos=_parse_position(data.get("Time")),
            posix_format=data.get("PosixFormat", False),
            stmt=node_from_json(data.get("Stmt")),
        )
    elif node_type == "CoprocClause":
        return CoprocClause(
            type=node_type,
            pos=_parse_position(data.get("Pos")),
            end=_parse_position(data.get("End")),
            coproc_pos=_parse_position(data.get("Coproc")),
            name=word_from_json(data.get("Name")),
            stmt=node_from_json(data.get("Stmt")),
        )
    elif node_type == "TestDecl":
        return TestDecl(
            type=node_type,
            pos=_parse_position(data.get("Pos")),
            end=_parse_position(data.get("End")),
            description=word_from_json(data.get("Description")),
            body=node_from_json(data.get("Body")),
        )
    elif node_type == "Comment":
        return Comment(
            type=node_type,
            hash_pos=_parse_position(data.get("Hash")),
            text=data.get("Text", ""),
        )
    elif node_type == "Assign":
        return Assign(
            type=node_type,
            pos=_parse_position(data.get("Pos")),
            end=_parse_position(data.get("End")),
            name=Lit(type="Lit", value=data.get("Name", "")),
            index=node_from_json(data.get("Index")),
            value=word_from_json(data.get("Value")),
            array=node_from_json(data.get("Array")),
            append=data.get("Append", False),
            naked=data.get("Naked", False),
        )
    elif node_type == "CaseItem":
        return CaseItem(
            type=node_type,
            pos=_parse_position(data.get("Pos")),
            end=_parse_position(data.get("End")),
            op=data.get("Op", ""),
            patterns=[word_from_json(w) for w in data.get("Patterns", [])],
            stmts=[stmt_from_json(s) for s in data.get("Stmts", [])],
        )
    elif node_type == "WordIter":
        return WordIter(
            type=node_type,
            pos=_parse_position(data.get("Pos")),
            end=_parse_position(data.get("End")),
            name=Lit(type="Lit", value=data.get("Name", "")),
            items=[word_from_json(w) for w in data.get("Items", [])],
        )
    elif node_type == "CStyleLoop":
        return CStyleLoop(
            type=node_type,
            pos=_parse_position(data.get("Pos")),
            end=_parse_position(data.get("End")),
            init=node_from_json(data.get("Init")),
            cond=node_from_json(data.get("Cond")),
            post=node_from_json(data.get("Post")),
        )
    elif node_type == "ArrayExpr":
        return ArrayExpr(
            type=node_type,
            pos=_parse_position(data.get("Pos")),
            end=_parse_position(data.get("End")),
            elems=[node_from_json(e) for e in data.get("Elems", [])],
        )
    elif node_type == "ArrayElem":
        return ArrayElem(
            type=node_type,
            pos=_parse_position(data.get("Pos")),
            end=_parse_position(data.get("End")),
            index=node_from_json(data.get("Index")),
            value=word_from_json(data.get("Value")),
        )
    
    return Node(
        type=node_type,
        pos=_parse_position(data.get("Pos")),
        end=_parse_position(data.get("End")),
    )


def stmt_from_json(data: dict) -> Stmt:
    """Convert shfmt JSON statement data to a typed Stmt object.
    
    Parses the command within the statement and extracts any associated
    file redirections.
    
    Args:
        data: shfmt JSON object representing a statement
    
    Returns:
        Stmt: Typed statement with parsed command and redirections
    """
    cmd_json = data.get("Cmd")
    cmd = node_from_json(cmd_json)
    redirs = None
    if "Redirs" in data:
        redirs = [redir_from_json(r) for r in data.get("Redirs", [])]
    elif cmd.type == "BinaryCmd":
        # Redirects on Y side of pipes should be on the statement, not BinaryCmd
        y_json = cmd_json.get("Y")
        if isinstance(y_json, dict) and "Redirs" in y_json:
            redirs = [redir_from_json(r) for r in y_json.get("Redirs", [])]
    return Stmt(
        cmd=cmd,
        position=_parse_position(data.get("Position")),
        pos=_parse_position(data.get("Pos")),
        end=_parse_position(data.get("End")),
        redirs=redirs,
    )


def word_from_json(data: dict) -> Word:
    """Convert shfmt JSON word data to a typed Word object.
    
    Parses all parts of the word (literals, variables, expansions) and
    constructs a complete Word node.
    
    Args:
        data: shfmt JSON object representing a word
    
    Returns:
        Word: Typed word with parsed parts
    """
    parts = [part_from_json(p) for p in data.get("Parts", [])]
    return Word(
        type="Word",
        pos=_parse_position(data.get("Pos")),
        end=_parse_position(data.get("End")),
        parts=parts,
    )


def part_from_json(data: dict) -> Part:
    """Convert shfmt JSON part data to a typed Part object.
    
    Handles all part types: literals, variables, parameter expansions,
    command substitutions, quoted strings, etc.
    
    Args:
        data: shfmt JSON object representing a word part
    
    Returns:
        Part: Typed part object
    """
    parts = None
    if "Parts" in data:
        parts = [part_from_json(p) for p in data.get("Parts", [])]
    
    # For DblQuoted, the value is the concatenation of inner parts
    value = data.get("Value")
    if data.get("Type") == "DblQuoted" and parts:
        value = "".join(str(p.value) if hasattr(p, "value") and p.value is not None else "" for p in parts)
    
    if data.get("Type") == "Lit":
        return Lit(
            type="Lit",
            pos=_parse_position(data.get("Pos")),
            end=_parse_position(data.get("End")),
            value=data.get("Value", ""),
            value_pos=_parse_position(data.get("ValuePos")),
            value_end=_parse_position(data.get("ValueEnd")),
        )
    elif data.get("Type") == "SglQuoted":
        return SglQuoted(
            type="SglQuoted",
            pos=_parse_position(data.get("Pos")),
            end=_parse_position(data.get("End")),
            value=data.get("Value", ""),
        )
    elif data.get("Type") == "CmdSubst":
        return CmdSubst(
            type="CmdSubst",
            pos=_parse_position(data.get("Pos")),
            end=_parse_position(data.get("End")),
            stmts=[stmt_from_json(s) for s in data.get("Stmts", [])],
            backquotes=data.get("Backquotes", False),
        )
    elif data.get("Type") == "ProcSubst":
        return ProcSubst(
            type="ProcSubst",
            pos=_parse_position(data.get("Pos")),
            end=_parse_position(data.get("End")),
            op=data.get("Op", ""),
            op_pos=_parse_position(data.get("OpPos")),
            rparen=_parse_position(data.get("Rparen")),
            stmts=[stmt_from_json(s) for s in data.get("Stmts", [])],
        )
    elif data.get("Type") == "ParamExp":
        # Extract parameter name from the Param field
        param_data = data.get("Param", {})
        param_value = ""
        if isinstance(param_data, dict):
            param_value = param_data.get("Value", "")
        # Extract index (if present)
        index_data = data.get("Index")
        index_node = None
        if isinstance(index_data, dict):
            index_node = word_from_json(index_data)
        # Extract exp (if present)
        exp_data = data.get("Exp")
        exp_value = None
        if isinstance(exp_data, dict):
            exp_value = exp_data
        return ParamExp(
            type="ParamExp",
            pos=_parse_position(data.get("Pos")),
            end=_parse_position(data.get("End")),
            param=param_value,
            short=data.get("Short", False),
            exp=exp_value,
            index=index_node,
            length=data.get("Length", False),
            dollar_pos=_parse_position(data.get("Dollar")),
        )
    elif data.get("Type") == "ArithmExp":
        # Arithmetic expansion: $((...))
        return ArithmExp(
            type="ArithmExp",
            pos=_parse_position(data.get("Pos")),
            end=_parse_position(data.get("End")),
            x=node_from_json(data.get("X")),
        )
    elif data.get("Type") == "ExtGlob":
        pattern_data = data.get("Pattern", {})
        return ExtGlob(
            type="ExtGlob",
            pos=_parse_position(data.get("Pos")),
            end=_parse_position(data.get("End")),
            op=data.get("Op", ""),
            op_pos=_parse_position(data.get("OpPos")),
            pattern=Lit(
                type="Lit",
                pos=_parse_position(pattern_data.get("Pos")),
                end=_parse_position(pattern_data.get("End")),
                value=pattern_data.get("Value", ""),
                value_pos=_parse_position(pattern_data.get("ValuePos")),
                value_end=_parse_position(pattern_data.get("ValueEnd")),
            ),
        )
    
    return Part(
        type=data.get("Type", ""),
        pos=_parse_position(data.get("Pos")),
        end=_parse_position(data.get("End")),
        value=value,
        parts=parts,
        extra=data.get("Stmts") if data.get("Type") == "CmdSubst" else None,
    )


def _parse_position(data: dict) -> Position:
    """Parse source position data from shfmt JSON.
    
    Args:
        data: shfmt JSON position object with Offset, Line, Col fields
    
    Returns:
        Position: Typed position object
    """
    return Position(
        offset=data.get("Offset", 0),
        line=data.get("Line", 0),
        col=data.get("Col", 0),
    )


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
    
    Example:
        tree = parse_ast('ls -la | grep txt')
        print(tree.type)        # 'File'
        print(len(tree.stmts))  # 1
        print(tree.stmts[0].cmd.type)  # 'BinaryCmd'
    """
    from .parser import parse
    raw = parse(command)
    return node_from_json(raw)
