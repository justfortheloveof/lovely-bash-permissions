"""Hook event processing for bash command execution.

Processes hook events from agent tools to decide whether to allow,
ask, block, or skip command execution.
"""

import re
import shlex
from typing import Any

from .config.effective_bash import get_effective_bash_config
from .config.manager import PermissionsManager
from .evaluate import evaluate_bash_command

HOOK_LABEL_PREFIX = "[♡ perms: "

#: (emoji, status label) per decision action - single source for both the
#: label prefix and the trailing marker after the label.
HOOK_STATUS = {
    "allow": ("💚", "auto-approved"),
    "ask": ("💛", "REQUIRES-USER-APPROVAL"),
    "block": ("❤️", "auto-rejected"),
}


#: The quoting shlex.quote() emits for an embedded single quote, so the
#: wrapper-matching regex below has to accept that exact spelling.
_SHLEX_QUOTE_ESCAPE = "'\"'\"'"

#: Matches a leading ``: '<label>' <emoji> ; `` wrapper as emitted by
#: :func:`_hook_command`. The label is a shlex-quoted string, so an embedded
#: quote appears as the 4-character sequence ``'"'"'`` rather than a bare
#: ``'``. Requires the ``[♡ perms: `` marker so a user's own ``: 'x' 💚 ; cmd``
#: is left alone, and anchors at the start so a trailing forged label is not
#: stripped.
_HOOK_LABEL_WRAPPER_RE = re.compile(
    r"^:\s*'\[♡ perms: (?:[^']|" + _SHLEX_QUOTE_ESCAPE + r")*'\s*(?:💚|💛|❤️)\s*;\s*",
    re.DOTALL,
)


def _strip_hook_wrappers(command: str) -> str:
    """Remove leading hook label wrappers so labelling stays idempotent.

    Devin feeds the rewritten command back through evaluation, and each pass
    labelled it again, so the command grew by one wrapper every round-trip
    (unbounded, ~81 chars per pass) even though the verdict never changed.
    Stripping first makes re-labelling a fixed point: wrapping a command that
    is already labelled returns the same string.
    """
    previous = None
    while previous != command:
        previous = command
        command = _HOOK_LABEL_WRAPPER_RE.sub("", command, count=1)
    return command


def _hook_label(action: str, reason: str) -> str:
    """Build e.g. '[♡ perms: 💚 auto-approved] reason'."""
    emoji, status = HOOK_STATUS[action]
    label = f"{HOOK_LABEL_PREFIX}{emoji} {status}]"
    return f"{label} {reason}" if reason else label


def _hook_command(action: str, reason: str, command: str) -> str:
    """Wrap a command: ``: '<label>' <emoji> ; <command>``.

    The label is shlex-quoted because the reason can contain a single quote -
    allowed patterns are echoed into it, so a config pattern like
    ``^echo '.*'$`` would otherwise terminate the wrapper's quoting early and
    leave the remainder of the reason to be parsed as shell code.
    """
    emoji, _ = HOOK_STATUS[action]
    return f": {shlex.quote(_hook_label(action, reason))} {emoji} ; {_strip_hook_wrappers(command)}"


def generate_hook_response(event: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any] | None:
    """Generate hook response JSON for agent tool permission events.

    Args:
        event: Hook event dict with hook_event_name.
        decision: dict with "action" ("allow" | "ask" | "block" |
             "skip") and optional "reason".

    Returns:
        JSON-serializable dict for the agent, or None to skip.
    """
    action = decision.get("action", "skip")
    reason = decision.get("reason", "")
    event_name = event.get("hook_event_name", "")
    tool_name = event.get("tool_name", "")
    tool_input = event.get("tool_input", {})
    command = tool_input.get("command", "") if isinstance(tool_input, dict) else ""

    if action == "skip":
        return None

    if event_name == "PreToolUse":
        if tool_name not in ("exec", "write_to_process") or not command:
            return None
        if action == "allow":
            return {
                "decision": "approve",
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "updatedInput": {"command": _hook_command(action, reason, command)},
                },
            }
        elif action == "block":
            return {
                "decision": "block",
                "reason": _hook_label(action, reason),
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "updatedInput": {"command": _hook_command(action, reason, command)},
                },
            }
        elif action == "ask":
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "updatedInput": {"command": _hook_command(action, reason, command)},
                }
            }

    if event_name == "PermissionRequest":
        if tool_name not in ("exec", "write_to_process") or not command:
            return None
        if action == "allow":
            return {"decision": "approve"}
        elif action == "block":
            return {"decision": "block", "reason": _hook_label(action, reason)}
        elif action == "ask":
            return None

    return None


_LEVEL_TO_ACTION = {"allow": "allow", "ask": "ask", "deny": "block"}


def _error_action(config: dict[str, Any], exc: BaseException) -> dict[str, Any]:
    """Map a failure to the configured ``error`` policy.

    ``bash.error`` (or its wildcard default, resolved by
    :func:`get_effective_bash_config`) decides the action for any command we
    could not analyse.  Falls back to ask when the config is unavailable.
    """
    level = config.get("error") or config.get("*") or "ask"
    action = _LEVEL_TO_ACTION.get(level, "ask")
    return {"action": action, "reason": f"error evaluating command (policy '{level}'): {exc}"}


def process_hook_event(event: dict[str, Any]) -> dict[str, Any]:
    """Process a hook event and decide allow/ask/block/skip.

    Extracts tool_name and command from the event. If tool_name is neither
    "exec" nor "write_to_process", or command is empty, returns skip. Otherwise
    loads config via PermissionsManager and evaluates the command.

    Args:
        event: Hook event dict with keys:
            - hook_event_name: name of the hook event
            - tool_name: name of the tool being called (e.g., "exec")
            - tool_input: dict containing command to execute

    Returns:
        dict with action ("allow", "ask", "block", "skip") and optional reason.
    """
    tool_name = event.get("tool_name", "")
    tool_input = event.get("tool_input", {})

    if not isinstance(tool_input, dict):
        return {"action": "skip"}

    command = tool_input.get("command", "")

    if tool_name not in ("exec", "write_to_process") or not command:
        return {"action": "skip"}

    project_dir = event.get("project_dir", ".")

    manager: PermissionsManager | None = None
    try:
        manager = PermissionsManager(project_dir)
        raw_config = manager.get_lovely_config()
    except (FileNotFoundError, OSError):
        reason = (manager and manager.get_error()) or "permissions config load failed"
        return {"action": "ask", "reason": f"config error (fallback to ask): {reason}"}
    except ValueError as exc:
        # Config exists but is invalid.  Return a block rather than letting
        # the exception escape: an exit 1 is logged by Devin and the command
        # runs anyway, so failing this way would approve a command whose
        # policy could not be read at all.
        return {"action": "block", "reason": f"invalid permissions config (blocked): {exc}"}

    try:
        config = get_effective_bash_config(raw_config.get("bash"), project_dir, raw_config.get("*", "ask"))
    except (ValueError, FileNotFoundError, OSError) as exc:
        # Effective config (lovely + Devin exec rules) could not be computed -
        # e.g. a malformed Devin Exec(...) allow rule. Fail closed instead of
        # asking, since a broken Devin config would also break the hook's own
        # label auto-approval.
        reason = manager.get_error() or f"effective bash config load failed: {exc}"
        return {"action": "block", "reason": f"config error (blocked): {reason}"}

    try:
        result = evaluate_bash_command(command, config)
    except Exception as exc:  # noqa: BLE001 - uniform routing through the `error` policy
        return _error_action(config, exc)

    status = result.get("status", "ask")
    reason = result.get("reason", "")

    action = _LEVEL_TO_ACTION[status]
    return {"action": action, "reason": reason}
