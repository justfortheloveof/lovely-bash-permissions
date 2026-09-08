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

### Number 3

**DONE (75dce53)** Consolidated duplicate blocked-pattern logic into single shared helper.

- `deny_item_to_pattern()` renamed to `_item_to_anchored_pattern()` (generic name, applies to both allow and deny lists)
- `effective_bash.py` now uses shared helper for both allow and deny pattern conversion
- `deny_item_to_pattern()` kept as backward-compatible alias
- 542 tests pass, ruff lint clean


### Number 6

**DONE (2e0571b)** Replaced bare except Exception with specific exception types.

- jsonc.py: OSError, UnicodeDecodeError for file read operations
- manager.py: kept broad Exception with noqa (intentional error-handling code)
- devin_cli.py: OSError for file write, ValueError/FileNotFoundError/OSError for config loading
- hook.py: FileNotFoundError/OSError for config load, same plus ValueError for bash config
- All noqa: BLE001 suppressions removed where specific exceptions used
- 542 tests pass

### Number 7

**TODO** `_word_value` helper duplicated — conceptually reimplemented in `evaluate.py`; should use single source of truth from `inspect.py`.

### Number 8

**DONE (b1cb4cc)** Fixed misleading docstring in `_resolve_output_level()` — renamed from "Any-asks semantics" to "Deny-first escalation" with clarified precedence rule.

### Number 9

**DONE (b1cb4cc)** `find_shfmt()` now checks if cached path still exists before returning; warns and re-searches if stale.

### Number 10

**DONE (b1cb4cc)** Removed orphaned "# Type mapping from shfmt's JSON to our dataclasses" section header in `converter.py`.
