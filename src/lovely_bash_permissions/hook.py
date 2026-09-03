"""Hook event processing for bash command execution.

Processes hook events from agent tools to decide whether to allow,
ask, block, or skip command execution.
"""

import sys
from typing import Any

from .config.effective_bash import get_effective_bash_config
from .config.manager import PermissionsManager
from .evaluate import evaluate_bash_command


def handle_load_error(err: Exception) -> dict[str, Any]:
    """Return a block result with error message.

    Args:
        err: The exception that occurred while loading config.

    Returns:
        dict with action "block" and reason.
    """
    return {"action": "block", "reason": str(err)}


def generate_hook_response(
    event: dict[str, Any], decision: dict[str, Any]
) -> dict[str, Any] | None:
    """Generate hook response JSON for agent tool permission events.

    Args:
        event: Hook event dict with hook_event_name.
        decision: dict with "action" ("allow" | "ask" | "block" | "skip") and optional "reason".

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
        if tool_name != "exec" or not command:
            return None
        if action == "allow":
            label = (
                f"[♡ perms: 💚 auto-approved] {reason}"
                if reason
                else "[♡ perms: 💚 auto-approved]"
            )
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "updatedInput": {"command": f": '{label}' ; {command}"},
                }
            }
        elif action == "block":
            label = "[♡ perms: ❤️ auto-rejected]"
            return {
                "decision": "block",
                "reason": reason,
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "updatedInput": {"command": f": '{label}' ; {command}"},
                },
            }
        elif action == "ask":
            label = (
                f"[♡ perms: 💛 REQUIRES-USER-APPROVAL] {reason}"
                if reason
                else "[♡ perms: 💛 REQUIRES-USER-APPROVAL]"
            )
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "updatedInput": {"command": f": '{label}' ; {command}"},
                }
            }

    if event_name == "PermissionRequest":
        if tool_name != "exec" or not command:
            return None
        if action == "allow":
            return {"decision": "approve"}
        elif action == "block":
            label = (
                f"[♡ perms: ❤️ auto-rejected] {reason}"
                if reason
                else "[♡ perms: ❤️ auto-rejected]"
            )
            return {"decision": "block", "reason": label}
        elif action == "ask":
            return None

    return None


def process_hook_event(event: dict[str, Any]) -> dict[str, Any]:
    """Process a hook event and decide allow/ask/block/skip.

    Extracts tool_name and command from the event. If tool_name != "exec"
    or command is empty, returns skip. Otherwise loads config via
    PermissionsManager and evaluates the command.

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

    if tool_name != "exec" or not command:
        return {"action": "skip"}

    project_dir = event.get("project_dir", ".")

    try:
        manager = PermissionsManager(project_dir)
        raw_config = manager.get_lovely_config()
    except Exception as e:  # noqa: BLE001
        print(f"error: {e}", file=sys.stderr)
        return handle_load_error(e)

    try:
        config = get_effective_bash_config(raw_config.get("bash"), project_dir)
    except Exception as e:  # noqa: BLE001
        print(f"error: {e}", file=sys.stderr)
        return handle_load_error(e)

    result = evaluate_bash_command(command, config)
    status = result.get("status", "ask")
    reason = result.get("reason", "")

    action = {"allow": "allow", "ask": "ask", "deny": "block"}[status]
    return {"action": action, "reason": reason}
