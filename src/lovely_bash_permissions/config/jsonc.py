"""JSONC parser using json5 library."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import json5


def parse_jsonc(text: str) -> Any | None:  # noqa: ANN401
    """Parse JSONC text using json5. Returns None on parse error."""
    cleaned = text.lstrip("\ufeff")  # strip BOM
    try:
        return json5.loads(cleaned)
    except (ValueError, TypeError):
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


def is_record(value: Any) -> bool:  # noqa: ANN401
    """Check if value is a plain object (dict)."""
    return isinstance(value, dict)
