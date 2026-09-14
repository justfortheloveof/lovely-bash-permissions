"""Compute effective bash permission config.

Combines the raw lovely-permissions bash config with Devin exec permission
regexes. Always includes the hook label regex so commands prefixed with
the hook label pass through the allowed pattern check.
"""

from typing import Any

from ..rules import _item_to_anchored_pattern
from .devin import exec_permission_to_regex, load_devin_exec_regexes

HOOK_COMMAND_PREFIX = ": '[♡ perms:"
HOOK_LABEL_REGEX = exec_permission_to_regex(HOOK_COMMAND_PREFIX)


def get_effective_bash_config(raw_bash: object, project_dir: str, top_level_wildcard: str = "ask") -> dict[str, Any]:
    """Combine raw lovely config with devin permissions.

    Args:
        raw_bash: dict or None (bash config from lovely-permissions)
        project_dir: str
        top_level_wildcard: the config-level wildcard (root ``*``), used as the
            fallback for the bash-level ``*`` (default "ask").

    Returns:
        dict with at least "*" : "ask", "allowed_cmds_regex" list,
        and "blocked_paths_regex" list
    """
    devin_regexes = load_devin_exec_regexes(project_dir)

    allowed_patterns: list[str] = []
    if raw_bash:
        bash: dict[str, Any] = raw_bash  # type: ignore[assignment]
        # Convert allow list to allowed patterns (shared helper, issue #3)
        allow_items = bash.get("allow", [])
        for item in allow_items:
            allowed_patterns.append(_item_to_anchored_pattern(item))
        # Also include explicit allowed_cmds_regex patterns
        for p in bash.get("allowed_cmds_regex", []):
            allowed_patterns.append(p)  # noqa: PERF402 — patterns used as-is
    allowed_patterns.append(HOOK_LABEL_REGEX)
    allowed_patterns.extend(devin_regexes)
    # Remove duplicates while preserving order
    allowed_patterns = list(dict.fromkeys(allowed_patterns))

    if raw_bash:
        # Load blocked_paths_regex directly from config, then merge deny list items
        blocked_patterns: list[str] = []
        for p in bash.get("blocked_paths_regex", []):
            blocked_patterns.append(p)  # noqa: PERF402 — patterns used as-is
        deny_items = bash.get("deny", [])
        blocked_patterns.extend(_item_to_anchored_pattern(d) for d in deny_items)

        resolved_star = bash.get("*") or top_level_wildcard or "ask"

        def _resolve(key: str) -> Any:  # noqa: ANN401
            """Resolve a policy option: explicit -> dict normalized -> wildcard."""
            value = bash.get(key)
            if isinstance(value, dict):
                return {**value, "*": value.get("*") or resolved_star}
            return value or resolved_star

        return {
            **bash,
            "*": resolved_star,
            "subshell": _resolve("subshell"),
            "variable_assignment": _resolve("variable_assignment"),
            "input_redirection": _resolve("input_redirection"),
            "background_execution": _resolve("background_execution"),
            "output_redirection": _resolve("output_redirection"),
            "allowed_cmds_regex": allowed_patterns,
            "blocked_paths_regex": blocked_patterns,
        }

    return {
        "*": top_level_wildcard or "ask",
        "allowed_cmds_regex": allowed_patterns,
        "blocked_paths_regex": [],
    }
