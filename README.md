# lovely-bash-permissions

A Python library for parsing bash commands into structured AST trees using [shfmt-py](https://pypi.org/project/shfmt-py/). Parse commands, extract commands and arguments, detect variables, analyze pipes and redirections, and traverse complex shell syntax.

Perfect for AI agents, shell scripting tools, permission checkers, and any application that needs to understand bash command structure.

## Installation

```bash
uv add lovely-bash-permissions
```

Or with pip:

```bash
pip install lovely-bash-permissions
```

Requires Python >= 3.14 and the `shfmt-py` binary (installed automatically via uv).

## Quick Start

```python
from lovely_bash_permissions import parse_ast, get_commands, get_arguments

# Parse a bash command
tree = parse_ast('ls -la | grep txt')

# Extract commands and arguments
print(get_commands(tree))       # ['ls', 'grep']
print(get_arguments(tree))     # [['-la'], ['txt']]
```

## API Reference

### Parser Functions

#### `parse_ast(command)` → `Node`

Parse a bash command string into a typed AST node. This is the main entry point for parsing.

```python
from lovely_bash_permissions import parse_ast

tree = parse_ast('ls -la')
print(tree.type)              # 'File'
print(len(tree.stmts))        # 1 statement
```

#### `parse(command, dialect="bash")` → `dict`

Parse a bash command and return raw shfmt JSON. Use this when you need the underlying JSON structure before it's converted to Python dataclasses.

```python
from lovely_bash_permissions import parse

# Default bash dialect
tree = parse('ls -la')

# Other dialects
zsh_tree = parse('ls -la', dialect="zsh")
posix_tree = parse('ls -la', dialect="posix")
```

Supported dialects: `bash`, `posix`, `mksh`, `bats`, `zsh`.

### Query Functions

#### `get_commands(tree)` → `List[str]`

Extract all command names from the AST, including commands in pipes, subshells, conditionals, and loops.

```python
from lovely_bash_permissions import parse_ast, get_commands

tree = parse_ast('cat file.txt | grep pattern | sort -u')
print(get_commands(tree))     # ['cat', 'grep', 'sort']
```

#### `get_arguments(tree)` → `List[List[str]]`

Extract arguments for each command (excluding the command name). Returns a list of argument lists, one per command.

```python
from lovely_bash_permissions import parse_ast, get_arguments

tree = parse_ast('cp file1.txt file2.txt')
print(get_arguments(tree))    # [['file1.txt', 'file2.txt']]

tree2 = parse_ast('ls -la | grep -i txt')
print(get_arguments(tree2))   # [['-la'], ['-i', 'txt']]
```

#### `has_variable(tree)` → `bool`

Check if the command contains any variable references (`$VAR`, `${VAR}`, command substitutions).

```python
from lovely_bash_permissions import parse_ast, has_variable

print(has_variable(parse_ast('ls -la')))                # False
print(has_variable(parse_ast('echo $HOME')))            # True
print(has_variable(parse_ast('echo "$HOME"')))          # True
print(has_variable(parse_ast('export PATH="$HOME/bin:$PATH"')))  # True
print(has_variable(parse_ast('cat /path/to/file')))     # False (path, not variable)
```

#### `get_redirections(tree)` → `List[dict]`

Extract file redirections from the AST. Returns a list of dicts with `op` (operator) and `target` (file path).

```python
from lovely_bash_permissions import parse_ast, get_redirections

tree = parse_ast('cat file.txt > output.txt')
redirs = get_redirections(tree)
print(redirs[0]['op'])      # '>'
print(redirs[0]['target'])  # 'output.txt'
```

#### `find_commands(tree)` → `List[CallExpr]`

Find all CallExpr nodes (command invocations) in the AST. Returns the full node objects rather than just names.

```python
from lovely_bash_permissions import parse_ast, find_commands

tree = parse_ast('ls -la | grep txt')
commands = find_commands(tree)
print(len(commands))        # 2
print(commands[0].args[0].parts[0].value)  # 'ls'
```

#### `find_arguments(tree)` → `List[List[Word]]`

Find all argument lists (excluding command names) as Word node objects.

```python
from lovely_bash_permissions import parse_ast, find_arguments

tree = parse_ast('ls -la /tmp')
args = find_arguments(tree)
print(len(args))            # 1
print(len(args[0]))         # 2 (two arguments: '-la' and '/tmp')
```

#### `has_pipe(tree)` → `bool`

Check if the command contains any pipe operators.

```python
from lovely_bash_permissions import parse_ast, has_pipe

print(has_pipe(parse_ast('ls -la')))          # False
print(has_pipe(parse_ast('ls | grep txt')))   # True
print(has_pipe(parse_ast('ls > file.txt')))   # False (redirect, not pipe)
```

#### `get_target_files(tree)` → `List[str]`

Extract file targets from redirections. Returns the names of files that will be modified or read by redirections.

```python
from lovely_bash_permissions import parse_ast, get_target_files

tree = parse_ast('cat file.txt > output.txt')
print(get_target_files(tree))  # ['output.txt']
```

### Visitor Pattern

#### `Visitor` class

The AST visitor pattern for custom traversal. Subclass `Visitor` and override specific `visit_*` methods to process particular node types.

```python
from lovely_bash_permissions import parse_ast, Visitor

class CommandCollector(Visitor):
    def __init__(self):
        super().__init__()
        self.commands = []
    
    def visit_call_expr(self, node):
        super().visit_call_expr(node)
        cmd_name = node.args[0].parts[0].value
        self.commands.append(cmd_name)

tree = parse_ast('cat file.txt | grep pattern | sort -u')
collector = CommandCollector()
collector.walk(tree)
print(collector.commands)  # ['cat', 'grep', 'sort']
```

Available visit methods:
- `visit(node)` — Dispatch to type-specific handler
- `visit_file(node)` — Top-level File nodes
- `visit_stmt(node)` — Individual statements
- `visit_call_expr(node)` — Command invocations
- `visit_binary_cmd(node)` — Pipe operations
- `visit_word(node)` — Bash words
- `visit_redir(node)` — File redirections
- `visit_part(node)` — Word parts (literals, variables, etc.)
- `visit_node(node)` — Generic/unmapped node types
- `visit_subshell(node)` — Parenthesized command groups
- `visit_if_clause(node)` — If/elif/else conditionals
- `visit_for_clause(node)` — For loops
- `visit_while_clause(node)` — While loops
- `visit_and_cmd(node)` — Logical AND (&&)
- `visit_or_cmd(node)` — Logical OR (||)
- `visit_case_clause(node)` — Case/switch statements
- `walk(node)` — Recursively visit all nodes

### AST Node Types

The parser uses dataclasses to represent bash syntax:

| Type | Description |
|------|-------------|
| `File` | Top-level container with `stmts` array |
| `Stmt` | Single statement with `cmd`, `pos`, `end`, optional `redirs` |
| `CallExpr` | Command invocation with `args` array |
| `BinaryCmd` | Pipe operator with `x`, `y` operands and `op` |
| `Word` | A word with `parts` array |
| `Part` | Part of a word (literal, variable, expansion) |
| `Redir` | Redirection with `op` and `word` |
| `Position` | Source position with `offset`, `line`, `col` |
| `Subshell` | Parenthesized command group |
| `IfClause` | If/elif/else conditional |
| `ForClause` | For loop |
| `WhileClause` | While loop |
| `AndCmd` | Logical AND (&&) |
| `OrCmd` | Logical OR (||) |
| `CaseClause` | Case/switch statement |

Inspect raw node structure:

```python
tree = parse_ast('ls | grep txt')
stmt = tree.stmts[0]
print(stmt.cmd.type)  # 'BinaryCmd'
print(stmt.cmd.op)   # '|'
```

## Examples

### Parsing Pipes

```python
from lovely_bash_permissions import parse_ast, get_commands, get_arguments

tree = parse_ast('cat data.csv | grep pattern | awk "{print $1}" | sort -u > results.txt')

print(get_commands(tree))
# ['cat', 'grep', 'awk', 'sort']

print(get_arguments(tree))
# [['data.csv'], ['pattern'], ['"{print $1}"'], ['-u']]
```

### Parsing Redirections

```python
from lovely_bash_permissions import parse_ast, get_redirections

# Output redirect
tree = parse_ast('cat file.txt > output.txt')
redirs = get_redirections(tree)
print(redirs[0]['op'])      # '>'
print(redirs[0]['target'])  # 'output.txt'

# Append redirect
tree2 = parse_ast('echo line >> log.txt')
redirs2 = get_redirections(tree2)
print(redirs2[0]['op'])     # '>>'

# Input redirect
tree3 = parse_ast('sort < input.txt')
redirs3 = get_redirections(tree3)
print(redirs3[0]['op'])     # '<'
```

### Parsing Variables

```python
from lovely_bash_permissions import parse_ast, has_variable

print(has_variable(parse_ast('ls -la')))
# False

print(has_variable(parse_ast('echo $HOME')))
# True

print(has_variable(parse_ast('cat /path/to/file')))
# False (path, not variable)

print(has_variable(parse_ast('echo "$HOME"')))
# True (variable in double quotes)
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

tree = parse_ast('for f in *.txt; do echo $f; done')
print(get_commands(tree))
# ['echo']

tree2 = parse_ast('while true; do sleep 1; done')
print(get_commands(tree2))
# ['sleep']
```

### Logical Operators

```python
from lovely_bash_permissions import parse_ast, get_commands

tree = parse_ast('test -f file && cat file')
print(get_commands(tree))
# ['test', 'cat']

tree2 = parse_ast('ping -c1 host || echo unreachable')
print(get_commands(tree2))
# ['ping', 'echo']
```

### Finding Dangerous Commands

```python
from lovely_bash_permissions import parse_ast, get_commands

def is_dangerous(tree):
    dangerous = {'rm', 'mv', 'cp', 'kill', 'reboot', 'shutdown'}
    commands = get_commands(tree)
    return any(c in dangerous for c in commands)

# Check before running
tree = parse_ast('rm -rf /tmp/cache')
if is_dangerous(tree):
    print("⚠️ Warning: this command could modify the system")
```

### Permission Checker

```python
from lovely_bash_permissions import parse_ast, get_target_files, get_redirections

def check_write_permissions(tree):
    """Check if command writes to files (output redirections)."""
    redirs = get_redirections(tree)
    write_ops = {'>', '>>', '2>', '2>>', '&>', '&>>'}
    
    for r in redirs:
        if r['op'] in write_ops:
            print(f"Writing to: {r['target']}")
    
    return bool([r for r in redirs if r['op'] in write_ops])

tree = parse_ast('cat file.txt > output.txt')
check_write_permissions(tree)
# Writing to: output.txt
```

### Parsing Multi-Statement Scripts

```python
from lovely_bash_permissions import parse_ast, get_commands

tree = parse_ast('echo step 1\necho step 2')
print(len(tree.stmts))       # 2
print(get_commands(tree))    # ['echo', 'echo']
```

### Custom Visitor: Variable Finder

```python
from lovely_bash_permissions import parse_ast, Visitor

class VariableFinder(Visitor):
    def __init__(self):
        super().__init__()
        self.variables = []
    
    def visit_part(self, node):
        super().visit_part(node)
        if node.type in ("Var", "ParamExp"):
            # Extract variable name from part
            name = None
            if node.type == "Var":
                name = node.parts[0].value if node.parts else None
            elif node.type == "ParamExp":
                name = node.parts[0].value if node.parts else None
            if name and name not in self.variables:
                self.variables.append(name)

tree = parse_ast('echo $HOME $PATH $USER')
finder = VariableFinder()
finder.walk(tree)
print(finder.variables)
# ['HOME', 'PATH', 'USER']
```

### Custom Visitor: Command Counter

```python
from lovely_bash_permissions import parse_ast, Visitor

class CommandCounter(Visitor):
    def __init__(self):
        super().__init__()
        self.count = 0
    
    def visit_call_expr(self, node):
        super().visit_call_expr(node)
        self.count += 1

tree = parse_ast('ls | grep txt | sort | uniq | tee output.txt')
counter = CommandCounter()
counter.walk(tree)
print(counter.count)
# 5
```

## Running Tests

```bash
uv sync
uv run pytest
```

## License

See the repository for license information.