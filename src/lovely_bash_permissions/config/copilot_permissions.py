"""Load Copilot CLI's persisted command approvals."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .copilot import get_copilot_home


def get_copilot_permissions_path() -> Path:
    """Return the configured Copilot permissions file path."""
    return get_copilot_home() / "permissions-config.json"


def _validate_permissions(data: object) -> dict[str, Any]:
    """Validate the saved-approval structure before importing any permission."""
    if not isinstance(data, dict):
        raise TypeError("expected a JSON object")

    locations = data.get("locations", {})
    if not isinstance(locations, dict):
        raise TypeError("'locations' must be an object")

    for location, details in locations.items():
        if not isinstance(location, str):
            raise TypeError("location keys must be strings")
        if not Path(location).is_absolute():
            raise ValueError("location keys must be absolute paths")
        if not isinstance(details, dict):
            raise TypeError(f"location {location!r} must be an object")
        approvals = details.get("tool_approvals", [])
        if not isinstance(approvals, list):
            raise TypeError(f"'tool_approvals' for {location!r} must be an array")
        allowed_directories = details.get("allowed_directories", [])
        if not isinstance(allowed_directories, list):
            raise TypeError(f"'allowed_directories' for {location!r} must be an array")
        if any(not isinstance(directory, str) for directory in allowed_directories):
            raise TypeError(f"'allowed_directories' for {location!r} must contain strings")
        if any(not Path(directory).is_absolute() for directory in allowed_directories):
            raise ValueError(f"'allowed_directories' for {location!r} must contain absolute paths")
        for approval in approvals:
            if not isinstance(approval, dict) or not isinstance(approval.get("kind"), str):
                raise TypeError(f"tool approvals for {location!r} must have a string 'kind'")
            if approval["kind"] == "commands":
                identifiers = approval.get("commandIdentifiers")
                if not isinstance(identifiers, list) or any(
                    not isinstance(identifier, str) for identifier in identifiers
                ):
                    raise TypeError(f"command approvals for {location!r} need string identifiers")
                if any(
                    not identifier.strip() or (identifier.endswith(":*") and not identifier[:-2].strip())
                    for identifier in identifiers
                ):
                    raise ValueError(f"command approvals for {location!r} need non-empty string identifiers")

    return locations


def load_saved_command_approvals(location: Path | str) -> tuple[list[str], str | None]:
    """Load persisted command identifiers for exactly one Copilot permission location.

    Missing files are normal. Any existing but unreadable or invalid file returns
    no approvals and a warning message, rather than retaining a partial import.
    """
    path = get_copilot_permissions_path()
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        if path.is_symlink():
            return [], f"cannot read Copilot saved approvals {path}: {exc}"
        return [], None
    except (OSError, UnicodeDecodeError) as exc:
        return [], f"cannot read Copilot saved approvals {path}: {exc}"

    try:
        locations = _validate_permissions(json.loads(text))
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        return [], f"Copilot saved approvals {path} are malformed: {exc}"

    matching_location = locations.get(str(Path(location)))
    if matching_location is None:
        return [], None

    identifiers = [
        identifier
        for approval in matching_location.get("tool_approvals", [])
        if approval["kind"] == "commands"
        for identifier in approval["commandIdentifiers"]
    ]
    return list(dict.fromkeys(identifiers)), None
