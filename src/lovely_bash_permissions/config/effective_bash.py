"""Compute effective bash permission config.

Combines the raw lovely-permissions bash config with Devin exec permission
regexes.

The hook's own ``: '<label>'`` wrapper is not part of the allowed patterns:
it is inert (the ``:`` builtin ignores its arguments) and is recognized
structurally by the evaluator so re-evaluated rewrites don't spuriously ask.
"""

from typing import Any

from .devin import load_devin_exec_regexes


def get_effective_bash_config(raw_bash: object, project_dir: str, top_level_wildcard: str = "ask") -> dict[str, Any]:
    """Combine raw lovely config with devin permissions.

    Args:
        raw_bash: dict or None (bash config from lovely-permissions)
        project_dir: str
        top_level_wildcard: the config-level wildcard (root ``*``), used as the
            fallback for the bash-level ``*`` (default "ask").

    Returns:
        dict with at least "*" : "ask", "error" : (bash error or wildcard),
        "allowed_cmds_regex" list, and "blocked_paths_regex" list
    """
    devin_regexes = load_devin_exec_regexes(project_dir)

    allowed_patterns: list[str] = []
    if raw_bash:
        bash: dict[str, Any] = raw_bash  # type: ignore[assignment]
        for p in bash.get("allowed_cmds_regex", []):
            allowed_patterns.append(p)  # noqa: PERF402 - patterns used as-is
    allowed_patterns.extend(devin_regexes)
    # Remove duplicates while preserving order
    allowed_patterns = list(dict.fromkeys(allowed_patterns))

    if raw_bash:
        blocked_patterns: list[str] = []
        for p in bash.get("blocked_paths_regex", []):
            blocked_patterns.append(p)  # noqa: PERF402 - patterns used as-is

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
            "error": _resolve("error"),
            "command_substitution": _resolve("command_substitution"),
            "process_substitution": _resolve("process_substitution"),
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
        "error": top_level_wildcard or "ask",
        "allowed_cmds_regex": allowed_patterns,
        "blocked_paths_regex": [],
    }
