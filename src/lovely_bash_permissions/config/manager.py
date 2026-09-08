"""PermissionsManager: loads and manages lovely-devin-permissions and Devin config."""

from typing import Any

from .devin import load_devin_exec_regexes
from .loader import load_permissions_config


class PermissionsManager:
    """Loads and manages lovely-permissions and Devin config.

    Loads lovely-permissions config and Devin exec regexes from disk.
    Exposes both for use by the bash tool.
    """

    def __init__(self, project_dir: str) -> None:
        """Create PermissionsManager. project_dir is the current working directory."""
        self._project_dir = project_dir
        self._lovely_config: dict[str, Any] = {}
        self._lovely_error: str | None = None
        self._devin_regexes: list[str] = []
        self._devin_error: str | None = None
        self._warnings: list[str] = []
        self._load()

    def _load(self) -> None:
        """Load config from disk, capturing errors."""
        self._warnings = []  # reset warnings on each reload

        try:
            self._lovely_config, warn_list = load_permissions_config(self._project_dir)
            self._warnings.extend(warn_list)
            self._lovely_error = None
        except FileNotFoundError as exc:
            # Config file missing — fall back to ask mode (safe default)
            self._warnings.append(str(exc))
            self._lovely_config = {}
            self._lovely_error = "no valid lovely-permissions config found"

        # Load Devin exec regexes
        try:
            self._devin_regexes = load_devin_exec_regexes(self._project_dir)
            self._devin_error = None
        except Exception as e:  # noqa: BLE001
            self._warnings.append(str(e))
            self._devin_regexes = []
            self._devin_error = str(e)

    def get_lovely_config(self) -> dict[str, Any]:
        """Return the merged lovely-permissions config.

        Raises ValueError if config failed to load.
        """
        if self._lovely_error:
            raise ValueError(self._lovely_error)
        return self._lovely_config

    def get_devin_exec_regexes(self) -> list[str]:
        """Return deduplicated list of Devin Exec permission regex strings.

        Raises ValueError if config failed to load or malformed entries found.
        """
        if self._devin_error:
            raise ValueError(self._devin_error)
        return self._devin_regexes

    def reload(self) -> None:
        """Reload config from disk."""
        self._load()

    def is_valid(self) -> bool:
        """Return True if lovely-permissions config loaded without errors."""
        return self._lovely_error is None

    def get_error(self) -> str | None:
        """Return error message if invalid, None if valid."""
        return self._lovely_error

    def get_warnings(self) -> list[str]:
        """Return warnings for config files that were skipped."""
        return self._warnings
