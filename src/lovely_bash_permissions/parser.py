"""
Core bash command parser using shfmt-py's --to-json flag.
"""

import json
import subprocess
import os
from typing import Optional


def parse(command: str, dialect: str = "bash") -> dict:
    """
    Parse a bash command using shfmt-py's --to-json flag.
    
    Args:
        command: The bash command to parse
        dialect: Shell dialect (bash, posix, mksh, bats, zsh). Default: bash
    
    Returns:
        Dictionary representing the AST
    
    Raises:
        ParseError: If the command cannot be parsed
    """
    shfmt_path = find_shfmt()
    
    # Handle empty/whitespace-only input gracefully
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
        )


def find_shfmt() -> str:
    """Find the shfmt binary in the virtual environment."""
    # Try common paths in order
    candidates = [
        ".venv/bin/shfmt",
        "venv/bin/shfmt",
        os.path.join(os.environ.get("VIRTUAL_ENV", ""), "bin/shfmt"),
        "shfmt",  # fallback to PATH
    ]
    
    for path in candidates:
        if os.path.exists(path):
            return path
    
    raise FileNotFoundError(
        "shfmt binary not found. Please ensure shfmt-py is installed."
    )


class ParseError(Exception):
    """Exception raised when bash command parsing fails."""
    
    def __init__(self, message: str, command: str = None,
                 returncode: int = None, stderr: str = None):
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
