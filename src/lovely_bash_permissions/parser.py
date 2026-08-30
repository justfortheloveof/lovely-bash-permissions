"""
Core bash command parser using shfmt-py's --to-json flag.
"""

import json
import subprocess
from typing import Optional


def parse(command: str, dialect: str = "bash") -> dict:
    """
    Parse a bash command using shfmt-py's --to-json flag.
    
    Args:
        command: The bash command to parse
        dialect: Shell dialect (bash, posix, mksh, bats, zsh). Default: bash
    
    Returns:
        Dictionary representing the AST
    """
    result = subprocess.run(
        [
            ".venv/bin/shfmt",
            f"--language-dialect={dialect}",
            "--to-json",
        ],
        input=command,
        capture_output=True,
        text=True,
    )
    
    if result.returncode != 0:
        raise ParseError(f"Failed to parse: {result.stderr}")
    
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise ParseError(f"Failed to parse JSON from shfmt: {e}")


class ParseError(Exception):
    """Exception raised when bash command parsing fails."""
    pass
