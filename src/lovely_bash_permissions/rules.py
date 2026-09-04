"""
Permission rules engine.

This module provides functions for evaluating permission rules
against bash command segments.
"""

from __future__ import annotations

import re
from typing import Any

WRITE_REDIRECT_OPS: frozenset[str] = frozenset({">", ">>", "&>", ">&", "&>>"})
COMBINED_OPS: frozenset[str] = frozenset({">&", "&>", "&>>"})
DEV_NULL: str = "/dev/null"


def _find_blocked_path(value: str, blocked_patterns: list[str]) -> tuple[bool, str]:
    """Check if a value matches any blocked path pattern.

    Returns (True, matching_pattern) if found, (False, "") otherwise.
    """
    for pattern in blocked_patterns:
        if re.search(pattern, value):
            return True, pattern
    return False, ""


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


def classify_output_redirection(redir: dict[str, Any]) -> list[str]:
    """Classify a single write redirection into policy-kind keys.

    Returns one of: 'other', 'stdout_to_dev_null', 'stderr_to_dev_null',
    'stderr_to_stdout'.  Combined operators (>&, &>, & >>) that target
    /dev/null yield both stdout+stderr kinds.

    Args:
        redir: A redirection dict from shfmt with keys 'Op' and 'Word'.

    Returns:
        List of kind strings this redirection triggers.
    """
    op = redir.get("Op", "")
    if op not in WRITE_REDIRECT_OPS:
        return []

    # Extract fd number (e.g. "2" from 2>&1) and target
    word = redir.get("Word", {})
    parts = word.get("Parts", [])

    fd: str | None = None
    target: str = ""

    # For >&/&>/& >> ops, shfmt puts fd in N.Value when present
    n = redir.get("N", {})
    fd: str | None = n.get("Value") if isinstance(n, dict) else None

    # Determine target value from first part's Value (filename)
    if parts:
        target = parts[0].get("Value", "")

    # fd duplication: 2>&1 means stderr -> stdout
    if op == ">&" and fd == "2" and target == "1":
        return ["stderr_to_stdout"]

    # Redirection to /dev/null
    if target == DEV_NULL:
        if op in COMBINED_OPS:
            return ["stdout_to_dev_null", "stderr_to_dev_null"]
        if fd == "2":
            return ["stderr_to_dev_null"]
        return ["stdout_to_dev_null"]  # fd=1 or default

    return ["other"]


def check_output_redirection(tree: dict[str, Any], rules: dict[str, Any]) -> dict[str, Any]:
    """Evaluate output redirections against rules.

    Extracts output redirections (> or >>) from the AST and applies
    the configured allow/ask/deny policy.

    When rules["output_redirection"] is a dict, kind-specific keys
    (stderr_to_dev_null, stderr_to_stdout, stdout_to_dev_null) are
    checked first, falling back to "*".

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
        if op in (">", ">>", "&>", ">&", "&>>"):
            redirections.append(redir)

    if not redirections:
        return {
            "status": "allow",
            "reason": "no output redirection",
        }

    targets = []
    kinds: list[str] = []
    for redir in redirections:
        target_word = redir.get("Word", {})
        parts = target_word.get("Parts", [])
        if parts:
            targets.append(parts[0].get("Value", ""))
        kinds.extend(classify_output_redirection(redir))

    level = _resolve_output_level(kinds, policy) if isinstance(policy, dict) else policy

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


def _resolve_output_level(kinds: list[str], policy: dict[str, Any]) -> str:
    """Resolve output redirection level using per-kind policy keys.

    Any-asks semantics: if ANY redirect resolves to deny, return deny;
    if any resolve to ask (and none deny), return ask; else allow.
    Kind-specific keys are checked first, falling back to wildcard "*".
    Non-special kinds ("other") fall back to the wildcard level.

    Args:
        kinds: List of redirection kind strings from classify_output_redirection.
        policy: Dict-form output_redirection policy.

    Returns:
        The resolved level string (allow/ask/deny).
    """
    wildcard_level = policy.get("*", "allow")

    has_deny = False
    has_ask = False
    for kind in kinds:
        level = wildcard_level if kind == "other" else policy.get(kind, wildcard_level)
        if level == "deny":
            has_deny = True
        elif level == "ask":
            has_ask = True
    if has_deny:
        return "deny"
    if has_ask:
        return "ask"
    return "allow"


def check_input_redirection(tree: dict[str, Any], rules: dict[str, Any] | None = None) -> dict[str, Any]:
    """Evaluate input redirections against rules.

    Extracts input redirections (< or <<) from the AST and applies
    the configured allow/ask/deny policy.

    When rules["input_redirection"] is a dict, uses wildcard "*" level.

    When input redirection policy is "ask", redirect targets are also checked
    against blocked_paths_regex from rules. If any target matches a blocked
    path pattern, the status is escalated to "deny" (overrides ask).

    Args:
        tree: The shfmt JSON AST representation of the bash command.
        rules: Policy dict with "input_redirection" key set to
            "allow", "ask", or "deny" (or object form with per-type policies).
            May also contain "blocked_paths_regex" for target validation.

    Returns:
        dict with "status" ("allow"/"ask"/"deny") and
        "reason" string.
        If no input redirection is found, returns
        {"status": "allow", "reason": "no input redirection"}.
    """
    rules = rules or {}
    policy = rules.get("input_redirection", "allow")

    # If policy is an object, use the wildcard level.
    # (TS version only uses wildcard for input redirection)
    level = policy.get("*", "allow") if isinstance(policy, dict) else policy

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

    # Check redirect targets against blocked_paths (security check, applies to all policies).
    blocked_patterns = rules.get("blocked_paths_regex", [])
    if blocked_patterns:
        for target in targets:
            matched, pattern = _find_blocked_path(target, blocked_patterns)
            if matched:
                return {
                    "status": "deny",
                    "reason": f'Redirect target "{target}" matches blocked path pattern {pattern}',
                }

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
    policy = rules.get("background_execution", "ask")

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
