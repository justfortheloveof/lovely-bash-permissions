"""Hook event processing for bash command execution.

Processes hook events from agent tools to decide whether to allow,
ask, block, or skip command execution.
"""

from typing import Any

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
        config = manager.get_lovely_config()
    except Exception as e:
        return handle_load_error(e)

    result = evaluate_bash_command(command, config)
    status = result.get("status", "ask")
    reason = result.get("reason", "")

    action = {"allow": "allow", "ask": "ask", "deny": "block"}[status]
    return {"action": action, "reason": reason}
