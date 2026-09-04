"""
Permission evaluation for bash commands.

This module provides the :func:`evaluate_bash_command` function, which
parses a bash command, extracts command segments, and evaluates each
segment against a permission configuration to determine whether to
allow, ask for approval, or deny the command.
"""

from __future__ import annotations

import re
from typing import Any

from .parser import ParseError, parse
from .rules import (
    check_background_execution,
    check_blocked_patterns,
    check_input_redirection,
    check_output_redirection,
)
from .segments import parse_segments


def _has_cmd_subst(tree: dict[str, Any]) -> bool:
    """Check if the AST contains any command substitution.

    Traverses the raw shfmt AST and returns True if any Word contains
    a CmdSubst or ProcSubst part.
    """

    def visit(node: object) -> bool:
        if not isinstance(node, dict):
            return False
        node_type = node.get("Type", "")
        if node_type == "Word":
            for part in node.get("Parts", []):
                if part.get("Type") in ("CmdSubst", "ProcSubst"):
                    return True
        for value in node.values():
            if isinstance(value, dict):
                if visit(value):
                    return True
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict) and visit(item):
                        return True
        return False

    return visit(tree)


def evaluate_bash_command(command: str, config: dict[str, Any]) -> dict[str, Any]:
    """Evaluate a bash command against a permission configuration.

    Parses the command using shfmt, extracts command segments, and
    evaluates each segment against rules from the configuration.
    Aggregates results:
        - All segments allowed -> return allow
        - Any segment denied -> return deny
        - Any segment asks -> return ask

    Args:
        command: The bash command to evaluate.
        config: Permission configuration dict with keys:
            - 'allowed_cmds_regex': list of regex patterns for allowed commands
            - 'blocked_paths_regex': list of regex patterns for blocked paths
            - 'output_redirection': allow/ask/deny policy
            - 'input_redirection': allow/ask/deny policy
            - 'background_execution': allow/ask/deny policy
            - Other policy keys from devin config

    Returns:
        dict with keys:
            - 'status': 'allow', 'ask', or 'deny'
            - 'reason': human-readable explanation
            - 'segments': list of per-segment results
    """
    # Extract rules from config
    allowed_patterns = config.get("allowed_cmds_regex", [])
    blocked_patterns = config.get("blocked_paths_regex", [])

    rules = {
        "output_redirection": config.get("output_redirection", "allow"),
        "input_redirection": config.get("input_redirection", "allow"),
        "background_execution": config.get("background_execution", "allow"),
    }

    # Parse the command to check for command substitution
    try:
        raw_tree = parse(command)
    except ParseError:
        # Empty or whitespace-only command
        return {
            "status": "allow",
            "reason": "empty command",
            "segments": [],
        }

    has_subshell = _has_cmd_subst(raw_tree)

    # Extract segments
    segments = parse_segments(command)

    # Determine the wildcard policy (default action for unmatched commands)
    wildcard = config.get("*", "ask")

    # Evaluate each segment
    segment_results = []
    overall_status = "allow"
    reasons = []
    any_segment_not_allowed = False

    # Collect all matched patterns across ALL segments (joined into one reason, like TS)

    def _display_pattern(p: str) -> str:
        """Strip anchors and wrap in slashes, matching TS format."""
        clean = p
        if clean.startswith("^"):
            clean = clean[1:]
        if clean.endswith("$"):
            clean = clean[:-1]
        return f"/{clean}/"

    all_matched_patterns: list[str] = []

    for i, segment in enumerate(segments):
        cmd_name = segment.get("command", "")
        args = segment.get("arguments", [])
        segment_result = {"index": i, "command": cmd_name, "args": args}

        # Check allowed patterns against the full command line
        if allowed_patterns:
            matched_patterns = []

            if len(segments) == 1:
                # Single command: use raw command text (preserves quotes)
                full_command = command.strip()
            else:
                # Multiple segments: use reconstructed text
                full_command = cmd_name
                if args:
                    full_command = " ".join([cmd_name, *args])
            for pattern in allowed_patterns:
                if re.match(pattern, full_command):
                    matched_patterns.append(pattern)
            if matched_patterns:
                segment_result["allowed"] = True
                all_matched_patterns.extend(matched_patterns)
            else:
                segment_result["allowed"] = False
                any_segment_not_allowed = True
        else:
            segment_result["allowed"] = True

        # Check blocked patterns
        if blocked_patterns:
            matched, pattern, value = check_blocked_patterns(cmd_name, args, blocked_patterns)
            if matched:
                segment_result["blocked"] = True
                overall_status = "deny"
                reasons.append(
                    f'Blocked by bash permissions: Argument "{value}" matches blocked path pattern '
                    f"{_display_pattern(pattern)}. The tool has not been run."
                )
            else:
                segment_result["blocked"] = False
        else:
            segment_result["blocked"] = False

        segment_results.append(segment_result)

    # Produce one joined reason from all matched patterns (like TS summarizeCommandMatches)
    if all_matched_patterns and overall_status == "allow":
        noun = "pattern" if len(all_matched_patterns) == 1 else "patterns"
        reasons.append(f"command matches allowed {noun} {', '.join(all_matched_patterns)}")

    # Check redirection rules
    output_result = check_output_redirection(raw_tree, rules)
    if output_result["status"] == "deny":
        overall_status = "deny"
        reasons.append(f"output redirection denied: {output_result['reason']}")
    elif output_result["status"] == "ask" and overall_status == "allow":
        overall_status = "ask"
        reasons.append(output_result["reason"])

    input_result = check_input_redirection(raw_tree, rules)
    if input_result["status"] == "deny":
        overall_status = "deny"
        reasons.append(f"input redirection denied: {input_result['reason']}")
    elif input_result["status"] == "ask" and overall_status == "allow":
        overall_status = "ask"
        reasons.append(input_result["reason"])

    bg_result = check_background_execution(raw_tree, rules)
    if bg_result["status"] == "deny":
        overall_status = "deny"
        reasons.append(f"background execution denied: {bg_result['reason']}")
    elif bg_result["status"] == "ask" and overall_status == "allow":
        overall_status = "ask"
        reasons.append(bg_result["reason"])

    # Commands not matching allowed patterns require approval
    if allowed_patterns and any_segment_not_allowed:
        non_matching = [seg["command"] for seg in segment_results if not seg.get("allowed", True)]
        if non_matching:
            names = [f'"{name}"' for name in non_matching]
            if len(non_matching) == 1:
                reasons.append(f"{names[0]} command does not match allowed patterns")
            else:
                reasons.append(f"{', '.join(names)} commands do not match allowed patterns")
        if overall_status == "allow":
            overall_status = wildcard

    # Command substitution requires approval
    if has_subshell:
        if overall_status == "allow":
            overall_status = wildcard
        reasons.append("command substitution detected")

    # If no specific rules matched, apply wildcard policy
    if not allowed_patterns and not blocked_patterns and overall_status == "allow" and wildcard != "allow":
        overall_status = wildcard
        reasons.append(f"wildcard policy is {wildcard}")

    return {
        "status": overall_status,
        "reason": "; ".join(reasons) if reasons else "command is allowed",
        "segments": segment_results,
    }
