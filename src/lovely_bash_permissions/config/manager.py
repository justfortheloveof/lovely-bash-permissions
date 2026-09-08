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
        self._validation_errors: list[str] = []
        self._devin_regexes: list[str] = []
        self._devin_error: str | None = None
        self._warnings: list[str] = []
        self._load()

    def _load(self) -> None:
        """Load config from disk, capturing errors."""
        self._warnings = []  # reset warnings on each reload
        self._validation_errors = []  # reset validation errors on each reload

        try:
            self._lovely_config, warn_list, error_list = load_permissions_config(self._project_dir)
            self._warnings.extend(warn_list)
            self._validation_errors = error_list
        except FileNotFoundError as exc:
            # Config file missing — fall back to ask mode (safe default)
            self._warnings.append(str(exc))
            self._lovely_config = {}
            self._validation_errors = [str(exc)]

        # Load Devin exec regexes
        try:
            self._devin_regexes = load_devin_exec_regexes(self._project_dir)
            self._devin_error = None
        except Exception as e:  # noqa: BLE001
            self._warnings.append(str(e))
            self._devin_regexes = []
            self._devin_error = str(e)

    @property
    def validation_errors(self) -> list[str]:
        """Return validation errors collected during config load."""
        return self._validation_errors

    @property
    def has_validation_errors(self) -> bool:
        """Return True if there are validation errors."""
        return bool(self._validation_errors)

    def get_lovely_config(self) -> dict[str, Any]:
        """Return the merged lovely-permissions config.

        Raises ValueError if validation errors exist.
        """
        if self._validation_errors:
            raise ValueError("\n".join(self._validation_errors))
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
        """Return True if lovely-permissions config loaded without validation errors."""
        return len(self._validation_errors) == 0

    def get_error(self) -> str | None:
        """Return first validation error if invalid, None if valid."""
        return self._validation_errors[0] if self._validation_errors else None

    def get_warnings(self) -> list[str]:
        """Return warnings for config files that were skipped."""
        return self._warnings
