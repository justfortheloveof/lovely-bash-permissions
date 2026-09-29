"""Resolve a raw bash config block into the dict the evaluator consumes.

Two functions, split along the host seam:

- :func:`resolve_bash_config` is host-agnostic. It knows the policy vocabulary
  and nothing else.
- :func:`get_effective_bash_config` is the Devin wrapper. It layers Devin's
  ``Exec()`` allow rules on top.

The split exists so a host with no ``Exec()`` concept - the Pi extension - can
resolve a block without reading a Devin config file. That was impossible while
the Devin merge was the first statement of the only entry point.

The hook's own ``: '<label>'`` wrapper is not part of the allowed patterns:
it is inert (the ``:`` builtin ignores its arguments) and is recognized
structurally by the evaluator so re-evaluated rewrites don't spuriously ask.
"""

from typing import Any

from ..policy import NON_CONSTRUCT_KEYS, POLICY_KEYS
from .devin import load_devin_exec_regexes


def resolve_bash_config(raw_bash: object, top_level_wildcard: str = "ask") -> dict[str, Any]:
    """Resolve every policy key in a raw bash block against the wildcards.

    Args:
        raw_bash: dict or None (a bash block, as it appears in a config file)
        top_level_wildcard: the config-level wildcard (root ``*``), used as the
            fallback for the bash-level ``*`` (default "ask").

    Returns:
        A dict with at least ``"*"``, ``"error"``, ``"allowed_cmds_regex"`` and
        ``"blocked_cmds_regex"``, plus every other key the block carried -
        including keys the caller never validated. The spread is deliberate: a
        host that hands us a block must not silently lose a key it passed on.

    NOTE: the branch is ``if not raw_bash:``, *not* ``if raw_bash is None:``,
    and that is load-bearing. An empty dict and ``None`` take the same branch,
    so ``{}`` never gets the ``{**bash}`` spread, never has its keys resolved,
    and returns the bare four-key default. Writing the more natural
    ``is None`` would spread ``{}``, resolve every policy key against the
    wildcard, and change the output for a config that is a documented no-op -
    drift introduced by the refactor meant to prevent exactly that. The
    parameter is typed ``object`` so the truthiness test stays honest; a
    ``dict`` signature would invite narrowing it away.

    If a future change needs to distinguish "absent" from "empty", that is a
    behaviour change and belongs in its own phase with its own baseline.
    """
    if not raw_bash:
        return {
            "*": top_level_wildcard or "ask",
            "error": top_level_wildcard or "ask",
            "allowed_cmds_regex": [],
            "blocked_cmds_regex": [],
        }

    bash: dict[str, Any] = raw_bash  # type: ignore[assignment]

    allowed_patterns: list[str] = []
    for p in bash.get("allowed_cmds_regex", []):
        allowed_patterns.append(p)  # noqa: PERF402 - patterns used as-is

    blocked_patterns: list[str] = []
    for p in bash.get("blocked_cmds_regex", []):
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
        # Driven by the shared vocabulary, so a key the evaluator gates is
        # always resolved here and vice versa. `error` is resolved alongside
        # them but read by the decision layer, not by the evaluator.
        **{key: _resolve(key) for key in (*POLICY_KEYS, *NON_CONSTRUCT_KEYS)},
        "allowed_cmds_regex": allowed_patterns,
        "blocked_cmds_regex": blocked_patterns,
    }


def get_effective_bash_config(raw_bash: object, project_dir: str, top_level_wildcard: str = "ask") -> dict[str, Any]:
    """Combine raw lovely config with devin permissions.

    Args:
        raw_bash: dict or None (bash config from lovely-permissions)
        project_dir: str
        top_level_wildcard: the config-level wildcard (root ``*``), used as the
            fallback for the bash-level ``*`` (default "ask").

    Returns:
        :func:`resolve_bash_config`'s output, with Devin's ``Exec()`` allow
        rules appended to ``allowed_cmds_regex`` and de-duplicated in place.
    """
    # Read before resolving, not after: a malformed Devin ``Exec()`` rule must
    # fail in the same place it always did, before any of this host's own
    # resolution has run.
    devin_regexes = load_devin_exec_regexes(project_dir)
    config = resolve_bash_config(raw_bash, top_level_wildcard)
    config["allowed_cmds_regex"] = list(dict.fromkeys([*config["allowed_cmds_regex"], *devin_regexes]))
    return config
