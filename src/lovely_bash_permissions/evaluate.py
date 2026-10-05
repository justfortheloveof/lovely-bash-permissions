"""
Permission evaluation for bash commands.

This module provides the :func:`evaluate_bash_command` function, which
parses a bash command, extracts command segments, and evaluates each
segment against a permission configuration to determine whether to
allow, ask for approval, or deny the command.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, TypedDict

from .ast import CallExpr, CmdSubst, Node, ProcSubst, Subshell
from .converter import node_from_json
from .inspect import iter_children, traverse
from .matching import match_texts
from .parser import parse
from .policy import POLICY_KEYS, Level, resolve_level, wildcard_level
from .rules import (
    check_background_execution,
    check_input_redirections,
    check_output_redirections,
)
from .segments import Segment, segments_from_ast
from .words import CMD_SUBST_PLACEHOLDER, word_exec, word_raw, word_value

#: Human labels for the construct policy keys, as they appear in reasons.
_CONSTRUCT_LABELS: dict[str, str] = {
    "command_substitution": "command substitution",
    "process_substitution": "process substitution",
    "subshell": "subshell (...)",
}

#: The *start* of a shell assignment: an identifier, optionally subscripted and
#: optionally ``+=``, then ``=``. Used to decide which operands of a
#: pseudo-command are assignments, so that ``export FOO=bar echo $(echo hi)``
#: names ``FOO=bar`` and not the two ordinary words after it.
#:
#: Matched with ``.match``, not ``.fullmatch``: this is a prefix test. The value
#: is arbitrary - ``FOO=bar``, ``B=(c)``, ``X=$(ls)`` - so requiring the whole
#: operand to be consumed would match nothing at all and quietly leave the
#: original behaviour in place.
_ASSIGNMENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\[[^\]]*\])?\+?=")


# ---------------------------------------------------------------------------
# Shared per-evaluation state
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ParsedCommand:
    """A command parsed exactly once, in every representation needed.

    The evaluator needs the raw shfmt JSON (for the heredoc-body and
    background-detection walks, which key off fields the typed AST does not
    carry), the typed AST (for the construct/substitution checks and the
    allowed-pattern walk) and the segment list (for the per-segment policy
    loop).  All three come from a single shfmt subprocess and a single
    JSON-to-AST conversion; producing them separately would mean spawning
    shfmt twice and re-converting the tree three times per evaluation.

    Attributes:
        raw: The shfmt JSON tree, exactly as :func:`parse` returned it.
        tree: The converted typed AST, or ``None`` when the converter could
            not produce one (in which case ``segments`` is empty and every
            typed-AST pass is a no-op, since there is no tree to walk).
        segments: Commands extracted from *tree*, in execution order.
    """

    raw: dict[str, Any]
    tree: Node | None
    segments: list[Segment]


class _SegmentResultBase(TypedDict):
    """The always-present part of a per-segment result."""

    index: int
    command: str
    arguments: list[str]


class SegmentResult(_SegmentResultBase, total=False):
    """One entry of the result dict's ``segments`` list.

    ``allowed`` / ``blocked`` are evaluation verdicts, not parser output, so
    they are only present on the paths that actually decided them.
    """

    allowed: bool
    blocked: bool


@dataclass
class _Verdict:
    """Mutable accumulator threaded through the evaluation steps.

    The steps are separated for readability, not for independence: several of
    them append to ``reasons`` and overwrite ``status``, so they must run in
    the order :func:`evaluate_bash_command` runs them in.  The order the
    reasons are appended in is observable - it is the reason string.
    """

    status: Level = "allow"
    reasons: list[str] = field(default_factory=list)
    any_segment_not_allowed: bool = False
    all_matched_patterns: list[str] = field(default_factory=list)
    visited_commands: set[str] = field(default_factory=set)
    nested_non_match: set[str] = field(default_factory=set)


def _parse_command(command: str) -> ParsedCommand:
    """Parse and convert a command once, into every form evaluation needs.

    Any parse or shfmt infrastructure failure raises ``ShfmtError``; the
    top-level hook handler maps it to the configurable ``error`` policy instead
    of silently falling back to the wildcard.
    """
    raw = parse(command)
    tree = node_from_json(raw)
    return ParsedCommand(raw=raw, tree=tree, segments=[] if tree is None else segments_from_ast(tree))


def _resolve_rules(config: dict[str, Any], blocked_patterns: list[str]) -> dict[str, Any]:
    """Resolve every policy key against the config wildcard into ``rules``.

    Driven by :data:`policy.POLICY_KEYS`, so a construct the evaluator gates and
    a construct the config accepts cannot drift apart.
    """
    return {
        **{key: resolve_level(config, key, wildcard_level(config)) for key in POLICY_KEYS},
        "blocked_cmds_regex": blocked_patterns,
    }


def _extract_subshell_contents(ast: Node | None) -> list[str]:
    """Extract literal text values from inside CmdSubst/ProcSubst nodes.

    Uses the typed AST so that substitutions nested inside quoted strings are
    found - unlike the raw-JSON visitor which missed CmdSubst/ProcSubst hidden
    inside DblQuoted/SglQuoted parts.

    Returns:
        List of literal text strings found inside command / process substitutions,
        extracted via :func:`~lovely_bash_permissions.words.word_value`.
    """
    if ast is None:
        return []
    contents: list[str] = []

    def visitor(node: Node) -> None:
        if isinstance(node, (CmdSubst, ProcSubst)):
            for stmt in node.stmts:
                if isinstance(stmt.cmd, CallExpr) and stmt.cmd.args:
                    # Extract each argument separately so blocked paths inside
                    # arguments are found - e.g. "/etc/passwd" in "cat /etc/passwd"
                    for arg in stmt.cmd.args:
                        raw = word_value(arg)
                        execd = word_exec(arg)
                        if raw not in contents:
                            contents.append(raw)
                        if execd != raw and execd not in contents:
                            contents.append(execd)

    traverse(ast, visitor, recurse_call_expr_args=True)
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
            hdoc = node.get("Hdoc")
            if node.get("Op") in ("<<", "<<-") and isinstance(hdoc, dict):
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


def _subst_flags(ast: Node | None) -> dict[str, bool]:
    """Detect which of the three substitution/subshell constructs appear.

    Returns ``{"command_substitution": bool, "process_substitution": bool,
    "subshell": bool}`` where the flags mark ``$(...)``/backticks,
    ``<(...)``/``>(...)``, and ``( ... )`` paren groups respectively.
    Uses typed-AST traversal so constructs nested inside quoted strings
    are detected too.
    """
    found = {"command_substitution": False, "process_substitution": False, "subshell": False}
    if ast is None:
        return found

    def visitor(node: Node) -> None:
        if isinstance(node, CmdSubst):
            found["command_substitution"] = True
        elif isinstance(node, ProcSubst):
            found["process_substitution"] = True
        elif isinstance(node, Subshell):
            found["subshell"] = True

    traverse(ast, visitor, recurse_call_expr_args=True)
    return found


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

    When any argument holds a real value (not a ``$(...)`` placeholder), the
    whole command line is matched; otherwise only the command name is, since
    the arguments are opaque and matching them could only ever be guessing.
    """
    cleaned = [_strip_quotes(a) for a in args]
    if any(CMD_SUBST_PLACEHOLDER not in a for a in cleaned):
        return name if not cleaned else " ".join([name, *cleaned])
    return name


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


def _match_allowed_patterns(
    name: str, args: list[str], allowed_patterns: list[str], normalized_args: list[str] | None = None
) -> list[str]:
    """Return the allowed patterns matched by this command (name + args).

    Thin wrapper over :func:`~.matching.match_texts` with approval-shaped settings: the
    executed form is tried first, the raw form only as a fallback for patterns
    carrying no ``(?!`` guard (the only shape a split text can fake), which
    preserves patterns written with explicit quotes.

    Matches are rejected when opaque ``$(...)`` arguments could change the
    pattern's verdict - see :func:`~.matching.opaque_match_unreliable`.  Such commands
    are treated as not allowed, requesting approval instead of auto-approving.

    Returns:
        Every matching pattern, in list order.
    """
    has_opaque = any(CMD_SUBST_PLACEHOLDER in a for a in args)
    matches = match_texts(
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

    Thin wrapper over :func:`~.matching.match_texts` with denial-shaped settings: both
    the executed and the raw join are always tried (OR semantics - a hit on
    either denies), and no opaque-argument guard applies because an unsafe
    denial needs none. Invalid patterns never hit.

    Returns:
        ``(True, pattern, value)`` for the first hit, where ``value`` is the
        joined line that hit (the normalized form preferred), else
        ``(False, None, None)``.
    """
    matches = match_texts(_texts_for(name, args, normalized_args), blocked_patterns, raw_fallback="always")
    if not matches:
        return False, None, None
    pattern, text = matches[0]
    return True, pattern, text


def _snippet(text: str) -> str:
    """Strip *text* and truncate it to 80 characters for a reason string."""
    snippet = text.strip()
    return snippet if len(snippet) <= 80 else snippet[:77] + "..."


def _argument_blocked_reason(value: str, pattern: str) -> str:
    """The deny reason for a blocked argument, exactly as *value* hit."""
    return (
        f'Blocked by bash permissions: Argument "{value}" matches blocked pattern {pattern}. The tool has not been run'
    )


def _blocked_reason(snippet_text: str, pattern: str) -> str:
    """Build the deny reason for a whole-command blocked hit, truncating a long snippet."""
    return _argument_blocked_reason(_snippet(snippet_text), pattern)


def _whole_command_hits(command: str, blocked_patterns: list[str]) -> list[tuple[str, str]]:
    """Match the command as written against the blocked patterns.

    The per-segment checks only ever see a segment's *executed* command line, so
    a blocked token that never reaches one - an expansion default
    (``echo ${BAR:-/etc/passwd}``), an array assignment (``A=(/etc/passwd)``), a
    ``[[ -f ... ]]`` test, a comment or a quoted mention - would slip through
    entirely. Matching the raw string as written closes that gap and keeps the
    established "block on mention" posture. It is purely additive: a hit here
    only ever forces a deny.

    The hook's verdict label (``: '<label>' <emoji> ; <cmd>``) is *not* carved
    out: it is scanned like any other command text. It contains no user payload
    - only the status word and, on an allow, the allow-list entry that matched -
    so scanning it cannot deny a command its own reason describes, and dropping
    the special case keeps the label subject to exactly the same rules as a
    user-written ``:``.
    """
    if not blocked_patterns:
        return []
    return match_texts([command], blocked_patterns, raw_fallback="always")


def _substitution_blocked_reasons(ast: Node | None, blocked_patterns: list[str]) -> list[str]:
    """Deny reasons for blocked tokens reachable only inside a substitution.

    A command substitution's inner command line never becomes a segment, so
    ``echo $(cat /etc/passwd)`` would otherwise be scanned only as ``echo
    $(...)``. The typed AST is walked for the substitution contents here; the
    empty-segments path and the main path both call this, which is why it is
    one function.
    """
    reasons: list[str] = []
    for text in _extract_subshell_contents(ast):
        matched, pattern, value = _match_blocked_patterns("", [text], blocked_patterns)
        if matched:
            reasons.append(_argument_blocked_reason(str(value), str(pattern)))
    return reasons


def _heredoc_blocked_reasons(raw: dict[str, Any], blocked_patterns: list[str]) -> list[str]:
    """Deny reasons for blocked tokens inside heredoc bodies.

    This catches interpreter-as-code vectors that have no bash-level
    ``$(...)`` expansion - e.g. ``python3 <<EOF\\nopen("/etc/passwd").read()\\nEOF``
    - which would otherwise read a blocked file if the interpreter were
    allow-listed. Mirrors the "block on mention" precedent already applied to
    arguments.

    Takes the *raw* tree on purpose: heredoc bodies live under ``Hdoc``, which
    the raw walk identifies by the ``Op``/``Hdoc`` pair. The typed AST carries
    the body as an ordinary ``Word``, which is indistinguishable from a normal
    redirect target, so converting would cost a walk and buy nothing.

    The empty-segments path and the main path both call this, which is why it
    is one function.
    """
    reasons: list[str] = []
    if not blocked_patterns:
        return reasons
    for body in _heredoc_body_texts(raw):
        for candidate in _block_scan_variants(body):
            matched, pattern, _value = _match_blocked_patterns("", [candidate], blocked_patterns)
            if matched:
                reasons.append(
                    f'Blocked by bash permissions: Heredoc body contains "{_snippet(candidate)}" '
                    f"matching blocked pattern {pattern}. The tool has not been run"
                )
                break
    return reasons


def _result(status: str, reasons: list[str], segments: list[SegmentResult]) -> dict[str, Any]:
    """Assemble the public result dict: ``reason`` is always ``reasons`` joined."""
    return {"status": status, "reason": "; ".join(reasons), "reasons": reasons, "segments": segments}


def _empty_segment_result(
    config: dict[str, Any],
    rules: dict[str, Any],
    parsed: ParsedCommand,
    flags: dict[str, bool],
    whole_command_hits: list[tuple[str, str]],
) -> dict[str, Any]:
    """Produce the finished result for a command that yielded no segments.

    Security scans still run, so constructs like ``[[ $(cat /etc/passwd) == x ]]``
    cannot bypass the blocked-path rules just because they produce no exec
    segments.  A hit on any of them denies outright; only when nothing
    matched does the wildcard / substitution policy decide.

    The fourth return path of :func:`evaluate_bash_command`, alongside
    :func:`_finalize_reasons`. It carries ``reasons`` on every branch for the
    same reason that one does: a verdict a host has to explain cannot leave
    the explanation list empty, and 120 of these rows across the golden corpus
    are ``ask``.
    """
    blocked_patterns: list[str] = config.get("blocked_cmds_regex", [])
    has_cmd_subst = flags["command_substitution"]
    has_proc_subst = flags["process_substitution"]
    wildcard = wildcard_level(config)

    reasons: list[str] = []
    if (has_cmd_subst or has_proc_subst) and blocked_patterns:
        reasons.extend(_substitution_blocked_reasons(parsed.tree, blocked_patterns))
    if blocked_patterns:
        reasons.extend(_heredoc_blocked_reasons(parsed.raw, blocked_patterns))
    for pattern, text in whole_command_hits:
        reasons.append(_blocked_reason(text, pattern))
    if reasons:
        return _result("deny", list(dict.fromkeys(reasons)), [])

    empty_reason = f"<empty command> produced no parseable segments - defaulting to wildcard policy ({wildcard})"

    if not (has_cmd_subst or has_proc_subst):
        return _result(wildcard, [empty_reason], [])

    # standalone arithmetic like `(( x[$(rm -rf /etc/x)] ))` produces no
    # segments, so the fallback auto-approved it under "*": "allow" even when
    # the substitution policy is "deny". Gate it by the resolved substitution
    # policy; only an explicit "allow" falls through to the wildcard default.
    # An *inherited* allow (key unset under a permissive wildcard) becomes ask:
    # the command produced no segments, so we cannot analyse what runs - default
    # fail-closed.
    subst_key = "command_substitution" if has_cmd_subst else "process_substitution"
    policy: str = rules[subst_key]
    if policy == "allow" and subst_key not in config:
        policy = "ask"
    if policy == "allow":
        return _result(wildcard, [empty_reason], [])
    subst_label = _CONSTRUCT_LABELS[subst_key]
    # A `deny` here is an absolute block, so the reason must not claim the
    # user can still approve it at runtime.
    reason = f"{subst_label} denied in config" if policy == "deny" else f"{subst_label} requires approval"
    return _result(policy, [reason], [])


def _collect_allowed_matches(tree: Node | None, allowed_patterns: list[str], verdict: _Verdict) -> None:
    """Match every ``CallExpr`` in the command against the allowed patterns.

    Real commands are counted here, once per ``CallExpr`` occurrence, whether or
    not they also became a segment - so the per-segment loop only has to add
    pseudo-commands (a command name with no ``CallExpr`` behind it, e.g. the
    ``export`` in ``export FOO``).  A non-matching command nested inside a
    substitution or subshell is recorded in ``nested_non_match`` for the
    substitution-policy gate.

    Walks the already-converted typed AST; on the raw JSON this pass would miss
    substitutions nested inside quoted strings.
    """
    if not allowed_patterns or tree is None:
        return

    def _walk(node: Node, depth: int) -> None:
        if isinstance(node, CallExpr) and node.args:
            name = word_value(node.args[0])
            raw_args = [word_raw(a) for a in node.args[1:]]
            exec_args = [word_exec(a) for a in node.args[1:]]
            verdict.visited_commands.add(_command_string(name, raw_args))
            matched = _match_allowed_patterns(name, raw_args, allowed_patterns, exec_args)
            if matched:
                verdict.all_matched_patterns.extend(matched)
            elif depth > 0:
                # The name only: the reason lists commands, and the arguments
                # are already in the prompt's command line.
                verdict.nested_non_match.add(name)
        new_depth = depth + (1 if isinstance(node, (CmdSubst, ProcSubst, Subshell)) else 0)
        for child in iter_children(node, include_call_args=True):
            _walk(child, new_depth)

    _walk(tree, 0)


def _evaluate_one_segment(
    segment: Segment,
    index: int,
    verdict: _Verdict,
    *,
    wildcard: Level,
    allowed_patterns: list[str],
    blocked_patterns: list[str],
    variable_assignment_policy: Any,  # noqa: ANN401
) -> SegmentResult:
    """Decide one segment's ``allowed`` / ``blocked`` flags.

    Returns the segment result (the per-segment half of the result dict) and
    folds its verdict into *verdict*: the status downgrade or denial, the deny
    reason, and - for a pseudo-command the AST walk could not see - the
    allowed patterns it matched.
    """
    cmd_name = segment.get("command", "")
    args = segment.get("arguments", [])
    result: SegmentResult = {"index": index, "command": cmd_name, "arguments": args}

    # Handle standalone variable assignments (no command name, only assignments)
    if cmd_name == "" and args:
        # A pseudo-command's `arguments` are the whole operand list, and only
        # the `NAME=value` entries are assignments. For `export FOO=bar echo
        # $(echo hi)` that is one assignment and two ordinary operands, so
        # naming all three told the user `echo` and `$(...)` were variable
        # assignments. They are the words being exported, not assignments.
        # Filtered only for the message: the policy still gates the whole
        # construct, which is what `export A=1 B` needs.
        assignments = [a for a in args if _ASSIGNMENT_RE.match(a)]
        shown = assignments or args
        if variable_assignment_policy == "allow":
            result["allowed"] = True
            # No verdict is written here, deliberately. `verdict.status` already
            # starts at "allow", so writing it changed nothing except when an
            # earlier segment had already decided the command - and then it
            # undid that decision. `cat /e"tc"/passwd; x=1` denied the blocked
            # read on its first segment, and this line turned the whole command
            # into an allow: the block list had matched, but only against the
            # segment's executed form, so the whole-command scan that runs
            # later (on the text as typed, `/e"tc"/passwd`) missed it, and every
            # later step can only downgrade an allow, never raise one. An
            # allowed assignment is a statement about *this* segment; it has no
            # business restoring a verdict another segment already reached.
            if not allowed_patterns:
                verdict.reasons.append(f"variable assignment allowed: {shown}")
        elif variable_assignment_policy == "deny":
            result["allowed"] = False
            verdict.status = "deny"
            verdict.reasons.append(f"variable assignment denied: {shown}")
        else:  # ask (default)
            result["allowed"] = False
            verdict.status = "ask"
            verdict.reasons.append(f"variable assignment requires approval: {shown}")
    elif allowed_patterns:
        # Check allowed patterns against command name.
        # If arguments contain real values (not CMD_SUBST_PLACEHOLDER placeholders),
        # check full command line so ^ls$ rejects "ls -la".
        norm_args = segment.get("normalized_arguments", args)
        matched_patterns = _match_allowed_patterns(cmd_name, args, allowed_patterns, norm_args)

        if matched_patterns:
            result["allowed"] = True
            # Real commands are already counted by the AST walk (each CallExpr
            # occurrence is matched once); only pseudo-commands (no CallExpr in
            # the AST, e.g. `export FOO` names) are added here.
            if _command_string(cmd_name, args) not in verdict.visited_commands:
                verdict.all_matched_patterns.extend(matched_patterns)
        else:
            result["allowed"] = False
            verdict.any_segment_not_allowed = True
    else:
        # No allow-list configured. A command is approved only by an
        # explicit "*": "allow" wildcard; otherwise it is left to the
        # wildcard (ask/deny) below.
        if wildcard == "allow":
            result["allowed"] = True
        else:
            result["allowed"] = False
            verdict.any_segment_not_allowed = True

    # Check blocked patterns. The hook's own inert `:` label is treated like
    # any other command, so it needs `Exec(:)` in the Devin allow list just
    # as a user-written `:` would; the label carries no privilege, because
    # the payload after `;` is scanned per-segment and as a whole command.
    result["blocked"] = False
    if blocked_patterns:
        blocked_norm_args: list[str] | None = segment.get("normalized_arguments")
        matched, pattern, value = _match_blocked_patterns(cmd_name, args, blocked_patterns, blocked_norm_args)
        if matched:
            result["blocked"] = True
            verdict.status = "deny"
            verdict.reasons.append(_argument_blocked_reason(str(value), str(pattern)))

    return result


def _apply_redirection_policies(
    segments: list[Segment], rules: dict[str, Any], raw: dict[str, Any], verdict: _Verdict
) -> None:
    """Run the output / input / background policies and aggregate them.

    Deny overrides ask in aggregation (deny anywhere → deny overall); ask only
    downgrades an otherwise-allow verdict, and a reason is only shown when its
    own status is the final one.
    """
    results = [
        r
        for r in (
            check_output_redirections(segments, rules),
            check_input_redirections(segments, rules),
            check_background_execution(raw, rules),
        )
        if r.get("matched", True)
    ]
    if any(r["status"] == "deny" for r in results):
        verdict.status = "deny"
    elif any(r["status"] == "ask" for r in results) and verdict.status == "allow":
        verdict.status = "ask"
    for r in results:
        if r["status"] == verdict.status:
            verdict.reasons.append(r["reason"])


def _apply_wildcard_resolution(
    segment_results: list[SegmentResult],
    verdict: _Verdict,
    *,
    wildcard: Level,
    allowed_patterns: list[str],
    segments: list[Segment],
) -> None:
    """Resolve segments no allow-list approved to the wildcard policy.

    Commands not approved by an allow-list or by an explicit ``"*": "allow"``
    wildcard resolve to the wildcard policy (ask/deny).
    """
    if not verdict.any_segment_not_allowed:
        return
    non_matching = [seg for seg in segment_results if not seg.get("allowed", True)]

    # A pseudo-command carries an empty name by design - a bare assignment, a
    # declaration operand, a redirection-only statement - and rendering that name
    # produced `"" , "export" commands do not match allowed patterns` in a
    # message a user reads. Two kinds, and they need different handling:
    #
    # - **with arguments** (a bare assignment): ``_evaluate_one_segment`` has
    #   already given it a specific and better reason -
    #   ``variable assignment requires approval: [...]`` - in every branch of its
    #   policy. Naming it again here is a second, meaningless mention.
    # - **without arguments** (redirection only): no reason of its own exists,
    #   so it has to be described. It is named by what it does, because a
    #   command allow-list genuinely cannot govern it and saying "does not match
    #   allowed patterns" implies a pattern could.
    named = [seg["command"] for seg in non_matching if seg["command"]]
    unnamed = [seg for seg in non_matching if not seg["command"] and not seg["arguments"]]
    if named:
        names = [f'"{name}"' for name in named]
        if allowed_patterns:
            if len(named) == 1:
                verdict.reasons.append(f"{names[0]} command does not match allowed patterns")
            else:
                verdict.reasons.append(f"{', '.join(names)} commands do not match allowed patterns")
        elif len(named) == 1:
            verdict.reasons.append(f"{names[0]} command is not allowlisted; wildcard policy is {wildcard}")
        else:
            verdict.reasons.append(f"{', '.join(names)} commands are not allowlisted; wildcard policy is {wildcard}")
    if unnamed:
        # Redirections live on the parsed segment, not on the result dict, so
        # the two are read together by index. `SegmentResult` deliberately does
        # not carry them: adding a key to the public `segments` output would
        # change every consumer's shape and the golden fingerprint with it.
        targets = sorted(
            {
                str(redir.get("Target"))
                for result in unnamed
                for redir in segments[result["index"]].get("redirections", [])
                if redir.get("Target")
            }
        )
        shown = ", ".join(f'"{target}"' for target in targets) if targets else "an unnamed command"
        if allowed_patterns:
            verdict.reasons.append(
                f"a redirection to {shown} has no command name, so a command allow-list cannot match it"
            )
        else:
            verdict.reasons.append(f"a redirection to {shown} produced no command; wildcard policy is {wildcard}")
    if verdict.status == "allow":
        verdict.status = wildcard


def _apply_substitution_policies(
    parsed: ParsedCommand,
    rules: dict[str, Any],
    flags: dict[str, bool],
    blocked_patterns: list[str],
    verdict: _Verdict,
) -> None:
    """Gate the command/process substitution policies onto the verdict.

    Also scans the substitution *contents* against the blocked patterns, and
    reports commands nested inside a substitution that the allow-list did not
    match - the non-match itself was already recorded by the AST walk (only
    depth > 0 CallExprs contribute).
    """
    has_cmd_subst = flags["command_substitution"]
    has_proc_subst = flags["process_substitution"]
    if not (has_cmd_subst or has_proc_subst):
        return

    if blocked_patterns:
        for reason in _substitution_blocked_reasons(parsed.tree, blocked_patterns):
            verdict.status = "deny"
            verdict.reasons.append(reason)

    if not verdict.nested_non_match:
        return
    names_str = ", ".join(f'"{n}"' for n in sorted(verdict.nested_non_match))
    verdict.reasons.append(f"{names_str} commands inside substitution/subshell do not match allowed patterns")
    subst_key = "command_substitution" if has_cmd_subst else "process_substitution"
    sub_policy = rules.get(subst_key, "ask")
    if verdict.status == "deny":
        # Already denied by blocked patterns check above, keep it
        pass
    elif sub_policy == "allow":
        verdict.status = "ask"  # Validation failed, allow policy → ask for approval
    elif sub_policy == "deny":
        verdict.status = "deny"  # Validation failed, deny policy → reject outright
        # The block comes from configuration, so say so: the non-match reason
        # above explains *what* was rejected, this explains that no amount of
        # approval at runtime would let it through.
        verdict.reasons.append(f"{_CONSTRUCT_LABELS[subst_key]} denied in config")
    else:  # ask
        verdict.status = sub_policy


def _construct_policy_verdict(
    flag: bool, key: str, label: str, current: Level, rules: dict[str, Any]
) -> tuple[Level, str | None]:
    """Gate one construct policy onto an existing verdict.

    ``deny`` is an ABSOLUTE block: it wins over the wildcard, over allow
    patterns, and over any other policy, and it is not overridable at
    runtime - only a config change lifts it.  That is what
    ``variable_assignment`` and the redirection policies already do (see
    :func:`_apply_redirection_policies`).  These construct keys were the
    holdouts: their gate only ran when the verdict was still ``allow``, so
    under the default ``"*": "ask"`` a ``deny`` here was silently inert - the
    wildcard had already spoken and the policy was never consulted.

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


def _apply_construct_policies(flags: dict[str, bool], rules: dict[str, Any], verdict: _Verdict) -> None:
    """Gate ``$(...)``, ``<(...)`` and ``( ... )`` independently."""
    # ( ... ) paren-group subshells: inner segments are already scanned above
    # (blocked patterns / allowed patterns); the policy gates the construct itself.
    for key, label in _CONSTRUCT_LABELS.items():
        verdict.status, added_reason = _construct_policy_verdict(flags[key], key, label, verdict.status, rules)
        if added_reason:
            verdict.reasons.append(added_reason)


def _finalize_reasons(verdict: _Verdict) -> list[str]:
    """The de-duplicated reasons, in append order, or nothing to say.

    Returns a *list*, and the two fallback shapes below are exactly the cases
    where it is empty: an allow that matched patterns the verdict did not
    otherwise have anything to say about, and an allow decided by the wildcard
    alone. Both produce a ``reason`` string; neither produces reasons to show.

    An empty list therefore means "allow, nothing to explain", never "verdict
    reached, explanation lost" - no ``ask`` or ``deny`` reaches the fallbacks,
    because a non-allow verdict always carries the reason that produced it.
    """
    if verdict.status == "allow" and verdict.all_matched_patterns:
        # Build approval reason from ALL matched patterns (top-level + nested)
        noun = "pattern" if len(verdict.all_matched_patterns) == 1 else "patterns"
        verdict.reasons.append(f"command matches allowed {noun}: {', '.join(verdict.all_matched_patterns)}")
    return list(dict.fromkeys(verdict.reasons))


def _finalize_reason(verdict: _Verdict, config: dict[str, Any], reasons: list[str]) -> str:
    """Assemble the human-readable reason from an already-finalized reason list.

    Approval reasons are only included when the status is ``allow``; when there
    is nothing to say at all, the verdict falls back to describing the pattern
    or the wildcard that allowed it.
    """
    if reasons:
        return "; ".join(reasons)
    if verdict.all_matched_patterns:
        noun = "pattern" if len(verdict.all_matched_patterns) == 1 else "patterns"
        return f"command matches allowed {noun}: {', '.join(verdict.all_matched_patterns)}"
    wildcard = wildcard_level(config)
    return "allowed by wildcard policy (allow)" if wildcard == "allow" else "allowed"


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
            - 'reason': human-readable explanation, the reasons joined on "; "
            - 'reasons': the same explanations as a list, de-duplicated in
              append order. A consumer that renders them must not re-split
              'reason' on "; ": most reasons contain a semicolon themselves,
              and a one-element list like ['"ls" command is not allowlisted;
              wildcard policy is ask'] would tear into two bullets. Empty only
              when the verdict is an 'allow' with nothing to explain - a
              matched pattern or the wildcard, see _finalize_reasons - and
              never for an 'ask' or 'deny'.
            - 'segments': list of per-segment results, each with 'command',
              'arguments', 'allowed', 'blocked' (allowed/blocked are
              evaluate-added metadata, absent from parse_segments output)

    Raises:
        ShfmtError: If the command cannot be parsed or shfmt fails.  The
            caller (hook) maps this to the ``error`` policy.
    """
    allowed_patterns = config.get("allowed_cmds_regex", [])
    blocked_patterns = config.get("blocked_cmds_regex", [])
    rules = _resolve_rules(config, blocked_patterns)

    # One parse, one conversion, one segment extraction - shared by every pass
    # below.  Any parse or shfmt infrastructure failure raises ShfmtError; the
    # top-level hook handler maps it to the configurable `error` policy instead
    # of silently falling back to the wildcard.
    parsed = _parse_command(command)

    # Whole-command blocked scan, computed before the segment loop but applied
    # after it, so the documented return shape - the `segments` key - is always
    # present and a deny recorded later can never overwrite this one.
    whole_command_hits = _whole_command_hits(command, blocked_patterns)

    flags = _subst_flags(parsed.tree)
    segments = parsed.segments

    # Handle empty-segment case: if no segments found, apply wildcard policy.
    if not segments:
        return _empty_segment_result(config, rules, parsed, flags, whole_command_hits)

    # Determine the wildcard policy (default action for unmatched commands)
    wildcard = wildcard_level(config)
    verdict = _Verdict()

    # Collect all matched patterns across ALL segments (joined into one reason, like TS)
    _collect_allowed_matches(parsed.tree, allowed_patterns, verdict)

    segment_results = [
        _evaluate_one_segment(
            segment,
            i,
            verdict,
            wildcard=wildcard,
            allowed_patterns=allowed_patterns,
            blocked_patterns=blocked_patterns,
            variable_assignment_policy=rules.get("variable_assignment", "ask"),
        )
        for i, segment in enumerate(segments)
    ]

    # Scan heredoc bodies as raw text against blocked patterns.
    if blocked_patterns:
        for reason in _heredoc_blocked_reasons(parsed.raw, blocked_patterns):
            verdict.status = "deny"
            verdict.reasons.append(reason)

    for pattern, text in whole_command_hits:
        verdict.status = "deny"
        verdict.reasons.append(_blocked_reason(text, pattern))

    # Redirection policy reads the segments, which already cover nested redirections.
    _apply_redirection_policies(segments, rules, parsed.raw, verdict)

    _apply_wildcard_resolution(
        segment_results, verdict, wildcard=wildcard, allowed_patterns=allowed_patterns, segments=segments
    )

    _apply_substitution_policies(parsed, rules, flags, blocked_patterns, verdict)

    _apply_construct_policies(flags, rules, verdict)

    reasons = _finalize_reasons(verdict)
    result = _result(verdict.status, reasons, segment_results)
    result["reason"] = _finalize_reason(verdict, config, reasons)
    return result
