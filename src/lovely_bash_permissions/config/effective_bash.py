"""Compute effective bash permission config.

Combines the raw lovely-permissions bash config with Devin exec permission
regexes. Always includes the hook label regex so commands prefixed with
the hook label pass through the allowed pattern check.
"""

import re

from .devin import exec_permission_to_regex, load_devin_exec_regexes

HOOK_LABEL_PREFIX = "[♡ perms: "
HOOK_COMMAND_PREFIX = ": [♡ perms:"
HOOK_LABEL_REGEX = exec_permission_to_regex(HOOK_COMMAND_PREFIX)
LABEL_EXEC_PERMISSION = "Exec(: '[♡ perms:)"
LABEL_EXEC_NAME = "label exec"


def _deny_item_to_regex(item: str) -> str:
    """Convert a deny list item to a regex pattern.

    Items can be bare command names ("curl") or command patterns
    ("rm -rf /"). Convert to regex that matches the command name.
    """
    # Trim quotes
    item = item.strip()
    if item.startswith("'") or item.startswith('"'):
        item = item[1:-1]
    if item.endswith("'") or item.endswith('"'):
        item = item[:-1]

    # If it contains spaces, it's a command pattern
    if " " in item:
        # Pattern is "rm -rf /" — match command "rm" with specific args
        parts = item.split(" ", 1)
        cmd = parts[0]
        # Escape regex special chars in the command name
        import re

        cmd_pattern = re.escape(cmd)
        return f"^{cmd_pattern}(\\s.*)?$"
    else:
        # Bare command name
        import re

        return f"^{re.escape(item)}$"


def get_effective_bash_config(raw_bash, project_dir: str) -> dict:
    """Combine raw lovely config with devin permissions.

    Args:
        raw_bash: dict or None (bash config from lovely-permissions)
        project_dir: str

    Returns:
        dict with at least "*" : "ask", "allowed_cmds_regex" list,
        and "blocked_paths_regex" list
    """
    devin_regexes = load_devin_exec_regexes(project_dir)

    allowed_patterns = []
    if raw_bash:
        # Convert allow list to allowed patterns
        allow_items = raw_bash.get("allow", [])
        for item in allow_items:
            allowed_patterns.append(f"^{re.escape(item)}$")
        # Also include explicit allowed_cmds_regex patterns
        allowed_patterns.extend(raw_bash.get("allowed_cmds_regex", []))
    allowed_patterns.append(HOOK_LABEL_REGEX)
    allowed_patterns.extend(devin_regexes)
    # Remove duplicates while preserving order
    allowed_patterns = list(dict.fromkeys(allowed_patterns))

    blocked_patterns = []
    if raw_bash:
        deny_items = raw_bash.get("deny", [])
        blocked_patterns = [_deny_item_to_regex(d) for d in deny_items]

    if not raw_bash:
        return {
            "*": "ask",
            "allowed_cmds_regex": allowed_patterns,
            "blocked_paths_regex": blocked_patterns,
        }
    return {
        "*": raw_bash.get("*", "ask"),
        **raw_bash,
        "allowed_cmds_regex": allowed_patterns,
        "blocked_paths_regex": blocked_patterns,
    }
