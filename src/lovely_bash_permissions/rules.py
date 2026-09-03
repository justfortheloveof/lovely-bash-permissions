"""
Permission rules engine.

This module provides functions for evaluating permission rules
against bash command segments.
"""

from __future__ import annotations

import re
from typing import Any


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


def check_output_redirection(tree: dict[str, Any], rules: dict) -> dict:
    """Evaluate output redirections against rules.

    Extracts output redirections (> or >>) from the AST and applies
    the configured allow/ask/deny policy.

    Args:
        tree: The shfmt JSON AST representation of the bash command.
        rules: Policy dict with "output_redirection" key set to
            "allow", "ask", or "deny" (or object form with per-type policies).

    Returns:
        dict with "status" ("allow"/"ask"/"deny") and "reason" string.
        If no output redirection is found, returns {"status": "allow", "reason": "no output redirection"}.
    """
    policy = rules.get("output_redirection", "allow")

    # If policy is an object, use the wildcard level for now
    # (per-type policies handled in the evaluator layer)
    if isinstance(policy, dict):
        level = policy.get("*", policy.get("allow", "allow"))
    else:
        level = policy

    redirections = []
    for stmt in tree.get("Stmts", []):
        for redir in stmt.get("Redirs", []):
            op = redir.get("Op", "")
            if op in (">", ">>"):
                target = ""
                word = redir.get("Word", {})
                parts = word.get("Parts", [])
                if parts:
                    target = parts[0].get("Value", "")
                redirections.append({"op": op, "target": target})

    if not redirections:
        return {
            "status": "allow",
            "reason": "no output redirection",
        }

    targets = [r["target"] for r in redirections]

    if level == "allow":
        return {
            "status": "allow",
            "reason": f"output redirection allowed to {', '.join(targets)}",
        }
    elif level == "ask":
        return {
            "status": "ask",
            "reason": "output redirection requires approval",
        }
    else:  # deny
        return {
            "status": "deny",
            "reason": f"output redirection denied to {', '.join(targets)}",
        }


def check_input_redirection(tree: dict[str, Any], rules: dict) -> dict:
    """Evaluate input redirections against rules.

    Extracts input redirections (< or <<) from the AST and applies
    the configured allow/ask/deny policy.

    Args:
        tree: The shfmt JSON AST representation of the bash command.
        rules: Policy dict with "input_redirection" key set to
            "allow", "ask", or "deny" (or object form with per-type policies).

    Returns:
        dict with "status" ("allow"/"ask"/"deny") and "reason" string.
        If no input redirection is found, returns {"status": "allow", "reason": "no input redirection"}.
    """
    policy = rules.get("input_redirection", "allow")

    # If policy is an object, use the wildcard level for now
    # (per-type policies handled in the evaluator layer)
    if isinstance(policy, dict):
        level = policy.get("*", policy.get("allow", "allow"))
    else:
        level = policy

    redirections = []
    for stmt in tree.get("Stmts", []):
        for redir in stmt.get("Redirs", []):
            op = redir.get("Op", "")
            if op in ("<", "<<"):
                target = ""
                word = redir.get("Word", {})
                parts = word.get("Parts", [])
                if parts:
                    target = parts[0].get("Value", "")
                redirections.append({"op": op, "target": target})

    if not redirections:
        return {
            "status": "allow",
            "reason": "no input redirection",
        }

    targets = [r["target"] for r in redirections]

    if level == "allow":
        return {
            "status": "allow",
            "reason": f"input redirection allowed from {', '.join(targets)}",
        }
    elif level == "ask":
        return {
            "status": "ask",
            "reason": "input redirection requires approval",
        }
    else:  # deny
        return {
            "status": "deny",
            "reason": f"input redirection denied from {', '.join(targets)}",
        }
