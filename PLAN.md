# Plan

## Objective

We are working on our python devin_cli functionality.

For each project documented below, you MUST orchestrate the implementation by ALWAYS spawning a research agent to investigate implemetation options. You then pick the proper implementation and spawn an agent for implementation of the chosen solution.

Test Examples:

```
uv run lovely-devin-permissions --test 'cmd'
node /home/alx/repos/jftlo/lovely-devin-permissions/dist/hook.js --test 'cmd'
```

## Projects

### 1. Trailing period in reason messages (PER-TOOL config) [x]
**Python**: Includes trailing period inside the quoted pattern — `"command matches allowed pattern ^ls(\\s+.*)?$."` (period INSIDE quotes)
**TS**: No trailing period — `"command matches allowed pattern ^ls(\\s+.*)?$"`
**Impact**: Cosmetic only — reason text differs but decision logic is identical.
**Desired Behaviour**: remove trailing period

### 2. Reason detail in ask decisions (non-redirection asks) [x]
**Python**: Includes matching patterns plus denial — `"command matches allowed pattern ^ls(\\s+.*)?$; \\"rm\\" command does not match allowed patterns"`
**TS**: Only includes denial — `"\"rm\" command does not match allowed patterns"`
**Impact**: Cosmetic — Python shows which segments matched, TS only shows denial.
**Desired Behaviour**: only include denial reasons when asking, approval reasons should only be shown on auto-approve

### 3. Background execution (`&`) default policy
**Python**: Approves — `background_execution` defaults to "allow" (no project config overrides it)
**TS**: Asks — `background_execution` defaults to "ask" (per effective-bash.ts: `'*': 'ask'`, no explicit background_execution)
**Root cause**: Python's rules.py line 372 defaults `background_execution` to "allow"; TS schema has no default for background_execution, falling back to `'*': 'ask'`.
**Impact**: Behavioral — Python is more permissive for background commands. May need alignment if TS behavior was intentional.
**Desired Behaviour**: Everything should default to ask. This is paramount.

### 4. Subshells `(cmd)` handling
**Python**: Approves — `"command is allowed"` (subshell itself passes)
**TS**: Asks — `"subshell or command substitution requires approval"`
**Root cause**: Same as #6 — TS treats subshells the same as command substitutions.
**Impact**: Behavioral — Python allows subshell-wrapped commands without review.
**Desired Behaviour**: This is unexpected. Our python parser sees the cmd in the subshell, even deeply nested. Our Python devin cli should catch these for the "subshell or cmd substitution" permission but also parse the inner cmd like any normal cmd

### 5. Input redirection (`<`) blocked paths check
**Python**: Approves `cat < /etc/passwd` — does NOT check blocked_paths against redirection targets
**TS**: Blocks `cat < /etc/passwd` — checks blocked_paths against redirect target (`"Redirect target \\"/etc/passwd\\" matches blocked path pattern"`)
**Root cause**: Python's evaluate.py only checks arguments, not redirection targets, against blocked_paths_regex.
**Impact**: Behavioral — Python is more permissive for input redirections to blocked paths. This may be a security concern.
**Desired Behaviour**: This is a problem, we should catch and block this

### 6. Heredoc input redirect (`<<`)
**Python**: Approves `cat << EOF` — treats as "empty command" when no args parsed
**TS**: Asks — `"input redirection requires approval because input_redirection is set to ask"`
**Root cause**: Python parser returns empty/whitespace command for heredoc; TS parses it as input redirect.
**Impact**: Behavioral — Python may miss input redirections that should be reviewed.
**Desired Behaviour**: This seems wrong, how is that an empty cmd? The parser probably has the info we need.

### 7. Whitespace-only commands
**Python**: Approves `"empty command"` — treats whitespace as empty, auto-approves
**TS**: Asks — `"bash permission is set to ask"` — treats whitespace as needing approval
**Impact**: Cosmetic/minor — both handle it, but Python approves while TS asks.
**Desired Behaviour**: This is unexpected, all cmds must pass through the approval same flow and whitespace only strings would be blocked with our current config
