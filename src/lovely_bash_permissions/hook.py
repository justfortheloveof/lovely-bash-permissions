"""Hook event processing for bash command execution.

Processes hook events from agent tools to decide whether to allow,
ask, block, or skip command execution.
"""

from typing import Any

from .config.effective_bash import get_effective_bash_config
from .config.manager import PermissionsManager
from .evaluate import evaluate_bash_command

HOOK_LABEL_PREFIX = "[♡ perms: "

#: (emoji, status label) per decision action — single source for both the
#: label prefix and the trailing marker after the label.
HOOK_STATUS = {
    "allow": ("💚", "auto-approved"),
    "ask": ("💛", "REQUIRES-USER-APPROVAL"),
    "block": ("❤️", "auto-rejected"),
}


def _hook_label(action: str, reason: str) -> str:
    """Build e.g. '[♡ perms: 💚 auto-approved] reason'."""
    emoji, status = HOOK_STATUS[action]
    label = f"{HOOK_LABEL_PREFIX}{emoji} {status}]"
    return f"{label} {reason}" if reason else label


def _hook_command(action: str, reason: str, command: str) -> str:
    """Wrap a command: ': '<label>' <emoji> ; <command>'."""
    emoji, _ = HOOK_STATUS[action]
    return f": '{_hook_label(action, reason)}' {emoji} ; {command}"


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

    try:
        config = get_effective_bash_config(raw_config.get("bash"), project_dir, raw_config.get("*", "ask"))
    except (ValueError, FileNotFoundError, OSError):
        reason = manager.get_error() or "effective bash config load failed"
        return {"action": "ask", "reason": f"config error (fallback to ask): {reason}"}

    try:
        result = evaluate_bash_command(command, config)
    except Exception as exc:  # noqa: BLE001 — uniform routing through the `error` policy
        return _error_action(config, exc)

    status = result.get("status", "ask")
    reason = result.get("reason", "")

    action = _LEVEL_TO_ACTION[status]
    return {"action": action, "reason": reason}
