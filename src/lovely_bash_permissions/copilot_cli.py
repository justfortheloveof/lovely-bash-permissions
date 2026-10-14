"""GitHub Copilot CLI's local ``preToolUse`` Bash hook adapter."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from . import decide
from .config.copilot import load_copilot_policy
from .config.copilot_permissions import load_saved_command_approvals
from .copilot_diagnostics import get_copilot_diagnostics


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


def _project_and_permission_location_from_event_cwd(value: object) -> tuple[Path, Path]:
    """Resolve the policy root and Copilot permission location from event cwd."""
    if not isinstance(value, str) or not value or not Path(value).is_absolute():
        raise ValueError("invalid hook input: 'cwd' must be an absolute directory path")

    try:
        event_dir = Path(value).resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValueError(f"invalid hook input: cannot resolve event 'cwd' {value!r}: {exc}") from exc
    if not event_dir.is_dir():
        raise ValueError(f"invalid hook input: event 'cwd' is not a directory: {event_dir}")

    try:
        result = subprocess.run(
            ["git", "-C", str(event_dir), "rev-parse", "--show-toplevel"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError(f"cannot determine project root from event 'cwd' {event_dir}: {exc}") from exc

    if result.returncode != 0:
        # A valid directory outside a checkout is its own project-policy root.
        return event_dir, event_dir

    root = result.stdout.strip()
    if not root:
        raise ValueError(f"cannot determine project root from event 'cwd' {event_dir}")
    try:
        checkout_root = Path(root).resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValueError(f"cannot resolve Git checkout root {root!r}: {exc}") from exc
    if not checkout_root.is_dir():
        raise ValueError(f"Git checkout root is not a directory: {checkout_root}")

    try:
        superproject = subprocess.run(
            ["git", "-C", str(event_dir), "rev-parse", "--show-superproject-working-tree"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        common_dir = subprocess.run(
            ["git", "-C", str(event_dir), "rev-parse", "--git-common-dir"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        git_dir = subprocess.run(
            ["git", "-C", str(event_dir), "rev-parse", "--git-dir"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError(f"cannot determine Copilot permission location from event 'cwd' {event_dir}: {exc}") from exc
    if superproject.returncode != 0 or common_dir.returncode != 0 or git_dir.returncode != 0:
        raise ValueError(f"cannot determine Copilot permission location from event 'cwd' {event_dir}")

    # Copilot scopes a submodule to its own checkout, not the containing
    # superproject. Its active checkout root already has that identity.
    if superproject.stdout.strip():
        return checkout_root, checkout_root

    common_path = Path(common_dir.stdout.strip())
    if not common_path.is_absolute():
        common_path = event_dir / common_path
    git_path = Path(git_dir.stdout.strip())
    if not git_path.is_absolute():
        git_path = event_dir / git_path
    try:
        common_path = common_path.resolve(strict=True)
        git_path = git_path.resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValueError(f"cannot resolve Copilot permission location from event 'cwd' {event_dir}: {exc}") from exc

    if common_path != git_path:
        # Linked worktrees have a per-worktree git dir and share the main
        # repository's common .git directory.
        main_root = common_path.parent
        if not main_root.is_dir():
            raise ValueError(f"Copilot main repository root is not a directory: {main_root}")
        return checkout_root, main_root
    return checkout_root, checkout_root


def _copilot_approval_regex(identifier: str) -> str:
    """Translate a Copilot command identifier to a full executed-command match."""
    prefix = identifier.endswith(":*")
    command = identifier[:-2] if prefix else identifier
    escaped = re.escape(command)
    body = f"{escaped}(?:\\s+.*)?" if prefix else escaped
    # The impossible lookahead makes Lovely's matcher use the executed form
    # only, rather than letting a quoted/raw spelling grant a saved approval.
    return f"^(?!\\b\\B){body}\\Z"


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
        project_dir, permission_location = _project_and_permission_location_from_event_cwd(payload.get("cwd"))
        config, top_level_wildcard = load_copilot_policy(project_dir)
    except ValueError as exc:
        return _deny(str(exc))

    approval_ids, warning = load_saved_command_approvals(permission_location)
    if warning:
        print(f"warning: {warning}", file=sys.stderr)
    bash_config = dict(config.get("bash") or {})
    if approval_ids:
        existing_patterns = bash_config.get("allowed_cmds_regex", [])
        imported_patterns = [_copilot_approval_regex(identifier) for identifier in approval_ids]
        bash_config["allowed_cmds_regex"] = list(dict.fromkeys([*existing_patterns, *imported_patterns]))

    decision = decide.decide_bash_command(command, bash_config, top_level_wildcard)
    action = decision["action"]
    reason = decision["reason"] or "command allowed by the configured Lovely policy"
    return {"action": action, "reason": reason}


def _emit_verdict(verdict: dict[str, str]) -> None:
    """Write Copilot's progress line followed by exactly one decision object."""
    action = verdict["action"]
    reason = verdict["reason"]
    progress = {"type": "progress", "message": f"Lovely policy: {action} — {reason}"}
    print(json.dumps(progress, ensure_ascii=False))
    print(json.dumps(_decision_object(verdict), ensure_ascii=False))


def _decision_object(verdict: dict[str, str]) -> dict[str, str]:
    """Translate a policy verdict to Copilot's final hook response."""
    action = verdict["action"]
    reason = verdict["reason"]
    decision: dict[str, str] = {"permissionDecision": action}
    if action != "allow":
        decision["permissionDecisionReason"] = reason
    return decision


def _show_config() -> None:
    """Print the selected Copilot sources and effective Bash policy."""
    try:
        project_dir, permission_location = _project_and_permission_location_from_event_cwd(str(Path.cwd()))
        result, warning = get_copilot_diagnostics(project_dir, permission_location, _copilot_approval_regex)
    except (ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)

    if warning:
        print(f"warning: {warning}", file=sys.stderr)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    sys.exit(0)


def main() -> None:
    """Read one Copilot hook payload and emit its native permission verdict."""
    parser = argparse.ArgumentParser(
        prog="lovely-copilot-permissions",
        description="Evaluate local GitHub Copilot CLI preToolUse Bash calls with Lovely policy.",
    )
    parser.add_argument(
        "--test",
        metavar="COMMAND",
        help="Print the Copilot decision for COMMAND without timeline progress.",
    )
    parser.add_argument("--show-config", action="store_true", help="Show policy sources and effective Bash config")
    args = parser.parse_args()

    if args.test is not None:
        payload = json.dumps({"cwd": str(Path.cwd()), "toolName": "bash", "toolArgs": {"command": args.test}})
        verdict = _decision_for_payload(payload)
        if verdict is None:
            raise RuntimeError("test mode did not produce a verdict")
        print(json.dumps(_decision_object(verdict), ensure_ascii=False))
        sys.exit(0)
    if args.show_config:
        _show_config()

    verdict = _decision_for_payload(sys.stdin.read())
    if verdict is None:
        sys.exit(0)

    _emit_verdict(verdict)
    # Copilot reads the JSON decision body. A policy deny is still a successfully
    # produced verdict; nonzero is reserved for failures that produce no verdict.
    sys.exit(0)


if __name__ == "__main__":
    main()
