"""
Permission rules engine.

This module provides functions for evaluating permission rules
against bash command segments.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

WRITE_REDIRECT_OPS: frozenset[str] = frozenset({">", ">>", ">|", "&>", ">&", "&>>", "<>"})
COMBINED_OPS: frozenset[str] = frozenset({">&", "&>", "&>>"})
DEV_NULL: str = "/dev/null"


def _raw_word_target(word: dict[str, Any]) -> str:
    """Reconstruct a full redirection target from a raw shfmt Word dict.

    Joins ALL parts (not just the first) so multi-part targets like
    ``"$DIR/out"`` or ``"/dev""/null"`` are identified. Lit values are
    backslash-unescaped (unquoted context); DblQuoted parts use their
    best-effort ``Value`` or their nested parts.
    """
    chunks: list[str] = []
    for part in word.get("Parts", []) if isinstance(word, dict) else []:
        if not isinstance(part, dict):
            continue
        ptype = part.get("Type")
        if ptype == "Lit":
            chunks.append(re.sub(r"\\([^\n])", r"\1", part.get("Value", "")))
        elif ptype == "SglQuoted":
            chunks.append(part.get("Value", ""))
        elif ptype == "DblQuoted":
            if part.get("Parts"):
                for sub in part["Parts"]:
                    if isinstance(sub, dict):
                        chunks.append(str(sub.get("Value", "")))
            else:
                chunks.append(part.get("Value") or "")
        else:
            v = part.get("Value")
            if isinstance(v, str):
                chunks.append(v)
    return "".join(chunks)


def _redir_target(redir: dict[str, Any]) -> str:
    """Best redirection target for policy decisions.

    Prefers the segment-level ``Target`` key (full executed form, produced
    by segments.py); falls back to reconstructing from raw Word parts.
    """
    t = redir.get("Target")
    if isinstance(t, str) and t:
        return t
    return _raw_word_target(redir.get("Word", {}) or {})


@lru_cache(maxsize=512)
def _compile_pattern(pattern: str) -> re.Pattern[str]:
    """Compile and cache a regex pattern. Raises ValueError on invalid pattern."""
    try:
        return re.compile(pattern)
    except re.error as exc:
        raise ValueError(f"invalid pattern {pattern!r}: {exc}") from exc


def _match_pattern(value: str, pattern: str) -> bool:
    """Check a single value against one pattern (unanchored search)."""
    try:
        return bool(_compile_pattern(pattern).search(value))
    except ValueError:
        return False


def _find_blocked_path(value: str, blocked_patterns: list[str]) -> tuple[bool, str]:
    """Check if a value matches any blocked path pattern.

    Returns (True, matching_pattern) if found, (False, "") otherwise.
    """
    for pattern in blocked_patterns:
        if _match_pattern(value, pattern):
            return True, pattern
    return False, ""


def _find_redirs(node: dict[str, Any]) -> list[dict[str, Any]]:
    """Recursively collect all redirection dicts from an AST node.

    Walks CallExpr.Redirs, BinaryCmd.X/Y/Redirs (merged list), and recurses into
    AndCmd/OrCmd operands so redirections nested inside pipes are found.

    Also recurses into heredoc bodies (``Hdoc.Parts``) so that command
    substitutions inside unquoted heredocs (``<<EOF … $(cmd) … EOF``)
    are discovered - bash expands these at runtime.

    Args:
        node: A dict representing an AST node from shfmt's JSON output.

    Returns:
        List of redirection dicts (each with "Op" and "Word").
    """
    redirs: list[dict[str, Any]] = []

    # Redirection-only compound operand (no Type/Cmd, just Redirs) - see
    # converter.node_from_json handling for `> f && cmd` (NEW_BUGS #3).
    if not node.get("Type") and node.get("Redirs"):
        redirs.extend(node["Redirs"])

    # CallExpr has Redirs directly on the node itself
    if node.get("Type") == "CallExpr":
        redirs.extend(node.get("Redirs", []))
        # Recurse into arguments to find CmdSubst/ProcSubst redirections
        for arg in node.get("Args", []):
            redirs.extend(_find_redirs(arg))

    # BinaryCmd: redirects live on X/Y wrapper nodes (left/right operands).
    # The converter merges these into a single ``redirs`` field for the
    # typed AST, but in raw JSON there is no merged list - only X/Y.
    if node.get("Type") == "BinaryCmd":
        x = node.get("X", {})
        redirs.extend(x.get("Redirs", []))
        y = node.get("Y", {})
        redirs.extend(y.get("Redirs", []))

    # AndCmd / OrCmd operands may also carry redirections
    if node.get("Type") in ("AndCmd", "OrCmd"):
        left = node.get("Left", {})
        redirs.extend(_find_redirs(left))
        right = node.get("Right", {})
        redirs.extend(_find_redirs(right))

    # CmdSubst / ProcSubst: recurse into each stmt's Cmd (raw JSON has "Stmts")
    if node.get("Type") in ("CmdSubst", "ProcSubst"):
        for stmt in node.get("Stmts", []):
            redirs.extend(stmt.get("Redirs", []))
            redirs.extend(_find_redirs(stmt.get("Cmd", {}) or {}))

    # Word: recurse into parts (may contain CmdSubst/ProcSubst).
    # Word nodes lack a "Type" field, so detect by presence of "Parts".
    if node.get("Parts"):
        for part in node["Parts"]:
            redirs.extend(_find_redirs(part))

    # Redir: recurse into Hdoc.Parts so heredoc body command substitutions
    # (e.g. $(cat /etc/passwd) inside <<EOF … EOF) are discovered.
    if node.get("Type") == "Redir":
        hdoc = node.get("Hdoc", {})
        if isinstance(hdoc, dict):
            for part in hdoc.get("Parts", []):
                redirs.extend(_find_redirs(part))

    return redirs


def _find_background_flags(node: dict[str, Any]) -> list[str]:
    """Recursively collect command names from a backgrounded AST node.

    Walks the whole subtree so any compound command type (Block, Subshell,
    IfClause, WhileClause, ForClause, CaseClause, CoprocClause, ...) yields
    the commands it runs.

    Args:
        node: A dict representing an AST node from shfmt's JSON output.

    Returns:
        List of command names found in CallExpr args.
    """
    results: list[str] = []

    if node.get("Type") == "CallExpr":
        args = node.get("Args", [])
        if args:
            parts = args[0].get("Parts", [])
            if parts:
                results.append(parts[0].get("Value", ""))

    for value in node.values():
        if isinstance(value, dict):
            results.extend(_find_background_flags(value))
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    results.extend(_find_background_flags(item))

    return results


def check_allowed_patterns(command_name: str, allowed_patterns: list[str]) -> bool:
    """Test command name against allowed_cmds_regex patterns.

    Uses cached regex compilation via _compile_pattern(). Returns True if the command
    name matches any pattern, False otherwise.

    Args:
        command_name: The name of the command to check.
        allowed_patterns: List of regex patterns to test against.

    Returns:
        True if command matches ANY pattern, False if matches none
        or patterns list is empty.
    """
    try:
        return any(_compile_pattern(p).search(command_name) for p in allowed_patterns)
    except ValueError:
        return False


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
        if _match_pattern(command_name, pattern):
            return True, pattern, command_name
    for arg in args:
        for pat in blocked_patterns:
            if _match_pattern(arg, pat):
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

    # For >&/&>/& >> ops, shfmt puts fd in N.Value when present
    n = redir.get("N", {})
    fd: str | None = None
    if isinstance(n, dict):
        fd = n.get("Value")

    # Determine target value (full target reconstructed from all parts)
    target: str = _redir_target(redir)

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
    policy = rules.get("output_redirection", "ask")

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
        if op in WRITE_REDIRECT_OPS:
            redirections.append(redir)

    if not redirections:
        return {
            "status": "allow",
            "reason": "no output redirection",
        }

    targets = []
    kinds: list[str] = []
    for redir in redirections:
        targets.append(_redir_target(redir))
        kinds.extend(classify_output_redirection(redir))

    # Check redirect targets against blocked paths (security check, applies to all policies).
    blocked_patterns = rules.get("blocked_paths_regex", [])
    if blocked_patterns:
        for target in targets:
            matched, pattern = _find_blocked_path(target, blocked_patterns)
            if matched:
                return {
                    "status": "deny",
                    "reason": f'Redirect target "{target}" matches blocked path pattern {pattern}',
                }

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

    Each kind is checked independently against its own policy key,
    falling back to wildcard "*".  Deny takes priority over ask.

    Args:
        kinds: List of redirection kind strings from classify_output_redirection.
        policy: Dict-form output_redirection policy.

    Returns:
        "allow", "ask", or "deny".
    """
    wildcard_level = policy.get("*", "ask")

    has_deny = False
    has_ask = False
    for kind in kinds:
        # Each kind gets its own level lookup, independent of others
        level = policy.get(kind, wildcard_level)
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
    policy = rules.get("input_redirection", "ask")

    # If policy is an object, use the wildcard level.
    # (TS version only uses wildcard for input redirection)
    level = policy.get("*", "ask") if isinstance(policy, dict) else policy

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
        if op in ("<", "<<", "<<<", "<&"):
            redirections.append({"op": op, "target": _redir_target(redir)})

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


def _check_segments_output_redirs(segments: list[dict[str, Any]], rules: dict[str, Any]) -> dict[str, Any]:
    """Evaluate output redirections collected from segments.

    Works on segment dicts produced by ``parse_segments`` - each segment's
    ``"redirections"`` list contains dicts with ``Op``, ``N``, and ``Word``.
    Applies the same policy logic as :func:`check_output_redirection` but
    operates on segment-level data (single source of truth, issue #2/#3).

    Args:
        segments: List of segment dicts from parse_segments.
        rules: Policy dict with ``output_redirection`` key.

    Returns:
        dict with ``status`` and ``reason``.
    """
    policy = rules.get("output_redirection", "ask")

    # compound-command redirections (while/until/if/{ } group) are
    # attributed to every inner segment - the same redirection appears once per
    # segment. Dedupe by (op, fd, target); distinct descriptors are preserved.
    redirections: list[dict[str, Any]] = []
    seen_output: set[tuple[str, str, str]] = set()
    for seg in segments:
        for r in seg.get("redirections", []):
            if r.get("Op") in WRITE_REDIRECT_OPS:
                target = _redir_target(r)
                # segment redirection dicts serialize the fd as a dict
                # ({} when absent, {"Value": "2"} for `2>`) - extract the scalar
                # fd so the dedupe key is hashable.
                n = r.get("N")
                fd = n.get("Value", "") if isinstance(n, dict) else ("" if n is None else str(n))
                key = (r.get("Op", ""), fd, target)
                if key not in seen_output:
                    seen_output.add(key)
                    redirections.append(r)

    if not redirections:
        return {"status": "allow", "matched": False, "reason": "no output redirection"}

    targets: list[str] = []
    kinds: list[str] = []
    for redir in redirections:
        targets.append(_redir_target(redir))
        kinds.extend(classify_output_redirection(redir))

    # Check redirect targets against blocked paths (security check, applies to all policies).
    blocked_patterns = rules.get("blocked_paths_regex", [])
    if blocked_patterns:
        for target in targets:
            matched, pattern = _find_blocked_path(target, blocked_patterns)
            if matched:
                return {
                    "status": "deny",
                    "reason": f'Redirect target "{target}" matches blocked path pattern {pattern}',
                }

    level = _resolve_output_level(kinds, policy) if isinstance(policy, dict) else policy

    if level == "allow":
        return {"status": "allow", "reason": f"output redirection allowed to {', '.join(targets)}"}
    elif level == "ask":
        return {"status": "ask", "reason": "output redirection requires approval"}
    else:
        return {"status": "deny", "reason": f"output redirection denied to {', '.join(targets)}"}


def _check_segments_input_redirs(segments: list[dict[str, Any]], rules: dict[str, Any]) -> dict[str, Any]:
    """Evaluate input redirections collected from segments.

    Segment-level counterpart to :func:`check_input_redirection`.

    Args:
        segments: List of segment dicts from parse_segments.
        rules: Policy dict with ``input_redirection`` key.

    Returns:
        dict with ``status`` and ``reason``.
    """
    rules = rules or {}
    policy = rules.get("input_redirection", "ask")
    level = policy.get("*", "ask") if isinstance(policy, dict) else policy

    # dedupe by (op, target) - compound-command redirections are
    # attributed to every inner segment.
    input_redirs: list[dict[str, Any]] = []
    seen_input: set[tuple[str, str]] = set()
    for seg in segments:
        for r in seg.get("redirections", []):
            if r.get("Op") in ("<", "<<", "<<<", "<&"):
                target = _redir_target(r)
                key = (r["Op"], target)
                if key not in seen_input:
                    seen_input.add(key)
                    input_redirs.append({"op": r["Op"], "target": target})

    if not input_redirs:
        return {"status": "allow", "matched": False, "reason": "no input redirection"}

    targets = [r["target"] for r in input_redirs]
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
        return {"status": "allow", "reason": f"input redirection allowed from {', '.join(targets)}"}
    elif level == "ask":
        return {"status": "ask", "reason": "input redirection requires approval"}
    else:
        return {"status": "deny", "reason": f"input redirection denied from {', '.join(targets)}"}


def _collect_background_command_names(node: dict[str, Any], results: list[str]) -> None:
    """Recursively collect command names being run in the background.

    Background flags can appear on any statement in the tree, not just the
    top-level ones - e.g. ``(echo hi &)`` or ``x=$(echo hi &)`` background the
    inner command while the outer statement has ``Background=false``.
    """
    if not isinstance(node, dict):
        return
    if node.get("Background") or node.get("Type") == "CoprocClause":
        results.extend(_find_background_flags(node.get("Cmd") or node))
    for value in node.values():
        if isinstance(value, dict):
            _collect_background_command_names(value, results)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    _collect_background_command_names(item, results)


def check_background_execution(tree: dict[str, Any], rules: dict[str, Any]) -> dict[str, Any]:
    """Evaluate background execution against rules.

    Detects background execution (trailing & operator) anywhere in the AST -
    including backgrounds nested inside subshells and command substitutions -
    and applies the configured allow/ask/deny policy.

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
    level = policy.get("*", "ask") if isinstance(policy, dict) else policy

    background_commands: list[str] = []
    _collect_background_command_names(tree, background_commands)
    background_commands = list(dict.fromkeys(background_commands))

    if not background_commands:
        return {
            "status": "allow",
            "matched": False,
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
