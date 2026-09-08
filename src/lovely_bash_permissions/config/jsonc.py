"""JSONC parser using json5 library."""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import json5


class JSONCDecodeError(ValueError):
    """Raised when json5 fails to parse; carries line/column position."""

    message: str
    column: int
    line: int

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


@dataclass
class JsoncLoadResult:
    """Result of loading a JSONC file, distinguishing success/failure modes."""

    value: dict[str, Any] | None
    error: str | None

    @classmethod
    def ok(cls, value: dict[str, Any]) -> JsoncLoadResult:
        return cls(value=value, error=None)

    @classmethod
    def missing(cls, path: str) -> JsoncLoadResult:
        return cls(value=None, error=f"file not found: {path}")

    @classmethod
    def parse_error(cls, path: str, msg: str, line: int = 0, col: int = 0) -> JsoncLoadResult:
        detail = msg
        if line:
            detail += f" at line {line} col {col}"
        return cls(value=None, error=f"{detail}\nin {path}")

    @classmethod
    def read_error(cls, path: str, err: BaseException) -> JsoncLoadResult:
        return cls(value=None, error=f"error reading {path}: {err}")


def read_jsonc_file(file_path: str) -> JsoncLoadResult:
    """Read and parse a JSONC file.

    Returns a JsoncLoadResult indicating success, missing file, read error, or parse error.
    """
    path = Path(file_path)
    if not path.exists():
        return JsoncLoadResult.missing(file_path)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        print(f"error reading {file_path}: {e}", file=sys.stderr)
        return JsoncLoadResult.read_error(file_path, e)
    try:
        value = parse_jsonc(text)
    except JSONCDecodeError as exc:
        print(f"error parsing {file_path}: {exc.message} at line {exc.line} col {exc.column}", file=sys.stderr)
        return JsoncLoadResult.parse_error(file_path, exc.message, exc.line, exc.column)
    if value is None:
        print(f"error parsing {file_path}: expected object, got null", file=sys.stderr)
        return JsoncLoadResult(value=None, error="expected object, got null")
    elif not isinstance(value, dict):
        print(f"error parsing {file_path}: expected object, got {type(value).__name__}", file=sys.stderr)
        return JsoncLoadResult(value=None, error=f"expected object, got {type(value).__name__}")
    return JsoncLoadResult.ok(value)


def is_record(value: Any) -> bool:  # noqa: ANN401
    """Check if value is a plain object (dict)."""
    return isinstance(value, dict)
