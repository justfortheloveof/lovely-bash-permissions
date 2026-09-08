# Plan: Pydantic Schema Validation for Config System

## Objective

Replace ad-hoc dict acceptance in the lovely-permissions config system with pydantic schema validation. The TS version uses a Zod schema (`../jftlo/lovely-devin-permissions/src/config/schema.ts`) — this plan adds equivalent pydantic models. Validation catches typos (e.g. `"alow"` instead of `"allow"`), invalid types, and broken regex patterns early with clear error messages.

## Background: Current Config System (no validation)

- **JSONC parser** (`config/jsonc.py`): strips comments/trailing commas, then `json.loads`.
- **Config loader** (`config/loader.py`): 3-tier merge (global/project/local), raises `FileNotFoundError` if all files invalid — but error message only lists paths.
- **Manager** (`config/manager.py`): catches all exceptions silently, exposes error via `get_error()`.
- **No validation**: any dict accepted; typos and invalid regexes silently become config entries.

## Implementation Steps (sequential, one agent per step)

---

### Step 1a: Create pydantic models and `_validate_config` function ✅ ✅

**Files**: `src/lovely_bash_permissions/config/schema.py` (NEW), `tests/test_schema.py` (NEW)

**What it does**: Define pydantic models for config and a validation function returning error messages.

**Step-by-step instructions (schema.py)**:

1. Add imports at top of file:
```python
from __future__ import annotations
import re
from enum import Enum
from typing import Any, Literal
from pydantic import BaseModel, field_validator, model_validator
```

2. Define `PermissionLevel` enum (module-level, outside any class):
```python
class PermissionLevel(str, Enum):
    allow = "allow"
    deny = "deny"
    ask = "ask"
```

3. Define single flat config model (module-level):
```python
class ToolConfig(BaseModel):
    permission: PermissionLevel | None = None
    blocked_paths_regex: list[str] = []
    allowed_cmds_regex: list[str] = []

    @field_validator("blocked_paths_regex", "allowed_cmds_regex", mode="before")
    @classmethod
    def strip_trailing_period(cls, v: list[str]) -> list[str]:
        return [p.rstrip(".") for p in v]
```
   - One model with all fields; `permission` and both `_regex` lists are optional, so any tool config dict is accepted (extra fields ignored via `extra="allow"` in step 1b).

4. Define `_validate_config(config: dict[str, Any]) -> list[str]` (module-level function):
   - Iterate top-level keys (tool names). For each value:
     - If `None`, skip (valid — null means "unset").
     - If dict, try `ToolConfig.model_validate(value)`. On `ValidationError`, collect all sub-error messages as strings, prefixed with `"tool '<key>': "`.
     - If not dict and not None (e.g. string/int/bool/list), add error: `"tool '<key>': expected object or null, got <type>"`.
   - After validating each tool config dict, validate `blocked_paths_regex` and `allowed_cmds_regex` entries as valid regexes: for each string entry, call `re.compile(entry)` — if it raises `re.error`, add error: `"tool '<key>': <field> pattern '{entry}' is invalid — {error_msg}"`.
   - Also validate `allow`/`deny` list items are strings (if present in any tool config dict).
   - Return accumulated error list (empty = valid).

**Step-by-step instructions (test_schema.py)**:

1. Import from `lovely_bash_permissions.config.schema`: `PermissionLevel`, `ToolConfig`, `_validate_config`.
2. Test cases (each is a function):
   - `test_valid_config`: `{}` → no errors.
   - `test_valid_bash_config`: `{"bash": {"permission": "allow", "blocked_paths_regex": ["^/tmp/"]}}` → no errors.
   - `test_invalid_permission_value`: `{"bash": {"permission": "alow"}}` → error contains "must be allow, deny, or ask".
   - `test_non_dict_tool_config`: `{"bash": "allow"}` → error mentions "expected object or null, got str".
   - `test_null_tool_config`: `{"bash": None}` → no errors (null is allowed).
   - `test_valid_regex`: `{"bash": {"blocked_paths_regex": ["^/tmp/"]}}` → no errors.
   - `test_invalid_regex`: `{"bash": {"blocked_paths_regex": ["["]}}` → error contains "is invalid".
   - `test_valid_allowed_cmds_regex`: `{"bash": {"allowed_cmds_regex": ["^ls"]}}` → no errors.
   - `test_valid_allow_deny_lists`: `{"bash": {"allow": ["git"], "deny": ["rm"]}}` → no errors.
   - `test_tool_config_model`: `{"bash": {"permission": "allow", "allowed_cmds_regex": ["^ls"]}}` → `ToolConfig.model_validate(...)` succeeds.

---

### Step 1b: Add pydantic models for the full permissions config dict ✅

**File**: `src/lovely_bash_permissions/config/schema.py` (append)

**What it does**: Define a model representing the entire config dict, so we can call `.model_validate()` on merged configs.

**Instructions**:
1. Define `PermissionsConfig(BaseModel)`:
```python
class PermissionsConfig(BaseModel):
    model_config = {"extra": "allow", "str_strip_whitespace": True}
```
2. Note: since `extra="allow"`, any tool key is accepted; detailed validation is done by `_validate_config()` (step 1a), not this model. The model mainly serves as a type hint + optional `.model_validate()` call.

**Tests**: Add to `tests/test_schema.py`:
- `test_permissions_config_model_valid`: `{"bash": {"permission": "allow"}}` → `PermissionsConfig.model_validate(...)` succeeds.
- `test_permissions_config_model_invalid`: `{"bash": "allow"}` → raises pydantic validation error.

---

### Step 1c: Integrate validation into config loader (rich errors)

**File**: `src/lovely_bash_permissions/config/loader.py` (edit — two changes)

**Change 1**: Import `_validate_config`:
```python
from .schema import _validate_config, PermissionsConfig
```

**Change 2**: In `load_permissions_config()`, after merging:
```python
validation_errors = _validate_config(merged)
if validation_errors:
    raise FileNotFoundError(
        f"no valid lovely-permissions config found\n  {chr(10).join('  ' + e for e in validation_errors)}"
    )
```

**Tests**: Add to `tests/test_config_loader.py`:
- `test_invalid_permission_raises`: config with `{"bash": {"permission": "alow"}}` → raises `FileNotFoundError`, message mentions "invalid permission".
- `test_bad_regex_raises`: config with `{"bash": {"blocked_paths_regex": ["["]}}` → raises, message mentions pattern.
- `test_multiple_errors_all_reported`: config with both typo and bad regex → error message lists BOTH errors.

---

### Step 1d: Enrich per-file parse error messages in loader

**File**: `src/lovely_bash_permissions/config/loader.py` (edit)

**Instructions**:
1. Change `parse_errors: list[str]` to `parse_errors: list[tuple[str, str]]` (path + reason).
2. Set reasons:
   - `"file not found"` when path doesn't exist.
   - `"invalid JSONC"` when parse returns None for non-dict or invalid.
   - `"expected object, got <type>"` when value is non-dict.
3. In the error message, include these reasons:
```python
if not loaded_any:
    details = "\n".join(f"  {p}: {r}" for p, r in parse_errors)
    raise FileNotFoundError(f"no valid lovely-permissions config found\n{details}")
```

**Tests**: Verify error message contains specific per-file reasons.

---

### Step 1e: Fix trailing comma edge cases in jsonc parser

**File**: `src/lovely_bash_permissions/config/jsonc.py` (edit)

**Instructions**:
1. Replace `_strip_trailing_commas()` with a version respecting string boundaries:
```python
def _strip_trailing_commas(text: str) -> str:
    result = []
    in_string = False
    escape_next = False
    i = 0
    while i < len(text):
        ch = text[i]
        if escape_next:
            result.append(ch)
            escape_next = False
            i += 1
            continue
        if ch == "\\":
            escape_next = True
            result.append(ch)
            i += 1
            continue
        if ch == '"':
            in_string = not in_string
            result.append(ch)
            i += 1
            continue
        if not in_string and ch == "," and i + 1 < len(text):
            next_non_ws = ""
            for j in range(i + 1, len(text)):
                if text[j] not in " \t\n\r":
                    next_non_ws = text[j]
                    break
            if next_non_ws in "}]":
                i += 1  # skip comma
                continue
        result.append(ch)
        i += 1
    return "".join(result)
```
2. Keep `_strip_comments()` unchanged.

**Tests**: Add to `tests/test_jsonc.py`:
- `test_trailing_comma_in_string`: `{"a": "1,"}` → parses as `{"a": "1,"}` (comma preserved).
- `test_trailing_comma_object`: `{"a": 1,}` → parses correctly.
- `test_nested_trailing_comma`: `{"a": {"b": 1,}}` → parses correctly.

---

### Step 1f: Add warnings list to manager

**File**: `src/lovely_bash_permissions/config/manager.py` (edit)

**Instructions**:
1. Add `_warnings: list[str] = []` field.
2. In `_load()`, append warnings when files are skipped (e.g., `self._warnings.append(f"skipped invalid config file: {path}")`).
3. Add method:
```python
def get_warnings(self) -> list[str]:
    return self._warnings
```

**Tests**: Verify warnings appear when one file is invalid but others load.

---

### Step 1g: Run full test suite and fix any issues

**Instructions**: Run `uv run pytest` end-to-end. Fix any failures from schema integration (e.g., old tests expecting plain dicts may need updating to expect validation errors). Commit all changes.

## Files Modified
- NEW: `src/lovely_bash_permissions/config/schema.py` (steps 1a, 1b)
- NEW: `tests/test_schema.py` (steps 1a, 1b)
- EDIT: `src/lovely_bash_permissions/config/loader.py` (steps 1c, 1d)
- EDIT: `src/lovely_bash_permissions/config/jsonc.py` (step 1e)
- EDIT: `src/lovely_bash_permissions/config/manager.py` (step 1f)
- EDIT: `tests/test_config_loader.py` (steps 1c, 1d)
- EDIT: `tests/test_jsonc.py` (step 1e)
