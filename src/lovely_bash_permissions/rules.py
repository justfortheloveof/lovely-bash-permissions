"""
Permission rules engine.

This module provides functions for evaluating permission rules
against bash command segments.
"""

from __future__ import annotations

import re


def check_allowed_patterns(command_name: str, allowed_patterns: list[str]) -> bool:
    """Test command name against allowed_cmds_regex patterns.

    Uses re.search() for regex matching. Returns True if the command
    name matches any pattern, False otherwise.

    Args:
        command_name: The name of the command to check.
        allowed_patterns: List of regex patterns to test against.

    Returns:
        True if command matches ANY pattern, False if matches none
        or patterns list is empty.
    """
    return any(re.search(pattern, command_name) for pattern in allowed_patterns)


def check_blocked_patterns(args: list[str], blocked_patterns: list[str]) -> bool:
    """Test each argument against blocked_paths_regex patterns.
    Returns True if any argument matches a blocked pattern, False otherwise.

    Args:
        args: List of argument strings to check.
        blocked_patterns: List of regex patterns to test against.

    Returns:
        True if ANY argument matches ANY blocked pattern,
        False if none match or patterns list is empty.
    """
    return any(re.search(pattern, arg) for arg in args for pattern in blocked_patterns)
