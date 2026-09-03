"""PermissionsManager: loads and manages lovely-devin-permissions and Devin config."""

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
        self._lovely_config = {}
        self._lovely_error = None
        self._devin_regexes = []
        self._devin_error = None
        self._load()

    def _load(self) -> None:
        """Load config from disk, capturing errors."""
        # Load lovely-permissions config
        try:
            self._lovely_config = load_permissions_config(self._project_dir)
            self._lovely_error = None
        except Exception as e:
            self._lovely_config = {}
            self._lovely_error = str(e)

        # Load Devin exec regexes
        try:
            self._devin_regexes = load_devin_exec_regexes(self._project_dir)
            self._devin_error = None
        except Exception as e:
            self._devin_regexes = []
            self._devin_error = str(e)

    def get_lovely_config(self) -> dict:
        """Return the merged lovely-permissions config (may be empty dict)."""
        return self._lovely_config

    def get_devin_exec_regexes(self) -> list:
        """Return deduplicated list of Devin Exec permission regex strings.

        Raises ValueError if any malformed Exec entries found.
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
