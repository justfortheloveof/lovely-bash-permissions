# Plan: Strengthen config schema — add missing bash permission fields and wildcard `*` (round 3)

## Objective

Add three improvements to the config system, drawn from the TypeScript `BashPermissions` implementation:

| # | Issue | Fix |
|---|-------|-----|
| 1 | Schema missing bash-specific permission fields (`output_redirection`, `input_redirection`, `background_execution`) | Model these in `ToolConfig`; they are recognized, validated, and consumed by `effective_bash.py` |
| 2 | No wildcard `*` permission level at config root (TS has `'*': permissionLevelSchema`) | Accept and validate `"*": "allow"/"deny"/"ask"` at top level; `effective_bash.py` reads it as default |

**Explicitly removed from scope**: allow/deny shorthand fields (`allow: [...]`, `deny: [...]`), and any other shorthands — these are **not** added. Hot-reload / file watching (issue 5), JSON schema/IDE support (issue 10), and issues 3, 6, 7, 8, 9 are deferred to a later plan.

## Background: Current state

- `config/schema.py`: Pydantic models (`ToolConfig`, `PermissionsConfig`) with `"extra": "allow"` — silently accepts typos, but also **omits** bash-specific fields the TS side consumes.
- `_TOOL_RECOGNIZED_FIELDS` lists `allow`, `deny`, `subshell`, `output_redirection`, `input_redirection`, `background_execution` as allowed keys, but `ToolConfig` only models `permission`, `blocked_paths_regex`, `allowed_cmds_regex`. Configs using the bash fields pass validation but are silently ignored by the evaluator.
- No wildcard `*` permission level at config root — TS has it, Python doesn't model it.


## Implementation Steps (sequential, one agent per step)

---

### Step 3a: Model bash-specific permission fields in `ToolConfig` (issue 1)

**Goal**: Add the four bash-specific permission fields that `effective_bash.py` consumes, so config files using them are validated rather than silently ignored.

**Changes**:
1. In `config/schema.py`, extend `ToolConfig` with:
   - `output_redirection: OutputRedirectionPolicy | None = None` — union of `PermissionLevel` (string) or dict with keys `*`, `stdout_to_dev_null`, `stderr_to_dev_null`, `stderr_to_stdout`.
   - `input_redirection: PermissionLevel | None = None`
   - `background_execution: PermissionLevel | None = None`
   - `subshell: PermissionLevel | None = None`
2. Define `OutputRedirectionPolicy` as a Pydantic model (or use a custom type with a validator) mirroring the TS `outputRedirectionPolicySchema`.
3. Remove `allow`, `deny` from `_TOOL_RECOGNIZED_FIELDS` — shorthand fields are **not** added (per project decision). Keep `subshell`, `output_redirection`, `input_redirection`, `background_execution`.

**Tests**: `test_tool_config_output_redirection_string`, `test_tool_config_output_redirection_dict`, `test_tool_config_input_background_subshell_levels`.

---

### Step 3b: Add wildcard `*` permission level at config root (issue 2)

**Goal**: Accept `"*": "allow"|"deny"|"ask"` at the top level, validating it as a `PermissionLevel`.

**Changes**:
1. In `PermissionsConfig`, add `wildcard: PermissionLevel | None = None` (or a field named `"*"` via `Field(alias="*")`) to model the root-level wildcard.
2. `_check_version` / `_check_top_level_keys` already skip `"*"` — keep that behavior; just add the field to the model.
3. Update `effective_bash.py` (`get_effective_bash_config`) to read the wildcard from config instead of hardcoding `"ask"` default.

**Tests**: `test_wildcard_allow`, `test_wildcard_deny`, `test_wildcard_ask`.

---

### Step 3c: Run full test suite and fix any issues

Run `uv run pytest` after each step. Fix linting (ruff, mypy) before committing.

## Files Modified
- EDIT: `src/lovely_bash_permissions/config/schema.py` (steps 3a, 3b)
- EDIT: `src/lovely_bash_permissions/config/effective_bash.py` (step 3b — read wildcard from config)

- EDIT: `tests/test_schema.py`, `tests/test_permissions_manager.py` (all steps)

## Why this is better than the current approach

| Old | New |
|---|---|
| Bash fields (`output_redirection`, etc.) silently ignored | Fields modeled, validated, consumed by evaluator |
| No wildcard `*` at config root | Root-level default permission level accepted and used |

