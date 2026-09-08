# Plan: Config System Improvements (#1, #5, #10)

## Overview

Three independent changes to the config system. Each step is self-contained so agents can work sequentially without cross-dependency.

---

- [x] ## Step 1a: Replace `extra="allow"` with `extra="forbid"` in PermissionsConfig

**File:** `src/lovely_bash_permissions/config/schema.py`
**Test file:** `tests/test_schema.py`

### Current state

- `PermissionsConfig.model_config = {"extra": "allow", ...}` — any unrecognized top-level key is silently accepted as a tool name, then validated against `ToolConfig`.
- Unknown keys become "tools" with no warning. Typos like `"Bash"` vs `"bash"` are silently accepted.

### Changes

1. In `schema.py`, change:
   ```python
   # Before
   model_config = {"extra": "allow", "str_strip_whitespace": True}
   ```
   ```python
   # After
   model_config = {"extra": "forbid", "str_strip_whitespace": True}
   ```

2. Add a constant `KNOWN_TOOLS` (set of str) listing the only recognized tool names:
   ```python
   KNOWN_TOOLS = frozenset({"bash"})
   ```

3. Add a `@model_validator(mode="after")` to `PermissionsConfig` that checks every extra key against `KNOWN_TOOLS`, raising a `ValueError` for unrecognized keys. The error message should name the unknown key.

### Tests to update/add (`tests/test_schema.py`)

- Existing test `test_unknown_top_level_key_rejected` already expects a `ValidationError` for `"Bash": "allow"` — verify it still passes (it will, since `"forbid"` rejects extra keys).
- Add a test `test_unknown_tool_name_rejected` that passes an unrecognized key (e.g. `"git"`) and asserts `ValidationError`.
- Add a test `test_known_tool_bash_accepted` confirming `"bash"` still works.

### Files affected
- `src/lovely_bash_permissions/config/schema.py` (model_config + validator)
- `tests/test_schema.py` (add/adjust tests)

---

- [x] ## Step 1b: Remove `extra="allow"` from ToolConfig (it already forbids)

**File:** `src/lovely_bash_permissions/config/schema.py`
**Test file:** `tests/test_schema.py`

### Current state

- `ToolConfig.model_config = {"extra": "forbid"}` — already forbids extra fields.
- Tests like `test_unrecognized_tool_field_warns` confirm `"blocked_path_regex"` (typo) raises.

### Changes

No code changes needed — this step is just confirming existing behavior and leaving the config as-is. The step exists so agents verify it hasn't regressed after Step 1a's changes (extra forbid at PermissionsConfig level now covers tool names too).

### Tests to verify (`tests/test_schema.py`)

- `test_unrecognized_tool_field_warns` — must still pass (extra forbid in ToolConfig).
- `test_allow_deny_shorthand_rejected` — must still pass.

### Files affected
- None (verification only). If any test fails, re-add `extra="forbid"` to ToolConfig.

---

- [x] ## Step 2: Per-kind output redirection policy resolution (issue #5)

**File:** `src/lovely_bash_permissions/rules.py`
**Test file:** `tests/test_rules.py` (or add to it)

### Current state

`_resolve_output_level(kinds, policy)` uses **deny-first escalation**: if ANY redirection kind resolves to deny → overall deny; else if any resolve to ask → overall ask. This means one `stderr_to_stdout: "deny"` kills ALL redirections including harmless ones like `stdout > /tmp/file`.

### Desired behavior

Each redirection kind gets its own level independently. The overall status is:
- **deny** if ANY kind resolves to deny (keep this)
- **ask** only if SOME kinds are ask and NONE are deny (keep this)

The difference: previously "ask" meant "at least one kind is ask". Now it means the same, but **each kind's level is looked up independently** from its own policy key, falling back to `"*"` wildcard. The current code already does per-kind lookup — the real fix is ensuring **non-special kinds ("other") also get their own independent level** rather than all lumping into wildcard.

Actually, re-reading `_resolve_output_level`: it already does per-kind lookup (`policy.get(kind, wildcard_level)`). The issue is that `"other"` kind falls back to wildcard for ALL non-special kinds together. Fix: each kind should independently check its own policy key, falling back to wildcard only if no specific key exists.

### Changes in `rules.py`

In `_resolve_output_level`:

```python
def _resolve_output_level(kinds: list[str], policy: dict[str, Any]) -> str:
    """Resolve output redirection level using per-kind policy keys.

    Each kind is checked independently against its own policy key,
    falling back to wildcard "*".  Deny takes priority over ask.

    Args:
        kinds: List of redirection kind strings (e.g. "stdout_to_dev_null").
        policy: Dict-form output_redirection policy with kind-specific keys.

    Returns:
        "allow", "ask", or "deny".
    """
    wildcard_level = policy.get("*", "allow")

    has_deny = False
    has_ask = False
    for kind in kinds:
        # Each kind gets its own level lookup, independent of others
        level = policy.get(kind, wildcard_level)
        if level == "deny":
            has_deny = True
        elif level == "ask":
            has_ask = True

    if has_deny:
        return "deny"
    if has_ask:
        return "ask"
    return "allow"
```

This is mostly the same code — key difference: **each kind independently checks its own policy key** instead of lumping "other" into wildcard. The current code already does this per-kind, but add a comment clarifying independence.

### Tests to add (`tests/test_rules.py`)

1. `test_output_redirection_per_kind_independent` — two redirections, one kind=stdout_to_dev_null with "allow", other kind=stderr_to_stdout with "ask" → overall should be "ask" (not deny).
2. `test_output_redirection_kind_deny_overrides` — one kind=allow, other kind=deny → overall "deny" (verify deny priority kept).
3. `test_output_redirection_all_allow` — all kinds "allow" → overall "allow".
4. `test_output_redirection_wildcard_fallback` — kind not in policy uses wildcard level.

### Files affected
- `src/lovely_bash_permissions/rules.py` (`_resolve_output_level`)
- `tests/test_rules.py` (new tests)

---

- [x] ## Step 3: Test hook.py config consumption integration (#10a)

**Test file:** `tests/test_hook_integration.py` (new file)

### Context

`hook.py` has two public functions:
- `generate_hook_response(event, decision)` — converts a permission decision into hook response JSON for the agent.
- `process_hook_event(event)` — loads config via `PermissionsManager`, evaluates command, returns action.

### Tests to add (`tests/test_hook_integration.py`)

Import from `lovely_bash_permissions.hook`:
- `generate_hook_response`
- `process_hook_event`

Tests:

1. `test_pretooluse_allow` — event with hook_event_name="PreToolUse", tool_name="exec", command="ls"; decision={"action":"allow"} → returns {"decision":"approve", "hookSpecificOutput":{"updatedInput":{"command":": '[♡ perms: 💚 auto-approved]' ; ls"}}}
2. `test_pretooluse_block` — action="block" → returns {"decision":"block", "reason":"[♡ perms: ❤️ auto-rejected]", ...}
3. `test_pretooluse_ask` — action="ask" → returns {"decision":"approve", "hookSpecificOutput":{"updatedInput":{"command":": '[♡ perms: 💛 REQUIRES-USER-APPROVAL]' ; ls"}}}
4. `test_pretooluse_skip` — action="skip" → returns None
5. `test_non_exec_tool_skipped` — tool_name!="exec" → process_hook_event returns {"action":"skip"}
6. `test_empty_command_skipped` — command="" → skip
7. `test_config_load_failure_fallback_ask` — project_dir pointing to nonexistent config dir → returns {"action":"ask", "reason": "..."} (config error fallback)
8. `test_effective_bash_config_failure_fallback_ask` — configure bash config to be invalid → returns {"action":"ask"}
9. `test_permission_request_allow` — event with hook_event_name="PermissionRequest", action="allow" → returns {"decision":"approve"}
10. `test_permission_request_block` — action="block" → returns {"decision":"block", "reason":...}
11. `test_permission_request_ask` — action="ask" → returns None (asks pass through)
12. `test_reason_preserved_in_block` — block with reason string → reason appears in response

### Files affected
- `tests/test_hook_integration.py` (new file)

---

- [x] ## Step 4: Test cli.py config consumption integration (#10b)

**Test file:** `tests/test_cli_integration.py` (new file, or add to existing `tests/test_cli.py`)

### Context

`cli.py` is the `lovely-bash-inspection` CLI. It parses bash code and prints an inspection report. It does **not** directly load permissions config, but it consumes parsed AST and has integration points worth testing (input modes, error handling).

### Tests to add (`tests/test_cli_integration.py`)

Import from `lovely_bash_permissions.cli`:
- `main` (entry point, returns exit code)

Tests:

1. `test_main_string_basic` — `main(["--string", "ls -la"])` → exit 0, output contains "cmd: ls"
2. `test_main_string_pipe` — `"ls | grep test"` → output mentions pipe
3. `test_main_empty_string` — `""` → exit 2 (usage error via `_die`)
4. `test_main_parse_error` — `"{" invalid"` → exit 3 (parse error)
5. `test_main_no_input` — no args, stdin is tty → exit 2 (no input error)
6. `test_main_dialect_arg` — `"--dialect", "zsh"` → parses without error

### Files affected
- `tests/test_cli_integration.py` (new file)

---

## Order of execution

1. **Step 1a** — schema forbid + known tools (changes core validation)
2. **Step 1b** — verify ToolConfig forbid (no code change, just test verification)
3. **Step 2** — per-kind resolution (changes rules logic, independent of schema)
4. **Step 3** — hook integration tests (tests existing code, independent)
5. **Step 4** — cli integration tests (tests existing code, independent)

Steps 1a and 2 modify source code; steps 3-4 only add tests.

## Commit messages

After each step completes, commit with:
- "Step 1a: PermissionsConfig forbid extra + known tools"
- "Step 1b: Verify ToolConfig forbid extra"
- "Step 2: Per-kind output redirection policy resolution"
- "Step 3: Hook integration tests"
- "Step 4: CLI integration tests"

## Verification

After all steps: `uv run pytest` must pass (both new and existing tests).
