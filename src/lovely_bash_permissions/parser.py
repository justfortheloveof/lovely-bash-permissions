"""
Core bash command parser using shfmt-py's --to-json flag.

This module provides the low-level interface to shfmt, converting bash
command strings into shfmt's JSON AST representation. The JSON output
is then converted to typed Python AST nodes by converter.py.

Supported shell dialects: bash, posix, mksh, bats, zsh.

Example:
    from lovely_bash_permissions.parser import parse
    raw_json = parse('ls -la | grep txt')
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from .errors import LovelyDevinPermissionsError

_VALID_DIALECTS = frozenset({"bash", "posix", "mksh", "bats", "zsh"})


def parse(command: str, dialect: str = "bash") -> dict[str, Any]:
    """
    Parse a bash command using shfmt-py's --to-json flag.

    Args:
        command: The bash command string to parse. Must be non-empty.
        dialect: Shell dialect for parsing. One of: "bash", "posix",
                "mksh", "bats", or "zsh".

    Returns:
        dict[str, Any]: The shfmt JSON AST representation as a Python dictionary.

    Raises:
        ParseError: If parsing fails (syntax error, invalid JSON).
        LovelyDevinPermissionsError: If the shfmt binary is missing or
            shfmt could not be run (timeout, OS error).
        ValueError: If *dialect* is not a recognised shell dialect.
    """
    if dialect not in _VALID_DIALECTS:
        raise ValueError(f"Unknown dialect {dialect!r}. Must be one of: {', '.join(sorted(_VALID_DIALECTS))}")

    try:
        shfmt_path = find_shfmt()
    except FileNotFoundError as e:
        raise LovelyDevinPermissionsError(str(e)) from e

    if not command.strip():
        raise ParseError("Empty command", command=command)

    try:
        result = subprocess.run(
            [
                shfmt_path,
                f"--language-dialect={dialect}",
                "--to-json",
            ],
            input=command,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise LovelyDevinPermissionsError(f"shfmt timed out while parsing command: {e}") from e
    except OSError as e:
        raise LovelyDevinPermissionsError(f"failed to run shfmt: {e}") from e

    if result.returncode != 0:
        raise ParseError(
            f"Failed to parse: {result.stderr.strip()}",
            command=command,
            returncode=result.returncode,
            stderr=result.stderr,
        )

    try:
        result_dict: dict[str, Any] = json.loads(result.stdout)
        return result_dict
    except json.JSONDecodeError as e:
        raise ParseError(
            f"Failed to parse JSON from shfmt: {e}",
            command=command,
        ) from e


_shfmt_cache: str | None = None


def _find_shfmt_uncached() -> str:
    """
    Locate the shfmt binary on the system (uncached).

    Searches the following locations in order:
        1. ``$VIRTUAL_ENV/bin/shfmt`` (if the env var is set)
        2. ``shfmt`` next to the running Python interpreter
        3. ``sys.prefix/bin/shfmt`` (covers virtualenvs
           where sys.executable resolves elsewhere)
        4. ``shfmt`` on the system PATH

    Returns:
        str: Absolute path to the shfmt binary.

    Raises:
        FileNotFoundError: If shfmt cannot be found.
    """
    candidates: list[Path] = []

    # 1. Active virtualenv from environment variable
    venv = os.environ.get("VIRTUAL_ENV")
    if venv:
        candidates.append(Path(venv) / "bin" / "shfmt")

    # 2. Same directory as the running Python interpreter
    candidates.append(Path(sys.executable).parent / "shfmt")

    # 3. sys.prefix (covers virtualenvs where sys.executable resolves elsewhere)
    candidates.append(Path(sys.prefix) / "bin" / "shfmt")

    for path in candidates:
        if path.is_file():
            return str(path)

    # 4. Fallback to system PATH
    system_shfmt = shutil.which("shfmt")
    if system_shfmt:
        return system_shfmt

    raise FileNotFoundError("shfmt binary not found. Please ensure shfmt-py is installed.")


def find_shfmt() -> str:
    """
    Locate the shfmt binary on the system.

    The result is cached for the lifetime of the process.  If the binary
    is moved or removed after the first successful lookup, a warning is
    emitted and the cache is cleared before re-searching.
    """
    global _shfmt_cache
    if _shfmt_cache is not None and Path(_shfmt_cache).is_file():
        return _shfmt_cache
    _shfmt_cache = _find_shfmt_uncached()
    return _shfmt_cache


class ParseError(LovelyDevinPermissionsError):
    """Exception raised when bash command parsing fails.

    Attributes:
        command: The original bash command that failed to parse.
        returncode: shfmt's exit code (non-zero indicates failure).
        stderr: Raw stderr output from shfmt.
    """

    def __init__(
        self,
        message: str,
        command: str | None = None,
        returncode: int | None = None,
        stderr: str | None = None,
    ) -> None:
        super().__init__(message)
        self.command = command
        self.returncode = returncode
        self.stderr = stderr

    def __str__(self) -> str:
        msg = super().__str__()
        if self.command:
            msg += f"\n  Command: {self.command!r}"
        if self.returncode is not None:
            msg += f"\n  Exit code: {self.returncode}"
        if self.stderr:
            msg += f"\n  Stderr: {self.stderr.strip()!r}"
        return msg
