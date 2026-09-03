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

Requires Python >= 3.10 and the `shfmt-py` binary (installed automatically via uv).

## Quick Start

```python
from lovely_bash_permissions import parse_ast, get_commands, get_arguments

# Parse a bash command
tree = parse_ast("ls -la | grep txt")

# Extract commands and arguments
print(get_commands(tree))  # ['ls', 'grep']
print(get_arguments(tree))  # [['-la'], ['txt']]
```

You can also use the lovely-bash-inspection CLI:

```bash
uv run lovely-bash-inspection --string 'echo hello | vim -'
```

## API Reference

### Parser Functions

#### `parse_ast(command)` → `File`

Parse a bash command string into a typed AST node. This is the main entry point for parsing.

```python
from lovely_bash_permissions import parse_ast

tree = parse_ast("ls -la")
print(tree.type)  # 'File'
print(len(tree.stmts))  # 1 statement
```

#### `parse(command, dialect="bash")` → `dict`

Parse a bash command and return raw shfmt JSON. Use this when you need the underlying JSON structure before it's converted to Python dataclasses.

```python
from lovely_bash_permissions import parse

# Default bash dialect
tree = parse("ls -la")

# Other dialects
zsh_tree = parse("ls -la", dialect="zsh")
posix_tree = parse("ls -la", dialect="posix")
```

Supported dialects: `bash`, `posix`, `mksh`, `bats`, `zsh`.

### Query Functions

#### `get_commands(tree)` → `List[str]`

Extract all command names from the AST, including commands in pipes, subshells, conditionals, and loops.

```python
from lovely_bash_permissions import parse_ast, get_commands

tree = parse_ast("cat file.txt | grep pattern | sort -u")
print(get_commands(tree))  # ['cat', 'grep', 'sort']
```

#### `get_arguments(tree)` → `List[List[str]]`

Extract arguments for each command (excluding the command name). Returns a list of argument lists, one per command.

```python
from lovely_bash_permissions import parse_ast, get_arguments

tree = parse_ast("cp file1.txt file2.txt")
print(get_arguments(tree))  # [['file1.txt', 'file2.txt']]

tree2 = parse_ast("ls -la | grep -i txt")
print(get_arguments(tree2))  # [['-la'], ['-i', 'txt']]
```

#### `has_variable(tree)` → `bool`

Check if the command contains any variable references (`$VAR`, `${VAR}`, command substitutions).

```python
from lovely_bash_permissions import parse_ast, has_variable

print(has_variable(parse_ast("ls -la")))  # False
print(has_variable(parse_ast("echo $HOME")))  # True
print(has_variable(parse_ast('echo "$HOME"')))  # True
print(has_variable(parse_ast('export PATH="$HOME/bin:$PATH"')))  # True
print(has_variable(parse_ast("cat /path/to/file")))  # False (path, not variable)
```

#### `get_redirections(tree)` → `List[RedirectionInfo]`

Extract file redirections from the AST. Returns a list of `RedirectionInfo` typed dicts with `op` (operator) and `target` (file path).

```python
from lovely_bash_permissions import parse_ast, get_redirections

tree = parse_ast("cat file.txt > output.txt")
redirs = get_redirections(tree)
print(redirs[0]["op"])  # '>'
print(redirs[0]["target"])  # 'output.txt'
```

#### `find_commands(tree)` → `List[CallExpr]`

Find all CallExpr nodes (command invocations) in the AST. Returns the full node objects rather than just names.

```python
from lovely_bash_permissions import parse_ast, find_commands

tree = parse_ast("ls -la | grep txt")
commands = find_commands(tree)
print(len(commands))  # 2
print(commands[0].args[0].parts[0].value)  # 'ls'
```

#### `find_arguments(tree)` → `List[List[Word]]`

Find all argument lists (excluding command names) as Word node objects.

```python
from lovely_bash_permissions import parse_ast, find_arguments

tree = parse_ast("ls -la /tmp")
args = find_arguments(tree)
print(len(args))  # 1
print(len(args[0]))  # 2 (two arguments: '-la' and '/tmp')
```

#### `has_pipe(tree)` → `bool`

Check if the command contains any pipe operators.

```python
from lovely_bash_permissions import parse_ast, has_pipe

print(has_pipe(parse_ast("ls -la")))  # False
print(has_pipe(parse_ast("ls | grep txt")))  # True
print(has_pipe(parse_ast("ls > file.txt")))  # False (redirect, not pipe)
```

#### `get_target_files(tree)` → `List[str]`

Extract file targets from redirections. Returns the names of files that will be modified or read by redirections.

```python
from lovely_bash_permissions import parse_ast, get_target_files

tree = parse_ast("cat file.txt > output.txt")
print(get_target_files(tree))  # ['output.txt']
```

### AST Node Types

The parser uses dataclasses to represent bash syntax:

| Type | Description |
|------|-------------|
| `File` | Top-level container with `stmts` array |
| `Stmt` | Single statement with `cmd`, `pos`, `end`, optional `redirs` |
| `CallExpr` | Command invocation with `args` array |
| `BinaryCmd` | Pipe/`&&`/`||` operator with `left`, `right` operands, `op`, and optional `redirs` |
| `Word` | A word with `parts` array |
| `Lit` | Literal string part of a word |
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
tree = parse_ast("ls | grep txt")
stmt = tree.stmts[0]
print(stmt.cmd.type)  # 'BinaryCmd'
print(stmt.cmd.op)  # '|'
```

## Examples

### Parsing Pipes

```python
from lovely_bash_permissions import parse_ast, get_commands, get_arguments

tree = parse_ast(
    'cat data.csv | grep pattern | awk "{print $1}" | sort -u > results.txt'
)

print(get_commands(tree))
# ['cat', 'grep', 'awk', 'sort']

print(get_arguments(tree))
# [['data.csv'], ['pattern'], ['"{print $1}"'], ['-u']]
```

### Parsing Redirections

```python
from lovely_bash_permissions import parse_ast, get_redirections

# Output redirect
tree = parse_ast("cat file.txt > output.txt")
redirs = get_redirections(tree)
print(redirs[0]["op"])  # '>'
print(redirs[0]["target"])  # 'output.txt'

# Append redirect
tree2 = parse_ast("echo line >> log.txt")
redirs2 = get_redirections(tree2)
print(redirs2[0]["op"])  # '>>'

# Input redirect
tree3 = parse_ast("sort < input.txt")
redirs3 = get_redirections(tree3)
print(redirs3[0]["op"])  # '<'
```

### Parsing Variables

```python
from lovely_bash_permissions import parse_ast, has_variable

print(has_variable(parse_ast("ls -la")))
# False

print(has_variable(parse_ast("echo $HOME")))
# True

print(has_variable(parse_ast("cat /path/to/file")))
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

tree = parse_ast("for f in *.txt; do echo $f; done")
print(get_commands(tree))
# ['echo']

tree2 = parse_ast("while true; do sleep 1; done")
print(get_commands(tree2))
# ['sleep']
```

### Logical Operators

```python
from lovely_bash_permissions import parse_ast, get_commands

tree = parse_ast("test -f file && cat file")
print(get_commands(tree))
# ['test', 'cat']

tree2 = parse_ast("ping -c1 host || echo unreachable")
print(get_commands(tree2))
# ['ping', 'echo']
```

### Finding Dangerous Commands

```python
from lovely_bash_permissions import parse_ast, get_commands


def is_dangerous(tree):
    dangerous = {"rm", "mv", "cp", "kill", "reboot", "shutdown"}
    commands = get_commands(tree)
    return any(c in dangerous for c in commands)


# Check before running
tree = parse_ast("rm -rf /tmp/cache")
if is_dangerous(tree):
    print("⚠️ Warning: this command could modify the system")
```

### Permission Checker

```python
from lovely_bash_permissions import parse_ast, get_target_files, get_redirections


def check_write_permissions(tree):
    """Check if command writes to files (output redirections)."""
    redirs = get_redirections(tree)
    write_ops = {">", ">>", "2>", "2>>", "&>", "&>>"}

    for r in redirs:
        if r["op"] in write_ops:
            print(f"Writing to: {r['target']}")

    return bool([r for r in redirs if r["op"] in write_ops])


tree = parse_ast("cat file.txt > output.txt")
check_write_permissions(tree)
# Writing to: output.txt
```

### Parsing Multi-Statement Scripts

```python
from lovely_bash_permissions import parse_ast, get_commands

tree = parse_ast("echo step 1\necho step 2")
print(len(tree.stmts))  # 2
print(get_commands(tree))  # ['echo', 'echo']
```

## Running Tests

### Permission Checker

```bash
uv sync
uv run pytest
```

## Lovely-Devin-Permissions Hook

`lovely-devin-permissions` is a Devin CLI permission hook that evaluates bash commands against configurable rules. It parses commands, extracts command segments, and evaluates each segment against rules from the configuration. It decides whether to allow, ask for approval, or deny execution based on rules for allowed patterns, blocked patterns, redirections, and more.

### Quick Start

```bash
# Test a command
eu run lovely-devin-permissions --test "ls -la"

# Check effective config
eu run lovely-devin-permissions --show-config

# Add required devin permission
eu run lovely-devin-permissions --setup
```

### Configuration

Configuration is loaded from multiple locations (highest precedence last):

1. `~/.config/devin/lovely-permissions.jsonc` (global)
2. `{project}/.devin/lovely-permissions.jsonc` (project)
3. `{project}/.devin/lovely-permissions.local.jsonc` (local)

Additionally, Devin's `config.json` files are consulted for `permissions.allow` entries:

1. `~/.config/devin/config.json` (global)
2. `{project}/.devin/config.json` (project)
3. `{project}/.devin/config.local.json` (local)

Files that don't exist are treated as empty objects `{}`. Configs are deep-merged: objects merge recursively, arrays concatenate, scalars override.

### Config Schema

```jsonc
{
  "bash": {
    "allowed_cmds_regex": [
      "^ls$",
      "^cat$",
      "^git$",
      "^npm run test$"
    ],
    "blocked_paths_regex": [
      "/etc/passwd",
      "/var/log"
    ],
    "output_redirection": "allow",
    "input_redirection": "ask",
    "background_execution": "deny"
  }
}
```

- **allowed_cmds_regex**: Regular expressions for allowed command names. Commands matching any pattern are allowed.
- **blocked_paths_regex**: Patterns for paths that should be blocked. If any argument matches, the command is denied.
- **output_redirection**: `allow`, `ask`, or `deny` for output redirections (`>`, `>>`)
- **input_redirection**: `allow`, `ask`, or `deny` for input redirections (`<`, `<<`)
- **background_execution**: `allow`, `ask`, or `deny` for background execution (`&`)

### Allowed Patterns

Commands match allowed patterns if the command name matches any pattern:

```bash
# Allowed
ls -la          # matches ^ls$
```

### Blocked Paths

Paths are blocked if any argument matches a blocked pattern:

```bash
# Blocked: /etc/passwd matches blocked pattern
cat /etc/passwd
```

### Redirection Rules

Redirections can be allowed, asked, or denied:

```bash
# Blocked: output redirection denied
echo "hello" > output.txt
```

### Background Execution

Background commands (with `&`) are evaluated separately:

```bash
# Blocked: background execution denied
long_running_command &
```

### Command Substitution

Commands with substitution (like `$(...)`) require approval regardless of other rules:

```bash
# Always asks, even if inner commands are allowed
echo "$(ls)"
```

### Aggregation Rules

For commands with multiple segments (pipes, `&&`, `||`), the most restrictive result wins:

| Scenario | Result |
|----------|--------|
| All allowed | Allow |
| All ask | Ask |
| All denied | Deny |
| Mixed allow/ask | Ask |
| Mixed allow/deny | Deny |
| Mixed ask/deny | Deny |

### Examples

```bash
# Allowed: both commands allowed
eu run lovely-devin-permissions --test "ls -la && cat file.txt"

# Ask: cat not allowed, ls is
eu run lovely-devin-permissions --test "ls -la && cat /etc/passwd"

# Blocked: cat /etc/passwd blocked
eu run lovely-devin-permissions --test "cat /etc/passwd"
```

### Dev Setup

For development, run the tests with:

```bash
uv run pytest
```

You can also run the hook in debug mode:

```bash
DEVIN_DEBUG=1 eu run lovely-devin-permissions --test "echo test"
```

### Testing Configs

Create test configs in a temporary project directory:

```bash
mkdir -p test-project/.devin
cat > test-project/.devin/lovely-permissions.jsonc << 'EOF'
{
  "bash": {
    "allowed_cmds_regex": ["^ls$", "^cat$"],
    "blocked_paths_regex": ["/etc/passwd"]
  }
}
EOF
DEVIN_PROJECT_DIR=test-project eu run lovely-devin-permissions --test "ls -la"
```

### License

See the repository for license information.
