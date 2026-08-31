# Plan: Complete Node Type Coverage (Agent-Ready Implementation Guide)

## Goal
Add all missing SHFMT node types as Python dataclasses to achieve 1-to-1 mapping with shfmt's AST.

This document is structured as a series of self-contained steps that can be executed by AI coding agents (Pi). Each step provides:
- The node types to implement
- The Go reference implementation (from mvdan/sh)
- The Python dataclass specification
- Required parser changes
- Test cases
- Dependencies on prior steps

## Current State

**Implemented (13):**
```
File, Stmt, CallExpr, Word, Redir, Subshell, IfClause, ForClause,
WhileClause, AndCmd, OrCmd, CaseClause, BinaryCmd
```

**Missing (30):**
```
Comment, Assign, Lit, SglQuoted, DblQuoted, ParamExp, CmdSubst,
ArithmExp, ProcSubst, ExtGlob, BraceExp, ArithmCmd, FuncDecl,
TestClause, LetClause, TimeClause, CoprocClause, TestDecl,
UnaryArithm, BinaryArithm, ParenArithm, FlagsArithm, UnaryTest,
BinaryTest, ParenTest, WordIter, CStyleLoop, CaseItem, ArrayExpr,
ArrayElem, Block
```

**Total SHFMT types: 43**

## Important: Read Before Starting

1. **Reference Implementation**: All node types are defined in https://github.com/mvdan/sh
2. **SHFMT CLI**: Run `/home/alx/repos/lovely-bash-permissions/.venv/bin/shfmt --to-json` on bash commands to inspect JSON output
3. **Existing Tests**: Run `uv run pytest` to verify nothing breaks
4. **Test Commands**: Run `uv run pytest tests/test_*.py -v` for detailed results

## Agent Workflow
For each step:
1. Read the node type specification below
2. Check existing `ast.py` for the mapping pattern
3. Implement the Python dataclass
4. Add to `NODE_TYPES` mapping
5. Update `node_from_json()` if needed
6. Add visitor method if needed
7. Write tests in `tests/test_nodes.py`
8. Run the test suite
9. Verify with a real bash command example

## [x] Step 1: Lit (Simple Literal)

Completed: Lit dataclass implemented in ast.py, registered in NODE_TYPES, parser updated, 19 tests added in test_parser.py::TestLitNodes. All 121 tests pass.

**Priority**: HIGH

**Go Reference**:
```go
type Lit struct {
    ValuePos, ValueEnd Pos
    Value              string
}
```

**Python Implementation**:
```python
@dataclass
class Lit(Node):
    """A shell literal string without any special characters."""
    type: str = "Lit"
    value: str = ""
    value_pos: Position = None
    value_end: Position = None
```

**Parser Changes**:
- Add to `NODE_TYPES`: `"Lit": Lit`
- In `part_from_json()`, handle `Type: "Lit"` → return `Lit` instance

**Test Cases**:
```bash
# Input: echo hello
# Expected: Word with single Lit part {type: "Lit", value: "hello"}

# Input: cat file.txt
# Expected: Word with Lit {type: "Lit", value: "file.txt"}
```

**Verification**:
```bash
/home/alx/repos/lovely-bash-permissions/.venv/bin/shfmt --to-json <<< "echo hello"
```

## [x] Step 2: SglQuoted (Single-Quoted String)

Completed: SglQuoted dataclass implemented in ast.py with comprehensive documentation, registered in NODE_TYPES, parser updated in part_from_json(), imported in inspect.py, exported from __init__.py. Added TestSglQuotedNodes test class with 9 test cases in test_parser.py. All 130 tests pass (121 existing + 9 new). Tested echo 'hello world', echo '$HOME' (no expansion), echo 'a' 'b', echo 'foo*', echo '', echo 'foo\\bar', echo '$', and position info. Verified with shfmt --to-json.

**Priority**: HIGH

**Go Reference**:
```go
type SglQuoted struct {
    Left, Right Pos
    Dollar      bool // $''
    Value       string
}
```

**Python Implementation**:
```python
@dataclass
class SglQuoted(Node):
    """A single-quoted string (no expansions inside)."""
    type: str = "SglQuoted"
    left: Position = None
    right: Position = None
    dollar: bool = False  # For $'' ANSI-C quoting
    value: str = ""
```

**Parser Changes**:
- Add to `NODE_TYPES`: `"SglQuoted": SglQuoted`
- Handle in `part_from_json()`

**Test Cases**:
```bash
# Input: echo 'hello world'
# Expected: Word with single SglQuoted part {type: "SglQuoted", value: "hello world"}

# Input: echo 'single $var'
# Expected: SglQuoted with value="single $var" (no expansion)
```

**Verification**:
```bash
/home/alx/repos/lovely-bash-permissions/.venv/bin/shfmt --to-json <<< "echo 'hello world'"
```

**Dependencies**: None

## [x] Step 3: DblQuoted (Double-Quoted String) (depends on: 1,2,4)

Completed: DblQuoted dataclass implemented in ast.py with parts field, registered in NODE_TYPES, parser updated in part_from_json(), 10 comprehensive tests added in TestDblQuotedNodes. All 153 tests pass (143 existing + 10 new). Tested nested parts, variable expansion, empty quotes, escape sequences, position info.

**Priority**: HIGH

**Go Reference**:
```go
type DblQuoted struct {
    Left, Right Pos
    Dollar      bool // $""
    Parts       []WordPart
}
```

**Python Implementation**:
```python
@dataclass
class DblQuoted(Node):
    """A double-quoted string that allows nested expansions."""
    type: str = "DblQuoted"
    left: Position = None
    right: Position = None
    dollar: bool = False
    parts: List['WordPart'] = None  # Can contain Lit, SglQuoted, ParamExp, CmdSubst, etc.
```

**Parser Changes**:
- Add to `NODE_TYPES`: `"DblQuoted": DblQuoted`
- Handle in `part_from_json()`
- Parts inside will be recursively parsed

**Test Cases**:
```bash
# Input: echo "hello $world"
# Expected: Word with single DblQuoted part
#   DblQuoted.parts = [Lit("hello "), ParamExp("world")]

# Input: echo "$USER is here"
# Expected: Word with DblQuoted containing [ParamExp("USER"), Lit(" is here")]
```

**Verification**:
```bash
/home/alx/repos/lovely-bash-permissions/.venv/bin/shfmt --to-json <<< 'echo "hello $world"'
```

**Dependencies**: Step 1 (Lit), Step 2 (SglQuoted), Step 4 (ParamExp)

## [x] Step 4: ParamExp (Parameter Expansion)

Completed: ParamExp dataclass implemented in ast.py with param, short, exp, index, length, dollar_pos fields. Registered in NODE_TYPES. Updated part_from_json() to parse ParamExp nodes. Added 13 new test cases in TestParamExpNodes. All 142 tests pass (129 existing + 13 new). Tested $HOME, ${HOME}, ${HOME:-default}, ${array[0]}, ${#VAR}, etc.

**Priority**: HIGH

**Go Reference**:
```go
type ParamExp struct {
    Dollar, Rbrace Pos
    Short bool       // $a instead of ${a}
    Param *Lit       // $var
    Index ArithmExpr // ${arr[i]}
    Exp   *Expansion // ${a:-default}, ${a%pattern}, etc.
}

type Expansion struct {
    Op   ParExpOperator
    Word *Word
}
```

**Python Implementation**:
```python
@dataclass
class ParamExp(Node):
    """Parameter expansion: $var, ${var}, ${var:-default}, ${arr[i]}."""
    type: str = "ParamExp"
    short: bool = False      # $var vs ${var}
    param: Optional['Lit'] = None       # The variable name
    index: Optional['ArithmExpr'] = None # Array index
    exp: Optional['Expansion'] = None   # Default value / pattern replacement

@dataclass
class Expansion(Node):
    """Expansion operation details inside a ParamExp."""
    type: str = "Expansion"
    op: str = ""          # ":-", ":=", "%", "%%", "#", "##", etc.
    word: Optional['Word'] = None
```

**Parser Changes**:
- Add to `NODE_TYPES`: `"ParamExp": ParamExp, "Expansion": Expansion`
- Handle in `part_from_json()`

**Test Cases**:
```bash
# Input: echo $HOME
# Expected: Word with ParamExp {type: "ParamExp", short: true, param: Lit("HOME")}

# Input: echo ${HOME:-default}
# Expected: Word with ParamExp {type: "ParamExp", param: Lit("HOME"), exp: Expansion(op:":-", word:Word(Lit("default")))}

# Input: echo ${array[0]}
# Expected: Word with ParamExp {type: "ParamExp", param: Lit("array"), index: BinaryArithm(...)}
```

**Verification**:
```bash
/home/alx/repos/lovely-bash-permissions/.venv/bin/shfmt --to-json <<< "echo $HOME"
```

**Dependencies**: Step 1 (Lit)

## [ ] Step 5: CmdSubst (Command Substitution)

**Priority**: HIGH

**Go Reference**:
```go
type CmdSubst struct {
    Left, Right Pos
    Backquotes bool
    Stmts []*Stmt
}
```

**Python Implementation**:
```python
@dataclass
class CmdSubst(Node):
    """Command substitution: $(cmd) or `cmd`."""
    type: str = "CmdSubst"
    backquotes: bool = False
    stmts: List['Stmt'] = None
```

**Parser Changes**:
- Add to `NODE_TYPES`: `"CmdSubst": CmdSubst`
- Handle in `part_from_json()`

**Test Cases**:
```bash
# Input: echo $(date)
# Expected: Word with CmdSubst {type: "CmdSubst", stmts: [Stmt(CallExpr("date"))]}

# Input: echo `date`
# Expected: Word with CmdSubst {type: "CmdSubst", backquotes: true, stmts: ...}
```

**Verification**:
```bash
/home/alx/repos/lovely-bash-permissions/.venv/bin/shfmt --to-json <<< "echo $(date)"
```

**Dependencies**: None

## [ ] Step 6: ArithmExp (Arithmetic Expansion)

**Priority**: HIGH

**Go Reference**:
```go
type ArithmExp struct {
    Left, Right Pos
    Bracket     bool // $[expr]
    Unsigned    bool
    X ArithmExpr
}
```

**Python Implementation**:
```python
@dataclass
class ArithmExp(Node):
    """Arithmetic expansion: $((expr)) or $[expr]."""
    type: str = "ArithmExp"
    bracket: bool = False
    unsigned: bool = False
    x: Optional['ArithmExpr'] = None
```

**Parser Changes**:
- Add to `NODE_TYPES`: `"ArithmExp": ArithmExp`
- Handle in `part_from_json()`

**Test Cases**:
```bash
# Input: echo $((2 + 2))
# Expected: Word with ArithmExp containing the arithmetic expression
```

**Dependencies**: None

## [ ] Step 7: ProcSubst (Process Substitution)

**Priority**: MEDIUM

**Go Reference**:
```go
type ProcSubst struct {
    OpPos, Rparen Pos
    Op            ProcOperator
    Stmts []*Stmt
}
```

**Python Implementation**:
```python
@dataclass
class ProcSubst(Node):
    """Process substitution: <(cmd) or >(cmd)."""
    type: str = "ProcSubst"
    op: str = ""          # "<" or ">"
    stmts: List['Stmt'] = None
```

**Parser Changes**:
- Add to `NODE_TYPES`: `"ProcSubst": ProcSubst`
- Handle in `part_from_json()`

**Test Cases**:
```bash
# Input: cat <(echo "hi")
# Expected: Word with ProcSubst {op: "<", stmts: [...]}
```

**Verification**:
```bash
/home/alx/repos/lovely-bash-permissions/.venv/bin/shfmt --to-json <<< "cat <(echo 'hi')"
```

**Dependencies**: None

## [ ] Step 8: ExtGlob (Extended Glob)

**Priority**: LOW

**Go Reference**:
```go
type ExtGlob struct {
    OpPos   Pos
    Op      GlobOperator
    Pattern *Lit
}
```

**Python Implementation**:
```python
@dataclass
class ExtGlob(Node):
    """Extended glob: @(pattern), +(pattern), *(pattern), ?(pattern), !(pattern)."""
    type: str = "ExtGlob"
    op: str = ""          # "@", "+", "*", "?", "!"
    pattern: Optional['Lit'] = None
```

**Parser Changes**:
- Add to `NODE_TYPES`: `"ExtGlob": ExtGlob`
- Handle in `part_from_json()`

**Test Cases**:
```bash
# Input: ls *.@(txt|md)
# Expected: Word with ExtGlob {op: "@", pattern: "txt|md"}
```

**Dependencies**: None

## [ ] Step 9: BraceExp (Brace Expansion)

**Priority**: LOW

**Go Reference**:
```go
type BraceExp struct {
    Sequence bool
    Elems    []*Word
}
```

**Python Implementation**:
```python
@dataclass
class BraceExp(Node):
    """Brace expansion: {a,b} or {1..10}."""
    type: str = "BraceExp"
    sequence: bool = False
    elems: List['Word'] = None
```

**Parser Changes**:
- Add to `NODE_TYPES`: `"BraceExp": BraceExp`
- Handle in `part_from_json()`

**Test Cases**:
```bash
# Input: ls {file1,file2}.txt
# Expected: Word with BraceExp {elems: [...]}
```

**Dependencies**: None

## [ ] Step 10: Block (Curly-Brace Group)

**Priority**: HIGH

**Go Reference**:
```go
type Block struct {
    Lbrace, Rbrace Pos
    Stmts []*Stmt
    Last  []Comment
}
```

**Python Implementation**:
```python
@dataclass
class Block(Node):
    """Block of statements: { cmd1; cmd2; }."""
    type: str = "Block"
    lbrace: Position = None
    rbrace: Position = None
    stmts: List['Stmt'] = None
    last: List['Comment'] = None
```

**Parser Changes**:
- Add to `NODE_TYPES`: `"Block": Block`
- Handle in `node_from_json()`

**Test Cases**:
```bash
# Input: { echo "a"; echo "b"; }
# Expected: Cmd with Block containing 2 statements
```

**Verification**:
```bash
/home/alx/repos/lovely-bash-permissions/.venv/bin/shfmt --to-json <<< "{ echo 'a'; echo 'b'; }"
```

**Dependencies**: None

## [ ] Step 11: FuncDecl (Function Declaration)

**Priority**: HIGH

**Go Reference**:
```go
type FuncDecl struct {
    Position Pos
    RsrvWord bool // "function f" style
    Parens   bool // with () parentheses
    Name     *Lit
    Names    []*Lit // zsh style
    Body     *Stmt
}
```

**Python Implementation**:
```python
@dataclass
class FuncDecl(Node):
    """Function declaration: function name { body } or name() { body }."""
    type: str = "FuncDecl"
    rsrv_word: bool = False   # "function" keyword used
    parens: bool = False      # () used
    name: Optional['Lit'] = None
    names: List['Lit'] = None    # zsh style multiple names
    body: Optional['Stmt'] = None
```

**Parser Changes**:
- Add to `NODE_TYPES`: `"FuncDecl": FuncDecl`
- Handle in `node_from_json()`

**Test Cases**:
```bash
# Input: function hello() { echo "hi"; }
# Expected: Cmd with FuncDecl {rsrv_word: true, parens: true, name: "hello", body: ...}
```

**Verification**:
```bash
/home/alx/repos/lovely-bash-permissions/.venv/bin/shfmt --to-json <<< 'function hello() { echo "hi"; }'
```

**Dependencies**: Step 10 (Block), Step 1 (Lit)

## [ ] Step 12: TestClause (Extended Test)

**Priority**: MEDIUM

**Go Reference**:
```go
type TestClause struct {
    Left, Right Pos
    X TestExpr
}
```

**Python Implementation**:
```python
@dataclass
class TestClause(Node):
    """Extended test: [[ condition ]]."""
    type: str = "TestClause"
    left: Position = None
    right: Position = None
    x: Optional['TestExpr'] = None
```

**Parser Changes**:
- Add to `NODE_TYPES`: `"TestClause": TestClause`
- Handle in `node_from_json()`

**Test Cases**:
```bash
# Input: [[ -f file.txt ]]
# Expected: Cmd with TestClause {x: UnaryTest {op: "-f", x: Lit("file.txt")}}
```

**Verification**:
```bash
/home/alx/repos/lovely-bash-permissions/.venv/bin/shfmt --to-json <<< "[[ -f file.txt ]]"
```

**Dependencies**: Step 1 (Lit)

## [ ] Step 13: ArithmCmd (Arithmetic Command)

**Priority**: MEDIUM

**Go Reference**:
```go
type ArithmCmd struct {
    Left, Right Pos
    Unsigned    bool
    X ArithmExpr
}
```

**Python Implementation**:
```python
@dataclass
class ArithmCmd(Node):
    """Arithmetic command: (( expr ))."""
    type: str = "ArithmCmd"
    unsigned: bool = False
    x: Optional['ArithmExpr'] = None
```

**Parser Changes**:
- Add to `NODE_TYPES`: `"ArithmCmd": ArithmCmd`
- Handle in `node_from_json()`

**Test Cases**:
```bash
# Input: (( i = i + 1 ))
# Expected: Cmd with ArithmCmd {x: BinaryArithm {op: "=", ...}}
```

**Verification**:
```bash
/home/alx/repos/lovely-bash-permissions/.venv/bin/shfmt --to-json <<< "(( i = i + 1 ))"
```

**Dependencies**: None

## [ ] Step 14: LetClause (Let Statement)

**Priority**: LOW

**Go Reference**:
```go
type LetClause struct {
    Let   Pos
    Exprs []ArithmExpr
}
```

**Python Implementation**:
```python
@dataclass
class LetClause(Node):
    """Let statement: let expr."""
    type: str = "LetClause"
    exprs: List['ArithmExpr'] = None
```

**Parser Changes**:
- Add to `NODE_TYPES`: `"LetClause": LetClause`
- Handle in `node_from_json()`

**Test Cases**:
```bash
# Input: let i = 10
# Expected: Cmd with LetClause {exprs: [..., BinaryArithm{op:"=",...}]}
```

**Verification**:
```bash
/home/alx/repos/lovely-bash-permissions/.venv/bin/shfmt --to-json <<< "let i = 10"
```

**Dependencies**: None

## [ ] Step 15: TimeClause (Time-Prefixed Command)

**Priority**: LOW

**Go Reference**:
```go
type TimeClause struct {
    Time        Pos
    PosixFormat bool
    Stmt        *Stmt
}
```

**Python Implementation**:
```python
@dataclass
class TimeClause(Node):
    """Time-prefixed command: time cmd."""
    type: str = "TimeClause"
    posix_format: bool = False
    stmt: Optional['Stmt'] = None
```

**Parser Changes**:
- Add to `NODE_TYPES`: `"TimeClause": TimeClause`
- Handle in `node_from_json()`

**Test Cases**:
```bash
# Input: time sleep 5
# Expected: Cmd with TimeClause {stmt: Stmt(CallExpr("sleep"))}
```

**Verification**:
```bash
/home/alx/repos/lovely-bash-permissions/.venv/bin/shfmt --to-json <<< "time sleep 5"
```

**Dependencies**: None

## [ ] Step 16: CoprocClause (Coprocess)

**Priority**: LOW

**Go Reference**:
```go
type CoprocClause struct {
    Coproc Pos
    Name   *Word
    Stmt   *Stmt
}
```

**Python Implementation**:
```python
@dataclass
class CoprocClause(Node):
    """Coprocess: coproc NAME { cmd }."""
    type: str = "CoprocClause"
    name: Optional['Word'] = None
    stmt: Optional['Stmt'] = None
```

**Parser Changes**:
- Add to `NODE_TYPES`: `"CoprocClause": CoprocClause`
- Handle in `node_from_json()`

**Test Cases**:
```bash
# Input: coproc myproc { echo "hi"; }
# Expected: Cmd with CoprocClause {name: "myproc", stmt: ...}
```

**Verification**:
```bash
/home/alx/repos/lovely-bash-permissions/.venv/bin/shfmt --to-json <<< "coproc myproc { echo 'hi'; }"
```

**Dependencies**: Step 10 (Block)

## [ ] Step 17: TestDecl (Bats Test)

**Priority**: LOW

**Go Reference**:
```go
type TestDecl struct {
    Position    Pos
    Description *Word
    Body        *Stmt
}
```

**Python Implementation**:
```python
@dataclass
class TestDecl(Node):
    """Bats test: @test "description" { body }."""
    type: str = "TestDecl"
    description: Optional['Word'] = None
    body: Optional['Stmt'] = None
```

**Parser Changes**:
- Add to `NODE_TYPES`: `"TestDecl": TestDecl`
- Handle in `node_from_json()`

**Test Cases**:
```bash
# Input: @test "example test" { [ 1 -eq 1 ]; }
# Expected: Cmd with TestDecl {description: "example test", body: ...}
```

**Verification**:
```bash
/home/alx/repos/lovely-bash-permissions/.venv/bin/shfmt --to-json -ln=bats <<< '@test "example test" { [ 1 -eq 1 ]; }'
```

**Dependencies**: Step 10 (Block)

## [ ] Step 18: Comment (Shell Comments)

**Priority**: HIGH

**Go Reference**:
```go
type Comment struct {
    Hash Pos
    Text string
}
```

**Python Implementation**:
```python
@dataclass
class Comment(Node):
    """Shell comment: # text."""
    type: str = "Comment"
    hash_pos: Position = None
    text: str = ""
```

**Parser Changes**:
- Add to `NODE_TYPES`: `"Comment": Comment`
- Handle in `node_from_json()`
- Comments appear in Stmt.Comments, IfClause.CondLast, etc.

**Test Cases**:
```bash
# Input: echo "hi"  # inline comment
# Expected: Stmt {cmd: CallExpr("echo"), comments: [Comment{text:"inline comment"}]}
```

**Verification**:
```bash
/home/alx/repos/lovely-bash-permissions/.venv/bin/shfmt --to-json <<< 'echo "hi"  # inline comment'
```

**Dependencies**: None

## [ ] Step 19: Assign (Variable Assignments)

**Priority**: HIGH

**Go Reference**:
```go
type Assign struct {
    Append bool       # +=
    Naked  bool       # without '='
    Name   *Lit
    Index  ArithmExpr
    Value  *Word
    Array  *ArrayExpr
}
```

**Python Implementation**:
```python
@dataclass
class Assign(Node):
    """Variable assignment: var=val, arr[i]=val, var+=val."""
    type: str = "Assign"
    append: bool = False      # +=
    naked: bool = False       # without =
    name: Optional['Lit'] = None
    index: Optional['ArithmExpr'] = None
    value: Optional['Word'] = None
    array: Optional['ArrayExpr'] = None
```

**Parser Changes**:
- Add to `NODE_TYPES`: `"Assign": Assign`
- Handle in `node_from_json()`
- Appears in CallExpr.Assigns

**Test Cases**:
```bash
# Input: var=hello
# Expected: Stmt with CallExpr {assigns: [Assign{name:"var", value:"hello"}]}

# Input: arr[0]=val
# Expected: CallExpr with Assign {name:"arr", index:..., value:"val"}
```

**Verification**:
```bash
/home/alx/repos/lovely-bash-permissions/.venv/bin/shfmt --to-json <<< "var=hello"
```

**Dependencies**: None

## [ ] Step 20: CaseItem (Case Branches)

**Priority**: HIGH

**Go Reference**:
```go
type CaseItem struct {
    Op       CaseOperator
    OpPos    Pos
    Patterns []*Word
    Stmts []*Stmt
}
```

**Python Implementation**:
```python
@dataclass
class CaseItem(Node):
    """Case statement branch: patterns) stmts;;"""
    type: str = "CaseItem"
    op: str = ""          # ")", ") )" or "esac"
    patterns: List['Word'] = None
    stmts: List['Stmt'] = None
```

**Parser Changes**:
- Add to `NODE_TYPES`: `"CaseItem": CaseItem`
- Handle in `node_from_json()`
- Appears in CaseClause.items

**Test Cases**:
```bash
# Input: case $x in a) echo "A";; b) echo "B";; esac
# Expected: CaseClause {items: [CaseItem{patterns:["a"], stmts:[...]}, CaseItem{...}]}
```

**Verification**:
```bash
/home/alx/repos/lovely-bash-permissions/.venv/bin/shfmt --to-json <<< 'case $x in a) echo "A";; b) echo "B";; esac'
```

**Dependencies**: Step 12 (CaseClause already exists)

## [ ] Step 21: UnaryArithm, BinaryArithm, ParenArithm, FlagsArithm (Arithmetic Expressions)

**Priority**: MEDIUM

**Go References**:
```go
type UnaryArithm struct {
    OpPos Pos
    Op    UnAritOperator
    Post  bool
    X     ArithmExpr
}

type BinaryArithm struct {
    OpPos Pos
    Op    BinAritOperator
    X, Y  ArithmExpr
}

type ParenArithm struct {
    Lparen, Rparen Pos
    X ArithmExpr
}

type FlagsArithm struct {
    Flags *Lit
    X     ArithmExpr
}
```

**Python Implementation**:
```python
@dataclass
class UnaryArithm(Node):
    """Unary arithmetic: -x, !x, x++, x--."""
    type: str = "UnaryArithm"
    op: str = ""          # "-", "!", "++", "--"
    post: bool = False    # x++ vs ++x
    x: Optional['ArithmExpr'] = None

@dataclass
class BinaryArithm(Node):
    """Binary arithmetic: a + b, a < b, a && b."""
    type: str = "BinaryArithm"
    op: str = ""          # "+", "-", "*", "/", "%", "<", ">", "&&", "||", etc.
    x: Optional['ArithmExpr'] = None
    y: Optional['ArithmExpr'] = None

@dataclass
class ParenArithm(Node):
    """Parenthesized arithmetic: (expr)."""
    type: str = "ParenArithm"
    x: Optional['ArithmExpr'] = None

@dataclass
class FlagsArithm(Node):
    """Zsh subscript flags: ${array[(flags)expr]}."""
    type: str = "FlagsArithm"
    flags: Optional['Lit'] = None
    x: Optional['ArithmExpr'] = None
```

**Parser Changes**:
- Add all to `NODE_TYPES`
- Handle in `node_from_json()`

**Test Cases**:
```bash
# Input: (( x = y + z ))
# Expected: ArithmCmd {x: BinaryArithm{op:"=", x:..., y:BinaryArithm{op:"+",...}}}
```

**Verification**:
```bash
/home/alx/repos/lovely-bash-permissions/.venv/bin/shfmt --to-json <<< "(( x = y + z ))"
```

**Dependencies**: Step 13 (ArithmCmd)

## [ ] Step 22: UnaryTest, BinaryTest, ParenTest (Test Expressions)

**Priority**: MEDIUM

**Go References**:
```go
type UnaryTest struct {
    OpPos Pos
    Op    UnTestOperator
    X     TestExpr
}

type BinaryTest struct {
    OpPos Pos
    Op    BinTestOperator
    X, Y  TestExpr
}

type ParenTest struct {
    Lparen, Rparen Pos
    X TestExpr
}
```

**Python Implementation**:
```python
@dataclass
class UnaryTest(Node):
    """Unary test: -f file, -z str."""
    type: str = "UnaryTest"
    op: str = ""          # "-f", "-z", "-n", "-d", etc.
    x: Optional['TestExpr'] = None

@dataclass
class BinaryTest(Node):
    """Binary test: a -eq b, a && b."""
    type: str = "BinaryTest"
    op: str = ""          # "-eq", "-ne", "&&", "||", etc.
    x: Optional['TestExpr'] = None
    y: Optional['TestExpr'] = None

@dataclass
class ParenTest(Node):
    """Parenthesized test: ( expr )."""
    type: str = "ParenTest"
    x: Optional['TestExpr'] = None
```

**Parser Changes**:
- Add all to `NODE_TYPES`
- Handle in `node_from_json()`

**Test Cases**:
```bash
# Input: [[ -f file && -r file ]]
# Expected: TestClause {x: BinaryTest{op:"&&", x:UnaryTest{op:"-f",...}, y:UnaryTest{op:"-r",...}}}
```

**Verification**:
```bash
/home/alx/repos/lovely-bash-permissions/.venv/bin/shfmt --to-json <<< "[[ -f file && -r file ]]"
```

**Dependencies**: Step 12 (TestClause)

## [ ] Step 23: WordIter, CStyleLoop (Loop Types)

**Priority**: HIGH

**Go References**:
```go
type WordIter struct {
    Name  *Lit
    InPos Pos
    Items []*Word
}

type CStyleLoop struct {
    Lparen, Rparen Pos
    Init, Cond, Post ArithmExpr
}
```

**Python Implementation**:
```python
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
    init: Optional['ArithmExpr'] = None
    cond: Optional['ArithmExpr'] = None
    post: Optional['ArithmExpr'] = None
```

**Parser Changes**:
- Add both to `NODE_TYPES`
- Handle in `node_from_json()`

**Test Cases**:
```bash
# Input: for f in *.txt; do echo $f; done
# Expected: ForClause {loop: WordIter{name:"f", items:[...]}}

# Input: for (let i=0; i<10; i++); do echo $i; done
# Expected: ForClause {loop: CStyleLoop{...}}
```

**Verification**:
```bash
/home/alx/repos/lovely-bash-permissions/.venv/bin/shfmt --to-json <<< 'for f in *.txt; do echo $f; done'
```

**Dependencies**: None

## [ ] Step 24: ArrayExpr, ArrayElem (Arrays)

**Priority**: HIGH

**Go References**:
```go
type ArrayExpr struct {
    Lparen, Rparen Pos
    Elems []*ArrayElem
    Last  []Comment
}

type ArrayElem struct {
    Index    ArithmExpr
    Value    *Word
    Comments []Comment
}
```

**Python Implementation**:
```python
@dataclass
class ArrayExpr(Node):
    """Array expression: ( elem1 elem2 )."""
    type: str = "ArrayExpr"
    elems: List['ArrayElem'] = None

@dataclass
class ArrayElem(Node):
    """Array element: index=value or just value."""
    type: str = "ArrayElem"
    index: Optional['ArithmExpr'] = None
    value: Optional['Word'] = None
```

**Parser Changes**:
- Add both to `NODE_TYPES`
- Handle in `node_from_json()`

**Test Cases**:
```bash
# Input: arr=(a b c)
# Expected: Assign {array: ArrayExpr{elems: [...]}}

# Input: arr=([0]=a [1]=b)
# Expected: Assign {array: ArrayExpr{elems: [ArrayElem{index:..., value:...}]}}
```

**Verification**:
```bash
/home/alx/repos/lovely-bash-permissions/.venv/bin/shfmt --to-json <<< "arr=(a b c)"
```

**Dependencies**: Step 19 (Assign)

## File Organization
├── ast.py (expand with all node dataclasses)
├── parser.py (update node_from_json with all types)
├── visitor.py (expand with all visit methods)
└── types/
    ├── words.py (Lit, SglQuoted, DblQuoted, Word)
    ├── expansions.py (ParamExp, CmdSubst, ArithmExp, etc.)
    ├── commands.py (Block, FuncDecl, TestClause, etc.)
    └── arithmetic.py (arithmetic expression types)
```

## Testing Plan
- Add test cases for each new node type
- Test round-tripping: parse → serialize → parse
- Verify all existing tests still pass
- Integration test: parse complex bash scripts with all constructs

## Milestones
1. **M1**: Word part types (Lit, SglQuoted, DblQuoted)
2. **M2**: Expansion types (ParamExp, CmdSubst, ArithmExp, etc.)
3. **M3**: Complex commands (Block, FuncDecl, TestClause, etc.)
4. **M4**: Supporting types (Comment, Assign, etc.)
5. **M5**: Complete coverage & documentation