# lovely-bash-permissions

A Python library for parsing bash commands using [shfmt-py](https://pypi.org/project/shfmt-py/). Parse commands into a structured AST and inspect them for commands, arguments, variables, pipes, and redirections.

Perfect for AI agents, shell scripting tools, and any application that needs to understand bash command structure.

## Installation

```bash
uv add lovely-bash-permissions
```

Or with pip:

```bash
pip install lovely-bash-permissions
```

Requires Python >= 3.14 and the `shfmt-py` binary.

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

### `parse_ast(command)` → `Node`

Parse a bash command string into a typed AST.

```python
from lovely_bash_permissions import parse_ast

tree = parse_ast('ls -la')
print(tree.type)              # 'File'
print(len(tree.stmts))        # 1 statement
```

### `parse(command, dialect="bash")` → `dict`

Parse a bash command and return raw shfmt JSON. Supports multiple shell dialects.

```python
from lovely_bash_permissions import parse

# Default bash dialect
tree = parse('ls -la')

# Other dialects
zsh_tree = parse('ls -la', dialect="zsh")
```

### `get_commands(tree)` → `List[str]`

Extract all command names from the AST, including piped commands.

```python
from lovely_bash_permissions import parse_ast, get_commands

tree = parse_ast('cat file.txt | grep pattern | sort -u')
print(get_commands(tree))     # ['cat', 'grep', 'sort']
```

### `get_arguments(tree)` → `List[List[str]]`

Extract arguments for each command (excluding the command name). Returns a list of argument lists, one per command.

```python
from lovely_bash_permissions import parse_ast, get_arguments

tree = parse_ast('cp file1.txt file2.txt')
print(get_arguments(tree))    # [['file1.txt', 'file2.txt']]

tree2 = parse_ast('ls -la | grep -i txt')
print(get_arguments(tree2))   # [['-la'], ['-i', 'txt']]
```

### `has_variable(tree)` → `bool`

Check if the command contains any variable references (`$VAR`, `"${VAR}"`, command substitutions).

```python
from lovely_bash_permissions import parse_ast, has_variable

print(has_variable(parse_ast('ls -la')))                # False
print(has_variable(parse_ast('echo $HOME')))            # True
print(has_variable(parse_ast('echo "$HOME"')))          # True
print(has_variable(parse_ast('export PATH="$HOME/bin:$PATH"')))  # True
```

### `get_redirections(tree)` → `List[dict]`

Extract redirections from the AST. Returns a list of dicts with `op` (operator) and `target` (file path).

```python
from lovely_bash_permissions import parse_ast, get_redirections

tree = parse_ast('cat file.txt > output.txt')
redirs = get_redirections(tree)
print(redirs)  # [{'op': '>', 'target': 'output.txt'}]
```

## AST Node Types

The parser uses dataclasses to represent bash syntax:

| Type | Description |
|------|-------------|
| `File` | Top-level node with `stmts` array |
| `Stmt` | Single statement with `cmd`, `pos`, `end`, optional `redirs` |
| `CallExpr` | Command invocation with `args` array |
| `BinaryCmd` | Pipe operator with `x`, `y` operands and `op` |
| `Word` | A word with `parts` array |
| `Part` | Part of a word (literal, variable, expansion) |
| `Redir` | Redirection with `op` and `word` |
| `Position` | Source position with `offset`, `line`, `col` |

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

### Parsing Multi-Statement Scripts

```python
from lovely_bash_permissions import parse_ast, get_commands

tree = parse_ast('echo step 1\necho step 2')
print(len(tree.stmts))       # 2
print(get_commands(tree))    # ['echo', 'echo']
```

## Running Tests

```bash
uv sync
uv run pytest
```

## License

See the repository for license information.