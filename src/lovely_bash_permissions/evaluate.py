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
from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict

from .ast import CallExpr, CmdSubst, Node, ProcSubst, Subshell
from .converter import node_from_json
from .inspect import _traverse, _word_exec, _word_raw, _word_value, iter_children
from .parser import parse
from .policy import POLICY_KEYS
from .rules import (
    _check_segments_input_redirs,
    _check_segments_output_redirs,
    _compile_pattern,
    check_background_execution,
)
from .segments import Segment, _segments_from_ast

#: Regex metacharacters (unescaped) or lone backslashes that mark a pattern
#: body as more than a plain escaped literal - i.e. not a bare-name anchor.
_BARE_NAME_META = re.compile(r"(?<!\\)[()\[\]{}.*+?|^$]|\\(?!\\)")


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

    status: str = "allow"
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
    return ParsedCommand(raw=raw, tree=tree, segments=[] if tree is None else _segments_from_ast(tree))


def _resolve_rules(config: dict[str, Any], blocked_patterns: list[str]) -> dict[str, Any]:
    """Resolve every policy key against the config wildcard into ``rules``.

    Driven by :data:`policy.POLICY_KEYS`, so a construct the evaluator gates and
    a construct the config accepts cannot drift apart.
    """
    return {
        **{key: _resolve_level(config, key) for key in POLICY_KEYS},
        "blocked_cmds_regex": blocked_patterns,
    }


def _extract_subshell_contents(ast: Node | None) -> list[str]:
    """Extract literal text values from inside CmdSubst/ProcSubst nodes.

    Uses the typed AST so that substitutions nested inside quoted strings are
    found - unlike the raw-JSON visitor which missed CmdSubst/ProcSubst hidden
    inside DblQuoted/SglQuoted parts.

    Returns:
        List of literal text strings found inside command / process substitutions,
        extracted via :func:`~lovely_bash_permissions.inspect._word_value`.
    """
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

    _traverse(ast, visitor, recurse_call_expr_args=True)
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


def _whole_command_hits(command: str, blocked_patterns: list[str]) -> list[tuple[str, str]]:
    """Match the command as written against the blocked patterns.

    The per-segment checks only ever see a segment's *executed* command line, so
    a blocked token that never reaches one - an expansion default
    (``echo ${BAR:-/etc/passwd}``), an array assignment (``A=(/etc/passwd)``), a
    ``[[ -f ... ]]`` test, a comment or a quoted mention - would slip through
    entirely. Matching the raw string as written closes that gap and keeps the
    established "block on mention" posture. It is purely additive: a hit here
    only ever forces a deny.
    """
    if not blocked_patterns:
        return []
    return _match_texts([_whole_command_scan_text(command)], blocked_patterns, raw_fallback="always")


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
            reasons.append(
                f'Blocked by bash permissions: Argument "{value}" matches blocked pattern '
                f"{pattern}. The tool has not been run"
            )
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
                snippet = candidate.strip()
                if len(snippet) > 80:
                    snippet = snippet[:77] + "..."
                reasons.append(
                    f'Blocked by bash permissions: Heredoc body contains "{snippet}" '
                    f"matching blocked pattern {pattern}. The tool has not been run"
                )
                break
    return reasons


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
    wildcard = config.get("*", "ask")

    reasons: list[str] = []
    if (has_cmd_subst or has_proc_subst) and blocked_patterns:
        reasons.extend(_substitution_blocked_reasons(parsed.tree, blocked_patterns))
    if blocked_patterns:
        reasons.extend(_heredoc_blocked_reasons(parsed.raw, blocked_patterns))
    for pattern, text in whole_command_hits:
        reasons.append(_blocked_reason(text, pattern))
    if reasons:
        deduped = list(dict.fromkeys(reasons))
        return {"status": "deny", "reason": "; ".join(deduped), "reasons": deduped, "segments": []}

    empty_reason = f"<empty command> produced no parseable segments - defaulting to wildcard policy ({wildcard})"

    if not (has_cmd_subst or has_proc_subst):
        return {
            "status": wildcard,
            "reason": empty_reason,
            "reasons": [empty_reason],
            "segments": [],
        }

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
        return {
            "status": wildcard,
            "reason": empty_reason,
            "reasons": [empty_reason],
            "segments": [],
        }
    subst_label = "command substitution" if has_cmd_subst else "process substitution"
    # A `deny` here is an absolute block, so the reason must not claim the
    # user can still approve it at runtime.
    reason = f"{subst_label} denied in config" if policy == "deny" else f"{subst_label} requires approval"
    return {
        "status": policy,
        "reason": reason,
        "reasons": [reason],
        "segments": [],
    }


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
            name = _word_value(node.args[0])
            raw_args = [_word_raw(a) for a in node.args[1:]]
            exec_args = [_word_exec(a) for a in node.args[1:]]
            verdict.visited_commands.add(_command_string(name, raw_args))
            matched = _match_allowed_patterns(name, raw_args, allowed_patterns, exec_args)
            if matched:
                verdict.all_matched_patterns.extend(matched)
            elif depth > 0:
                rest = " ".join(_word_value(a) for a in node.args[1:])
                full_cmd = name if not rest else f"{name} {rest}"
                verdict.nested_non_match.add(name if name != full_cmd else full_cmd)
        new_depth = depth + (1 if isinstance(node, (CmdSubst, ProcSubst, Subshell)) else 0)
        for child in iter_children(node, include_call_args=True):
            _walk(child, new_depth)

    _walk(tree, 0)


def _evaluate_one_segment(
    segment: Segment,
    index: int,
    verdict: _Verdict,
    *,
    wildcard: str,
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
        if variable_assignment_policy == "allow":
            result["allowed"] = True
            # If variable_assignment is explicitly "allow", don't override with wildcard policy
            if not allowed_patterns:
                verdict.status = "allow"
                verdict.reasons.append(f"variable assignment allowed: {args}")
        elif variable_assignment_policy == "deny":
            result["allowed"] = False
            verdict.status = "deny"
            verdict.reasons.append(f"variable assignment denied: {args}")
        else:  # ask (default)
            result["allowed"] = False
            verdict.status = "ask"
            verdict.reasons.append(f"variable assignment requires approval: {args}")
    elif allowed_patterns:
        # Check allowed patterns against command name.
        # If arguments contain real values (not "$(...)" placeholders),
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
    if blocked_patterns:
        blocked_norm_args: list[str] | None = segment.get("normalized_arguments")
        matched, pattern, value = _match_blocked_patterns(cmd_name, args, blocked_patterns, blocked_norm_args)
        if matched:
            result["blocked"] = True
            verdict.status = "deny"
            verdict.reasons.append(
                f'Blocked by bash permissions: Argument "{value}" matches blocked pattern '
                f"{pattern}. The tool has not been run"
            )
        else:
            result["blocked"] = False
    else:
        result["blocked"] = False

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
            _check_segments_output_redirs(segments, rules),
            _check_segments_input_redirs(segments, rules),
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
    segment_results: list[SegmentResult], verdict: _Verdict, *, wildcard: str, allowed_patterns: list[str]
) -> None:
    """Resolve segments no allow-list approved to the wildcard policy.

    Commands not approved by an allow-list or by an explicit ``"*": "allow"``
    wildcard resolve to the wildcard policy (ask/deny).
    """
    if not verdict.any_segment_not_allowed:
        return
    non_matching = [seg["command"] for seg in segment_results if not seg.get("allowed", True)]
    if non_matching:
        names = [f'"{name}"' for name in non_matching]
        if allowed_patterns:
            if len(non_matching) == 1:
                verdict.reasons.append(f"{names[0]} command does not match allowed patterns")
            else:
                verdict.reasons.append(f"{', '.join(names)} commands do not match allowed patterns")
        elif len(non_matching) == 1:
            verdict.reasons.append(f"{names[0]} command is not allowlisted; wildcard policy is {wildcard}")
        else:
            verdict.reasons.append(f"{', '.join(names)} commands are not allowlisted; wildcard policy is {wildcard}")
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
    sub_policy = rules.get("command_substitution", "ask") if has_cmd_subst else rules.get("process_substitution", "ask")
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
        verdict.reasons.append(
            ("command substitution" if has_cmd_subst else "process substitution") + " denied in config"
        )
    else:  # ask
        verdict.status = sub_policy


def _construct_policy_verdict(
    flag: bool, key: str, label: str, current: str, rules: dict[str, Any]
) -> tuple[str, str | None]:
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
    for flag, key, label in (
        (flags["command_substitution"], "command_substitution", "command substitution"),
        (flags["process_substitution"], "process_substitution", "process substitution"),
        # ( ... ) paren-group subshells: inner segments are already scanned
        # above (blocked patterns / allowed patterns); the policy gates the
        # construct itself.
        (flags["subshell"], "subshell", "subshell (...)"),
    ):
        verdict.status, added_reason = _construct_policy_verdict(flag, key, label, verdict.status, rules)
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
    if verdict.reasons:
        seen: list[str] = []
        for r in verdict.reasons:
            if r not in seen:
                seen.append(r)
        return seen
    return []


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
    wildcard = config.get("*", "ask")
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
    wildcard = config.get("*", "ask")
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

    _apply_wildcard_resolution(segment_results, verdict, wildcard=wildcard, allowed_patterns=allowed_patterns)

    _apply_substitution_policies(parsed, rules, flags, blocked_patterns, verdict)

    _apply_construct_policies(flags, rules, verdict)

    reasons = _finalize_reasons(verdict)
    return {
        "status": verdict.status,
        "reason": _finalize_reason(verdict, config, reasons),
        "reasons": reasons,
        "segments": segment_results,
    }
