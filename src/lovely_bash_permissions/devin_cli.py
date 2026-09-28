"""Lovely-devin-permissions CLI.

Two modes:
  - Hook mode: receives JSON hook events on stdin (e.g., from Devin agent)
  - CLI mode: interactive with argv flags (--setup, --test, --show-config)

CLI flags take precedence over stdin.
"""

import argparse
import json
import os
import sys
from typing import Any, NoReturn

from .config.devin import (
    get_devin_config_file_paths,
    get_devin_global_config_dir,
)
from .config.effective_bash import get_effective_bash_config
from .config.jsonc import read_jsonc_file
from .config.loader import get_permissions_config_file_paths
from .config.manager import PermissionsManager
from .hook import HOOK_LABEL_PREFIX, generate_hook_response, process_hook_event

#: The Devin ``permissions.allow`` entry that lets the hook's own ``:`` no-op
#: label run without prompting again. Deliberately just ``Exec(:)`` rather than a
#: pattern quoting the label text: the allowed-matcher compares against each
#: segment's *executed* line, which has its quotes stripped, so a pattern
#: containing the label's literal ``'`` could never match. ``:`` ignores its
#: arguments, so allowing it grants nothing.
LABEL_EXEC_NAME = "Exec(:)"


def with_error_prefix(message: str) -> str:
    return f"{HOOK_LABEL_PREFIX} ERROR] {message}"


def emit_block(reason: str) -> NoReturn:
    """Print a block decision to stdout and exit with Devin's block exit code (2)."""
    print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
    sys.exit(2)


def get_project_dir() -> str:
    return os.environ.get("DEVIN_PROJECT_DIR") or os.getcwd()


def handle_setup() -> None:
    """Add label exec permission to devin global config."""
    config_dir = get_devin_global_config_dir()
    config_path = config_dir / "config.json"

    # Ensure directory exists
    config_dir.mkdir(parents=True, exist_ok=True)

    # Read existing config (or {} if missing). If the file is unreadable or
    # malformed, abort without writing so we never destroy the user's config.
    if config_path.exists():
        if config_path.stat().st_size == 0:
            config = {}
        else:
            result = read_jsonc_file(str(config_path))
            if result.error is not None:
                print(
                    with_error_prefix(
                        f"config {config_path} is not valid JSON/JSONC ({result.error}) - "
                        "aborting to avoid overwriting it"
                    ),
                    file=sys.stderr,
                )
                sys.exit(1)
            if not isinstance(result.value, dict):
                print(
                    with_error_prefix(
                        f"config {config_path} must be a JSON object, got {type(result.value).__name__} - "
                        "aborting to avoid overwriting it"
                    ),
                    file=sys.stderr,
                )
                sys.exit(1)
            config = result.value
    else:
        config = {}

    # Refuse to clobber unexpected shapes
    if "permissions" in config and not isinstance(config["permissions"], dict):
        print(
            with_error_prefix(
                f"config {config_path} has a non-object 'permissions' field - aborting to avoid overwriting it"
            ),
            file=sys.stderr,
        )
        sys.exit(1)
    permissions = config.setdefault("permissions", {})
    if "allow" in permissions and not isinstance(permissions["allow"], list):
        print(
            with_error_prefix(
                f"config {config_path} has a non-list 'permissions.allow' field - aborting to avoid overwriting it"
            ),
            file=sys.stderr,
        )
        sys.exit(1)
    allow = permissions.setdefault("allow", [])

    # Check if already present
    if LABEL_EXEC_NAME in allow:
        print(f'The Devin permission "{LABEL_EXEC_NAME}" is' + f" already present in {config_path}")
        sys.exit(0)

    # Append and write
    allow.append(LABEL_EXEC_NAME)
    try:
        with open(config_path, "w") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
            f.write("\n")
        print(f'Added "{LABEL_EXEC_NAME}" to {config_path} so Devin' + ' auto-approves the hook\'s ":" no-op label')
        sys.exit(0)
    except OSError as e:
        print(with_error_prefix(f"Failed to write config: {e}"), file=sys.stderr)
        sys.exit(1)


def handle_test(command: str) -> None:
    """Test a command as a PreToolUse event."""
    project_dir = get_project_dir()
    event = {
        "hook_event_name": "PreToolUse",
        "tool_name": "exec",
        "tool_input": {"command": command},
        "project_dir": project_dir,
    }
    result = process_hook_event(event)
    if result.get("action") == "skip":
        print("No response generated for the test command")
        sys.exit(0)
    response = generate_hook_response(event, result)
    if response is None:
        print("No response generated for the test command")
        sys.exit(0)
    print(json.dumps(response, indent=2, ensure_ascii=False))
    sys.exit(0 if result.get("action") != "block" else 2)


def handle_show_config() -> None:
    """Print effective config and file paths."""
    project_dir = get_project_dir()
    files = []
    for path in get_permissions_config_file_paths(project_dir):
        files.append({"path": path, "exists": os.path.exists(path)})
    for path in get_devin_config_file_paths(project_dir):
        files.append({"path": path, "exists": os.path.exists(path)})

    manager = PermissionsManager(project_dir)
    if not manager.is_valid():
        print(
            with_error_prefix(f"Invalid permissions config: {manager.get_error()}"),
            file=sys.stderr,
        )
        sys.exit(1)

    raw_bash = manager.get_lovely_config()
    try:
        bash = get_effective_bash_config(raw_bash.get("bash"), project_dir, raw_bash.get("*", "ask"))
    except (ValueError, FileNotFoundError, OSError):
        print(with_error_prefix("effective bash config load failed"), file=sys.stderr)
        sys.exit(1)

    result = {"files": files, "effectiveConfig": bash}
    print(json.dumps(result, indent=2, ensure_ascii=False))
    sys.exit(0)


def handle_hook_event(event: dict[str, Any]) -> dict[str, Any] | None:
    """Process a hook event and write response to stdout."""
    result = process_hook_event(event)
    if result.get("action") == "skip":
        return None
    response = generate_hook_response(event, result)
    return response


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="lovely-devin-permissions",
        description="Lovely-devin-permissions hook CLI",
    )
    parser.add_argument(
        "-s",
        "--setup",
        action="store_true",
        help="Add label exec permission to devin global config",
    )
    parser.add_argument("-t", "--test", type=str, help="Test a command as a PreToolUse event")
    parser.add_argument("--show-config", action="store_true", help="Show effective config")

    args = parser.parse_args()

    hook_mode = False
    # CLI flags take precedence
    try:
        if args.setup:
            handle_setup()
        elif args.test is not None:
            handle_test(args.test)
        elif args.show_config:
            handle_show_config()
        else:
            hook_mode = True
            # Hook mode: check if stdin has data
            if sys.stdin.isatty():
                # No input in interactive mode, exit silently
                sys.exit(0)
            try:
                raw = sys.stdin.read().strip()
                if not raw:
                    sys.exit(0)
                event = json.loads(raw)
            except json.JSONDecodeError as exc:
                # Fail closed: an unparseable decision request is never an allow.
                emit_block(with_error_prefix(f"invalid JSON on stdin: {exc}"))

            # Validate structure
            if not isinstance(event, dict):
                emit_block(with_error_prefix("invalid hook event: JSON payload is not an object"))
            tool_name = event.get("tool_name", "")
            tool_input = event.get("tool_input", {})
            if tool_name not in ("exec", "write_to_process"):
                sys.exit(0)
            if not isinstance(tool_input, dict):
                emit_block(with_error_prefix(f"invalid hook event: {tool_name} tool_input is not an object"))
            command = tool_input.get("command", "")
            if not command:
                sys.exit(0)

            event.setdefault("project_dir", get_project_dir())
            response = handle_hook_event(event)
            if response is not None:
                print(json.dumps(response, ensure_ascii=False))
                if response.get("decision") == "block":
                    sys.exit(2)
            sys.exit(0)
    except Exception as exc:  # noqa: BLE001 - hook mode fails closed, other modes error out
        if hook_mode:
            emit_block(with_error_prefix(f"unexpected error: {exc}"))
        print(with_error_prefix(f"unexpected error: {exc}"), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
