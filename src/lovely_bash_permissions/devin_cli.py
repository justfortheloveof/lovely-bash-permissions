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
from pathlib import Path

from .config.devin import (
    get_devin_config_file_paths,
)
from .config.effective_bash import (
    HOOK_LABEL_PREFIX,
    LABEL_EXEC_NAME,
    get_effective_bash_config,
)
from .config.loader import get_permissions_config_file_paths
from .config.manager import PermissionsManager
from .hook import generate_hook_response, process_hook_event


def get_devin_global_config_dir():
    devin_dir = os.environ.get("DEVIN_GLOBAL_CONFIG_DIR")
    if devin_dir:
        return Path(devin_dir)
    return Path(os.path.expanduser("~/.config/devin"))


def with_error_prefix(message):
    return f"{HOOK_LABEL_PREFIX} ERROR] {message}"


def get_project_dir():
    return os.environ.get("DEVIN_PROJECT_DIR") or os.getcwd()


def handle_setup():
    """Add label exec permission to devin global config."""
    config_dir = get_devin_global_config_dir()
    config_path = config_dir / "config.json"

    # Ensure directory exists
    config_dir.mkdir(parents=True, exist_ok=True)

    # Read existing config (or {} if missing)
    if config_path.exists():
        try:
            with open(config_path) as f:
                config = json.load(f)
        except json.JSONDecodeError:
            config = {}
    else:
        config = {}

    # Ensure structure
    if not isinstance(config, dict):
        config = {}
    if "permissions" not in config:
        config["permissions"] = {}
    if "allow" not in config["permissions"]:
        config["permissions"]["allow"] = []

    allow = config["permissions"]["allow"]
    if not isinstance(allow, list):
        allow = []
        config["permissions"]["allow"] = allow

    # Check if already present
    if LABEL_EXEC_NAME in allow:
        print(
            f"{HOOK_LABEL_PREFIX}Label exec permission already present in {config_path}"
        )
        sys.exit(0)

    # Append and write
    allow.append(LABEL_EXEC_NAME)
    try:
        with open(config_path, "w") as f:
            json.dump(config, f, indent=2)
        print(f"{HOOK_LABEL_PREFIX}Added label exec permission to {config_path}")
        sys.exit(0)
    except Exception as e:
        print(with_error_prefix(f"Failed to write config: {e}"), file=sys.stderr)
        sys.exit(1)


def handle_test(command):
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
    print(json.dumps(response, indent=2))
    sys.exit(0 if result.get("action") != "block" else 2)


def handle_show_config():
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
        bash = get_effective_bash_config(raw_bash.get("bash"), project_dir)
    except Exception as e:
        print(with_error_prefix(str(e)), file=sys.stderr)
        sys.exit(1)

    result = {"files": files, "effectiveConfig": bash}
    print(json.dumps(result, indent=2))
    sys.exit(0)


def handle_hook_event(event):
    """Process a hook event and write response to stdout."""
    result = process_hook_event(event)
    if result.get("action") == "skip":
        return None
    response = generate_hook_response(event, result)
    return response


def main():
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
    parser.add_argument(
        "-t", "--test", type=str, help="Test a command as a PreToolUse event"
    )
    parser.add_argument(
        "--show-config", action="store_true", help="Show effective config"
    )

    args = parser.parse_args()

    # CLI flags take precedence
    if args.setup:
        handle_setup()
    elif args.test is not None:
        handle_test(args.test)
    elif args.show_config:
        handle_show_config()
    else:
        # Hook mode: check if stdin has data
        if sys.stdin.isatty():
            # No input in interactive mode, exit silently
            sys.exit(0)
        try:
            raw = sys.stdin.read().strip()
            if not raw:
                sys.exit(0)
            event = json.loads(raw)
        except json.JSONDecodeError:
            sys.exit(0)

        # Validate structure
        tool_name = event.get("tool_name", "")
        tool_input = event.get("tool_input", {})
        if tool_name != "exec":
            sys.exit(0)
        if not isinstance(tool_input, dict):
            sys.exit(0)
        command = tool_input.get("command", "")
        if not command:
            sys.exit(0)

        response = handle_hook_event(event)
        if response is not None:
            print(json.dumps(response))
        sys.exit(0)


if __name__ == "__main__":
    main()
