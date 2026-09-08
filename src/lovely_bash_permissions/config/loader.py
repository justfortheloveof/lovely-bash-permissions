"""Lovely-devin-permissions config loader.

Loads and merges configuration from three locations (highest precedence last):
  1. ~/.config/devin/lovely-permissions.jsonc (global)
  2. {project}/.devin/lovely-permissions.jsonc (project)
  3. {project}/.devin/lovely-permissions.local.jsonc (local)

Uses deep merge: objects merged recursively, arrays concatenated, scalars override.
"""

from pathlib import Path
from typing import Any

from .devin import get_devin_global_config_dir
from .jsonc import is_record, read_jsonc_file
from .schema import PermissionsConfig, _validate_config

PROJECT_CONFIG_FILE = "lovely-permissions.jsonc"


def get_permissions_config_file_paths(project_dir: str) -> list[str]:
    """Return the three config file paths (global, project, local)."""
    return [
        str(get_devin_global_config_dir() / PROJECT_CONFIG_FILE),
        str(Path(project_dir) / ".devin" / PROJECT_CONFIG_FILE),
        str(Path(project_dir) / ".devin" / "lovely-permissions.local.jsonc"),
    ]


def merge_deep(target: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    """Deep merge source into target.

    Objects are merged recursively, arrays are concatenated, scalars override.
    """
    result = dict(target)
    for key, value in source.items():
        existing: dict[str, Any] | None = result.get(key)
        if existing is not None and is_record(existing) and is_record(value):
            result[key] = merge_deep(existing, value)
        elif isinstance(existing, list) and isinstance(value, list):
            result[key] = existing + value
        else:
            result[key] = value
    return result


def load_permissions_config(project_dir: str) -> dict[str, Any]:
    """Load and merge lovely-devin-permissions config.

    Returns:
        Merged config dict.

    Raises:
        FileNotFoundError: if none of the config files exist or all are invalid.
    """
    paths = get_permissions_config_file_paths(project_dir)

    # Load each file, missing/invalid -> {}
    configs: list[dict[str, Any]] = []
    loaded_any = False
    parse_errors: list[str] = []
    for path in paths:
        data = read_jsonc_file(path)
        if data is not None and isinstance(data, dict):
            configs.append(data)
            loaded_any = True
        else:
            configs.append({})
            parse_errors.append(path)

    if not loaded_any:
        raise FileNotFoundError(
            f"no valid lovely-permissions config found (checked: {', '.join(paths)}); "
            f"parsed with errors: {', '.join(parse_errors)}"
        )

    # Merge in order: global < project < local
    merged: dict[str, Any] = {}
    for cfg in configs:
        merged = merge_deep(merged, cfg)

    # Validate merged config — catch typos and invalid patterns early
    try:
        PermissionsConfig.model_validate(merged)
    except ValueError as exc:
        raise FileNotFoundError(f"no valid lovely-permissions config found\n  {exc}") from exc

    validation_errors = _validate_config(merged)
    if validation_errors:
        raise FileNotFoundError("no valid lovely-permissions config found\n" + "\n  ".join(validation_errors))

    return merged
