# Lovely-Devin-Permissions

A Devin CLI permission hook that evaluates bash commands against configurable rules.

## Overview

lovely-devin-permissions is a permission checking system for bash commands that combines:

- **Lovely-permissions config**: A JSONC configuration format with deep merge across multiple sources
- **Devin config loading**: Extracts `permissions.allow` entries from Devin's three config files
- **Bash command parsing**: Uses shfmt to parse commands into structured AST trees
- **Multi-segment evaluation**: Handles pipes, `&&`, `||`, background, and nested commands
- **Rule-based evaluation**: Allowed patterns, blocked patterns, redirection rules, background rules
- **Hook event processing**: Processes PreToolUse and PermissionRequest events from Devin

## Installation

```bash
uv add lovely-devin-permissions
```

Or from source:

```bash
git clone https://github.com/your-org/lovely-devin-permissions.git
cd lovely-devin-permissions
uv sync
```

## Quick Start

```bash
# Test a command
eu run lovely-devin-permissions --test "ls -la"

# Show effective config
eu run lovely-devin-permissions --show-config

# Setup hook in Devin config
eu run lovely-devin-permissions --setup
```

## Configuration

### Sources

Configuration is loaded from multiple sources (highest precedence last):

1. **Global**: `~/.config/devin/lovely-permissions.jsonc`
2. **Project**: `{project}/.devin/lovely-permissions.jsonc`
3. **Local**: `{project}/.devin/lovely-permissions.local.jsonc`

Additionally, Devin's `config.json` files are consulted for `permissions.allow` entries:

1. **Global**: `~/.config/devin/config.json`
2. **Project**: `{project}/.devin/config.json`
3. **Local**: `{project}/.devin/config.local.json`

Files that don't exist are treated as empty objects `{}`. Configs are **deep-merged**: objects merge recursively, arrays concatenate, scalars override.

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

| Field | Type | Description |
|-------|------|-------------|
| `allowed_cmds_regex` | array of strings | Regular expressions for allowed command names |
| `blocked_paths_regex` | array of strings | Patterns for paths that should be blocked |
| `output_redirection` | "allow"\|"ask"\|"deny" | Rule for output redirections (`>`, `>>`) |
| `input_redirection` | "allow"\|"ask"\|"deny" | Rule for input redirections (`<`, `<<`) |
| `background_execution` | "allow"\|"ask"\|"deny" | Rule for background execution (`&`) |

## Command-Line Interface

### Flags

```
lovely-devin-permissions [options]
  --setup, -s              Add the required Devin permission for the hook label
  --show-config            Print the effective bash permission configuration and considered files
  --test <command>         Test a command as a PreToolUse event and pretty print the response
  --help, -h              Show help
```

### Mode Detection

The CLI detects its mode based on command-line flags and stdin:

- **CLI mode**: Any flag is provided (`--setup`, `--test`, `--show-config`)
- **Hook mode**: No CLI flags and stdin has data
- **No input**: No CLI flags and stdin is empty → exit 0 silently

## Permission Rules

### Allowed Patterns

```bash
# Allowed: matches ^ls$
ls -la
```

Commands match allowed patterns if the command name matches any pattern in `allowed_cmds_regex`.

### Blocked Patterns

```bash
# Blocked: /etc/passwd matches blocked pattern
cat /etc/passwd
```

Paths are blocked if any argument matches a pattern in `blocked_paths_regex`.

### Redirection Rules

```bash
# Blocked: output redirection denied
echo "hello" > output.txt
```

### Background Rules

```bash
# Blocked: background execution denied
long_running_command &
```

### Command Substitution

```bash
# Always asks, even if inner commands are allowed
echo "$(ls)"
```

Commands with command substitution (e.g., `$(...)`) require approval regardless of other rules.

## Aggregation Rules

For commands with multiple segments (pipes, `&&`, `||`), the most restrictive result wins:

| Scenario | Result |
|----------|--------|
| All allowed | Allow |
| All ask | Ask |
| All denied | Deny |
| Mixed allow/ask | Ask |
| Mixed allow/deny | Deny |
| Mixed ask/deny | Deny |

## Examples

```bash
# Allowed: both commands allowed
eu run lovely-devin-permissions --test "ls -la && cat file.txt"

# Ask: cat not allowed, ls is
eu run lovely-devin-permissions --test "ls -la && cat /etc/passwd"

# Blocked: cat /etc/passwd blocked
eu run lovely-devin-permissions --test "cat /etc/passwd"
```

## Dev Setup

```bash
uv sync
uv run pytest
```

## Testing Configs

Create test configs in a temporary project directory:

```bash
mkdir -p test-project/.devin
cat > test-project/.devin/lovely-permissions.jsonc << 'EOF2'
{
  "bash": {
    "allowed_cmds_regex": ["^ls$", "^cat$"],
    "blocked_paths_regex": ["/etc/passwd"]
  }
}
EOF2
DEVIN_PROJECT_DIR=test-project eu run lovely-devin-permissions --test "ls -la"
```
