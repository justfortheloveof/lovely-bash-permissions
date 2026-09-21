# lovely-bash-permissions

A Python library for parsing bash commands into structured, typed AST trees using [shfmt-py](https://pypi.org/project/shfmt-py/) as the parsing backend. Parse commands, inspect and traverse the AST to extract commands and arguments, detect variables, analyze pipes and redirections, and handle complex shell syntax like substitutions, subshells, loops, and conditionals.

Perfect for AI agents, shell scripting tools, permission checkers, syntax analysis, and any application that needs to understand bash command structure.

## Related Project: lovely-devin-permissions

This repository also ships `lovely-devin-permissions`, a Devin CLI permission hook built on top of this library. It parses bash commands, evaluates each command segment against configurable rules and decides whether to allow, ask for approval, or deny execution.

See [README.lovely-devin-permissions.md](README.lovely-devin-permissions.md) for installation, hook registration, the config schema, and troubleshooting.

## Installation

```bash
uv add lovely-bash-permissions
```

Or with pip:

```bash
pip install lovely-bash-permissions
```

Requires Python >= 3.10 and the `shfmt-py` binary (installed automatically via uv).

## Quick Start

```python
from lovely_bash_permissions import parse_ast, get_commands, get_arguments

# Parse a bash command into an AST
tree = parse_ast("ls -la | grep txt")

# Extract commands and arguments
print(get_commands(tree))  # ['ls', 'grep']
print(get_arguments(tree))  # [['-la'], ['txt']]
```

You can also inspect commands from the command line:

```bash
uv run lovely-bash-inspection --string 'echo hello | vim -'
```

## Parser

### `parse_ast(command)` → `File`

Parse a bash command string into a typed AST rooted at a `File` node. This is the main entry point.

```python
from lovely_bash_permissions import parse_ast

tree = parse_ast("ls -la")
print(tree.type)  # 'File'
print(len(tree.stmts))  # 1
```

### `parse(command, dialect="bash")` → `dict`

Parse a bash command and return the raw shfmt JSON as a Python dict. Use this when you need the underlying JSON structure before it is converted to typed dataclasses.

```python
from lovely_bash_permissions import parse

tree = parse("ls -la")
print(tree["Type"])  # 'File'

# Other shell dialects
zsh_tree = parse("ls -la", dialect="zsh")
posix_tree = parse("ls -la", dialect="posix")
```

Supported dialects: `bash`, `posix`, `mksh`, `bats`, `zsh`. An unknown dialect raises `ValueError`.

### Errors

- `ParseError` - raised when the input cannot be parsed (syntax error, empty command, or shfmt failure). Carries `.command`, `.returncode`, and `.stderr` attributes.
- `LovelyDevinPermissionsError` - raised when the shfmt binary is missing or shfmt could not be run (timeout, OS error).

```python
from lovely_bash_permissions import parse_ast, ParseError

try:
    parse_ast('echo "unclosed')
except ParseError as exc:
    print(exc.returncode)  # shfmt exit code
    print(exc.stderr)  # raw shfmt error output
```

## AST

Parsed commands are represented as nested Python dataclasses. Every node inherits from `Node`, which provides:

- `type` - the node type name (e.g. `"File"`, `"CallExpr"`, `"Word"`)
- `pos` / `end` - `Position` source locations (`offset`, `line`, `col`)

Nodes print a nested, human-readable repr (source-position fields are omitted), so you can inspect a tree directly:

```python
from lovely_bash_permissions import parse_ast

tree = parse_ast("ls -la | grep txt")
print(tree)
# File(type='File', stmts=[Stmt(type='Stmt', cmd=BinaryCmd(type='BinaryCmd', op='|',
#   left=CallExpr(type='CallExpr', args=[Word(type='Word', parts=[Lit(type='Lit', value='ls')]),
#     Word(type='Word', parts=[Lit(type='Lit', value='-la')])]),
#   right=CallExpr(type='CallExpr', args=[Word(type='Word', parts=[Lit(type='Lit', value='grep')]),
#     Word(type='Word', parts=[Lit(type='Lit', value='txt')])])))])
```

### Node type reference

**Words & word parts** - a `Word` is a list of parts; a part can be any of:

| Type | Description | Key fields |
| ------ | ------------- | ------------ |
| `Word` | A word composed of parts | `parts` |
| `Lit` | Plain literal string (`hello`, `file.txt`) | `value` |
| `SglQuoted` | Single-quoted string `'...'` | `value` |
| `DblQuoted` | Double-quoted string `"..."` | `parts`, `value` |
| `ParamExp` | Parameter expansion `$VAR`, `${VAR}`, `${VAR:-def}`, `${VAR/pat/rep}`, `${VAR:off:len}` | `param`, `short`, `exp`, `index`, `length`, `all`, `orig`, `replacement`, `slice` |
| `ParamExpExp` | The operand/word part of a parameter expansion (the `word` in `${VAR:-word}`, `${VAR%word}`, ...) | `op`, `word` |
| `ParamExpSlice` | The slicing part `${VAR:offset:length}` | `offset`, `length` |
| `CmdSubst` | Command substitution `$(...)` / backticks | `stmts`, `backquotes` |
| `ProcSubst` | Process substitution `<(...)` / `>(...)` | `op`, `stmts` |
| `ArithmExp` | Arithmetic expansion `$((...))` | `x` |
| `BraceExp` | Brace expansion `{a,b}` / `{1..5}` | `sequence`, `elems` |
| `ExtGlob` | Extended globbing `@(pat | pat)` | `op`, `pattern` |

**Commands & assignments**

| Type | Description | Key fields |
| ------ | ------------- | ------------ |
| `File` | Top-level container | `stmts` |
| `Stmt` | Single statement wrapping a command | `cmd`, `position`, `redirs` |
| `CallExpr` | Command invocation (`ls -la`) | `args`, `assigns` |
| `Assign` | Variable assignment `var=val`, `a[i]=v`, `x+=v` | `name`, `index`, `value`, `array`, `append`, `naked` |
| `DeclClause` | Declaration builtin (`export`, `local`, `readonly`) | `variant`, `args`, `assigns` |
| `ArrayExpr` / `ArrayElem` | Array literal `(a b c)` and an element | `elems` / `index`, `value` |

**Sequences & operators**

| Type | Description | Key fields |
| ------ | ------------- | ------------ |
| `BinaryCmd` | Pipe or sequence (`\|\|` pipelines, `;`, `&`) | `op`, `left`, `right`, `left_redirs`, `right_redirs`, `redirs` |
| `AndCmd` | Logical AND `&&` | `left`, `right` |
| `OrCmd` | Logical OR `\|\|` | `left`, `right` |

**Control flow**

| Type | Description | Key fields |
| ------ | ------------- | ------------ |
| `Subshell` | Parenthesized group `( ... )` | `stmts` |
| `Block` | Braced group `{ ...; }` | `stmts` |
| `IfClause` | `if` / `elif` / `else` | `cond_stmts`, `then_stmts`, `elif_branches`, `else_stmts` |
| `ElifBranch` | One `elif` branch | `cond`, `body` |
| `ForClause` | `for` loop over words | `var`, `words`, `body` |
| `WordIter` | The `for var in ...` foreach part | `name`, `items` |
| `CStyleLoop` | C-style loop `for ((...))` | `init`, `cond`, `post` |
| `WhileClause` | `while` loop | `cond_stmts`, `body` |
| `CaseClause` | `case` / `switch` statement | `expr`, `branches` |
| `CaseBranch` | A `case` branch (patterns + body) | `patterns`, `body` |
| `CaseItem` | A `case` item (`patterns) stmts;;`) | `op`, `patterns`, `stmts` |
| `FuncDecl` | Function definition | `name`, `body`, `parens`, `rsrv_word` |
| `CoprocClause` | Coprocess `coproc NAME { cmd; }` | `name`, `stmt` |

**Tests & arithmetic**

| Type | Description | Key fields |
| ------ | ------------- | ------------ |
| `TestClause` | Extended test `[[ ... ]]` | `body` |
| `UnaryTest` | Unary test (`-f file`, `-z str`) | `op`, `x` |
| `BinaryTest` | Binary test (`a == b`, `-eq`) | `op`, `left`, `right` |
| `ParenTest` | Parenthesized test `( expr )` | `body` |
| `ArithmCmd` | Arithmetic command `(( ... ))` | `body` |
| `BinaryArithm` | Binary arithmetic | `op`, `left`, `right` |
| `UnaryArithm` | Unary arithmetic (`-x`, `x++`) | `op`, `post`, `x` |
| `ParenArithm` | Parenthesized arithmetic | `body` |
| `LetClause` | `let` statement | `exprs` |
| `TimeClause` | `time`-prefixed command | `stmt`, `posix_format` |
| `TestDecl` | Bats `@test "desc" { ... }` | `description`, `body` |

**Other**

| Type | Description | Key fields |
| ------ | ------------- | ------------ |
| `Redir` | Redirection (`>`, `>>`, `<`, `2>`) | `op`, `n`, `word`, `hdoc`, `op_pos` |
| `Comment` | Shell comment | `text` |
| `Node` | Base class; also used for unmapped shfmt types | `type` |

### Redirections

A `Redir` node describes one redirection:

- `op` - the operator (`>`, `>>`, `<`, `<<`, `<<<`, `2>`, `>&`, `|&`…)
- `n` - the file descriptor number (e.g. `2` in `2>file`), or `None`
- `word` - the file target as a `Word`
- `hdoc` - heredoc body (only for `<<` / `<<-`; bash expands `$(...)` and backticks inside unquoted heredocs)

## Inspection API

### Command extraction

```python
from lovely_bash_permissions import parse_ast, get_commands, find_commands

# Extract command names, recursively
tree = parse_ast("cat file.txt | grep pattern | sort -u")
print(get_commands(tree))  # ['cat', 'grep', 'sort']

# Or get the full CallExpr nodes
commands = find_commands(parse_ast("ls -la | grep txt"))
print(len(commands))  # 2
print(commands[0].args[0].parts[0].value)  # 'ls'
```

`get_commands` and `find_commands` recurse into `CallExpr` arguments **and** assignment values, so commands inside `$(...)`, process substitutions, subshells, functions, loops, conditionals, and parameter-expansion operands (`${var/pat/$(cmd)}`, `${var:-$(cmd)}`, `${var:0:$(cmd)}`, ...) are all discovered:

```python
print(get_commands(parse_ast("echo $(git status | head -1)")))  # ['echo', 'git', 'head']
print(get_commands(parse_ast("counts=$(ls | wc -l)")))  # ['ls', 'wc']
print(get_commands(parse_ast("echo ${x//a/$(rm -rf x)}")))  # ['echo', 'rm']
```

### Argument extraction

```python
from lovely_bash_permissions import parse_ast, get_arguments, find_arguments

tree = parse_ast("cp file1.txt file2.txt")
print(get_arguments(tree))  # [['file1.txt', 'file2.txt']]

tree2 = parse_ast("ls -la | grep -i txt")
print(get_arguments(tree2))  # [['-la'], ['-i', 'txt']]
```

`get_arguments` returns the string value of each argument (excluding the command name). `find_arguments` returns the raw `Word` nodes instead of strings:

```python
args = find_arguments(parse_ast("ls -la /tmp"))
print(len(args))  # 1
print(len(args[0]))  # 2 (two arguments: '-la' and '/tmp')
```

Word values are best-effort and **quote delimiters are stripped** - `"hello"` and `'hello'` both yield `hello`. Variable and substitution parts are rendered in lossy form (e.g. `$VAR`, `$(...)`).

### Feature checks

```python
from lovely_bash_permissions import parse_ast, has_variable, has_pipe

print(has_variable(parse_ast("ls -la")))  # False
print(has_variable(parse_ast("echo $HOME")))  # True
print(has_variable(parse_ast('echo "$HOME"')))  # True
print(has_variable(parse_ast("echo $(date)")))  # True
print(has_variable(parse_ast("cat /path/to/file")))  # False (path, not variable)

print(has_pipe(parse_ast("ls -la")))  # False
print(has_pipe(parse_ast("ls | grep txt")))  # True
print(has_pipe(parse_ast("ls |& cat")))  # True (|& counts)
print(has_pipe(parse_ast("ls > file.txt")))  # False (redirect, not pipe)
```

### Redirections

```python
from lovely_bash_permissions import parse_ast, get_redirections, get_target_files

tree = parse_ast("cat file.txt > output.txt")
redirs = get_redirections(tree)
print(redirs[0]["op"])  # '>'
print(redirs[0]["target"])  # 'output.txt'

# "2>&1" is an fd-duplication: op '>&', target '1'
print(get_redirections(parse_ast("ls 2>&1")))  # [{'op': '>&', 'target': '1'}]

# Just the file paths
print(get_target_files(parse_ast("cat file.txt > output.txt")))  # ['output.txt']
```

### Traversal semantics

The inspection functions differ in how they walk the tree:

| Function | Descends into `$(...)` / assignment values? |
| ---------- | --------------------------------------------- |
| `get_commands`, `find_commands` | Yes - nested commands are discovered |
| `get_arguments`, `find_arguments` | No - collects the literal argument words of each call |
| `has_variable`, `has_pipe`, `get_redirections`, `get_target_files` | Yes - full traversal |

### Traversal & comparison helpers

```python
from lovely_bash_permissions import parse_ast, iter_children, structurally_equal

# iter_children: yield the direct child nodes of any node
tree = parse_ast("ls | grep txt").stmts[0].cmd
print([type(c).__name__ for c in iter_children(tree)])
# ['CallExpr', 'CallExpr']          -- the two sides of the pipe

# CallExpr args are skipped by default; pass include_call_args=True to include them
call = parse_ast("ls -la /tmp").stmts[0].cmd
print([type(w).__name__ for w in iter_children(call, include_call_args=True)])
# ['Word', 'Word', 'Word']

# structurally_equal: compare two ASTs ignoring source positions
print(structurally_equal(parse_ast("echo hi"), parse_ast("echo hi")))  # True
print(structurally_equal(parse_ast("echo hi"), parse_ast("echo ho")))  # False
```

`structurally_equal` is useful in tests and when diffing trees produced from different source locations, since it ignores all position fields.

## CLI: lovely-bash-inspection

The `lovely-bash-inspection` command parses bash code and prints a per-statement inspection summary.

```bash
# Inline string
uv run lovely-bash-inspection --string 'cat file.txt | grep pattern | sort -u > results.txt'

# From a file
uv run lovely-bash-inspection --file script.sh

# From stdin
echo 'ls -la | grep txt' | uv run lovely-bash-inspection

# Choose a shell dialect
uv run lovely-bash-inspection --string 'echo hi' --dialect zsh
```

Sample output:

```text
statement 1 `cat file.txt | grep pattern | sort -u > results.txt`:
  cmd: cat
  args: file.txt
  cmd: grep
  args: pattern
  cmd: sort
  args: -u
  redirection: > results.txt

Variables: no
Pipes:     yes
```

Exit codes:

| Code | Meaning |
| ------ | --------- |
| `0` | Success |
| `2` | Usage error (bad/missing arguments, unreadable file, empty input) |
| `3` | Parse error (shfmt could not parse the input) |

## Examples

### Pipes

```python
from lovely_bash_permissions import parse_ast, get_commands, get_arguments

tree = parse_ast("cat data.csv | grep pattern | sort -u > results.txt")

print(get_commands(tree))
# ['cat', 'grep', 'sort']

print(get_arguments(tree))
# [['data.csv'], ['pattern'], ['-u']]
```

### Redirections

```python
from lovely_bash_permissions import parse_ast, get_redirections

print(get_redirections(parse_ast("cat file.txt > output.txt")))  # [{'op': '>', 'target': 'output.txt'}]
print(get_redirections(parse_ast("echo line >> log.txt")))  # [{'op': '>>', 'target': 'log.txt'}]
print(get_redirections(parse_ast("sort < input.txt")))  # [{'op': '<', 'target': 'input.txt'}]
```

### Variables

```python
from lovely_bash_permissions import parse_ast, has_variable

print(has_variable(parse_ast("ls -la")))  # False
print(has_variable(parse_ast("echo $HOME")))  # True
print(has_variable(parse_ast('echo "$HOME"')))  # True (variable in double quotes)
print(has_variable(parse_ast("cat /path/to/file")))  # False (path, not variable)
```

### Command substitution

`get_commands` digs into `$(...)`, noting inner commands:

```python
from lovely_bash_permissions import parse_ast, get_commands

tree = parse_ast("echo 'project: '$(basename $(git rev-parse --show-toplevel))")
print(get_commands(tree))
# ['echo', 'basename', 'git']
```

### Conditionals

```python
from lovely_bash_permissions import parse_ast, get_commands

tree = parse_ast('if test -f file.txt; then cat file.txt; else echo "missing"; fi')

# get_commands traverses all branches
print(get_commands(tree))
# ['test', 'cat', 'echo']
```

### Loops

```python
from lovely_bash_permissions import parse_ast, get_commands

tree = parse_ast("for f in *.txt; do echo $f; done")
print(get_commands(tree))
# ['echo']

tree2 = parse_ast("while true; do sleep 1; done")
print(get_commands(tree2))
# ['true', 'sleep']  -- the condition command is included
```

### Logical operators

```python
from lovely_bash_permissions import parse_ast, get_commands

tree = parse_ast("test -f file && cat file")
print(get_commands(tree))
# ['test', 'cat']

tree2 = parse_ast("ping -c1 host || echo unreachable")
print(get_commands(tree2))
# ['ping', 'echo']
```

### Multi-statement scripts

```python
from lovely_bash_permissions import parse_ast, get_commands

tree = parse_ast("echo step 1\necho step 2")
print(len(tree.stmts))  # 2
print(get_commands(tree))  # ['echo', 'echo']
```

### Finding dangerous commands

```python
from lovely_bash_permissions import parse_ast, get_commands


def is_dangerous(tree):
    dangerous = {"rm", "mv", "cp", "kill", "reboot", "shutdown"}
    commands = get_commands(tree)
    return any(c in dangerous for c in commands)


# Check before running
tree = parse_ast("rm -rf /tmp/cache")
if is_dangerous(tree):
    print("Warning: this command could modify the system")
```

### Checking write permissions

```python
from lovely_bash_permissions import parse_ast, get_redirections


def check_write_permissions(tree):
    """Check if a command writes to files (output redirections)."""
    redirs = get_redirections(tree)
    write_ops = {">", ">>", "2>", "2>>", "&>", "&>>"}
    return [r for r in redirs if r["op"] in write_ops]


tree = parse_ast("cat file.txt > output.txt")
print(check_write_permissions(tree))
# [{'op': '>', 'target': 'output.txt'}]
```

## Running Tests

```bash
uv sync
uv run pytest
```

## License

See the repository for license information.
