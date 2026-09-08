"""JSONC (JSON with Comments) parser.

Strips comments and parses JSON. Supports both .json and .jsonc files.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any


def _strip_comments(text: str) -> str:
    """Remove block comments /* ... */ and line comments // ... from JSONC text."""
    # Block comments first
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    # Then line comments
    text = re.sub(r"//[^\n]*", "", text)
    return text


def _strip_trailing_commas(text: str) -> str:
    """Remove trailing commas before closing brackets."""
    # Trailing comma in objects: {"a": 1,}
    text = re.sub(r",(\s*[}\]])", r"\1", text)
    # Trailing comma in arrays: [1, 2,]
    return text


def parse_jsonc(text: str) -> dict[str, Any] | list[Any] | str | int | float | bool | None:
    """Parse JSONC text into a Python object.

    Returns:
        Any valid JSON value, or None if parsing fails or input is empty
    """
    if not text or not text.strip():
        return None

    # Remove BOM if present
    text = text.lstrip("\ufeff")

    # Strip comments
    text = _strip_comments(text)

    # Strip trailing commas
    text = _strip_trailing_commas(text)

    try:
        return json.loads(text)  # type: ignore[no-any-return]
    except json.JSONDecodeError:
        return None


def read_jsonc_file(file_path: str) -> dict[str, Any] | None:
    """Read and parse a JSONC file.

    Returns:
        dict if the file exists and contains a valid JSON object
        None if the file doesn't exist, is empty/invalid, or contains a non-object value
    """
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


def is_record(value: dict[str, Any] | list[Any] | str | float | bool | None) -> bool:
    """Check if value is a dictionary (plain object in JSON terms)."""
    return isinstance(value, dict)
