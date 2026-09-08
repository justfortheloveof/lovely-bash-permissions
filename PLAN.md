# Plan

## Objective

We are working on our python devin_cli functionality.

For each ISSUE documented below, you MUST orchestrate the implementation by ALWAYS spawning a research agent to investigate implementation options. You then pick the proper implementation and spawn an agent for implementation of the chosen solution.

Test Examples:

```
uv run lovely-devin-permissions --test 'cmd'
node /home/alx/repos/jftlo/lovely-devin-permissions/dist/hook.js --test 'cmd'
```

## ISSUES

### Number 1

**DONE (31a51d4)** Fixed subshell permission bug.

### Number 3

**DONE (75dce53)** Consolidated duplicate blocked-pattern logic into single shared helper.

- `deny_item_to_pattern()` renamed to `_item_to_anchored_pattern()` (generic name, applies to both allow and deny lists)
- `effective_bash.py` now uses shared helper for both allow and deny pattern conversion
- `deny_item_to_pattern()` kept as backward-compatible alias
- 542 tests pass, ruff lint clean

The issue was in `evaluate_bash_command()` at lines ~319-320: when nested commands inside a subshell didn't match allowed patterns and `subshell_policy == "allow"`, it set `overall_status = "deny"` (auto-rejected). But "allow" policy means skip validation — failed validation should result in ask (user approval needed), not deny.

Fix: changed the condition to check `overall_status == "deny"` first (blocked paths already set this), then handle each policy: allow → ask, deny → deny, ask → ask.

Both `echo $(herdr)` and `herdr` now correctly return ASK (REQUIRES-USER-APPROVAL) instead of block.

Unexpected:
```
lovely-bash-permissions devin-cli ❯ uv run lovely-devin-permissions -t 'echo $(herdr)'
{
  "decision": "block",
  "reason": "[♡ perms: ❤️ auto-rejected] \"herdr\" commands inside subshell do not match allowed patterns.",
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "updatedInput": {
      "command": ": '[♡ perms: ❤️ auto-rejected] \"herdr\" commands inside subshell do not match allowed patterns.' ; echo $(herdr)"
    }
  }
}
```

### Number 6

**TODO** Bare `except Exception` with noqa suppression — multiple files catch all exceptions (`hook.py`, `manager.py`, `devin_cli.py`). Should catch specific exceptions (FileNotFoundError, ValueError).

### Number 7

**TODO** `_word_value` helper duplicated — conceptually reimplemented in `evaluate.py`; should use single source of truth from `inspect.py`.

### Number 8

**TODO** `_resolve_output_level()` docstring says "Any-asks semantics" but implementation uses deny-first priority — misleading documentation.

### Number 9

**TODO** Stale `find_shfmt()` cache — lru_cache doesn't check if binary exists/moved, causing silent FileNotFoundError until process restart.

### Number 10

**TODO** Unused converter section header in `converter.py` (~line 37) — dead space between orphaned header and actual converters.

Expected:
```
lovely-bash-permissions devin-cli ✗ uv run lovely-devin-permissions -t 'herdr'
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "updatedInput": {
      "command": ": '[♡ perms: 💛 REQUIRES-USER-APPROVAL] \"herdr\" command does not match allowed patterns.' ; herdr"
    }
  }
}
```

### Number 6

**TODO** Bare `except Exception` with noqa suppression — multiple files catch all exceptions (`hook.py`, `manager.py`, `devin_cli.py`). Should catch specific exceptions (FileNotFoundError, ValueError).

### Number 7

**TODO** `_word_value` helper duplicated — conceptually reimplemented in `evaluate.py`; should use single source of truth from `inspect.py`.

### Number 8

**TODO** `_resolve_output_level()` docstring says "Any-asks semantics" but implementation uses deny-first priority — misleading documentation.

### Number 9

**TODO** Stale `find_shfmt()` cache — lru_cache doesn't check if binary exists/moved, causing silent FileNotFoundError until process restart.

### Number 10

**TODO** Unused converter section header in `converter.py` (~line 37) — dead space between orphaned header and actual converters.
