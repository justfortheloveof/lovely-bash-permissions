# Plan: Config System Improvements (#2, #3, #7)

## Overview

Three independent changes to the config system. Each step is self-contained so agents can work sequentially without cross-dependency.

**Issue #2**: `PermissionsConfig` has `extra="allow"` but `_check_top_level_keys` rejects unknown keys — two validators fight each other. Fix: use `extra="forbid"` and keep only a clean validator.

**Issue #3**: Silent validation failures — unrecognized/typo keys (e.g. `"blocked_path_regex"`) are silently dropped by pydantic `extra="forbid"` with no warning; config errors in `PermissionsManager._load()` are swallowed into warnings but never raised.

**Issue #7**: Regex validation — patterns compiled once at load time, but dict stores raw strings; consumers re-compile on every match. Fix: validate at load time AND compile-on-demand, store compiled objects so consumers don't re-compile. Also add runtime validation at match time for safety.

---

## Step 2a: Replace `extra="allow"` with `extra="forbid"` in PermissionsConfig (schema.py)

**File:** `src/lovely_bash_permissions/config/schema.py`
**Test file:** `tests/test_schema.py`

### Current state

```python
class PermissionsConfig(BaseModel):
    model_config = {"extra": "allow", "str_strip_whitespace": True}
```

Any unrecognized top-level key is silently accepted as a tool name, then validated against `KNOWN_TOOLS`. Typos like `"Bash"` vs `"bash"` are silently accepted.

### Changes

1. In `schema.py`, change PermissionsConfig's model_config:
```python
# Before
model_config = {"extra": "allow", "str_strip_whitespace": True}
# After
model_config = {"extra": "forbid", "str_strip_whitespace": True}
```

2. Keep `_check_top_level_keys` validator (it already rejects unknown tool names). Since pydantic now forbids extras at the model level, the validator becomes redundant — remove it and add a docstring comment noting forbid is handled by model_config.

### Tests to update/add (`tests/test_schema.py`)

- Existing test `test_unknown_top_level_key_rejected` already expects a `ValidationError` for `"Bash": "allow"` — verify it still passes (it will, since `"forbid"` rejects extra keys).
- Add a test `test_unknown_tool_name_rejected` that passes an unrecognized key (e.g. `"git"`) and asserts `ValidationError`.
- Add a test `test_known_tool_bash_accepted` confirming `"bash"` still works.

### Files affected
- `src/lovely_bash_permissions/config/schema.py` (model_config change, remove redundant validator)
- `tests/test_schema.py`

---

## Step 2b: Remove `extra="allow"` from ToolConfig (it already forbids)

**File:** `src/lovely_bash_permissions/config/schema.py`
**Test file:** `tests/test_schema.py`

### Current state

```python
class ToolConfig(BaseModel):
    model_config = {"extra": "forbid"}
```

Already forbids extra fields. Tests like `test_unrecognized_tool_field_warns` confirm `"blocked_path_regex"` (typo) raises.

### Changes

No code changes needed — just confirm existing behavior hasn't regressed after Step 2a's changes (forbid now works at PermissionsConfig level too).

### Tests to verify (`tests/test_schema.py`)

- `test_unrecognized_tool_field_warns` — must still pass.
- `test_allow_deny_shorthand_rejected` — must still pass.

### Files affected
- None (verification only). If any test fails, re-add `extra="forbid"` to ToolConfig.

---

## Step 3a: Surface config validation errors (loader.py + manager.py)

**File:** `src/lovely_bash_permissions/config/loader.py` and `manager.py`
**Test file:** `tests/test_config_loader.py`

### Current state

In `loader.py`, `load_permissions_config()`:
- Parse errors become warnings appended to return list: `"skipped invalid config file: ..."`
- Pydantic validation errors caught and appended as `"config validation error: ..."`.

In `manager.py`, `PermissionsManager._load()`:
- Catches all exceptions from both loaders, stores messages in `_warnings`.
- Consumers must explicitly call `get_warnings()` — errors never raised.

### Changes in `loader.py`

1. Change return type:
```python
def load_permissions_config(project_dir: str) -> tuple[dict[str, Any], list[str], list[str]]:
    """Returns (merged_config, warnings, validation_errors)."""
```

2. Collect parse errors into a separate list (not just warnings):
```python
validation_errors = []  # new
for path, reason in parse_errors:
    warnings.append(f"skipped invalid config file: {path} ({reason})")
    validation_errors.append(reason)  # new

try:
    PermissionsConfig.model_validate(merged)
except ValueError as exc:
    warnings.append(f"config validation error: {exc}")
    validation_errors.append(str(exc))  # new
return merged, warnings, validation_errors
```

### Changes in `manager.py`

1. `_load()` now receives 3 values:
```python
self._lovely_config, warn_list, error_list = load_permissions_config(...)
self._validation_errors = error_list  # new attribute
```

2. Add property:
```python
@property
def validation_errors(self) -> list[str]:
    return self._validation_errors

@property
def has_validation_errors(self) -> bool:
    return bool(self._validation_errors)
```

3. In `get_lovely_config()`, **raise** validation errors:
```python
def get_lovely_config(self) -> dict[str, Any]:
    if self._validation_errors:
        raise ValueError("\n".join(self._validation_errors))
    return self._lovely_config
```

### Tests (`tests/test_config_loader.py`)

1. `test_load_returns_validation_errors_list` — config with invalid regex → third return value non-empty.
2. `test_manager_validation_errors_property` — manager with invalid config has errors via property.
3. `test_get_lovely_config_raises_on_errors` — manager with invalid config → `get_lovely_config()` raises ValueError.

### Files affected
- `src/lovely_bash_permissions/config/loader.py` (return 3 values)
- `src/lovely_bash_permissions/config/manager.py` (new property, raise in getter)
- `tests/test_config_loader.py`

---

## Step 3b: Warn about unknown keys instead of silent drop (schema.py)

**File:** `src/lovely_bash_permissions/config/schema.py`
**Test file:** `tests/test_schema.py`

### Current state

Typos like `"blocked_path_regex"` (missing 's') silently dropped by pydantic `extra="forbid"`. No warning emitted.

### Changes

Add a post-validator to PermissionsConfig that logs warnings for unrecognized keys:
```python
import logging

log = logging.getLogger(__name__)

@model_validator(mode="after")
def _warn_unknown_keys(self) -> "PermissionsConfig":
    known = {"version", "wildcard"} | KNOWN_TOOLS
    for key in self.model_extra or {}:
        if key not in known:
            log.warning("unknown config key '%s' — unrecognized tool name or typo?", key)
    return self
```

### Tests (`tests/test_schema.py`)

1. `test_unknown_key_logs_warning` — config with `"git": "allow"` → warning logged, config still loads.
2. `test_typo_key_logs_warning` — `"blocked_path_regex"` → warning logged, field dropped but not silently.

### Files affected
- `src/lovely_bash_permissions/config/schema.py` (post-validator)
- `tests/test_schema.py`

---

## Step 7a: Compile regex patterns once, store compiled objects (rules.py)

**File:** `src/lovely_bash_permissions/rules.py`
**Test file:** `tests/test_rules.py`

### Current state

Patterns compiled once in `field_validator("blocked_paths_regex")`, but dict stores raw strings (`compiled.pattern`). Consumers (e.g. `effective_bash.py`, `evaluate.py`) re-compile on every match call — wasteful, validation only at load time.

### Changes in `rules.py`

1. Add compiled-pattern cache:
```python
from functools import lru_cache

@lru_cache(maxsize=512)
def _compile_pattern(pattern: str):
    """Compile and cache a regex pattern. Raises re.error on invalid pattern."""
    return re.compile(pattern)
```

2. In `_item_to_anchored_pattern(item)`: validate at match time by calling `_compile_pattern()` (cached). If invalid, raise `re.error`.

3. In `_resolve_output_level`, patterns now come from cache — deduplication handled by lru_cache.

### Tests (`tests/test_rules.py`)

1. `test_compile_pattern_caches` — same pattern compiled twice returns same object (identity check with `is`).
2. `test_compile_pattern_invalid_raises` — invalid regex → `re.error`.
3. `test_item_to_anchored_pattern_returns_compiled` — valid item returns compiled pattern object, not raw string.

### Files affected
- `src/lovely_bash_permissions/rules.py` (add `_compile_pattern`, update consumers)
- `tests/test_rules.py`

---

## Step 7b: Add runtime validation at match time (rules.py)

**File:** `src/lovely_bash_permissions/rules.py`
**Test file:** `tests/test_rules.py`

### Changes

1. `_compile_pattern()` already validates at match time (called per-match, cached). Add docstring explaining.

2. In `_item_to_anchored_pattern(item)`, wrap compilation in try/except and raise descriptive error:
```python
def _item_to_anchored_pattern(item):
    try:
        return _compile_pattern(pattern)
    except re.error as exc:
        raise ValueError(f"invalid pattern '{pattern}': {exc}") from exc
```

### Tests (`tests/test_rules.py`)

1. `test_item_to_anchored_pattern_invalid_raises` — bad regex → ValueError.
2. `test_item_to_anchored_pattern_valid_compiles` — valid item returns compiled pattern.

### Files affected
- `src/lovely_bash_permissions/rules.py` (error wrapping)
- `tests/test_rules.py`

---

## Order of execution

1. **Step 2a** — forbid extra in PermissionsConfig (core change)
2. **Step 2b** — verify ToolConfig forbid (no code change, just test verification)
3. **Step 3a** — surface errors in loader/manager (independent, depends on schema conceptually)
4. **Step 3b** — warn about unknown keys (independent)
5. **Step 7a** — compile-on-demand caching (independent)
6. **Step 7b** — runtime validation wrapping (depends on 7a)

Steps 2a, 3a are the most impactful source changes. Steps 2b, 3b add safety/warnings. Step 7a is the core caching fix.

## Commit messages

After each step completes, commit with:
- "Step 2a: PermissionsConfig forbid extra + known tools"
- "Step 2b: Verify ToolConfig forbid extra"
- "Step 3a: Surface config validation errors to consumers"
- "Step 3b: Warn about unknown config keys"
- "Step 7a: Compile regex patterns once with cache"
- "Step 7b: Runtime validation at match time"

## Verification

After all steps: `uv run pytest` must pass (both new and existing tests).
Run with `-v` flag to confirm all 6+ new tests pass.
