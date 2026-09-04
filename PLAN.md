# Plan

## Objective

The all potential variations and edge cases of commands you test with the `--test` flag of the Python VS TS programs and document ALL differences in the "Findings" section.

Examples:

```
uv run lovely-devin-permissions --test 'cmd'
node /home/alx/repos/jftlo/lovely-devin-permissions/dist/hook.js --test 'cmd'
```

## Findings

### 1. Trailing period in reason messages (PER-TOOL config)
**Python**: Includes trailing period inside the quoted pattern — `"command matches allowed pattern ^ls(\\s+.*)?$."` (period INSIDE quotes)
**TS**: No trailing period — `"command matches allowed pattern ^ls(\\s+.*)?$"`
**Impact**: Cosmetic only — reason text differs but decision logic is identical.

### 2. Reason detail in updatedInput (block decisions)
**Python**: Includes full reason text inside updatedInput — `"Blocked by bash permissions: Argument \\"/etc/passwd\\" matches blocked path pattern /\\/etc/. The tool has not been run."`
**TS**: Only includes the label — `"[♡ perms: ❤️ auto-rejected]"`
**Impact**: Cosmetic only — both block, but Python's updatedInput is more informative.

### 3. Reason detail in ask decisions (non-redirection asks)
**Python**: Includes matching patterns plus denial — `"command matches allowed pattern ^ls(\\s+.*)?$; \\"rm\\" command does not match allowed patterns"`
**TS**: Only includes denial — `"\"rm\" command does not match allowed patterns"`
**Impact**: Cosmetic — Python shows which segments matched, TS only shows denial.

### 4. Redirection reason format (PER-TOOL config)
**Python**: `"output redirection requires approval"` — generic reason
**TS**: `"output redirection requires approval because output_redirection is set to ask"` — explains the config setting
**Impact**: Cosmetic — TS gives more context.

### 5. Background execution (`&`) default policy
**Python**: Approves — `background_execution` defaults to "allow" (no project config overrides it)
**TS**: Asks — `background_execution` defaults to "ask" (per effective-bash.ts: `'*': 'ask'`, no explicit background_execution)
**Root cause**: Python's rules.py line 372 defaults `background_execution` to "allow"; TS schema has no default for background_execution, falling back to `'*': 'ask'`.
**Impact**: Behavioral — Python is more permissive for background commands. May need alignment if TS behavior was intentional.

### 6. Command substitution (`$(...)`) handling
**Python**: Approves — does NOT require approval for command substitutions (echo $(ls) passes)
**TS**: Asks — `"subshell or command substitution requires approval"`
**Root cause**: Python does not check has_variable() for approval; TS explicitly requires approval for substitutions.
**Impact**: Behavioral — Python is more permissive. Substitution commands may execute without review in Python that TS would block.

### 7. Subshells `(cmd)` handling
**Python**: Approves — `"command is allowed"` (subshell itself passes)
**TS**: Asks — `"subshell or command substitution requires approval"`
**Root cause**: Same as #6 — TS treats subshells the same as command substitutions.
**Impact**: Behavioral — Python allows subshell-wrapped commands without review.

### 8. Input redirection (`<`) blocked paths check
**Python**: Approves `cat < /etc/passwd` — does NOT check blocked_paths against redirection targets
**TS**: Blocks `cat < /etc/passwd` — checks blocked_paths against redirect target (`"Redirect target \\"/etc/passwd\\" matches blocked path pattern"`)
**Root cause**: Python's evaluate.py only checks arguments, not redirection targets, against blocked_paths_regex.
**Impact**: Behavioral — Python is more permissive for input redirections to blocked paths. This may be a security concern.

### 9. Heredoc input redirect (`<<`)
**Python**: Approves `cat << EOF` — treats as "empty command" when no args parsed
**TS**: Asks — `"input redirection requires approval because input_redirection is set to ask"`
**Root cause**: Python parser returns empty/whitespace command for heredoc; TS parses it as input redirect.
**Impact**: Behavioral — Python may miss input redirections that should be reviewed.

### 10. Whitespace-only commands
**Python**: Approves `"empty command"` — treats whitespace as empty, auto-approves
**TS**: Asks — `"bash permission is set to ask"` — treats whitespace as needing approval
**Impact**: Cosmetic/minor — both handle it, but Python approves while TS asks.

### 11. Empty command (zero length)
**Both**: Return "No response generated" — identical behavior.

### Summary of behavioral differences (affecting decisions)
| Scenario | Python | TS |
|----------|--------|----|
| `cmd &` (background) | approve | ask |
| `$(...)` substitution | approve | ask |
| `(subshell)` | approve | ask |
| `< blocked_path` input redirect | approve | block |
| `<< heredoc` | approve | ask |
| whitespace-only | approve | ask |

### Summary of cosmetic differences (same decision, different message)
- Trailing period in reason strings
- Reason detail level in updatedInput (block/ask decisions)
- Redirection reason verbosity
