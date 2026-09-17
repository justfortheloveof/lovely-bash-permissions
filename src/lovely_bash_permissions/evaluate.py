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

from .ast import CallExpr, CmdSubst, Node, ProcSubst
from .converter import node_from_json
from .inspect import _traverse, _word_raw, _word_value, iter_children
from .parser import parse
from .rules import (
    _check_segments_input_redirs,
    _check_segments_output_redirs,
    check_background_execution,
    check_blocked_patterns,
)
from .segments import parse_segments


class _Found(Exception):
    """Raised to short-circuit traversal when a match is found."""


#: Regex metacharacters (unescaped) or lone backslashes that mark a pattern
#: body as more than a plain escaped literal — i.e. not a bare-name anchor.
_BARE_NAME_META = re.compile(r"(?<!\\)[()\[\]{}.*+?|^$]|\\(?!\\)")


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


def _heredoc_body_texts(tree: dict[str, Any]) -> list[str]:
    """Extract the literal text of every heredoc body in a raw JSON tree.

    Heredoc bodies (``Redir.Hdoc.Parts``) are fed to the receiving command's
    stdin at runtime. For data-consuming commands (``wc``, ``sort``,
    ``json.tool``) the body is inert text; for interpreters (``python3``,
    ``node``, ``bash``, ``sh``, ...) the body is *source code* that can open
    arbitrary files — e.g. ``open("/etc/passwd").read()``.  The body is
    therefore scanned against ``blocked_paths_regex`` as raw text, matching
    the tool's conservative "block on mention" precedent for command-line
    arguments (``echo /etc/passwd`` is already denied).

    Command-substitution parts inside the body are excluded here — their
    *inner commands* are scanned separately by the subshell-content pass.

    Redir dicts in the raw JSON carry no "Type" field — heredoc redirections
    are identified by their ``Op`` (``<<`` / ``<<-``) and ``Hdoc`` keys.

    Returns:
        List of heredoc body text strings (one per ``<<`` / ``<<-`` redir).
    """
    texts: list[str] = []

    def _walk(node: object) -> None:
        if isinstance(node, dict):
            if node.get("Op") in ("<<", "<<-") and isinstance(node.get("Hdoc"), dict):
                hdoc = node.get("Hdoc")
                assert isinstance(hdoc, dict)
                parts = hdoc.get("Parts", [])
                body = "".join(
                    str(p.get("Value", "")) for p in parts if isinstance(p, dict) and isinstance(p.get("Value"), str)
                )
                if body:
                    texts.append(body)
            for value in node.values():
                _walk(value)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(tree)
    return texts


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


def _strip_quotes(s: str) -> str:
    """Strip matching outer quotes from a string.

    Bash treats ``echo 'hello'`` and ``echo hello`` identically from a
    security perspective.  Stripping quotes before pattern matching
    ensures that negative-lookahead patterns (e.g.
    ``^sort(?!\\s+(-o|--output)\\b).*$``) match correctly even when
    the argument is quoted.
    """
    if len(s) >= 2 and s[0] in ("'", '"') and s[-1] == s[0]:
        return s[1:-1]
    return s


def _command_string(name: str, args: list[str]) -> str:
    """Build the full command string used for allowed-pattern matching.

    Mirrors the historical segment-loop semantics: when any argument holds a
    real value (not a ``$(...)`` placeholder), the whole command line is
    matched; otherwise only the command name is.
    """
    cleaned = [_strip_quotes(a) for a in args]
    if any("$(...)" not in a for a in cleaned):
        return name if not cleaned else " ".join([name, *cleaned])
    return name


#: Raw first-argument prefixes emitted by the hook for its own ``:`` no-op label.
#: The bare ``:`` builtin ignores its arguments, so a matching segment carries
#: no behavior — it is recognized (not "approved") so re-evaluated rewrites do
#: not spuriously ask. Uses the raw (quote-preserving) argument form so the
#: label's literal quoting is honored regardless of ``_strip_quotes``.
_HOOK_LABEL_ARG_PREFIXES = ("'[♡ perms: ", '"[♡ perms: ')


def _is_hook_label_segment(cmd_name: str, args: list[str]) -> bool:
    """True when the segment is the hook's own inert ``:`` label wrapper.

    The hook wraps approved/asked/blocked commands as
    ``: '<label>' <emoji> ; <cmd>``. When Devin feeds that rewritten command
    back through evaluation, the ``:`` wrapper must not be flagged as an
    unmatched command. It is exempted from the allowed-pattern check; the
    payload command(s) after ``;`` are still evaluated normally, so a forged
    label cannot smuggle an unauthorized command past the rules.
    """
    return cmd_name == ":" and bool(args) and args[0].startswith(_HOOK_LABEL_ARG_PREFIXES)


def _opaque_match_unreliable(pattern: str) -> bool:
    """True when an opaque ``$(...)`` argument can hide the token a pattern
    constrains, making a literal match on the placeholder unsafe to approve.

    Two pattern shapes are affected: line-spanning negative lookaheads
    (e.g. ``^find(?!.*\\s-(exec|delete|ok)...)``, whose ``(?!)`` scans the
    whole command line and cannot see tokens produced at runtime by a
    substitution) and bare-name anchors such as ``^true$`` (which accept no
    arguments, so a command whose argument list is hidden entirely behind
    ``$(...)`` must not be approved against them).
    """
    # Line-spanning negative lookahead: the guard scans the whole command
    # line, so a substitute token never appears in the matched string.
    if "(?!" in pattern:
        return True
    # Bare-name anchor (e.g. ^name$ from allowed_cmds_regex): accept no
    # arguments, so any argument hidden behind $(...) invalidates the match.
    # The body must be plain escaped text with no regex metacharacters.
    body = pattern[1:-1] if pattern.startswith("^") and pattern.endswith("$") else None
    if body is None:
        return False
    return not _BARE_NAME_META.search(body) if body else False


def _match_allowed_patterns(name: str, args: list[str], allowed_patterns: list[str]) -> list[str]:
    """Return the allowed patterns matched by this command (name + args).

    Matches are rejected when opaque ``$(...)`` arguments could change the
    pattern's verdict — see :func:`_opaque_match_unreliable`.  Such commands
    are treated as not allowed, requesting approval instead of auto-approving.
    """
    full = _command_string(name, args)
    has_opaque = any("$(...)" in a for a in args)
    matched: list[str] = []
    for pattern in allowed_patterns:
        if not re.search(pattern, full):
            continue
        if has_opaque and _opaque_match_unreliable(pattern):
            continue
        matched.append(pattern)
    return matched


def _resolve_level(config: dict[str, Any], key: str) -> Any:  # noqa: ANN401
    """Resolve a policy option against the config wildcard.

    An explicit value wins. Dict-form policies (``output_redirection``,
    ``input_redirection``, ``background_execution``) get their missing ``*``
    injected from the wildcard — the *immediate wildcard parent* for the
    per-kind levels. Otherwise the value inherits the wildcard.
    """
    value = config.get(key)
    if isinstance(value, dict):
        return {**value, "*": value.get("*") or config.get("*", "ask")}
    return value if value is not None else config.get("*", "ask")


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
            - 'output_redirection': allow/ask/deny policy
            - 'input_redirection': allow/ask/deny policy
            - 'background_execution': allow/ask/deny policy
            - 'subshell': allow/ask/deny policy
            - 'variable_assignment': allow/ask/deny policy
            - 'allowed_cmds_regex': list of regex patterns for allowed commands
            - 'blocked_paths_regex': list of regex patterns for blocked paths
            - '*': wildcard policy; any option omitted above inherits it
              (default "ask")

    Returns:
        dict with keys:
            - 'status': 'allow', 'ask', or 'deny'
            - 'reason': human-readable explanation
            - 'segments': list of per-segment results, each with 'command',
              'arguments', 'allowed', 'blocked' (allowed/blocked are
              evaluate-added metadata, absent from parse_segments output)

    Raises:
        LovelyDevinPermissionsError: If the command cannot be parsed or shfmt
            fails.  The caller (hook) maps this to the ``error`` policy.
    """
    # Extract rules from config
    allowed_patterns = config.get("allowed_cmds_regex", [])
    blocked_patterns = config.get("blocked_paths_regex", [])

    rules = {
        "output_redirection": _resolve_level(config, "output_redirection"),
        "input_redirection": _resolve_level(config, "input_redirection"),
        "background_execution": _resolve_level(config, "background_execution"),
        "subshell": _resolve_level(config, "subshell"),
        "variable_assignment": _resolve_level(config, "variable_assignment"),
        "blocked_paths_regex": blocked_patterns,
    }

    # Parse the command to check for command substitution.  Any parse or
    # shfmt infrastructure failure raises LovelyDevinPermissionsError; the
    # top-level hook handler maps it to the configurable `error` policy
    # instead of silently falling back to the wildcard (bug #2).
    raw_tree = parse(command)

    has_subshell = _has_cmd_subst(raw_tree)

    # Extract segments
    segments = parse_segments(command)

    # Handle empty-segment case: if no segments found, apply wildcard policy.
    if not segments:
        _wildcard = config.get("*", "ask")
        if not allowed_patterns and not blocked_patterns:
            _wildcard = "allow"
        return {
            "status": _wildcard,
            "reason": f"<empty command> produced no parseable segments — defaulting to wildcard policy ({_wildcard})",
        }

    # Determine the wildcard policy (default action for unmatched commands)
    wildcard = config.get("*", "ask")

    # Evaluate each segment
    overall_status = "allow"
    reasons = []
    any_segment_not_allowed = False
    variable_assignment_policy = rules.get("variable_assignment", "ask")
    _va_segment_evaluated = False

    # Default values for redirection results (initialized before loop so they're always defined).
    output_result: dict[str, Any] = {"status": "allow", "matched": False, "reason": "no output redirection"}
    input_result: dict[str, Any] = {"status": "allow", "matched": False, "reason": "no input redirection"}
    bg_result: dict[str, Any] = {"status": "allow", "matched": False, "reason": "no background execution"}

    # Collect all matched patterns across ALL segments (joined into one reason, like TS)

    all_matched_patterns: list[str] = []
    visited_commands: set[str] = set()
    nested_non_match: set[str] = set()
    segment_results: list[dict[str, Any]] = []

    if allowed_patterns:
        ast_root = node_from_json(raw_tree)
        if ast_root is not None:

            def _walk(node: Node, depth: int) -> None:
                if isinstance(node, CallExpr) and node.args:
                    name = _word_value(node.args[0])
                    raw_args = [_word_raw(a) for a in node.args[1:]]
                    visited_commands.add(_command_string(name, raw_args))
                    matched = _match_allowed_patterns(name, raw_args, allowed_patterns)
                    if matched:
                        all_matched_patterns.extend(matched)
                    elif depth > 0:
                        rest = " ".join(_word_value(a) for a in node.args[1:])
                        full_cmd = name if not rest else f"{name} {rest}"
                        nested_non_match.add(name if name != full_cmd else full_cmd)
                new_depth = depth + (1 if isinstance(node, (CmdSubst, ProcSubst)) else 0)
                for child in iter_children(node, include_call_args=True):
                    _walk(child, new_depth)

            _walk(ast_root, 0)

    for i, segment in enumerate(segments):
        cmd_name = segment.get("command", "")
        args = segment.get("arguments", [])
        segment_result = {"index": i, "command": cmd_name, "arguments": args}

        # Handle standalone variable assignments (no command name, only assignments)
        if cmd_name == "" and args:
            _va_segment_evaluated = True
            if variable_assignment_policy == "allow":
                segment_result["allowed"] = True
                # If variable_assignment is explicitly "allow", don't override with wildcard policy
                if not allowed_patterns:
                    overall_status = "allow"
            elif variable_assignment_policy == "deny":
                segment_result["allowed"] = False
                overall_status = "deny"
                reasons.append(f"variable assignment denied: {args}")
            else:  # ask (default)
                segment_result["allowed"] = False
                overall_status = "ask"
                reasons.append(f"variable assignment requires approval: {args}")
        elif _is_hook_label_segment(cmd_name, args):
            # The hook's own `:` no-op label wrapper — inert (the `:` builtin
            # ignores its args) and exempted from the allowed-pattern check so
            # re-evaluated rewrites don't spuriously ask. Payload segments are
            # still evaluated normally below.
            segment_result["allowed"] = True
        elif allowed_patterns:
            # Check allowed patterns against command name.
            # If arguments contain real values (not "$(...)" placeholders),
            # check full command line so ^ls$ rejects "ls -la".
            matched_patterns = _match_allowed_patterns(cmd_name, args, allowed_patterns)

            if matched_patterns:
                segment_result["allowed"] = True
                # Real commands are already counted by the AST walk above (each
                # CallExpr occurrence is matched once); only pseudo-commands
                # (no CallExpr in the AST, e.g. `export FOO` names) are added here.
                if _command_string(cmd_name, args) not in visited_commands:
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
                    f"{pattern}. The tool has not been run"
                )
            else:
                segment_result["blocked"] = False
        else:
            segment_result["blocked"] = False

        segment_results.append(segment_result)

    # Scan heredoc bodies as raw text against blocked paths. This catches
    # interpreter-as-code vectors that have no bash-level `$(...)` expansion —
    # e.g. `python3 <<EOF\nopen("/etc/passwd").read()\nEOF` — which would
    # otherwise read a blocked file if the interpreter were allow-listed.
    # Mirrors the "block on mention" precedent already applied to args.
    if blocked_patterns:
        for body in _heredoc_body_texts(raw_tree):
            # Check the whole body and each non-empty line, so end-anchored
            # patterns (e.g. `\.env$`) match a path on its own line.
            candidates = [body] + [ln.strip() for ln in body.splitlines() if ln.strip()]
            for candidate in candidates:
                matched, pattern, _value = check_blocked_patterns("", [candidate], blocked_patterns)
                if matched:
                    snippet = candidate.strip()
                    if len(snippet) > 80:
                        snippet = snippet[:77] + "..."
                    overall_status = "deny"
                    reasons.append(
                        f'Blocked by bash permissions: Heredoc body contains "{snippet}" '
                        f"matching blocked path pattern {pattern}. The tool has not been run"
                    )
                    break

    # Collect matched patterns as approval reasons (only shown when status is allow).
    # NOTE: approval_reason must be built AFTER _walk() so it includes nested command matches.

    # Check redirection rules (from segments — single source of truth, issue #2/#3)
    output_result = _check_segments_output_redirs(segments, rules)

    input_result = _check_segments_input_redirs(segments, rules)

    bg_result = check_background_execution(raw_tree, rules)

    # Deny overrides ask in aggregation (deny anywhere → deny overall)
    _redir_results = [r for r in (output_result, input_result, bg_result) if r.get("matched", True)]
    if any(r["status"] == "deny" for r in _redir_results):
        overall_status = "deny"
    elif any(r["status"] == "ask" for r in _redir_results) and overall_status == "allow":
        overall_status = "ask"
    for _r in _redir_results:
        if _r["status"] == overall_status:
            reasons.append(_r["reason"])

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
                        f"{pattern}. The tool has not been run"
                    )

        # Also validate nested commands against allowed patterns.
        # Non-matching commands inside substitutions were collected by the
        # unconditional AST walk above (only depth>0 CallExprs contribute).
        if nested_non_match:
            names_str = ", ".join(f'"{n}"' for n in sorted(nested_non_match))
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
    # But don't override variable_assignment decisions (variable_assignment is more specific)
    _redir_matched = output_result.get("matched", True)
    _input_matched = input_result.get("matched", True)
    _bg_matched = bg_result.get("matched", True)
    _va_applied = _va_segment_evaluated
    if (
        not allowed_patterns
        and not blocked_patterns
        and overall_status == "allow"
        and wildcard != "allow"
        and not _subshell_allowed
        and not _va_applied
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
        approval_reason = f"command matches allowed {noun}: {', '.join(all_matched_patterns)}"
        reasons.append(approval_reason)
    if reasons:
        seen: list[str] = []
        for r in reasons:
            if r not in seen:
                seen.append(r)
        reason_str = "; ".join(seen)
    elif all_matched_patterns:
        noun = "pattern" if len(all_matched_patterns) == 1 else "patterns"
        reason_str = f"command matches allowed {noun}: {', '.join(all_matched_patterns)}"
    else:
        _wp = config.get("*", "ask")
        reason_str = f"allowed by wildcard policy ({_wp})"
    return {
        "status": overall_status,
        "reason": reason_str,
        "segments": segment_results,
    }
