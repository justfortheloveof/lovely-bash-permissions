"""JSONC (JSON with Comments) parser.

Strips comments and parses JSON. Supports both .json and .jsonc files.
"""

import json
import re
import sys
from pathlib import Path


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


def parse_jsonc(text: str) -> dict | list | None:
    """Parse JSONC text into a Python object.

    Returns:
        dict, list, or None if parsing fails or input is empty
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
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def read_jsonc_file(file_path: str) -> dict | None:
    """Read and parse a JSONC file.

    Returns:
        dict if the file exists and contains valid JSONC
        None if the file doesn't exist or is empty/invalid
    """
    path = Path(file_path)
    if not path.exists():
        return None

    try:
        text = path.read_text(encoding="utf-8")
        return parse_jsonc(text)
    except Exception as e:  # noqa: BLE001
        print(f"error: {e}", file=sys.stderr)
        return None


def is_record(value: dict | list | None) -> bool:
    """Check if value is a dictionary (plain object in JSON terms)."""
    return isinstance(value, dict)
