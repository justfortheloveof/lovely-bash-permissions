"""Shared event builders for hook integration tests."""

from typing import Any


def _pretooluse_exec_event(command: str = "ls") -> dict[str, Any]:
    """Return a PreToolUse event for tool 'exec'."""
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": "exec",
        "tool_input": {"command": command},
    }


def _permission_request_event(command: str = "ls") -> dict[str, Any]:
    """Return a PermissionRequest event for tool 'exec'."""
    return {
        "hook_event_name": "PermissionRequest",
        "tool_name": "exec",
        "tool_input": {"command": command},
    }
