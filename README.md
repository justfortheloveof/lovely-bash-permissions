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

Both exception types live in the package root, and one inherits the other:

- `ShfmtError` - raised when no trustworthy parse could be obtained: the shfmt binary is missing, shfmt timed out, the subprocess failed with an OS error, or the command is nested too deeply to convert safely.
- `ParseError` - a **subclass** of `ShfmtError`, raised when the input itself is the problem (syntax error, empty command, shfmt exited non-zero, undecodable JSON). Adds `.command`, `.returncode`, and `.stderr`.

`ParseError` being a subclass matters for `except`: catching `ShfmtError` catches every way the backend can fail, while catching `ParseError` narrows to "this input is not valid shell". An unknown `dialect` is not either of these - `parse` raises `ValueError` for it.

```python
from lovely_bash_permissions import parse_ast, ParseError, ShfmtError

try:
    parse_ast('echo "unclosed')
except ParseError as exc:
    print(exc.returncode)  # shfmt exit code
    print(exc.stderr)  # raw shfmt error output
except ShfmtError as exc:
    print(f"backend unavailable: {exc}")
```

## AST

Parsed commands are represented as nested Python dataclasses. Every node inherits from `Node`, which provides:

- `type` - the node type name (e.g. `"File"`, `"CallExpr"`, `"Word"`)
- `pos` / `end` - `Position` source locations (`offset`, `line`, `col`)

Nodes print a nested, human-readable repr (source-position fields are omitted). The repr is **depth-limited**: fields are shown one level deep and anything below that collapses to `<Type ...>`, so a top-level `print(tree)` stays one line:

```python
from lovely_bash_permissions import parse_ast

tree = parse_ast("ls -la | grep txt")
print(tree)
# File(type='File', stmts=[<Stmt ...>])

# Drill in, one level at a time:
print(tree.stmts[0].cmd)
# BinaryCmd(type='BinaryCmd', op='|', left=<CallExpr ...>, right=<CallExpr ...>)
print(tree.stmts[0].cmd.left.args[0].parts[0])
# Lit(type='Lit', value='ls')
```

Fields left at their default (`None`, `""`, `[]`) are omitted entirely, so a node's repr shows only what the parse actually found.

### Node type reference

**Words & word parts** - a `Word` is a list of parts; a part can be any of:

| Type | Description | Key fields |
| ------ | ------------- | ------------ |
| `Word` | A word composed of parts | `parts` |
| `Lit` | Plain literal string (`hello`, `file.txt`) | `value` |
| `SglQuoted` | Single-quoted string `'...'` | `value` |
| `DblQuoted` | Double-quoted string `"..."` | `parts`, `value` |
| `ParamExp` | Parameter expansion `$VAR`, `${VAR}`, `${VAR:-def}`, `${VAR/pat/rep}`, `${VAR:off:len}` | `param`, `short`, `excl`, `names`, `length`, `all`, `exp`, `index`, `orig`, `replacement`, `slice` |
| `ParamExpExp` | The operand/word part of a parameter expansion (the `word` in `${VAR:-word}`, `${VAR%word}`, ...) | `op`, `word` |
| `ParamExpSlice` | The slicing part `${VAR:offset:length}` | `offset`, `length` |
| `CmdSubst` | Command substitution `$(...)` / backticks | `stmts`, `backquotes` |
| `ProcSubst` | Process substitution `<(...)` / `>(...)` | `op`, `stmts` |
| `ArithmExp` | Arithmetic expansion `$((...))` | `x` |
| `ExtGlob` | Extended globbing `@(pat \| pat)` | `op`, `pattern` |

`ParamExp` carries three flags that make a given expansion a *different* expression from the plain `${x}` they resemble: `length` (`${#x}`, string length), `excl` (`${!x}` indirect, and the `${!prefix*}` prefix form whose glob lives in `names`), and `all` (`${x//a/b}`, replace-all). A brace expansion (`{a,b}`, `{1..5}`) is not a node - shfmt does not expand it, so it arrives as ordinary `Lit` parts.

**Commands & assignments**

| Type | Description | Key fields |
| ------ | ------------- | ------------ |
| `File` | Top-level container | `stmts` |
| `Stmt` | Single statement wrapping a command | `cmd`, `position`, `redirs` |
| `CallExpr` | Command invocation (`ls -la`) | `args`, `assigns` |
| `Assign` | Variable assignment `var=val`, `a[i]=v`, `x+=v` | `name`, `index`, `value`, `array`, `append`, `naked` |
| `DeclClause` | Declaration builtin (`export`, `local`, `readonly`, `declare`, `typeset`) | `variant`, `args`, `assigns` |
| `ArrayExpr` / `ArrayElem` | Array literal `(a b c)` and an element | `elems` / `index`, `value` |

**Sequences & operators**

There is one node type for every two-operand operator; read `op` to tell them apart. `;`, `&` and newline are *not* operators here - each is a separate `Stmt` in `File.stmts`.

| Type | Description | Key fields |
| ------ | ------------- | ------------ |
| `BinaryCmd` | Two operands joined by `\|`, `\|&`, `&&` or `\|\|` | `op`, `left`, `right`, `left_redirs`, `right_redirs`, `redirs` |

`left_redirs` / `right_redirs` are the redirections belonging to the `X` and `Y` operands respectively; `redirs` is both lists concatenated, kept for convenience. Prefer the per-side fields when you need to know which side owns a redirection.

**Control flow**

| Type | Description | Key fields |
| ------ | ------------- | ------------ |
| `Subshell` | Parenthesized group `( ... )` | `stmts` |
| `Block` | Braced group `{ ...; }` | `stmts` |
| `IfClause` | `if` / `elif` / `else` | `cond_stmts`, `then_stmts`, `elif_branches`, `else_stmts` |
| `ElifBranch` | One `elif` branch | `cond`, `body` |
| `ForClause` | `for` loop over words | `var`, `words`, `body`, `cstyle` |
| `CStyleLoop` | C-style loop prelude `for ((init; cond; post))`, held in `ForClause.cstyle` | `init`, `cond`, `post` |
| `WhileClause` | `while` loop | `cond_stmts`, `body` |
| `CaseClause` | `case` / `switch` statement | `expr`, `branches` |
| `CaseBranch` | One `case` branch (its match patterns + body) | `patterns`, `body` |
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
| `FlagsArithm` | Zsh subscript flags, `${array[(flags)expr]}` | `flags`, `x` |
| `LetClause` | `let` statement | `exprs` |
| `TimeClause` | `time`-prefixed command | `stmt`, `posix_format` |
| `TestDecl` | Bats `@test "desc" { ... }` | `description`, `body` |

**Other**

| Type | Description | Key fields |
| ------ | ------------- | ------------ |
| `Redir` | Redirection (`>`, `>>`, `<`, `2>`) | `op`, `n`, `word`, `hdoc`, `op_pos` |
| `Node` | Base class; also the defensive fallback for any shfmt type the converter does not map | `type` |

shfmt keeps comments in a side channel of its own (`Last` / `Comments` lists carrying `Hash` and `Text`), and this library does not convert them. A comment therefore contributes no node: `parse_ast("# note")` is a `File` with no statements, and a trailing `# note` leaves the preceding command untouched. Strip comments yourself if you need them.

Most nodes also carry `*_pos` fields (`op_pos`, `value_pos`, `dollar_pos`, ...) that mark where a sub-part starts. They are excluded from `repr` output and from `structurally_equal`.

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

Word values are best-effort and **quote delimiters are stripped** - `"hello"` and `'hello'` both yield `hello`. Variable and substitution parts are rendered in lossy form (`$VAR`, `${VAR:-def}`, `$(...)`), and a double-quoted region is rendered from its parts rather than from its stored `value`, so `"pre${x}y"` comes back as `pre$xy` - the expansion stays visible instead of collapsing to text the user never typed.

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

Each record is a `RedirectionInfo` typed dict with two keys, `op` and `target`. Note that `op` never carries an fd prefix - `2>file` reports `op: ">"`, not `"2>"` - so a pattern that wants to distinguish stderr from stdout has to read `Redir.n` off the AST instead. `target` is the executed form (`"$D/out.txt"` gives `$D/out.txt`), and a redirection with no word at all is skipped.

These records are a deliberately small, display-friendly view. For the shape the permission engine works on - which splits the fd into its own `N` key and adds the normalized argument list - see [`parse_segments`](#segments-parse_segments).

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

## Segments: `parse_segments`

`parse_segments(command, dialect="bash")` is the flat, execution-order view of a command: one dict per thing bash actually runs, split at every `|`, `|&`, `&&`, `||`, `;` and `&`. It is the input the Devin half's policy engine consumes, and it imports from the subpackage rather than the package root:

```python
from lovely_bash_permissions.segments import parse_segments

print(parse_segments("cat file.txt > output.txt | grep -i pattern"))
# [{'command': 'cat', 'arguments': ['file.txt'], 'normalized_arguments': ['file.txt'],
#   'redirections': [{'Op': '>', 'N': {}, 'Target': 'output.txt'}]},
#  {'command': 'grep', 'arguments': ['-i', 'pattern'], 'normalized_arguments': ['-i', 'pattern'],
#   'redirections': []}]
```

| Key | Meaning |
| ---- | ------- |
| `command` | Command name, or `""` for a pseudo-command (a bare assignment, a declaration operand, a redirection-only statement) |
| `arguments` | Argument words **as written**, quotes intact |
| `normalized_arguments` | The same words in their *executed* form - quotes removed, backslashes unescaped. Omitted for pseudo-commands, which have no real argument list; read it with `segment.get("normalized_arguments", segment["arguments"])` |
| `redirections` | List of redirection records (below) |

Each redirection record has exactly three keys:

| Key | Meaning |
| ---- | ------- |
| `Op` | The operator with any fd prefix split off: `2>` arrives as `Op: ">"` with `N` set |
| `N` | `{"Value": "<fd>"}` when the operator carried an explicit descriptor, `{}` when it did not |
| `Target` | The redirect target in its executed form - every word part joined, quotes removed, backslashes unescaped |

`Target` is the only field policy is decided on, because it is the string bash actually opens. `"$DIR/out.txt"`, `"/dev""/null"` and `/etc\/passwd` all resolve through it to the path that would really be used.

```python
print(parse_segments('echo hi 2>"/dev""/null"'))
# ... 'redirections': [{'Op': '>', 'N': {'Value': '2'}, 'Target': '/dev/null'}] ...
```

An empty list from `parse_segments` is ambiguous: it means either "no commands here" or "the command could not be parsed", because a parse failure is swallowed and reported as zero segments. If you need to tell those apart, call `parse` (or `parse_ast`) first and handle the exception it raises.

The `Segment` and `SegmentRedirection` types exported from `lovely_bash_permissions.segments` are `TypedDict`s describing this shape; the runtime values are plain dicts, so subscript access works as shown.

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
    # `op` never carries an fd prefix, so "2>" and "2>>" are spelled ">"/">>".
    write_ops = {">", ">>", ">|", "<>", "&>", "&>>", ">&"}
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
