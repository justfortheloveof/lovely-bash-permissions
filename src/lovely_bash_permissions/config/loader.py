"""Lovely-devin-permissions config loader.

Loads and merges configuration from three locations (highest precedence last):
  1. ~/.config/devin/lovely-permissions.jsonc (global)
  2. {project}/.devin/lovely-permissions.jsonc (project)
  3. {project}/.devin/lovely-permissions.local.jsonc (local)

Uses deep merge: objects merged recursively, arrays concatenated, scalars override.
"""

from pathlib import Path

from .devin import get_devin_global_config_dir
from .jsonc import is_record, read_jsonc_file

PROJECT_CONFIG_FILE = "lovely-permissions.jsonc"


def get_permissions_config_file_paths(project_dir: str) -> list:
    """Return the three config file paths (global, project, local)."""
    return [
        str(get_devin_global_config_dir() / PROJECT_CONFIG_FILE),
        str(Path(project_dir) / ".devin" / PROJECT_CONFIG_FILE),
        str(Path(project_dir) / ".devin" / "lovely-permissions.local.jsonc"),
    ]


def merge_deep(target: dict, source: dict) -> dict:
    """Deep merge source into target.

    Objects are merged recursively, arrays are concatenated, scalars override.
    """
    result = dict(target)
    for key, value in source.items():
        existing = result.get(key)
        if is_record(existing) and is_record(value):
            result[key] = merge_deep(existing, value)
        elif isinstance(existing, list) and isinstance(value, list):
            result[key] = existing + value
        else:
            result[key] = value
    return result


def load_permissions_config(project_dir: str) -> dict:
    """Load and merge lovely-devin-permissions config.

    Returns:
        Merged config dict.

    Raises:
        FileNotFoundError: if none of the config files exist or all are invalid.
    """
    paths = get_permissions_config_file_paths(project_dir)

    # Load each file, missing/invalid -> {}
    configs = []
    loaded_any = False
    for path in paths:
        data = read_jsonc_file(path)
        if is_record(data):
            configs.append(data)
            loaded_any = True
        else:
            configs.append({})

    if not loaded_any:
        raise FileNotFoundError(f"no valid lovely-permissions config found (checked: {', '.join(paths)})")

    # Merge in order: global < project < local
    merged = {}
    for cfg in configs:
        merged = merge_deep(merged, cfg)

    return merged
