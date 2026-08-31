"""
Core bash command parser using shfmt-py's --to-json flag.

This module provides the low-level interface to shfmt, converting bash
command strings into shfmt's JSON AST representation. The JSON output
is then converted to typed Python AST nodes by ast.py.

Supported shell dialects: bash, posix, mksh, bats, zsh.

Example:
    from lovely_bash_permissions.parser import parse
    raw_json = parse('ls -la | grep txt')
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

_VALID_DIALECTS = frozenset({"bash", "posix", "mksh", "bats", "zsh"})


def parse(command: str, dialect: str = "bash") -> dict:
    """
    Parse a bash command using shfmt-py's --to-json flag.

    Args:
        command: The bash command string to parse. Must be non-empty.
        dialect: Shell dialect for parsing. One of: "bash", "posix",
                "mksh", "bats", or "zsh".

    Returns:
        dict: The shfmt JSON AST representation as a Python dictionary.

    Raises:
        ParseError: If parsing fails (syntax error, invalid JSON, missing binary).
        ValueError: If *dialect* is not a recognised shell dialect.
        FileNotFoundError: If no shfmt binary can be located.
    """
    if dialect not in _VALID_DIALECTS:
        raise ValueError(
            f"Unknown dialect {dialect!r}. Must be one of: {', '.join(sorted(_VALID_DIALECTS))}"
        )

    shfmt_path = find_shfmt()

    if not command.strip():
        raise ParseError("Empty command")

    result = subprocess.run(
        [
            shfmt_path,
            f"--language-dialect={dialect}",
            "--to-json",
        ],
        input=command,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise ParseError(
            f"Failed to parse: {result.stderr.strip()}",
            command=command,
            returncode=result.returncode,
            stderr=result.stderr,
        )

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise ParseError(
            f"Failed to parse JSON from shfmt: {e}",
            command=command,
        ) from e


def find_shfmt() -> str:
    """
    Locate the shfmt binary on the system.

    Searches the following locations in order:
        1. Virtual-environment ``bin/shfmt`` (resolved relative to *this*
           package, not the caller's working directory)
        2. ``$VIRTUAL_ENV/bin/shfmt``
        3. ``shfmt`` on the system PATH

    Returns:
        str: Absolute path to the shfmt binary.

    Raises:
        FileNotFoundError: If shfmt cannot be found.
    """
    # Resolve relative to this package's location so that it works
    # regardless of the caller's working directory.
    pkg_dir = Path(__file__).resolve().parent
    project_root = pkg_dir.parent.parent  # src/../..

    candidates = [
        project_root / ".venv" / "bin" / "shfmt",
        project_root / "venv" / "bin" / "shfmt",
    ]

    venv = os.environ.get("VIRTUAL_ENV")
    if venv:
        candidates.append(Path(venv) / "bin" / "shfmt")

    for path in candidates:
        if path.is_file():
            return str(path)

    # Fallback to system PATH
    system_shfmt = shutil.which("shfmt")
    if system_shfmt:
        return system_shfmt

    raise FileNotFoundError(
        "shfmt binary not found. Please ensure shfmt-py is installed."
    )


class ParseError(Exception):
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
    ):
        super().__init__(message)
        self.command = command
        self.returncode = returncode
        self.stderr = stderr

    def __str__(self):
        msg = super().__str__()
        if self.command:
            msg += f"\n  Command: {self.command!r}"
        if self.returncode is not None:
            msg += f"\n  Exit code: {self.returncode}"
        if self.stderr:
            msg += f"\n  Stderr: {self.stderr.strip()!r}"
        return msg
