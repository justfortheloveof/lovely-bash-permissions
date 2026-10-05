"""
Permission rules engine.

This module provides functions for evaluating permission rules
against bash command segments.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from typing import Any, Literal, TypedDict

from .matching import first_match
from .policy import Level, wildcard_level
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


class _PolicyResultBase(TypedDict):
    status: Level
    reason: str


class PolicyResult(_PolicyResultBase, total=False):
    """The outcome of one construct check (output, input, background).

    ``matched`` is present, and ``False``, only when the construct does not
    occur at all; the evaluator drops those results before aggregating.
    """

    matched: bool


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


def _blocked_target_result(targets: Sequence[str], rules: dict[str, Any]) -> PolicyResult | None:
    """Deny when any redirect target matches a blocked pattern.

    A security check, so it applies whatever the redirection policy says.
    """
    for target in targets:
        pattern = first_match(target, rules.get("blocked_cmds_regex", []))
        if pattern is not None:
            return {"status": "deny", "reason": f'Redirect target "{target}" matches blocked pattern {pattern}'}
    return None


def _redirection_result(direction: Literal["output", "input"], level: object, targets: Sequence[str]) -> PolicyResult:
    """The verdict and reason for a resolved redirection level.

    Anything that is neither ``allow`` nor ``ask`` denies.
    """
    preposition = "to" if direction == "output" else "from"
    if level == "allow":
        return {"status": "allow", "reason": f"{direction} redirection allowed {preposition} {', '.join(targets)}"}
    if level == "ask":
        return {"status": "ask", "reason": f"{direction} redirection requires approval"}
    return {"status": "deny", "reason": f"{direction} redirection denied {preposition} {', '.join(targets)}"}


def _unique_redirections(segments: list[Segment], ops: Collection[str], *, by_fd: bool) -> list[SegmentRedirection]:
    """The redirections among *segments* whose operator is in *ops*, de-duplicated.

    Compound-command redirections (while/until/if/``{ }`` group) are attributed
    to every inner segment, so the same redirection appears once per segment.
    Deduped by ``(op, target)``, plus the fd when *by_fd* - output keeps
    distinct descriptors apart. The segment producers serialize the fd as a
    str (``""`` when absent, ``"2"`` for ``2>``), and that scalar is the key.
    """
    unique: list[SegmentRedirection] = []
    seen: set[tuple[str, str, str]] = set()
    for seg in segments:
        for r in seg.get("redirections") or []:
            if r.get("Op") not in ops:
                continue
            fd = r.get("N", {}).get("Value", "") if by_fd else ""
            key = (r.get("Op", ""), fd, _redir_target(r))
            if key not in seen:
                seen.add(key)
                unique.append(r)
    return unique


def _command_names_in(node: dict[str, Any]) -> list[str]:
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
            results.extend(_command_names_in(value))
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    results.extend(_command_names_in(item))

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
    falling back to wildcard "*".  Deny takes priority over ask, and ask
    over allow.

    **Anything that is not an ``allow`` denies.** This used to read
    ``deny -> ask -> else allow``, which made every level it did not
    recognise resolve to ``allow`` - including ``"block"``, the word Devin's
    own wire protocol uses for a refusal, and including a level arriving from
    an unvalidated config at all.  That is the one resolver in the package
    that failed open: its three siblings (:func:`_redirection_result` for the
    plain form, :func:`check_input_redirections`,
    :func:`check_background_execution`) all end in ``deny``, and this one sat
    next to them disagreeing.  The schema rejects a bad level before either
    host evaluates, but this function is reachable from
    :func:`lovely_bash_permissions.evaluate.evaluate_bash_command`, which is a
    documented public entry point that takes an unvalidated config dict.

    The precedence is unchanged for the three real levels: a kind that denies
    still wins over a kind that asks, and a kind that asks still wins over a
    kind that allows.

    Args:
        kinds: List of redirection kind strings from classify_output_redirection.
        policy: Dict-form output_redirection policy.

    Returns:
        "allow", "ask", or "deny".  Never anything else, whatever ``policy``
        holds.
    """
    default = wildcard_level(policy)

    has_allow = False
    has_ask = False
    for kind in kinds:
        # Each kind gets its own level lookup, independent of others
        level = policy.get(kind, default)
        if level == "ask":
            has_ask = True
        elif level != "allow":
            # deny, and anything unrecognised, together: the strictest reading
            # is the only safe one for a level nobody validated.
            return "deny"
        else:
            has_allow = True
    if has_ask:
        return "ask"
    if has_allow:
        return "allow"
    # No kinds at all: nothing was classified, so no level was ever read and the
    # strictness above does not apply - this is "nothing to govern", not "a level
    # I did not recognise". Unreachable from `check_output_redirections`, which
    # classifies every operator it filtered to as a write; kept as allow for the
    # sake of the unit contract, not for any caller's benefit.
    return "allow"


def check_output_redirections(segments: list[Segment], rules: dict[str, Any]) -> PolicyResult:
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
    """
    redirections = _unique_redirections(segments, WRITE_REDIRECT_OPS, by_fd=True)
    if not redirections:
        return {"status": "allow", "matched": False, "reason": "no output redirection"}

    targets = [_redir_target(redir) for redir in redirections]
    blocked = _blocked_target_result(targets, rules)
    if blocked is not None:
        return blocked

    policy = rules.get("output_redirection", "ask")
    if isinstance(policy, dict):
        kinds = [kind for redir in redirections for kind in classify_output_redirection(redir)]
        level = _resolve_output_level(kinds, policy)
    else:
        level = policy
    return _redirection_result("output", level, targets)


def check_input_redirections(segments: list[Segment], rules: dict[str, Any]) -> PolicyResult:
    """Evaluate input redirections collected from segments.

    Segment-level counterpart to :func:`check_output_redirections`, and
    the single source of truth for input redirection policy.

    Args:
        segments: List of segment dicts from parse_segments.
        rules: Policy dict with ``input_redirection`` key.
    """
    redirections = _unique_redirections(segments, INPUT_REDIRECT_OPS, by_fd=False)
    if not redirections:
        return {"status": "allow", "matched": False, "reason": "no input redirection"}

    targets = [_redir_target(redir) for redir in redirections]
    blocked = _blocked_target_result(targets, rules)
    if blocked is not None:
        return blocked

    policy = rules.get("input_redirection", "ask")
    level = wildcard_level(policy) if isinstance(policy, dict) else policy
    return _redirection_result("input", level, targets)


def _collect_background_command_names(node: dict[str, Any], results: list[str]) -> None:
    """Recursively collect command names being run in the background.

    Background flags can appear on any statement in the tree, not just the
    top-level ones - e.g. ``(echo hi &)`` or ``x=$(echo hi &)`` background the
    inner command while the outer statement has ``Background=false``.
    """
    if not isinstance(node, dict):
        return
    if node.get("Background") or node.get("Type") == "CoprocClause":
        results.extend(_command_names_in(node.get("Cmd") or node))
    for value in node.values():
        if isinstance(value, dict):
            _collect_background_command_names(value, results)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    _collect_background_command_names(item, results)


def check_background_execution(tree: dict[str, Any], rules: dict[str, Any]) -> PolicyResult:
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
    # The schema only admits a plain level; a dict (from an unvalidated
    # config) is read by its wildcard.
    level = wildcard_level(policy) if isinstance(policy, dict) else policy

    background_commands: list[str] = []
    _collect_background_command_names(tree, background_commands)
    background_commands = list(dict.fromkeys(background_commands))

    if not background_commands:
        return {
            "status": "allow",
            "matched": False,
            "reason": "no background execution",
        }

    names = ", ".join(background_commands)
    if level == "allow":
        return {"status": "allow", "reason": f"background execution allowed: {names}"}
    if level == "ask":
        return {"status": "ask", "reason": f"background execution requires approval: {names}"}
    return {"status": "deny", "reason": f"background execution denied: {names}"}
