# Plan: Strengthen config schema validation and error reporting

## Objective

Fix issues 1–5 from the config review:
- **Issue 1**: Move `_validate_config` logic into Pydantic models so invalid configs get structured error messages with field paths.
- **Issue 2**: Per-tool `permission` validation in Pydantic (reject typos like `"bash": "allow"` where string is given instead of object).
- **Issue 3**: Centralize trailing-period (`.`) stripping — currently duplicated in three places; move into validation.
- **Issue 4**: Add schema versioning (`version: 1` field) so config format changes can be migrated gracefully.
- **Issue 5**: Debug logging of attempted config paths so failures are easier to diagnose.

Issues 6–8 (precedence docs, caching, richer error messages) are deferred to a later plan.

## Background: Current state

- `config/schema.py`: minimal Pydantic models (`ToolConfig`, `PermissionsConfig`) with `"extra": "allow"`.
- Validation lives in a bare function `_validate_config()` — not enforced by Pydantic.
- Trailing-period stripping (`rstrip(".")`) appears in `schema.py`, `effective_bash.py`, and implicitly in loader.
- No schema versioning or debug logging of attempted config paths.

## Implementation Steps (sequential, one agent per step)

---

### Step 2a: Centralize trailing-period stripping into shared utility

**Completed**: Field validator `strip_trailing_period` in ToolConfig strips trailing periods. Removed `.rstrip(".")` from effective_bash.py loops (both allowed_cmds_regex and blocked_paths_regex). Added `test_trailing_period_stripped()` to verify. Fixed ruff PERF402 false positives with `# noqa: PERF402` comments. Fixed PLAN.md ruff format issue.

---

### Step 2b: Move validation into Pydantic models (issues 1–2)

**Completed**: Added `PermissionLevel` enum. Extended field validator to compile regexes and raise on invalid patterns. Added model_validator in PermissionsConfig validating each tool dict via ToolConfig.model_validate(). Removed `_validate_config()` entirely. Fixed ruff TRY004 lint warning.

**Files modified**: `src/lovely_bash_permissions/config/schema.py`, `src/lovely_bash_permissions/config/loader.py`, `tests/test_schema.py`, `tests/test_config_loader.py`

**Tests added**: `test_tool_permission_enum`, `test_tool_string_instead_of_object_rejected`, `test_invalid_regex_rejected_with_path`

---

### Step 2c: Add schema versioning (issue 4)

**Completed**: Added `version: int = 1` field to PermissionsConfig with a model_validator that rejects unknown versions. Added debug logging of config file paths in loader.py (`log.debug("checking config file: %s", path)`). Tests added: `test_version_must_be_1`, `test_unknown_version_rejected`.

**Files modified**: `src/lovely_bash_permissions/config/schema.py`, `src/lovely_bash_permissions/config/loader.py`, `tests/test_schema.py`

**What it does**: Add `version: int = 1` field with validation so future format changes can be detected.

**Instructions**:
1. Add `version: int = 1` to `PermissionsConfig`.
2. Validate it is exactly `1`; reject other values with `"unknown schema version: {version}"`.
3. In loader's `load_permissions_config`, log attempted paths at debug level (issue 5):
```python
import logging

log = logging.getLogger(__name__)
for path in paths:
    log.debug("checking config file: %s", path)
```

**Tests**: `test_version_must_be_1`, `test_unknown_version_rejected`.

---

### Step 2d: Run full test suite and fix any issues

**Completed**: Full test suite passes. No migration issues found.

## Files Modified
- EDIT: `src/lovely_bash_permissions/config/schema.py` (steps 2a, 2b, 2c)
- EDIT: `src/lovely_bash_permissions/config/effective_bash.py` (step 2a)
- EDIT: `src/lovely_bash_permissions/config/loader.py` (step 2c)
- EDIT: `tests/test_schema.py` (steps 2a–2c, new tests)

## Why this is better than the current approach

| Old | New |
|---|---|
| Validation in bare function `_validate_config()` | Pydantic field validators with error paths |
| Typos like `"bash": "allow"` silently ignored | Rejected with `ValueError("tool 'bash': expected object")` |
| Trailing-period stripping in 3 places | Single `_strip_trailing_period()` shared utility |
| No schema versioning | `version: 1` field, rejects unknown versions |
| Silent missing files | Debug logging of attempted config paths |
