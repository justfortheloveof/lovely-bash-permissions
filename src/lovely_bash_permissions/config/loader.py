"""Lovely-devin-permissions config loader.

Loads and merges configuration from three locations (highest precedence last):
  1. ~/.config/devin/lovely-permissions.jsonc (global)
  2. {project}/.devin/lovely-permissions.jsonc (project)
  3. {project}/.devin/lovely-permissions.local.jsonc (local)

Uses deep merge: objects merged recursively, arrays concatenated, scalars override.
"""

import logging
from pathlib import Path
from typing import Any

from .devin import get_devin_global_config_dir
from .jsonc import is_record, read_jsonc_file
from .schema import PermissionsConfig

log = logging.getLogger(__name__)
PROJECT_CONFIG_FILE = "lovely-permissions.jsonc"


def get_permissions_config_file_paths(project_dir: str) -> list[str]:
    """Return the three config file paths (global, project, local)."""
    return [
        str(get_devin_global_config_dir() / PROJECT_CONFIG_FILE),
        str(Path(project_dir) / ".devin" / PROJECT_CONFIG_FILE),
        str(Path(project_dir) / ".devin" / "lovely-permissions.local.jsonc"),
    ]


#: The three config levels, in merge order (later overrides earlier).
CONFIG_LEVELS: tuple[str, str, str] = ("global", "project", "local")


def _origin_of(path: tuple[str, ...], origins: dict[tuple[str, ...], str]) -> str | None:
    """The level that last set *path*, or the nearest ancestor it was set under."""
    for end in range(len(path), 0, -1):
        level = origins.get(path[:end])
        if level is not None:
            return level
    return None


def merge_deep(
    target: dict[str, Any],
    source: dict[str, Any],
    warnings: list[str] | None = None,
    *,
    source_level: str = "project",
    origins: dict[tuple[str, ...], str] | None = None,
    _path: tuple[str, ...] = (),
) -> tuple[dict[str, Any], list[str]]:
    """Deep merge source into target.

    Objects are merged recursively, arrays are concatenated, scalars override.
    An override that changes a value is reported as a warning naming the
    dotted key, the level that overrides it (*source_level*) and the level that
    had set it. *origins* records which level last set each key and is updated
    in place, so a caller merging several levels in turn can pass the same
    mapping to every call; without it the overridden level is reported as
    ``global``.

    Returns:
        Tuple of (merged dict, list of conflict warning strings).
    """
    if warnings is None:
        warnings = []
    if origins is None:
        origins = {}

    result: dict[str, Any] = dict(target)

    for key, value in source.items():
        path = (*_path, str(key))
        existing = result.get(key)
        if is_record(existing) and is_record(value):
            result[key], _ = merge_deep(
                existing, value, warnings, source_level=source_level, origins=origins, _path=path
            )
        elif isinstance(existing, list) and isinstance(value, list):
            result[key] = existing + value
        else:
            if key in target and existing != value:
                overridden = _origin_of(path, origins) or "global"
                warnings.append(f"key '{'.'.join(path)}' defined in {source_level} config overrides {overridden}")
            result[key] = value
            origins[path] = source_level
    return result, warnings


def load_permissions_config(project_dir: str) -> tuple[dict[str, Any], list[str], list[str]]:
    """Load and merge lovely-devin-permissions config.

    Returns:
        Tuple of (merged config dict, warnings list, validation_errors list).

    When no config file exists anywhere the result is a valid empty config
    (``{}``) with a warning, so callers fall back to the safe default (ask).
    When config files exist but none can be parsed, validation_errors is
    populated and the merged config is ``{}``.
    """
    paths = get_permissions_config_file_paths(project_dir)

    # Load each file, missing/invalid -> {}
    configs: list[dict[str, Any]] = []
    loaded_any = False
    parse_errors: list[tuple[str, str]] = []
    for path in paths:
        log.debug("checking config file: %s", path)
        result = read_jsonc_file(path)
        if result.error is None and isinstance(result.value, dict):
            configs.append(result.value)
            loaded_any = True
        else:
            configs.append({})
            reason = result.error if result.error else "invalid JSONC"
            parse_errors.append((path, reason))

    warnings: list[str] = []
    validation_errors: list[str] = []
    if not loaded_any:
        details = "\n".join(f"  {p}: {r}" for p, r in parse_errors)
        if all(reason.startswith("file not found:") for _, reason in parse_errors):
            warnings.append("no lovely-permissions config file found; using safe default (ask for everything)")
            return {}, warnings, []
        warnings.append(f"no valid lovely-permissions config found\n{details}")
        validation_errors.append(f"no valid lovely-permissions config found\n{details}")
        return {}, warnings, validation_errors

    for path, reason in parse_errors:
        warnings.append(f"skipped invalid config file: {path} ({reason})")

    # Merge in order: global < project < local
    merged: dict[str, Any] = {}
    origins: dict[tuple[str, ...], str] = {}
    for level, cfg in zip(CONFIG_LEVELS, configs, strict=True):
        merged, merge_warnings = merge_deep(merged, cfg, source_level=level, origins=origins)
        warnings.extend(merge_warnings)

    # Validate merged config - Pydantic enforces schema (typos, invalid patterns)
    try:
        PermissionsConfig.model_validate(merged)
    except ValueError as exc:
        warnings.append(f"config validation error: {exc}")
        validation_errors.append(str(exc))

    return merged, warnings, validation_errors
