"""JSONC parser using json5 library."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import json5


class JSONCDecodeError(ValueError):
    """Raised when json5 fails to parse; carries line/column position."""

    def __init__(self, message: str) -> None:
        self.message = message
        match = re.search(r"at column (\d+)", message)
        self.column = int(match.group(1)) if match else 0
        # Extract line number from "<file>:<line>" prefix
        line_match = re.search(r"^(?:<[^>]+>|\S+):(\d+)", message)
        self.line = int(line_match.group(1)) if line_match else 0


def parse_jsonc(text: str) -> Any | None:  # noqa: ANN401
    """Parse JSONC text using json5. Returns None on parse error."""
    cleaned = text.lstrip("\ufeff")  # strip BOM
    try:
        return json5.loads(cleaned)
    except (ValueError, TypeError) as exc:
        raise JSONCDecodeError(str(exc)) from None


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
    try:
        value = parse_jsonc(text)
    except JSONCDecodeError as exc:
        print(f"error parsing {file_path}: expected ... at line {exc.line} col {exc.column}", file=sys.stderr)
        return None
    if value is None:
        print(f"error parsing {file_path}: invalid JSONC (null value)", file=sys.stderr)
    elif not isinstance(value, dict):
        print(f"error parsing {file_path}: expected object, got {type(value).__name__}", file=sys.stderr)
        return None
    return value


def is_record(value: Any) -> bool:  # noqa: ANN401
    """Check if value is a plain object (dict)."""
    return isinstance(value, dict)
