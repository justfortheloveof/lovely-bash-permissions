"""
Permission rules engine.

This module provides functions for evaluating permission rules
against bash command segments.
"""

from __future__ import annotations

import re
from typing import Any


def _find_redirs(node: dict[str, Any]) -> list[dict[str, Any]]:
    """Recursively collect all redirection dicts from an AST node.

    Walks CallExpr.Redirs, BinaryCmd.X/Y/Redirs (merged list), and recurses into
    AndCmd/OrCmd operands so redirections nested inside pipes are found.

    Args:
        node: A dict representing an AST node from shfmt's JSON output.

    Returns:
        List of redirection dicts (each with "Op" and "Word").
    """
    redirs: list[dict[str, Any]] = []

    # CallExpr has Redirs directly on the node itself
    if node.get("Type") == "CallExpr":
        redirs.extend(node.get("Redirs", []))

    # BinaryCmd has Redirs on X/Y wrapper nodes (also merged at node level)
    if node.get("Type") == "BinaryCmd":
        redirs.extend(node.get("Redirs", []))
        x = node.get("X", {})
        redirs.extend(x.get("Redirs", []))  # wrapper-level RedDirs
        y = node.get("Y", {})
        redirs.extend(y.get("Redirs", []))  # wrapper-level RedDirs

    # AndCmd / OrCmd operands may also carry redirections
    if node.get("Type") in ("AndCmd", "OrCmd"):
        left = node.get("Left", {})
        redirs.extend(_find_redirs(left))
        right = node.get("Right", {})
        redirs.extend(_find_redirs(right))

    return redirs


def _find_background_flags(node: dict[str, Any]) -> list[str]:
    """Recursively collect background flags from an AST node.

    Finds statements with ``Background: true`` regardless of whether their Cmd
    is a CallExpr or BinaryCmd (pipes).

    Args:
        node: A dict representing an AST node from shfmt's JSON output.

    Returns:
        List of (command_name, background_flag) tuples found in CallExpr args.
    """
    results: list[str] = []

    if node.get("Type") == "CallExpr":
        args = node.get("Args", [])
        if args:
            parts = args[0].get("Parts", [])
            if parts:
                results.append(parts[0].get("Value", ""))

    if node.get("Type") == "BinaryCmd":
        x = node.get("X", {})
        results.extend(_find_background_flags(x.get("Cmd", {})))
        y = node.get("Y", {})
        results.extend(_find_background_flags(y.get("Cmd", {})))

    if node.get("Type") in ("AndCmd", "OrCmd"):
        left = node.get("Left", {})
        results.extend(_find_background_flags(left))
        right = node.get("Right", {})
        results.extend(_find_background_flags(right))

    return results


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


def check_blocked_patterns(
    command_name: str, args: list[str], blocked_patterns: list[str]
) -> tuple[bool, str | None, str | None]:
    """Test command name and arguments against blocked_paths_regex patterns.

    Returns a tuple of (matched: bool, pattern: str | None, value: str | None)
    where pattern is the matching regex and value is which arg/command matched.

    Args:
        command_name: The name of the command to check.
        args: List of argument strings to check.
        blocked_patterns: List of regex patterns to test against.

    Returns:
        (True, pattern, value) if any match,
        (False, None, None) otherwise.
    """
    if not blocked_patterns:
        return False, None, None
    for pattern in blocked_patterns:
        if re.search(pattern, command_name):
            return True, pattern, command_name
    for arg in args:
        for pat in blocked_patterns:
            if re.search(pat, arg):
                return True, pat, arg
    return False, None, None


def check_output_redirection(tree: dict[str, Any], rules: dict[str, Any]) -> dict[str, Any]:
    """Evaluate output redirections against rules.

    Extracts output redirections (> or >>) from the AST and applies
    the configured allow/ask/deny policy.

    Args:
        tree: The shfmt JSON AST representation of the bash command.
        rules: Policy dict with "output_redirection" key set to
            "allow", "ask", or "deny" (or object form with per-type policies).

    Returns:
        dict with "status" ("allow"/"ask"/"deny") and
        "reason" string.
        If no output redirection is found, returns
        {"status": "allow", "reason": "no output redirection"}.
    """
    policy = rules.get("output_redirection", "allow")

    # If policy is an object, use the wildcard level for now
    # (per-type policies handled in the evaluator layer)
    level = policy.get("*", policy.get("allow", "allow")) if isinstance(policy, dict) else policy

    redirs = []
    for stmt in tree.get("Stmts", []):
        # Redirs on the statement node itself (simple statements)
        redirs.extend(stmt.get("Redirs", []))
        # Redirs inside Cmd (pipes BinaryCmd, etc.)
        cmd = stmt.get("Cmd", {})
        redirs.extend(_find_redirs(cmd))

    redirections = []
    for redir in redirs:
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


def check_input_redirection(tree: dict[str, Any], rules: dict[str, Any]) -> dict[str, Any]:
    """Evaluate input redirections against rules.

    Extracts input redirections (< or <<) from the AST and applies
    the configured allow/ask/deny policy.

    Args:
        tree: The shfmt JSON AST representation of the bash command.
        rules: Policy dict with "input_redirection" key set to
            "allow", "ask", or "deny" (or object form with per-type policies).

    Returns:
        dict with "status" ("allow"/"ask"/"deny") and
        "reason" string.
        If no input redirection is found, returns
        {"status": "allow", "reason": "no input redirection"}.
    """
    policy = rules.get("input_redirection", "allow")

    # If policy is an object, use the wildcard level for now
    # (per-type policies handled in the evaluator layer)
    level = policy.get("*", policy.get("allow", "allow")) if isinstance(policy, dict) else policy

    redirs = []
    for stmt in tree.get("Stmts", []):
        # Redirs on the statement node itself (simple statements)
        redirs.extend(stmt.get("Redirs", []))
        # Redirs inside Cmd (pipes BinaryCmd, etc.)
        cmd = stmt.get("Cmd", {})
        redirs.extend(_find_redirs(cmd))

    redirections = []
    for redir in redirs:
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


def check_background_execution(tree: dict[str, Any], rules: dict[str, Any]) -> dict[str, Any]:
    """Evaluate background execution against rules.

    Detects background execution (trailing & operator) from the AST and
    applies the configured allow/ask/deny policy.

    Args:
        tree: The shfmt JSON AST representation of the bash command.
        rules: Policy dict with "background_execution" key set to
            "allow", "ask", or "deny" (or object form with per-type policies).

    Returns:
        dict with "status" ("allow"/"ask"/"deny") and
        "reason" string.
        If no background execution is found, returns
        {"status": "allow", "reason": "no background execution"}.
    """
    policy = rules.get("background_execution", "allow")

    # If policy is an object, use the wildcard level for now
    # (per-type policies handled in the evaluator layer)
    level = policy.get("*", policy.get("allow", "allow")) if isinstance(policy, dict) else policy

    background_commands = []
    for stmt in tree.get("Stmts", []):
        if stmt.get("Background"):
            cmd = stmt.get("Cmd", {})
            background_commands.extend(_find_background_flags(cmd))

    if not background_commands:
        return {
            "status": "allow",
            "reason": "no background execution",
        }

    if level == "allow":
        return {
            "status": "allow",
            "reason": f"background execution allowed: {', '.join(background_commands)}",
        }
    elif level == "ask":
        return {
            "status": "ask",
            "reason": (f"background execution requires approval: {', '.join(background_commands)}"),
        }
    else:  # deny
        return {
            "status": "deny",
            "reason": f"background execution denied: {', '.join(background_commands)}",
        }
