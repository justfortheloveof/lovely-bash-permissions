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

from .ast import Node
from .converter import node_from_json
from .inspect import _traverse, _word_value
from .parser import ParseError, parse
from .rules import (
    _check_segments_input_redirs,
    _check_segments_output_redirs,
    check_background_execution,
    check_blocked_patterns,
)
from .segments import parse_segments


class _Found(Exception):
    """Raised to short-circuit traversal when a match is found."""


def _extract_subshell_contents(tree: dict[str, Any]) -> list[str]:
    """Extract literal text values from inside CmdSubst/ProcSubst nodes.

    Uses the typed AST (via :func:`~lovely_bash_permissions.converter.node_from_json`)
    so that substitutions nested inside quoted strings are found —
    unlike the raw-JSON visitor which missed CmdSubst/ProcSubst
    hidden inside DblQuoted/SglQuoted parts.

    Returns:
        List of literal text strings found inside subshells,
        extracted via :func:`~lovely_bash_permissions.inspect._word_value`.
    """
    ast = node_from_json(tree)
    if ast is None:
        return []
    contents: list[str] = []

    def visitor(node: Node) -> None:
        from .ast import CallExpr, CmdSubst, ProcSubst

        if isinstance(node, (CmdSubst, ProcSubst)):
            for stmt in node.stmts:
                if isinstance(stmt.cmd, CallExpr) and stmt.cmd.args:
                    # Extract each argument separately so blocked paths inside
                    # arguments are found — e.g. "/etc/passwd" in "cat /etc/passwd"
                    for arg in stmt.cmd.args:
                        contents.append(_word_value(arg))

    _traverse(ast, visitor, recurse_call_expr_args=True)
    return contents


def _has_cmd_subst(tree: dict[str, Any]) -> bool:
    """Check if the AST contains any command substitution.

    Uses typed AST traversal so that substitutions nested inside quoted
    strings are detected, unlike the raw-JSON visitor which missed them.
    """
    ast = node_from_json(tree)
    if ast is None:
        return False

    def visitor(node: Node) -> None:
        from .ast import CmdSubst, ProcSubst

        if isinstance(node, (CmdSubst, ProcSubst)):
            raise _Found

    try:
        _traverse(ast, visitor, recurse_call_expr_args=True)
    except _Found:
        return True
    return False


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
            - 'subshell': allow/ask/deny policy (default "ask")
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
        "output_redirection": config.get("output_redirection", "ask"),
        "input_redirection": config.get("input_redirection", "ask"),
        "background_execution": config.get("background_execution", "ask"),
        "subshell": config.get("subshell", "ask"),
        "blocked_paths_regex": blocked_patterns,
    }

    # Parse the command to check for command substitution
    try:
        raw_tree = parse(command)
    except ParseError as e:
        _wildcard = config.get("*", "ask")
        return {
            "status": _wildcard,
            "reason": f"ParseError: {e}, defaulting approval decision to bash permission configuration ({_wildcard}).",
        }

    has_subshell = _has_cmd_subst(raw_tree)

    # Extract segments
    segments = parse_segments(command)

    # Handle empty-segment case: if no segments found and allowed_patterns exist,
    # treat as non-matching so wildcard policy applies instead of auto-approving.
    if not segments and allowed_patterns:
        _wildcard = config.get("*", "ask")
        return {
            "status": _wildcard,
            "reason": f"<empty command> produced no parseable segments — defaulting to wildcard policy ({_wildcard}).",
        }

    # Determine the wildcard policy (default action for unmatched commands)
    wildcard = config.get("*", "ask")

    # Evaluate each segment
    overall_status = "allow"
    reasons = []
    any_segment_not_allowed = False

    # Collect all matched patterns across ALL segments (joined into one reason, like TS)

    all_matched_patterns: list[str] = []

    for i, segment in enumerate(segments):
        cmd_name = segment.get("command", "")
        args = segment.get("arguments", [])
        segment_result = {"index": i, "command": cmd_name, "args": args}

        # Check allowed patterns against command name.
        # If arguments contain real values (not "$(...)" placeholders),
        # check full command line so ^ls$ rejects "ls -la".
        if allowed_patterns:
            matched_patterns = []

            has_real_args = any("$(...)" not in a for a in args)
            if has_real_args:
                full_command = cmd_name
                if args:
                    full_command = " ".join([cmd_name, *args])
                for pattern in allowed_patterns:
                    if re.match(pattern, full_command):
                        matched_patterns.append(pattern)
            else:
                for pattern in allowed_patterns:
                    if re.match(pattern, cmd_name):
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
                    f"{pattern}. The tool has not been run."
                )
            else:
                segment_result["blocked"] = False
        else:
            segment_result["blocked"] = False

        segment_results.append(segment_result)

        # Collect matched patterns as approval reasons (only shown when status is allow).
        # NOTE: approval_reason must be built AFTER _walk() so it includes nested command matches.

        # Check redirection rules (from segments — single source of truth, issue #2/#3)
        output_result = _check_segments_output_redirs(segments, rules)

        input_result = _check_segments_input_redirs(segments, rules)

        bg_result = check_background_execution(raw_tree, rules)

        # Deny overrides ask in aggregation (deny anywhere → deny overall)
        if output_result["status"] == "deny" or input_result["status"] == "deny" or bg_result["status"] == "deny":
            overall_status = "deny"
            if output_result["status"] == "deny":
                reasons.append(f"output redirection denied: {output_result['reason']}")
            if input_result["status"] == "deny":
                reasons.append(f"input redirection denied: {input_result['reason']}")
            if bg_result["status"] == "deny":
                reasons.append(f"background execution denied: {bg_result['reason']}")
        elif output_result["status"] == "ask" and overall_status == "allow":
            overall_status = "ask"
            reasons.append(output_result["reason"])
        elif input_result["status"] == "ask" and overall_status == "allow":
            overall_status = "ask"
            reasons.append(input_result["reason"])
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

        # Subshell/command substitution policy check;
        # also check inner content against blocked paths and allowed patterns
        subshell_policy = rules.get("subshell", "ask")
        _subshell_allowed = False
        if has_subshell:
            subshell_contents = _extract_subshell_contents(raw_tree)

            # Check nested commands against blocked paths (already done above, keep it)
            if blocked_patterns and subshell_contents:
                for text in subshell_contents:
                    matched, pattern, value = check_blocked_patterns("", [text], blocked_patterns)
                    if matched:
                        overall_status = "deny"
                        reasons.append(
                            f'Blocked by bash permissions: Argument "{value}" matches blocked path pattern '
                            f"{pattern}. The tool has not been run."
                        )

            # Also validate nested commands against allowed patterns.
            # Check only the command name (first word), matching segment-level
            # allowed-check behavior (which checks command names, not full args).
            if allowed_patterns:
                non_match_names: set[str] = set()
                ast_subshell = node_from_json(raw_tree)
                if ast_subshell is not None:
                    # Recursively walk the AST tracking CmdSubst/ProcSubst nesting depth.
                    def _walk(node: Node, depth: int) -> None:
                        from .ast import CallExpr, CmdSubst, ProcSubst

                        if isinstance(node, (CallExpr,)) and node.args:
                            # Skip top-level CallExpr — already checked as a segment.
                            if depth == 0:
                                pass
                            else:
                                first = _word_value(node.args[0])
                                rest = " ".join(_word_value(a) for a in node.args[1:])
                                full_cmd = first if not rest else f"{first} {rest}"

                                # Check each pattern individually:
                                # - exact-match patterns (no \\s, no .*) with args → check full_cmd
                                # Nested commands with real args check full_cmd only
                                # (name fallback would let "find -exec" match ^find$).
                                matched = False
                                matching_patterns: list[str] = []
                                has_real_args = (
                                    any("$(...)" not in _word_value(a) for a in node.args[1:])
                                    if hasattr(node, "args") and len(node.args) > 1
                                    else False
                                )
                                if has_real_args:
                                    for p in allowed_patterns:
                                        if re.match(p, full_cmd):
                                            matched = True
                                            matching_patterns.append(p)
                                else:
                                    for p in allowed_patterns:
                                        if re.match(p, first):
                                            matched = True
                                            matching_patterns.append(p)
                                if matched:
                                    all_matched_patterns.extend(matching_patterns)
                                else:
                                    non_match_names.add(first if first != full_cmd else full_cmd)

                        # Increment depth when entering a substitution.
                        new_depth = depth + (1 if isinstance(node, (CmdSubst, ProcSubst)) else 0)
                        from .inspect import iter_children

                        for child in iter_children(node, include_call_args=True):
                            _walk(child, new_depth)

                    _walk(ast_subshell, 0)
                    if non_match_names:
                        names_str = ", ".join(f'"{n}"' for n in sorted(non_match_names))
                        reasons.append(f"{names_str} commands inside subshell do not match allowed patterns")
                        if overall_status == "deny":
                            # Already denied by blocked paths check above, keep it
                            pass
                        elif subshell_policy == "allow":
                            overall_status = "ask"  # Validation failed, allow policy → ask for approval
                        elif subshell_policy == "deny":
                            overall_status = "deny"  # Validation failed, deny policy → reject outright
                        else:  # ask
                            overall_status = subshell_policy
            if overall_status == "allow":
                if subshell_policy != "allow":
                    overall_status = subshell_policy
                    reasons.append("subshell or command substitution requires approval")
                else:
                    _subshell_allowed = True
        # If no specific rules matched and nothing else triggered ask/deny, apply wildcard policy
        _redir_matched = output_result["reason"] != "no output redirection"
        _input_matched = input_result["reason"] != "no input redirection"
        _bg_matched = bg_result["reason"] != "no background execution"
        if (
            not allowed_patterns
            and not blocked_patterns
            and overall_status == "allow"
            and wildcard != "allow"
            and not _subshell_allowed
        ):
            if _redir_matched or _input_matched or _bg_matched:
                pass  # specific rules matched; don't override with wildcard
            else:
                overall_status = wildcard
                reasons.append(f"wildcard policy is {wildcard}")
        # Only include approval reasons when status is allow; hide them for ask/deny
        if overall_status == "allow" and all_matched_patterns:
            # Build approval reason from ALL matched patterns (top-level + nested)
            noun = "pattern" if len(all_matched_patterns) == 1 else "patterns"
            approval_reason = f"command matches allowed {noun} {', '.join(all_matched_patterns)}"
            reasons.append(approval_reason)
        if reasons:
            reason_str = "; ".join(r.rstrip(".!? ") for r in reasons)
            if len(reasons) == 1:
                reason_str += "."
        elif all_matched_patterns:
            noun = "pattern" if len(all_matched_patterns) == 1 else "patterns"
            reason_str = f"command matches allowed {noun} {', '.join(all_matched_patterns)}"
        else:
            reason_str = "command matches allowed pattern"
        return {
            "status": overall_status,
            "reason": reason_str,
            "segments": segment_results,
        }
