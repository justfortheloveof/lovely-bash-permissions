# Plan: Migrate to json5 JSONC library

## Objective

Replace our hand-rolled JSONC parser (`config/jsonc.py`) with the `json5` library, which natively supports comments (`//`, `/* */`), trailing commas, and the full JSONC spec. This eliminates ~40 lines of custom parsing code (comment stripping, trailing-comma handling, escape tracking) and gives us richer error messages.

The TS reference (`../jftlo/lovely-devin-permissions/src/config/jsonc.ts`) uses `jsonc-parser` — Python's `json5` is the equivalent.

## Background: Current parser (hand-rolled)

- `config/jsonc.py`: strips block/line comments via regex, then strips trailing commas with a custom state machine (string-boundary aware), then calls `json.loads`.
- Comments are stripped by two regex passes (`_strip_comments` + `_strip_trailing_commas`).
- Error messages are generic: `"invalid JSONC"`, no line/column info.

## Implementation Steps (sequential, one agent per step)

---

### Step 1a: Add json5 dependency and replace parser

**File**: `pyproject.toml` (edit), `src/lovely_bash_permissions/config/jsonc.py` (rewrite)

**What it does**: Add `json5` to project dependencies and rewrite the parser to use it.

**Instructions (pyproject.toml)**:
1. Add `json5` to `[project.dependencies]`:
```toml
json5 = ">=0.15"
```

**Instructions (jsonc.py)** — rewrite to this minimal form, matching the TS reference:
```python
"""JSONC parser using json5 library."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import json5


def parse_jsonc(text: str) -> Any | None:
    """Parse JSONC text using json5. Returns None on parse error."""
    cleaned = text.lstrip("\ufeff")  # strip BOM
    try:
        return json5.loads(cleaned, allow_trailing_comma=True)
    except (json5.JSON5DecodeError, ValueError):
        return None


def read_jsonc_file(file_path: str) -> dict[str, Any] | None:
    """Read and parse a JSONC file. Returns dict or None."""
    path = Path(file_path)
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        print(f"error reading {file_path}: {e}", file=sys.stderr)
        return None
    value = parse_jsonc(text)
    if value is None:
        print(f"error parsing {file_path}: invalid JSONC", file=sys.stderr)
    elif not isinstance(value, dict):
        print(f"error parsing {file_path}: expected object, got {type(value).__name__}", file=sys.stderr)
        return None
    return value


def is_record(value: Any) -> bool:
    """Check if value is a plain object (dict)."""
    return isinstance(value, dict)
```

**Tests**: Add to `tests/test_jsonc.py`:
- `test_parse_valid_jsonc`: config with comments and trailing commas → parses correctly.
- `test_parse_invalid_jsonc`: malformed JSONC (e.g. trailing comma after value with no closing bracket) → returns None, or raises JSON5DecodeError if strict mode used.
- `test_parse_with_bom`: file starting with BOM → parses correctly (BOM stripped by us, json5 handles rest).

---

### Step 1b: Enrich error messages from json5 parse errors

**File**: `src/lovely_bash_permissions/config/jsonc.py` (edit)

**What it does**: Convert json5's structured parse errors into readable messages. Currently our parser just says `"invalid JSONC"` — json5's exceptions carry line/column info we can surface.

**Instructions**:
1. Catch `json5.JSON5DecodeError` (or ValueError) in `parse_jsonc`.
2. In `read_jsonc_file`, format the error into a message like `"error parsing {file_path}: expected ',' or '}' at line 3 col 5"`.

**Tests**: Verify error messages from invalid configs contain position info.

---

### Step 1c: Remove duplicate validation logic (consolidate into loader)

**File**: `src/lovely_bash_permissions/config/manager.py` (edit)

**What it does**: The manager currently re-validates config after loading (`PermissionsConfig.model_validate` + `_validate_config`). Since `loader.py::load_permissions_config()` already validates and raises on error, the manager's validation is dead code.

**Instructions**:
1. In `manager.py::_load()`, after merging configs, call the loader's validation instead of duplicating:
```python
from .loader import load_permissions_config, merge_deep  # or just call loader's function

# Instead of re-validating:
self._lovely_config = merged  # loader already validated this
```
2. Simplify `_load()` to skip the redundant `PermissionsConfig.model_validate` + `_validate_config` blocks — those now live in `loader.py`.

**Tests**: Verify manager still rejects invalid configs (via loader's exception) and reports errors through `get_error()`.

---

### Step 1d: Simplify per-file error reporting in loader

**File**: `src/lovely_bash_permissions/config/loader.py` (edit)

**What it does**: json5 now handles parsing — we only need to report "file not found" vs "invalid JSONC".

**Instructions**:
1. Simplify the error reason logic — no more manual `re.sub` + `json.loads` re-parsing to detect errors:
```python
if data is None and Path(path).exists():
    reason = "invalid JSONC"
elif not Path(path).exists():
    reason = "file not found"
else:
    reason = f"expected object, got {type(data).__name__}"
```

**Tests**: Verify error messages still contain per-file reasons.

---

### Step 1e: Remove trailing-comma edge-case tests

**File**: `tests/test_jsonc.py` (edit)

**What it does**: Tests for trailing-comma-in-string edge cases (`test_trailing_comma_in_string`, etc.) are now obsolete — `json5` handles them. Remove the old edge-case tests and add one general "trailing commas work" test.

**Instructions**:
1. Remove tests that verified our hand-rolled trailing-comma logic (string-boundary awareness).
2. Add one test: `test_trailing_commas`: config with trailing commas → parses correctly via json5.

---

### Step 1f: Run full test suite and fix any issues

**Instructions**: Run `uv run pytest` end-to-end. Fix any failures from json5 migration (e.g., error message formats, edge-case behavior differences between our parser and json5). Commit all changes.

## Files Modified
- EDIT: `pyproject.toml` (add json5 dependency) — step 1a
- REWRITE: `src/lovely_bash_permissions/config/jsonc.py` (steps 1a, 1b)
- EDIT: `src/lovely_bash_permissions/config/loader.py` (steps 1c, 1d)
- EDIT: `src/lovely_bash_permissions/config/manager.py` (step 1c)
- EDIT: `tests/test_jsonc.py` (steps 1a, 1e)

## Why this is simpler than the original plan

| Old approach | New (json5) |
|---|---|
| ~40 lines of comment/trailing-comma regex code | ~15 lines total, json5 does it all |
| Generic "invalid JSONC" errors | Structured parse errors with line/col |
| Manual trailing-comma edge-case tests | One test, library handles it |
| Duplicate validation (loader + manager) | Validation lives in loader only |
