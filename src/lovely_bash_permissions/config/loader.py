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


def _warn_conflict(key: str, level1: str, level2: str, warnings: list[str]) -> None:
    """Append a warning string when the same key is defined in two levels."""
    warnings.append(f"key '{key}' defined in {level2} config overrides {level1}")


def merge_deep(
    target: dict[str, Any], source: dict[str, Any], warnings: list[str] | None = None
) -> tuple[dict[str, Any], list[str]]:
    """Deep merge source into target.

    Objects are merged recursively, arrays are concatenated, scalars override.

    Returns:
        Tuple of (merged dict, list of conflict warning strings).
    """
    if warnings is None:
        warnings = []

    result: dict[str, Any] = {}
    for key, value in target.items():
        result[key] = value

    for key, value in source.items():
        existing: dict[str, Any] | None = result.get(key)
        if existing is not None and is_record(existing) and is_record(value):
            merged_child, _ = merge_deep(existing, value, warnings)
            result[key] = merged_child
        elif isinstance(existing, list) and isinstance(value, list):
            result[key] = existing + value
        else:
            if key in target and existing != value:
                _warn_conflict(key, "global", "project", warnings)
            result[key] = value
    return result, warnings


def load_permissions_config(project_dir: str) -> tuple[dict[str, Any], list[str], list[str]]:
    """Load and merge lovely-devin-permissions config.

    Returns:
        Tuple of (merged config dict, warnings list, validation_errors list).

    Raises:
        FileNotFoundError: if none of the config files exist (all missing).
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

    if not loaded_any:
        details = "\n".join(f"  {p}: {r}" for p, r in parse_errors)
        raise FileNotFoundError(f"no valid lovely-permissions config found\n{details}")

    warnings: list[str] = []
    validation_errors: list[str] = []
    for path, reason in parse_errors:
        warnings.append(f"skipped invalid config file: {path} ({reason})")

    # Merge in order: global < project < local
    merged: dict[str, Any] = {}
    for cfg in configs:
        merged, merge_warnings = merge_deep(merged, cfg)
        warnings.extend(merge_warnings)

    # Validate merged config — Pydantic enforces schema (typos, invalid patterns)
    try:
        PermissionsConfig.model_validate(merged)
    except ValueError as exc:
        warnings.append(f"config validation error: {exc}")
        validation_errors.append(str(exc))

    return merged, warnings, validation_errors
