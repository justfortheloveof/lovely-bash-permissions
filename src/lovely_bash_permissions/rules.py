"""
Permission rules engine.

This module provides functions for evaluating permission rules
against bash command segments.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from .segments import Segment, SegmentRedirection

#: Redirection operators that open a file for writing (or for reading *and*
#: writing, as ``<>`` does).  Gates the ``output_redirection`` policy.
WRITE_REDIRECT_OPS: frozenset[str] = frozenset({">", ">>", ">|", "&>", ">&", "&>>", "<>"})

#: Redirection operators that feed a command from a file, a here-document or a
#: here-string.  Gates the ``input_redirection`` policy.
#:
#: ``<<-`` is the tab-stripping here-document: bash consumes the body exactly as
#: it does for ``<<``, differing only in how the delimiter is matched, so it
#: must be gated identically or ``cat <<-EOF`` reads an arbitrary file with no
#: policy ever consulted.
#:
#: Together with ``WRITE_REDIRECT_OPS`` this covers every operator the parser
#: can emit.  ``<>`` is read-write and is classified as a write; that is the
#: stricter of the two, since it cannot write without also reading.
INPUT_REDIRECT_OPS: frozenset[str] = frozenset({"<", "<<", "<<-", "<<<", "<&"})

COMBINED_OPS: frozenset[str] = frozenset({">&", "&>", "&>>"})
DEV_NULL: str = "/dev/null"


def _redir_target(redir: SegmentRedirection) -> str:
    """Redirection target for policy decisions.

    Reads the segment-level ``Target`` key, which ``segments._redir_dicts``
    always sets: the full executed form (all word parts joined, quotes
    removed, backslashes unescaped) of the redirect target.  That is the string
    bash actually opens, which is the only thing a policy can be decided on.

    A part-wise projection of the target must not be reconstructed here: it
    reduces every word part to a bare ``Value`` string and so has already
    lost the quoting, escapes and expansions that distinguish
    ``/dev""/null`` from ``/dev/xnull``, which makes it strictly lossier than
    the ``Target`` computed from the intact word.  ``_redir_dicts`` populates
    ``Target`` unconditionally for every redirection it emits, so there is no
    case where a reconstruction would have anything to add.
    """
    return redir.get("Target", "")


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
    """Check if a value matches any blocked pattern.

    Returns (True, matching_pattern) if found, (False, "") otherwise.
    """
    for pattern in blocked_patterns:
        if _match_pattern(value, pattern):
            return True, pattern
    return False, ""


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


def classify_output_redirection(redir: SegmentRedirection) -> list[str]:
    """Classify a single write redirection into policy-kind keys.

    Returns one of: 'other', 'stdout_to_dev_null', 'stderr_to_dev_null',
    'stderr_to_stdout'.  Combined operators (>&, &>, & >>) that target
    /dev/null yield both stdout+stderr kinds.

    Args:
        redir: A :class:`~lovely_bash_permissions.segments.SegmentRedirection`
            as carried by a segment.

    Returns:
        List of kind strings this redirection triggers.
    """
    op = redir.get("Op", "")
    if op not in WRITE_REDIRECT_OPS:
        return []

    # For >&/&>/& >> ops, shfmt puts fd in N.Value when present
    fd: str | None = redir.get("N", {}).get("Value")

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


def _check_segments_output_redirs(segments: list[Segment], rules: dict[str, Any]) -> dict[str, Any]:
    """Evaluate output redirections collected from segments.

    Works on segment dicts produced by ``parse_segments`` - each segment's
    ``"redirections"`` list holds :class:`SegmentRedirection` records.  This is
    the single source of truth for output redirection policy: the segment parser
    has already walked the whole command, including redirections nested inside
    pipes, subshells and command substitutions, so a second raw-AST traversal
    would be redundant and would risk missing the nested ones.

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
    redirections: list[SegmentRedirection] = []
    seen_output: set[tuple[str, str, str]] = set()
    for seg in segments:
        for r in seg.get("redirections") or []:
            if r.get("Op") in WRITE_REDIRECT_OPS:
                target = _redir_target(r)
                # the segment producers serialize the fd as a str
                # ("" when absent, "2" for `2>`) - that scalar is the dedupe key.
                fd = r.get("N", {}).get("Value", "")
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
    blocked_patterns = rules.get("blocked_cmds_regex", [])
    if blocked_patterns:
        for target in targets:
            matched, pattern = _find_blocked_path(target, blocked_patterns)
            if matched:
                return {
                    "status": "deny",
                    "reason": f'Redirect target "{target}" matches blocked pattern {pattern}',
                }

    level = _resolve_output_level(kinds, policy) if isinstance(policy, dict) else policy

    if level == "allow":
        return {"status": "allow", "reason": f"output redirection allowed to {', '.join(targets)}"}
    elif level == "ask":
        return {"status": "ask", "reason": "output redirection requires approval"}
    else:
        return {"status": "deny", "reason": f"output redirection denied to {', '.join(targets)}"}


def _check_segments_input_redirs(segments: list[Segment], rules: dict[str, Any]) -> dict[str, Any]:
    """Evaluate input redirections collected from segments.

    Segment-level counterpart to :func:`_check_segments_output_redirs`, and
    the single source of truth for input redirection policy.

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
    input_redirs: list[dict[str, str]] = []
    seen_input: set[tuple[str, str]] = set()
    for seg in segments:
        for r in seg.get("redirections") or []:
            if r.get("Op") in INPUT_REDIRECT_OPS:
                target = _redir_target(r)
                key = (r["Op"], target)
                if key not in seen_input:
                    seen_input.add(key)
                    input_redirs.append({"op": r["Op"], "target": target})

    if not input_redirs:
        return {"status": "allow", "matched": False, "reason": "no input redirection"}

    targets = [r["target"] for r in input_redirs]
    blocked_patterns = rules.get("blocked_cmds_regex", [])
    if blocked_patterns:
        for target in targets:
            matched, pattern = _find_blocked_path(target, blocked_patterns)
            if matched:
                return {
                    "status": "deny",
                    "reason": f'Redirect target "{target}" matches blocked pattern {pattern}',
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
