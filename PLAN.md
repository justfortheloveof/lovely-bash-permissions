# Plan: Strengthen config schema validation and error reporting (round 2)

## Objective

Fix issues 1, 3, 5, 6, 7, and 9 from the config review:

| # | Issue | Fix |
|---|-------|-----|
| 1 | `extra: "allow"` silently accepts typos (e.g. `"Bash": {}`) | Reject unknown top-level keys, emit warnings for unrecognized fields per tool |
| 3 | `blocked_paths_regex` / `allowed_cmds_regex` patterns validated at runtime only | Validate each pattern compiles during config load, fail fast |
| 5 | `read_jsonc_file` returns None on any read error, indistinguishable from missing file | Return a result type with success/failure + error reason enum (`NotFound`, `PermissionDenied`, `ParseError`) |
| 6 | No e2e test that precedence ordering works (global < project < local) | Add tests writing all 3 files with conflicting values, verify highest precedence wins |
| 7 | Config has no schema documentation output command | Add `--show-config` and `--test "<cmd>"` CLI commands (mirror TypeScript) |
| 9 | Deep merge replaces whole nested objects instead of merging their keys (e.g. global `bash.allowed_cmds_regex` lost when local adds `bash.blocked_paths_regex`) | Fix merge to recursively merge object keys; warn on cross-level key conflicts |

Issues 2, 4, 8 (per-tool inheritance docs, caching/TTL, config file existence check in tests) are deferred to a later plan.

## Background: Current state

- `config/schema.py`: Pydantic models (`ToolConfig`, `PermissionsConfig`) with `"extra": "allow"` — silently accepts typos.
- Pattern validation (`_strip_trailing_period`) happens at model-validation time but regex validity isn't checked until runtime.
- `read_jsonc_file` returns `None` on any error, hiding the cause (missing file vs permission denied).
- Merge replaces nested objects wholesale — global `bash.allowed_cmds_regex` is lost when local adds any key to `bash`.
- No end-to-end test verifies precedence ordering actually works.

## Implementation Steps (sequential, one agent per step)

---

### Step 3a: Add result type and improve error reporting in jsonc reader (issue 5)

**Goal**: Replace `read_jsonc_file` returning `(dict | None)` with a typed result that distinguishes missing files, permission errors, and parse errors.

**Changes**:
1. Add `class JsoncLoadResult` dataclass in `jsonc.py`:
   - Fields: `value: dict[str, Any] | None`, `error: str | None`
   - Factories: `JsoncLoadResult.ok(dict)`, `JsoncLoadResult.missing(path)`, `JsoncLoadResult.parse_error(path, msg, line, col)`, `JsoncLoadResult.read_error(path, err)`
2. Rewrite `read_jsonc_file` to return `JsoncLoadResult`.
3. Update every caller (`loader.py`, `devin.py`) to match on result type instead of checking `None`.

**Tests**: `test_jsonc_load_result_missing`, `test_jsonc_load_result_parse_error`, `test_jsonc_load_result_perm_denied`.

---

### Step 3b: Fix deep merge to recursively merge nested objects (issue 9)

**Completed**: Modified `merge_deep()` in loader.py to recursively merge nested objects and collect conflict warnings. Updated all existing tests for new return type `(dict, list[str])`. Added `_warn_conflict` helper. Tests updated in test_config_loader.py and test_jsonc.py. All 583 tests pass; linting clean.

**Changes**:
1. In `loader.py` `merge_deep()`: after merging objects recursively, collect keys present in both target and source for that object; when they conflict (same key, different values), emit a warning like `"key 'allowed_cmds_regex' defined in project config overrides global"`.
2. Add helper `_warn_conflict(key, level1, level2)` that appends to a warnings list threaded through merge.

**Tests**: `test_merge_nested_objects_both_keys`, `test_merge_warns_on_conflict`.

---

### Step 3c: Validate regex patterns at config load time (issue 7)

**Goal**: Fail fast during config load when a pattern doesn't compile, rather than failing at command-evaluation time.

**Changes**:
1. In `ToolConfig`, extend the field validator to call `re.compile()` on each pattern; catch `re.error` and raise a Pydantic `ValueError(f"tool '{key}': invalid pattern: {exc}")`.
2. Ensure `loader.py` propagates the validation error as a config-load failure (already handled by existing try/except around `model_validate`).

**Tests**: `test_invalid_regex_rejected_at_load`, `test_empty_pattern_acceptable`.

---

### Step 3d: Reject unknown top-level keys, warn on unrecognized tool fields (issue 1)

**Goal**: Typos like `"Bash": {"permission":"allow"}` should be rejected; unrecognized keys inside a tool object should warn.

**Changes**:
1. `PermissionsConfig`: add model_validator that checks each top-level key against known keys (`version`, `"*"`, plus any tool name whose value is a dict). Unknown top-level keys raise `ValueError("unknown config key: '<key>'").
2. Inside `_check_tool_dicts`: for known tool keys, warn on unrecognized field names (e.g., `blocked_path_regex` typo instead of `blocked_paths_regex`).

**Tests**: `test_unknown_top_level_key_rejected`, `test_unrecognized_tool_field_warns`.

---

### Step 3e: Add precedence-ordering e2e tests (issue 6)

**Goal**: Verify that global < project < local precedence ordering actually works.

**Changes**:
1. In `tests/test_permissions_manager.py`, add test writing all three config files with conflicting values for the same tool key.
2. Assert that `manager.get_lovely_config()` returns the value from local > project > global (last wins).
3. Add test for cross-level merge: global sets `bash.allowed_cmds_regex`, local sets `bash.blocked_paths_regex` — verify both keys survive in merged config (links to step 3b fix).

**Tests**: `test_precedence_local_wins`, `test_cross_level_merge_both_keys`.

---

### Step 3g: Run full test suite and fix any issues

Run `uv run pytest` after each step. Fix linting (ruff, mypy) before committing.

## Files Modified
- EDIT: `src/lovely_bash_permissions/config/jsonc.py` (steps 3a, 3c)
- EDIT: `src/lovely_bash_permissions/config/schema.py` (steps 3b, 3d)
- EDIT: `src/lovely_bash_permissions/config/loader.py` (steps 3a, 3b)
- EDIT: `src/lovely_bash_permissions/cli.py` (step 3f)
- EDIT: `tests/test_jsonc.py`, `tests/test_schema.py`, `tests/test_config_loader.py`, `tests/test_permissions_manager.py` (all steps)

## Why this is better than the current approach

| Old | New |
|---|---|
| `extra: "allow"` silently accepts typos | Unknown top-level keys rejected; unrecognized tool fields warned |
| Patterns validated at runtime only | Invalid patterns fail fast during config load |
| `read_jsonc_file` returns None on any error | Typed result distinguishes missing / permission denied / parse error |
| Deep merge replaces nested objects wholesale | Objects merged recursively; conflicts warned |
| No precedence ordering tests | E2E tests verify global < project < local wins |
