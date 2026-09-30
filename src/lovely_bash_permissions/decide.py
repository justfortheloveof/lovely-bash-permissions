"""The decision: one bash command, one config, one verdict.

Host-agnostic. This module holds the whole of "should this command run, and if
not, why" and nothing about how any host asks or reports it. The Devin hook
and the Pi server are two callers of one implementation, so a policy change
cannot land in one and miss the other.

**This module speaks ``deny``.** ``deny`` is this product's policy vocabulary:
the level a user writes and the level the evaluator returns. ``block`` is
Devin's wire vocabulary, spoken only by :mod:`lovely_bash_permissions.hook` at
the seam, and only because Devin branches on it to decide the command's fate.
Forwarding a ``deny`` where ``block`` is expected is not a cosmetic mismatch -
it misses every ``elif action == "block"`` branch, so the response generator
returns ``None``, the CLI never reaches its exit-2 path, and the denied command
runs. The rename is therefore done by the caller, explicitly, and never here.
See D12.
"""

from __future__ import annotations

from typing import Any

from .config.effective_bash import resolve_bash_config
from .evaluate import evaluate_bash_command
from .policy import Level

#: The product's level vocabulary, mapped to itself. Named so the seam reads as
#: a translation of one vocabulary into the host's, rather than as a lookup with
#: a surprise value in it.
LEVEL_TO_ACTION: dict[str, Level] = {"allow": "allow", "ask": "ask", "deny": "deny"}


def error_action(config: dict[str, Any], exc: BaseException) -> dict[str, Any]:
    """Map a failure to the configured ``error`` policy.

    ``bash.error`` decides the action for any command we could not analyse - a
    parse failure, a missing shfmt binary, a config the caller passed through
    unvalidated. Falls back to the wildcard, then to ask.

    ``error`` is a :data:`~lovely_bash_permissions.policy.NON_CONSTRUCT_KEYS`
    key: the evaluator's own level resolution never touches it, only
    :func:`~lovely_bash_permissions.config.effective_bash.resolve_bash_config`
    populates it. A config handed straight to :func:`decide_bash_command` is
    resolved first, so this reads a populated value on both hosts.

    The reason uses the exception's *user* form where it has one. A
    :class:`~lovely_bash_permissions.parser.ParseError` renders four lines for a
    traceback - the command, an exit code, and shfmt's stderr repeating the
    message - and this string is a prompt bullet and a model-facing tool result,
    so it takes the one-line form instead. Anything else without that method
    falls back to ``str()``.

    Returns the same three keys as a normal verdict, ``reasons`` included: a
    failure is a verdict a host has to explain, and this path can be ``ask``.
    """
    level = config.get("error") or config.get("*") or "ask"
    action = LEVEL_TO_ACTION.get(level, "ask")
    user_form = getattr(exc, "user_message", None)
    detail = user_form() if callable(user_form) else str(exc)
    reason = f"error evaluating command (policy '{level}'): {detail}"
    return {"action": action, "reason": reason, "reasons": [reason]}


def decide_bash_command(command: str, config: dict[str, Any], top_level_wildcard: str = "ask") -> dict[str, Any]:
    """Evaluate a command against a config, resolving the config first.

    Args:
        command: the bash command to evaluate.
        config: a *raw* bash block, exactly as a config file declares it. It is
            resolved through
            :func:`~lovely_bash_permissions.config.effective_bash.resolve_bash_config`
            before evaluation, so every policy key has its wildcard applied and
            ``error`` is populated.
        top_level_wildcard: the mode's wildcard, the fallback for a block that
            declares no ``*`` of its own. Required for the same reason: without
            it, ``{"allowed_cmds_regex": ["^ls"]}`` under an ``allow`` mode
            resolves to ``*": "ask"`` and asks.

    Resolving here rather than leaving it to the caller is not tidiness. Omit
    it and ``error`` is absent from the config, so every shfmt failure falls
    back to ``*`` - which on an already-resolved config is a real level and on
    an unresolved one may be missing entirely. Either way an unparseable
    command under ``{"*": "allow"}`` reports ``ask`` instead of the policy the
    user wrote. Silent, and in the permissive direction.

    Returns:
        ``{"action": "allow" | "ask" | "deny", "reason": str, "reasons": [str]}``.
        ``reasons`` is the per-reason breakdown of ``reason``; it is empty
        exactly when the evaluator had nothing to say beyond a matched
        pattern or the wildcard, which never happens for a non-allow verdict.
    """
    resolved = resolve_bash_config(config, top_level_wildcard)
    try:
        result = evaluate_bash_command(command, resolved)
    except Exception as exc:  # noqa: BLE001 - uniform routing through the `error` policy
        return error_action(resolved, exc)

    return {
        "action": LEVEL_TO_ACTION[result.get("status", "ask")],
        "reason": result.get("reason", ""),
        "reasons": result.get("reasons", []),
    }
