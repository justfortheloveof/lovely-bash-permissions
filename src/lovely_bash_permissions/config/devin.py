"""Devin config loader.

Loads Devin configuration from three locations (highest precedence last):
  1. ~/.config/devin/config.json (global)
  2. {project}/.devin/config.json (project)
  3. {project}/.devin/config.local.json (local)

Extracts permissions.allow entries and parses Exec(...) patterns into
anchored regex strings for command matching.
"""

import re
from pathlib import Path

from .jsonc import is_record, read_jsonc_file

# Exec pattern: "Exec(git)" or "Exec(npm run)" or "Exec(:)"
EXEC_PATTERN = re.compile(r"^Exec\(([^()]*)\)$")


def get_devin_global_config_dir() -> Path:
    """Return the Devin global config directory.

    Uses APPDATA on Windows, ~/.config/devin elsewhere.
    Respects DEVIN_GLOBAL_CONFIG_DIR environment variable.
    """
    import os

    devin_dir = os.environ.get("DEVIN_GLOBAL_CONFIG_DIR")
    if devin_dir:
        return Path(devin_dir)
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "devin"
    return Path.home() / ".config" / "devin"


def get_devin_config_file_paths(project_dir: str) -> list:
    """Return the three Devin config file paths (global, project, local)."""
    return [
        str(get_devin_global_config_dir() / "config.json"),
        str(Path(project_dir) / ".devin" / "config.json"),
        str(Path(project_dir) / ".devin" / "config.local.json"),
    ]


def escape_regexp(value: str) -> str:
    """Escape regex metacharacters in a string.

    Escapes: . * + ? ^ $ { } ( ) | [ ] \\
    (Matches TypeScript's escapeRegExp behavior, which doesn't escape spaces.)
    """
    return re.sub(r"([.*+?^${}()|[\]\\])", r"\\\1", value)


def exec_permission_to_regex(prefix: str) -> str:
    """Convert an Exec permission prefix to an anchored regex.

    Converts "git" to "^git(\\s|$)" and "npm run" to "^npm run(\\s|$)".
    """
    trimmed = prefix.strip()
    return "^" + escape_regexp(trimmed) + "(\\s|$)"


def load_devin_exec_permissions(project_dir: str):
    """Load and parse Devin Exec permissions from all config files.

    Returns:
        dict with 'permissions' (list of {source, prefix, regex})
        and 'errors' (list of error messages).
    """
    sources = get_devin_config_file_paths(project_dir)

    permissions = []
    errors = []

    for source in sources:
        data = read_jsonc_file(source)
        if not is_record(data):
            continue

        # Extract permissions.allow (may not exist)
        allow_list = []
        perms = data.get("permissions")
        if is_record(perms):
            allow_list = perms.get("allow", [])
            if not isinstance(allow_list, list):
                allow_list = []

        for entry in allow_list:
            # Only strings are valid Exec patterns
            if not isinstance(entry, str):
                continue

            match = EXEC_PATTERN.match(entry)
            if not match:
                # Only error on malformed Exec(...) entries, ignore others
                if entry.startswith("Exec("):
                    errors.append(
                        f'Invalid Exec(...) permission in {source}: "{entry}"'
                    )
                continue

            prefix = (match.group(1) or "").strip()
            if not prefix:
                errors.append(f'Invalid Exec(...) permission in {source}: "{entry}"')
                continue

            permissions.append(
                {
                    "source": source,
                    "prefix": prefix,
                    "regex": exec_permission_to_regex(prefix),
                }
            )

    return {"permissions": permissions, "errors": errors}


def load_devin_exec_regexes(project_dir: str):
    """Load and deduplicate Devin Exec permission regexes.

    Raises ValueError if any malformed Exec(...) entries are found.
    """
    result = load_devin_exec_permissions(project_dir)
    if result["errors"]:
        raise ValueError("\n".join(result["errors"]))
    # Deduplicate while preserving order
    seen = set()
    unique = []
    for perm in result["permissions"]:
        regex = perm["regex"]
        if regex not in seen:
            seen.add(regex)
            unique.append(regex)
    return unique
