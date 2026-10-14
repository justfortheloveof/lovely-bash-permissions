"""GitHub Copilot CLI's local ``preToolUse`` Bash hook adapter."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from . import decide
from .config.copilot import CopilotPolicyError, load_copilot_policy


def _deny(reason: str) -> dict[str, str]:
    """Build a denial for a hook request that cannot be evaluated."""
    return {"action": "deny", "reason": reason}


def _decode_tool_args(value: object) -> dict[str, Any]:
    """Normalize Copilot's object or JSON-encoded ``toolArgs`` shape."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"toolArgs is not valid JSON: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise TypeError("toolArgs must be an object or a JSON-encoded object")
    return value


def _decision_for_payload(raw: str) -> dict[str, str] | None:
    """Turn one Copilot hook payload into a policy verdict, or skip its tool."""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        return _deny(f"invalid hook input: malformed JSON ({exc.msg})")

    if not isinstance(payload, dict):
        return _deny("invalid hook input: expected a JSON object")

    tool_name = payload.get("toolName")
    if not isinstance(tool_name, str):
        return _deny("invalid hook input: 'toolName' must be a string")
    if tool_name != "bash":
        return None

    try:
        tool_args = _decode_tool_args(payload.get("toolArgs"))
    except (TypeError, ValueError) as exc:
        return _deny(f"invalid hook input: {exc}")

    command = tool_args.get("command")
    if not isinstance(command, str):
        return _deny("invalid hook input: Bash toolArgs must contain a string 'command'")

    try:
        config, top_level_wildcard = load_copilot_policy()
    except CopilotPolicyError as exc:
        return _deny(str(exc))

    decision = decide.decide_bash_command(command, config.get("bash") or {}, top_level_wildcard)
    action = decision["action"]
    reason = decision["reason"] or "command allowed by the configured Lovely policy"
    return {"action": action, "reason": reason}


def _emit_verdict(verdict: dict[str, str]) -> None:
    """Write Copilot's progress line followed by exactly one decision object."""
    action = verdict["action"]
    reason = verdict["reason"]
    progress = {"type": "progress", "message": f"Lovely policy: {action} — {reason}"}
    decision: dict[str, str] = {"permissionDecision": action}
    if action != "allow":
        decision["permissionDecisionReason"] = reason

    print(json.dumps(progress, ensure_ascii=False))
    print(json.dumps(decision, ensure_ascii=False))


def main() -> None:
    """Read one Copilot hook payload and emit its native permission verdict."""
    parser = argparse.ArgumentParser(
        prog="lovely-copilot-permissions",
        description="Evaluate local GitHub Copilot CLI preToolUse Bash calls with Lovely policy.",
    )
    parser.parse_args()

    verdict = _decision_for_payload(sys.stdin.read())
    if verdict is None:
        sys.exit(0)

    _emit_verdict(verdict)
    # Copilot reads the JSON decision body. A policy deny is still a successfully
    # produced verdict; nonzero is reserved for failures that produce no verdict.
    sys.exit(0)


if __name__ == "__main__":
    main()
