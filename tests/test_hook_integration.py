"""Integration tests for hook.py config consumption.

Tests generate_hook_response and process_hook_event across allow/block/ask/skip
decision paths, plus config-load-failure fallback behavior.
"""

from typing import Any
from unittest.mock import patch

from lovely_bash_permissions.hook import generate_hook_response, process_hook_event

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# 1–4: PreToolUse decision paths via generate_hook_response
# ---------------------------------------------------------------------------


def test_pretooluse_allow() -> None:
    """PreToolUse with action=allow → approve decision, updatedInput command."""
    event = _pretooluse_exec_event("ls")
    result = generate_hook_response(event, {"action": "allow"})

    assert result is not None
    assert result["decision"] == "approve"
    output = result["hookSpecificOutput"]
    assert output["hookEventName"] == "PreToolUse"
    updated = output["updatedInput"]["command"]
    assert updated == ": '[♡ perms: 💚 auto-approved]' ; ls"


def test_pretooluse_block() -> None:
    """PreToolUse with action=block → block decision, reason included."""
    event = _pretooluse_exec_event("ls")
    result = generate_hook_response(event, {"action": "block", "reason": "not allowed"})

    assert result is not None
    assert result["decision"] == "block"
    assert "[♡ perms: ❤️ auto-rejected] not allowed" in result["reason"]
    output = result["hookSpecificOutput"]
    assert "auto-rejected" in output["updatedInput"]["command"]


def test_pretooluse_ask() -> None:
    """PreToolUse with action=ask → updatedInput with approval-required label."""
    event = _pretooluse_exec_event("ls")
    result = generate_hook_response(event, {"action": "ask"})

    assert result is not None
    output = result["hookSpecificOutput"]
    updated = output["updatedInput"]["command"]
    assert updated == ": '[♡ perms: 💛 REQUIRES-USER-APPROVAL]' ; ls"


def test_pretooluse_skip() -> None:
    """PreToolUse with action=skip → None (no response)."""
    event = _pretooluse_exec_event("ls")
    result = generate_hook_response(event, {"action": "skip"})

    assert result is None


# ---------------------------------------------------------------------------
# 5–6: process_hook_event skip paths
# ---------------------------------------------------------------------------


def test_non_exec_tool_skipped() -> None:
    """Non-exec tool → process_hook_event returns skip."""
    event = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",  # not "exec"
        "tool_input": {"command": "ls"},
    }
    result = process_hook_event(event)

    assert result == {"action": "skip"}


def test_empty_command_skipped() -> None:
    """Empty command → process_hook_event returns skip."""
    event = _pretooluse_exec_event("")  # command is empty string
    result = process_hook_event(event)

    assert result == {"action": "skip"}


# ---------------------------------------------------------------------------
# 7–8: config-load-failure fallback → ask
# ---------------------------------------------------------------------------


def test_config_load_failure_fallback_ask() -> None:
    """Project dir with nonexistent config dir → fallback to ask."""
    event = _pretooluse_exec_event("ls")

    with patch(
        "lovely_bash_permissions.hook.PermissionsManager",
        side_effect=FileNotFoundError("no config files found"),
    ):
        result = process_hook_event(event)

    assert result["action"] == "ask"
    assert "config error (fallback to ask)" in result["reason"]


def test_effective_bash_config_failure_fallback_ask() -> None:
    """Invalid bash config → effective_bash raises, fallback to ask."""
    event = _pretooluse_exec_event("ls")

    with (
        patch("lovely_bash_permissions.hook.PermissionsManager") as MockMgr,
        patch("lovely_bash_permissions.hook.get_effective_bash_config") as mock_eff,
    ):
        # Mock manager construction to succeed with a valid config
        instance = MockMgr.return_value
        instance.get_lovely_config.return_value = {"bash": {"allowed_cmds_regex": []}}

        # But effective_bash config loading fails
        mock_eff.side_effect = ValueError("invalid bash config")

        result = process_hook_event(event)

    assert result["action"] == "ask"
    assert "config error (fallback to ask)" in result["reason"]


# ---------------------------------------------------------------------------
# 9–12: PermissionRequest decision paths via generate_hook_response
# ---------------------------------------------------------------------------


def test_permission_request_allow() -> None:
    """PermissionRequest with action=allow → approve decision."""
    event = _permission_request_event("ls")
    result = generate_hook_response(event, {"action": "allow"})

    assert result == {"decision": "approve"}


def test_permission_request_block() -> None:
    """PermissionRequest with action=block → block decision."""
    event = _permission_request_event("ls")
    result = generate_hook_response(event, {"action": "block", "reason": "blocked by policy"})

    assert result is not None
    assert result["decision"] == "block"
    assert "[♡ perms: ❤️ auto-rejected]" in result["reason"]


def test_permission_request_ask() -> None:
    """PermissionRequest with action=ask → None (asks pass through)."""
    event = _permission_request_event("ls")
    result = generate_hook_response(event, {"action": "ask"})

    assert result is None


def test_reason_preserved_in_block() -> None:
    """Block with a custom reason string → reason appears in response."""
    event = _pretooluse_exec_event("rm -rf /")
    reason_text = "dangerous command: rm -rf"
    result = generate_hook_response(event, {"action": "block", "reason": reason_text})

    assert result is not None
    assert result["decision"] == "block"
    assert reason_text in result["reason"]
    # Also check updatedInput contains the label with reason
    assert reason_text in result["hookSpecificOutput"]["updatedInput"]["command"]
