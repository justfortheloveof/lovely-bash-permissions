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
import subprocess
import os
from typing import Optional


def parse(command: str, dialect: str = "bash") -> dict:
    """
    Parse a bash command using shfmt-py's --to-json flag.
    
    Spawns the shfmt binary with --to-json to convert the command string into
    shfmt's typed JSON AST representation. This is the lowest-level parser
    function - for typed Python AST nodes, use parse_ast() from ast.py instead.
    
    Args:
        command: The bash command string to parse. Must be non-empty.
        dialect: Shell dialect for parsing. Options: "bash" (default), "posix",
                "mksh", "bats", or "zsh". Affects parsing of dialect-specific
                features.
    
    Returns:
        dict: The shfmt JSON AST representation as a Python dictionary. The
            top-level object has Type="File" with a Stmts array.
    
    Raises:
        ParseError: If shfmt returns a non-zero exit code (syntax error in the
            command), if shfmt's output is not valid JSON, or if the shfmt binary
            cannot be found.
        FileNotFoundError: If no shfmt binary can be located on the system.
    
    Example:
        raw = parse('ls -la | grep txt')
        print(raw['Type'])        # "File"
        print(len(raw['Stmts']))  # 1
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
    """
    Locate the shfmt binary on the system.
    
    Searches the following locations in order:
        1. .venv/bin/shfmt (local uv virtual environment)
        2. venv/bin/shfmt (alternative virtual environment)
        3. $VIRTUAL_ENV/bin/shfmt (generic virtual environment)
        4. shfmt (fallback to system PATH)
    
    Returns:
        str: Absolute or relative path to the shfmt binary.
    
    Raises:
        FileNotFoundError: If shfmt cannot be found in any of the searched
            locations. This typically indicates that shfmt-py is not installed
            or the virtual environment is not properly set up.
    """
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
    """
    Exception raised when bash command parsing fails.
    
    Captures details about the parsing error including the original command,
    shfmt's exit code, and any stderr output. This allows callers to provide
    detailed error messages to users or log comprehensive debugging info.
    
    Attributes:
        command: The original bash command that failed to parse.
        returncode: shfmt's exit code (non-zero indicates failure).
        stderr: Raw stderr output from shfmt.
    
    Example:
        try:
            parse('ls -la')
        except ParseError as e:
            print(e.command)       # 'ls -la'
            print(e.returncode)   # exit code
            print(e.stderr)       # shfmt error details
    """
    
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
