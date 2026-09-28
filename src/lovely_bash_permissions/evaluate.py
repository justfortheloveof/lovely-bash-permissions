"""
Permission evaluation for bash commands.

This module provides the :func:`evaluate_bash_command` function, which
parses a bash command, extracts command segments, and evaluates each
segment against a permission configuration to determine whether to
allow, ask for approval, or deny the command.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any, Literal

from .ast import CallExpr, CmdSubst, Node, ProcSubst, Subshell
from .converter import node_from_json
from .inspect import _traverse, _word_exec, _word_raw, _word_value, iter_children
from .parser import parse
from .rules import (
    _check_segments_input_redirs,
    _check_segments_output_redirs,
    _compile_pattern,
    check_background_execution,
)
from .segments import parse_segments

#: Regex metacharacters (unescaped) or lone backslashes that mark a pattern
#: body as more than a plain escaped literal - i.e. not a bare-name anchor.
_BARE_NAME_META = re.compile(r"(?<!\\)[()\[\]{}.*+?|^$]|\\(?!\\)")


def _extract_subshell_contents(tree: dict[str, Any]) -> list[str]:
    """Extract literal text values from inside CmdSubst/ProcSubst nodes.

    Uses the typed AST (via :func:`~lovely_bash_permissions.converter.node_from_json`)
    so that substitutions nested inside quoted strings are found -
    unlike the raw-JSON visitor which missed CmdSubst/ProcSubst
    hidden inside DblQuoted/SglQuoted parts.

    Returns:
        List of literal text strings found inside command / process substitutions,
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
                    # arguments are found - e.g. "/etc/passwd" in "cat /etc/passwd"
                    for arg in stmt.cmd.args:
                        raw = _word_value(arg)
                        execd = _word_exec(arg)
                        if raw not in contents:
                            contents.append(raw)
                        if execd != raw and execd not in contents:
                            contents.append(execd)

    _traverse(ast, visitor, recurse_call_expr_args=True)
    return contents


def _heredoc_body_texts(tree: dict[str, Any]) -> list[str]:
    """Extract the literal text of every heredoc body in a raw JSON tree.

    Heredoc bodies (``Redir.Hdoc.Parts``) are fed to the receiving command's
    stdin at runtime. For data-consuming commands (``wc``, ``sort``,
    ``json.tool``) the body is inert text; for interpreters (``python3``,
    ``node``, ``bash``, ``sh``, ...) the body is *source code* that can open
    arbitrary files - e.g. ``open("/etc/passwd").read()``.  The body is
    therefore scanned against ``blocked_cmds_regex`` as raw text, matching
    the tool's conservative "block on mention" precedent for command-line
    arguments (``echo /etc/passwd`` is already denied).

    Command-substitution parts inside the body are excluded here - their
    *inner commands* are scanned separately by the substitution-content pass.

    Redir dicts in the raw JSON carry no "Type" field - heredoc redirections
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


def _subst_flags(tree: dict[str, Any]) -> dict[str, bool]:
    """Detect which of the three substitution/subshell constructs appear.

    Returns ``{"command_substitution": bool, "process_substitution": bool,
    "subshell": bool}`` where the flags mark ``$(...)``/backticks,
    ``<(...)``/``>(...)``, and ``( ... )`` paren groups respectively.
    Uses typed-AST traversal so constructs nested inside quoted strings
    are detected too.
    """
    ast = node_from_json(tree)
    if ast is None:
        return {"command_substitution": False, "process_substitution": False, "subshell": False}

    found = {"command_substitution": False, "process_substitution": False, "subshell": False}

    def visitor(node: Node) -> None:
        if isinstance(node, CmdSubst):
            found["command_substitution"] = True
        elif isinstance(node, ProcSubst):
            found["process_substitution"] = True
        elif isinstance(node, Subshell):
            found["subshell"] = True

    _traverse(ast, visitor, recurse_call_expr_args=True)
    return found


def _has_cmd_subst(tree: dict[str, Any]) -> bool:
    """Check if the AST contains any command or process substitution.

    Retained for backwards compatibility with existing callers; new code
    should use :func:`_subst_flags` and gate each construct on its own key.
    """
    flags = _subst_flags(tree)
    return flags["command_substitution"] or flags["process_substitution"]


def _block_scan_variants(text: str) -> list[str]:
    """Raw text plus a conservative quote/backslash-stripped variant.

    Stripping ``'``, ``"`` and backslashes turns split spellings like
    ``/e"tc"/passwd`` into the executed path so blocked patterns catch
    them; it is a superset (it can over-match, never under-match).
    """
    stripped = re.sub(r"['\"\\]", "", text)
    return [text, stripped] if stripped != text else [text]


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


def _texts_for(name: str, args: list[str], normalized_args: list[str] | None) -> list[str]:
    """Build the ordered candidate texts a command segment is matched against.

    The EXECUTED / quote-normalized join comes first (when *normalized_args*
    is given) so negative lookaheads in guard patterns are evaluated on the
    text bash actually runs; the raw join follows it. A nameless segment
    (a bare assignment or pseudo-command) is joined with a leading space by
    :func:`_command_string`, so that space is stripped from each candidate.

    Returns:
        Deduplicated candidate texts in match-priority order; the raw join
        alone when *normalized_args* is ``None``.
    """
    candidates: list[str] = []
    if normalized_args is not None:
        candidates.append(_command_string(name, normalized_args))
    candidates.append(_command_string(name, args))
    texts: list[str] = []
    for text in candidates:
        if not name and text.startswith(" "):
            text = text[1:]
        if text not in texts:
            texts.append(text)
    return texts


def _match_texts(
    texts: Sequence[str],
    patterns: Sequence[str],
    *,
    opaque_guard: bool = False,
    raw_fallback: Literal["always", "only-if-no-lookahead"] = "always",
    has_opaque: bool = False,
) -> list[tuple[str, str]]:
    """Match *patterns* against *texts* - the single core behind both regex lists.

    Iteration is pattern-major (outer loop over patterns, inner over texts),
    so results come back in pattern order and at most one entry per pattern.
    ``texts[0]`` is the executed / normalized form and is always tried;
    ``texts[1:]`` is the raw form and is tried per *raw_fallback*:

    - ``"always"``: both forms are tried (OR semantics - a hit on either
      counts, which is what the denied direction wants).
    - ``"only-if-no-lookahead"``: the raw form is a fallback only for patterns
      that contain no ``(?!`` guard, because a quote-split spelling can fake
      the text a lookahead scans but cannot change a lookahead's own verdict.

    Args:
        texts: Candidate texts in match-priority order (see :func:`_texts_for`).
        patterns: Regex patterns to try, in list order.
        opaque_guard: Drop matches whose pattern is unsafe to trust when the
            command hides arguments behind ``$(...)`` (see
            :func:`_opaque_match_unreliable`).
        raw_fallback: Whether and when the raw-form texts are tried.
        has_opaque: Whether the command actually holds a ``$(...)`` argument
            (only then can *opaque_guard* fire).

    Returns:
        ``(pattern, text_that_hit)`` pairs in pattern order. Invalid patterns
        are skipped rather than raised, so one bad regex can neither crash
        evaluation nor silently approve a command.
    """
    if not texts:
        return []
    matches: list[tuple[str, str]] = []
    for pattern in patterns:
        try:
            compiled = _compile_pattern(pattern)
        except ValueError:
            continue
        candidates = texts[:1] if raw_fallback == "only-if-no-lookahead" and "(?!" in pattern else texts
        hit = next((text for text in candidates if compiled.search(text)), None)
        if hit is None:
            continue
        # The guard shape's verdict depends on tokens a substitution can hide,
        # so a match here must not stand in for approval.
        if opaque_guard and has_opaque and _opaque_match_unreliable(pattern):
            continue
        matches.append((pattern, hit))
    return matches


def _match_allowed_patterns(
    name: str, args: list[str], allowed_patterns: list[str], normalized_args: list[str] | None = None
) -> list[str]:
    """Return the allowed patterns matched by this command (name + args).

    Thin wrapper over :func:`_match_texts` with approval-shaped settings: the
    executed form is tried first, the raw form only as a fallback for patterns
    carrying no ``(?!`` guard (the only shape a split text can fake), which
    preserves patterns written with explicit quotes.

    Matches are rejected when opaque ``$(...)`` arguments could change the
    pattern's verdict - see :func:`_opaque_match_unreliable`.  Such commands
    are treated as not allowed, requesting approval instead of auto-approving.

    Returns:
        Every matching pattern, in list order.
    """
    has_opaque = any("$(...)" in a for a in args)
    matches = _match_texts(
        _texts_for(name, args, normalized_args),
        allowed_patterns,
        opaque_guard=True,
        raw_fallback="only-if-no-lookahead",
        has_opaque=has_opaque,
    )
    return [pattern for pattern, _text in matches]


def _match_blocked_patterns(
    name: str, args: list[str], blocked_patterns: list[str], normalized_args: list[str] | None = None
) -> tuple[bool, str | None, str | None]:
    """Return whether a joined command line matches blocked patterns.

    Thin wrapper over :func:`_match_texts` with denial-shaped settings: both
    the executed and the raw join are always tried (OR semantics - a hit on
    either denies), and no opaque-argument guard applies because an unsafe
    denial needs none. Invalid patterns never hit (mirrors
    :func:`rules._match_pattern`).

    Returns:
        ``(True, pattern, value)`` for the first hit, where ``value`` is the
        joined line that hit (the normalized form preferred), else
        ``(False, None, None)``.
    """
    matches = _match_texts(_texts_for(name, args, normalized_args), blocked_patterns, raw_fallback="always")
    if not matches:
        return False, None, None
    pattern, text = matches[0]
    return True, pattern, text


def _resolve_level(config: dict[str, Any], key: str) -> Any:  # noqa: ANN401
    """Resolve a policy option against the config wildcard.

    An explicit value wins. Dict-form policies (``output_redirection``,
    ``input_redirection``, ``background_execution``) get their missing ``*``
    injected from the wildcard - the *immediate wildcard parent* for the
    per-kind levels. Otherwise the value inherits the wildcard.
    """
    value = config.get(key)
    if isinstance(value, dict):
        return {**value, "*": value.get("*") or config.get("*", "ask")}
    return value if value is not None else config.get("*", "ask")


def _whole_command_scan_text(command: str) -> str:
    """Return the command text used for the whole-command blocked scan.

    The hook's verdict label (``: '<label>' <emoji> ; <cmd>``) is *not* carved
    out: it is scanned like any other command text. It contains no user payload
    - only the status word and, on an allow, the allow-list entry that matched -
    so scanning it cannot deny a command its own reason describes, and dropping
    the special case keeps the label subject to exactly the same rules as a
    user-written ``:``.
    """
    return command


def _blocked_reason(snippet_text: str, pattern: str) -> str:
    """Build the deny reason for a blocked hit, truncating a long snippet."""
    snippet = snippet_text.strip()
    if len(snippet) > 80:
        snippet = snippet[:77] + "..."
    return f'Blocked by bash permissions: Argument "{snippet}" matches blocked pattern {pattern}. The tool has not been run'


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
            - 'command_substitution': allow/ask/deny policy for $(...) / backticks
            - 'process_substitution': allow/ask/deny policy for <(...) / >(...)
            - 'subshell': allow/ask/deny policy for ( ... ) paren groups
            - 'variable_assignment': allow/ask/deny policy
            - 'allowed_cmds_regex': list of regex patterns for allowed commands
            - 'blocked_cmds_regex': list of regex patterns for blocked commands
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
    blocked_patterns = config.get("blocked_cmds_regex", [])

    rules = {
        "output_redirection": _resolve_level(config, "output_redirection"),
        "input_redirection": _resolve_level(config, "input_redirection"),
        "background_execution": _resolve_level(config, "background_execution"),
        "command_substitution": _resolve_level(config, "command_substitution"),
        "process_substitution": _resolve_level(config, "process_substitution"),
        "subshell": _resolve_level(config, "subshell"),
        "variable_assignment": _resolve_level(config, "variable_assignment"),
        "blocked_cmds_regex": blocked_patterns,
    }

    # Parse the command to check for command substitution.  Any parse or
    # shfmt infrastructure failure raises LovelyDevinPermissionsError; the
    # top-level hook handler maps it to the configurable `error` policy
    # instead of silently falling back to the wildcard (bug #2).
    raw_tree = parse(command)

    # Whole-command blocked scan. The per-segment checks below only ever see a
    # segment's *executed* command line, so a blocked token that never reaches
    # one - an expansion default (`echo ${BAR:-/etc/passwd}`), an array
    # assignment (`A=(/etc/passwd)`), a `[[ -f ... ]]` test, a comment or a
    # quoted mention - would slip through entirely. Matching the raw string as
    # written closes that gap and keeps the established "block on mention"
    # posture. It is purely additive: a hit here only ever forces a deny.
    whole_command_hits: list[tuple[str, str]] = []
    if blocked_patterns:
        whole_command_hits = _match_texts([_whole_command_scan_text(command)], blocked_patterns, raw_fallback="always")

    subst_flags = _subst_flags(raw_tree)
    has_cmd_subst = subst_flags["command_substitution"]
    has_proc_subst = subst_flags["process_substitution"]
    has_paren_subshell = subst_flags["subshell"]

    # Extract segments
    segments = parse_segments(command)

    # Handle empty-segment case: if no segments found, apply wildcard policy.
    # Security scans still run so constructs like `[[ $(cat /etc/passwd) == x ]]`
    # cannot bypass the blocked-path rules just because they produce no exec
    # segments (bug #2).
    if not segments:
        _wildcard = config.get("*", "ask")
        _empty_status: str = "allow"
        _empty_reasons: list[str] = []
        if (has_cmd_subst or has_proc_subst) and blocked_patterns:
            for text in _extract_subshell_contents(raw_tree):
                matched, pattern, value = _match_blocked_patterns("", [text], blocked_patterns)
                if matched:
                    _empty_status = "deny"
                    _empty_reasons.append(
                        f'Blocked by bash permissions: Argument "{value}" matches blocked pattern '
                        f"{pattern}. The tool has not been run"
                    )
        if blocked_patterns:
            for body in _heredoc_body_texts(raw_tree):
                candidates = _block_scan_variants(body)
                for candidate in candidates:
                    matched, pattern, _value = _match_blocked_patterns("", [candidate], blocked_patterns)
                    if matched:
                        snippet = candidate.strip()
                        if len(snippet) > 80:
                            snippet = snippet[:77] + "..."
                        _empty_status = "deny"
                        _empty_reasons.append(
                            f'Blocked by bash permissions: Heredoc body contains "{snippet}" '
                            f"matching blocked pattern {pattern}. The tool has not been run"
                        )
                        break
        for _pattern, _text in whole_command_hits:
            _empty_status = "deny"
            _empty_reasons.append(_blocked_reason(_text, _pattern))
        if _empty_reasons:
            _empty_status = "deny"
            _empty_reason = "; ".join(dict.fromkeys(_empty_reasons))
        elif has_cmd_subst or has_proc_subst:
            # standalone arithmetic like `(( x[$(rm -rf /etc/x)] ))`
            # produces no segments, so the fallback auto-approved it under
            # "*": "allow" even when the substitution policy is "deny". Gate
            # it by the resolved substitution policy; only an explicit
            # "allow" falls through to the wildcard default. An *inherited*
            # allow (key unset under a permissive wildcard) becomes ask: the
            # command produced no segments, so we cannot analyse what runs -
            # default fail-closed.
            _cs_policy = rules["command_substitution"] if has_cmd_subst else rules["process_substitution"]
            _cs_key = "command_substitution" if has_cmd_subst else "process_substitution"
            if _cs_policy == "allow" and _cs_key not in config:
                _cs_policy = "ask"
            if _cs_policy == "allow":
                _empty_status = _wildcard
                _empty_reason = (
                    f"<empty command> produced no parseable segments - defaulting to wildcard policy ({_wildcard})"
                )
            else:
                _empty_status = _cs_policy
                # A `deny` here is an absolute block, so the reason must not
                # claim the user can still approve it at runtime.
                _subst_label = "command substitution" if has_cmd_subst else "process substitution"
                _empty_reason = (
                    f"{_subst_label} denied in config" if _cs_policy == "deny" else f"{_subst_label} requires approval"
                )
        else:
            _empty_status = _wildcard
            _empty_reason = (
                f"<empty command> produced no parseable segments - defaulting to wildcard policy ({_wildcard})"
            )
        return {"status": _empty_status, "reason": _empty_reason, "segments": []}

    # Determine the wildcard policy (default action for unmatched commands)
    wildcard = config.get("*", "ask")

    # Evaluate each segment
    overall_status = "allow"
    reasons = []
    any_segment_not_allowed = False
    variable_assignment_policy = rules.get("variable_assignment", "ask")

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
                    exec_args = [_word_exec(a) for a in node.args[1:]]
                    visited_commands.add(_command_string(name, raw_args))
                    matched = _match_allowed_patterns(name, raw_args, allowed_patterns, exec_args)
                    if matched:
                        all_matched_patterns.extend(matched)
                    elif depth > 0:
                        rest = " ".join(_word_value(a) for a in node.args[1:])
                        full_cmd = name if not rest else f"{name} {rest}"
                        nested_non_match.add(name if name != full_cmd else full_cmd)
                new_depth = depth + (1 if isinstance(node, (CmdSubst, ProcSubst, Subshell)) else 0)
                for child in iter_children(node, include_call_args=True):
                    _walk(child, new_depth)

            _walk(ast_root, 0)

    for i, segment in enumerate(segments):
        cmd_name = segment.get("command", "")
        args = segment.get("arguments", [])
        segment_result = {"index": i, "command": cmd_name, "arguments": args}

        # Handle standalone variable assignments (no command name, only assignments)
        if cmd_name == "" and args:
            if variable_assignment_policy == "allow":
                segment_result["allowed"] = True
                # If variable_assignment is explicitly "allow", don't override with wildcard policy
                if not allowed_patterns:
                    overall_status = "allow"
                    reasons.append(f"variable assignment allowed: {args}")
            elif variable_assignment_policy == "deny":
                segment_result["allowed"] = False
                overall_status = "deny"
                reasons.append(f"variable assignment denied: {args}")
            else:  # ask (default)
                segment_result["allowed"] = False
                overall_status = "ask"
                reasons.append(f"variable assignment requires approval: {args}")
        elif allowed_patterns:
            # Check allowed patterns against command name.
            # If arguments contain real values (not "$(...)" placeholders),
            # check full command line so ^ls$ rejects "ls -la".
            norm_args = segment.get("normalized_arguments", args)
            matched_patterns = _match_allowed_patterns(cmd_name, args, allowed_patterns, norm_args)

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
            # No allow-list configured. A command is approved only by an
            # explicit "*": "allow" wildcard; otherwise it is left to the
            # wildcard (ask/deny) below.
            if wildcard == "allow":
                segment_result["allowed"] = True
            else:
                segment_result["allowed"] = False
                any_segment_not_allowed = True

        # Check blocked patterns. The hook's own inert `:` label is treated like
        # any other command, so it needs `Exec(:)` in the Devin allow list just
        # as a user-written `:` would; the label carries no privilege, because
        # the payload after `;` is scanned per-segment and as a whole command.
        if blocked_patterns:
            norm_args = segment.get("normalized_arguments")
            matched, pattern, value = _match_blocked_patterns(cmd_name, args, blocked_patterns, norm_args)
            if matched:
                segment_result["blocked"] = True
                overall_status = "deny"
                reasons.append(
                    f'Blocked by bash permissions: Argument "{value}" matches blocked pattern '
                    f"{pattern}. The tool has not been run"
                )
            else:
                segment_result["blocked"] = False
        else:
            segment_result["blocked"] = False

        segment_results.append(segment_result)

    # Scan heredoc bodies as raw text against blocked patterns. This catches
    # interpreter-as-code vectors that have no bash-level `$(...)` expansion -
    # e.g. `python3 <<EOF\nopen("/etc/passwd").read()\nEOF` - which would
    # otherwise read a blocked file if the interpreter were allow-listed.
    # Mirrors the "block on mention" precedent already applied to args.
    if blocked_patterns:
        for body in _heredoc_body_texts(raw_tree):
            candidates = _block_scan_variants(body)
            for candidate in candidates:
                matched, pattern, _value = _match_blocked_patterns("", [candidate], blocked_patterns)
                if matched:
                    snippet = candidate.strip()
                    if len(snippet) > 80:
                        snippet = snippet[:77] + "..."
                    overall_status = "deny"
                    reasons.append(
                        f'Blocked by bash permissions: Heredoc body contains "{snippet}" '
                        f"matching blocked pattern {pattern}. The tool has not been run"
                    )
                    break

    # Apply the whole-command blocked scan computed before the segment loop.
    # Done here (not as an early return) so the documented return shape - the
    # `segments` key - is always present, and so a deny recorded below can
    # never overwrite this one.
    if whole_command_hits:
        for _pattern, _text in whole_command_hits:
            overall_status = "deny"
            reasons.append(_blocked_reason(_text, _pattern))

    # Collect matched patterns as approval reasons (only shown when status is allow).
    # NOTE: approval_reason must be built AFTER _walk() so it includes nested command matches.

    # Check redirection rules (from segments - single source of truth, issue #2/#3)
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

    # Commands not approved by an allow-list or by an explicit "*": "allow"
    # wildcard resolve to the wildcard policy (ask/deny).
    if any_segment_not_allowed:
        non_matching = [seg["command"] for seg in segment_results if not seg.get("allowed", True)]
        if non_matching:
            names = [f'"{name}"' for name in non_matching]
            if allowed_patterns:
                if len(non_matching) == 1:
                    reasons.append(f"{names[0]} command does not match allowed patterns")
                else:
                    reasons.append(f"{', '.join(names)} commands do not match allowed patterns")
            elif len(non_matching) == 1:
                reasons.append(f"{names[0]} command is not allowlisted; wildcard policy is {wildcard}")
            else:
                reasons.append(f"{', '.join(names)} commands are not allowlisted; wildcard policy is {wildcard}")
        if overall_status == "allow":
            overall_status = wildcard

    # Command substitution / process substitution policy checks; also check
    # inner content against blocked patterns and allowed patterns.
    if has_cmd_subst or has_proc_subst:
        subshell_contents = _extract_subshell_contents(raw_tree)

        # Check nested commands against blocked patterns (already done above, keep it)
        if blocked_patterns and subshell_contents:
            for text in subshell_contents:
                matched, pattern, value = _match_blocked_patterns("", [text], blocked_patterns)
                if matched:
                    overall_status = "deny"
                    reasons.append(
                        f'Blocked by bash permissions: Argument "{value}" matches blocked pattern '
                        f"{pattern}. The tool has not been run"
                    )

        # Also validate nested commands against allowed patterns.
        # Non-matching commands inside substitutions were collected by the
        # unconditional AST walk above (only depth>0 CallExprs contribute).
        if nested_non_match:
            names_str = ", ".join(f'"{n}"' for n in sorted(nested_non_match))
            reasons.append(f"{names_str} commands inside substitution/subshell do not match allowed patterns")
            _sub_policy = (
                rules.get("command_substitution", "ask") if has_cmd_subst else rules.get("process_substitution", "ask")
            )
            if overall_status == "deny":
                # Already denied by blocked patterns check above, keep it
                pass
            elif _sub_policy == "allow":
                overall_status = "ask"  # Validation failed, allow policy → ask for approval
            elif _sub_policy == "deny":
                overall_status = "deny"  # Validation failed, deny policy → reject outright
                # The block comes from configuration, so say so: the non-match
                # reason above explains *what* was rejected, this explains that
                # no amount of approval at runtime would let it through.
                reasons.append(
                    ("command substitution" if has_cmd_subst else "process substitution") + " denied in config"
                )
            else:  # ask
                overall_status = _sub_policy

    def _construct_policy_verdict(flag: bool, key: str, label: str, current: str) -> tuple[str, str | None]:
        """Gate one construct policy onto an existing verdict.

        ``deny`` is an ABSOLUTE block: it wins over the wildcard, over allow
        patterns, and over any other policy, and it is not overridable at
        runtime - only a config change lifts it.  That is what
        ``variable_assignment`` and the redirection policies already do (see the
        aggregation above).  These construct keys were the holdouts: their gate
        only ran when the verdict was still ``allow``, so under the default
        ``"*": "ask"`` a ``deny`` here was silently inert - the wildcard had
        already spoken and the policy was never consulted.

        ``ask`` keeps its narrower meaning: it only downgrades an otherwise
        ``allow`` verdict, i.e. it prevents auto-approval, and keeps the
        "requires approval" wording because that is still actionable at runtime.
        A verdict that is already ``deny`` is never softened.

        Returns:
            The new status, and the reason to append (or None for no change).
        """
        if not flag or current == "deny":
            return current, None
        pol = rules.get(key, "ask")
        if pol == "deny":
            return "deny", f"{label} denied in config"
        if pol != "allow" and current == "allow":
            return pol, f"{label} requires approval"
        return current, None

    # $(...), <(...) and ( ... ) each gate independently.
    for _flag, _key, _label in (
        (has_cmd_subst, "command_substitution", "command substitution"),
        (has_proc_subst, "process_substitution", "process substitution"),
        # ( ... ) paren-group subshells: inner segments are already scanned
        # above (blocked patterns / allowed patterns); the policy gates the
        # construct itself.
        (has_paren_subshell, "subshell", "subshell (...)"),
    ):
        overall_status, _added_reason = _construct_policy_verdict(_flag, _key, _label, overall_status)
        if _added_reason:
            reasons.append(_added_reason)

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
        reason_str = "allowed by wildcard policy (allow)" if _wp == "allow" else "allowed"
    return {
        "status": overall_status,
        "reason": reason_str,
        "segments": segment_results,
    }
