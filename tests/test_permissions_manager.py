"""Tests for PermissionsManager."""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from lovely_bash_permissions.config.loader import get_permissions_config_file_paths
from lovely_bash_permissions.config.manager import PermissionsManager


@pytest.fixture
def mock_project(tmp_path: Path) -> Path:
    """Create a temporary project directory with .devin subdirectory."""
    devin_dir = tmp_path / ".devin"
    devin_dir.mkdir()
    return tmp_path


class TestPermissionsManagerConstruction:
    """Test PermissionsManager constructor behavior."""

    @patch("lovely_bash_permissions.config.manager.load_permissions_config")
    @patch("lovely_bash_permissions.config.manager.load_devin_exec_regexes")
    def test_loads_during_construction(self, mock_devin: MagicMock, mock_lovely: MagicMock, mock_project: Path) -> None:
        """Manager should load config during construction."""
        mock_lovely.return_value = {"read": {"permission": "ask"}}
        mock_devin.return_value = ["^git"]

        manager = PermissionsManager(str(mock_project))

        assert manager.is_valid()
        assert manager.get_lovely_config() == {"read": {"permission": "ask"}}
        assert manager.get_devin_exec_regexes() == ["^git"]

    @patch("lovely_bash_permissions.config.manager.load_permissions_config")
    @patch("lovely_bash_permissions.config.manager.load_devin_exec_regexes")
    def test_defaults_when_loader_throws(
        self, mock_devin: MagicMock, mock_lovely: MagicMock, mock_project: Path
    ) -> None:
        """When loader throws, config should be empty and manager invalid."""
        mock_lovely.side_effect = Exception("bad config")
        mock_devin.side_effect = Exception("bad devin config")

        manager = PermissionsManager(str(mock_project))

        assert not manager.is_valid()
        with pytest.raises(ValueError, match="bad config"):
            manager.get_lovely_config()
        with pytest.raises(ValueError, match="bad devin config"):
            manager.get_devin_exec_regexes()
        assert manager.get_error() == "bad config"

    @patch("lovely_bash_permissions.config.manager.load_permissions_config")
    @patch("lovely_bash_permissions.config.manager.load_devin_exec_regexes")
    def test_handles_non_exception_throws(
        self, mock_devin: MagicMock, mock_lovely: MagicMock, mock_project: Path
    ) -> None:
        """Manager should handle non-Exception throws gracefully."""
        # Python doesn't have "throw 'string'" like JS, use Exception with string
        mock_lovely.side_effect = Exception("plain string error")
        mock_devin.return_value = []

        manager = PermissionsManager(str(mock_project))

        assert not manager.is_valid()
        assert manager.get_error() == "plain string error"


class TestPermissionsManagerReload:
    """Test PermissionsManager.reload() behavior."""

    @patch("lovely_bash_permissions.config.manager.load_permissions_config")
    @patch("lovely_bash_permissions.config.manager.load_devin_exec_regexes")
    def test_reload_loads_fresh_config(self, mock_devin: MagicMock, mock_lovely: MagicMock, mock_project: Path) -> None:
        """reload() should load fresh config from disk."""
        mock_lovely.return_value = {"read": {"permission": "ask"}}
        mock_devin.return_value = ["^git"]

        manager = PermissionsManager(str(mock_project))

        # Change the mock return values
        mock_lovely.return_value = {"write": {"permission": "allow"}}
        mock_devin.return_value = ["^npm", "^pip"]

        manager.reload()

        assert manager.is_valid()
        assert manager.get_lovely_config() == {"write": {"permission": "allow"}}
        assert manager.get_devin_exec_regexes() == ["^npm", "^pip"]

    @patch("lovely_bash_permissions.config.manager.load_permissions_config")
    @patch("lovely_bash_permissions.config.manager.load_devin_exec_regexes")
    def test_reload_clears_errors(self, mock_devin: MagicMock, mock_lovely: MagicMock, mock_project: Path) -> None:
        """reload() should clear previous errors if config loads successfully."""
        mock_lovely.side_effect = Exception("initial error")
        mock_devin.return_value = []

        manager = PermissionsManager(str(mock_project))
        assert not manager.is_valid()

        # Now loader succeeds
        mock_lovely.side_effect = None
        mock_lovely.return_value = {"read": {"permission": "ask"}}
        mock_devin.return_value = ["^git"]

        manager.reload()

        assert manager.is_valid()
        assert manager.get_error() is None
        assert manager.get_lovely_config() == {"read": {"permission": "ask"}}

    @patch("lovely_bash_permissions.config.manager.load_permissions_config")
    @patch("lovely_bash_permissions.config.manager.load_devin_exec_regexes")
    def test_reload_captures_new_errors(
        self, mock_devin: MagicMock, mock_lovely: MagicMock, mock_project: Path
    ) -> None:
        """reload() should capture new errors."""
        mock_lovely.return_value = {"read": {"permission": "ask"}}
        mock_devin.return_value = []

        manager = PermissionsManager(str(mock_project))
        assert manager.is_valid()

        # Now loader fails
        mock_lovely.side_effect = Exception("new error")
        mock_devin.side_effect = Exception("new devin error")

        manager.reload()

        assert not manager.is_valid()
        assert manager.get_error() == "new error"
        with pytest.raises(ValueError, match="new error"):
            manager.get_lovely_config()

    @patch("lovely_bash_permissions.config.manager.load_permissions_config")
    @patch("lovely_bash_permissions.config.manager.load_devin_exec_regexes")
    def test_reload_passes_project_dir(self, mock_devin: MagicMock, mock_lovely: MagicMock, mock_project: Path) -> None:
        """reload() should pass project_dir to loaders."""
        mock_lovely.return_value = {}
        mock_devin.return_value = []

        manager = PermissionsManager(str(mock_project))
        manager.reload()

        mock_lovely.assert_called_with(str(mock_project))
        mock_devin.assert_called_with(str(mock_project))


class TestPermissionsManagerGetMethods:
    """Test PermissionsManager getter methods."""

    @patch("lovely_bash_permissions.config.manager.load_permissions_config")
    @patch("lovely_bash_permissions.config.manager.load_devin_exec_regexes")
    def test_get_lovely_config_returns_dict(
        self, mock_devin: MagicMock, mock_lovely: MagicMock, mock_project: Path
    ) -> None:
        """get_lovely_config() should always return a dict."""
        mock_lovely.return_value = {"bash": {"permission": "allow"}}
        mock_devin.return_value = []

        manager = PermissionsManager(str(mock_project))

        config = manager.get_lovely_config()
        assert isinstance(config, dict)
        assert config == {"bash": {"permission": "allow"}}

    @patch("lovely_bash_permissions.config.manager.load_permissions_config")
    @patch("lovely_bash_permissions.config.manager.load_devin_exec_regexes")
    def test_get_devin_exec_regexes_raises_on_error(
        self, mock_devin: MagicMock, mock_lovely: MagicMock, mock_project: Path
    ) -> None:
        """get_devin_exec_regexes() should raise ValueError when devin loader fails."""
        mock_lovely.return_value = {}
        mock_devin.side_effect = Exception("devin load failed")

        manager = PermissionsManager(str(mock_project))

        with pytest.raises(ValueError) as exc_info:
            manager.get_devin_exec_regexes()
        assert "devin load failed" in str(exc_info.value)

    @patch("lovely_bash_permissions.config.manager.load_permissions_config")
    @patch("lovely_bash_permissions.config.manager.load_devin_exec_regexes")
    def test_get_devin_exec_regexes_returns_list(
        self, mock_devin: MagicMock, mock_lovely: MagicMock, mock_project: Path
    ) -> None:
        """get_devin_exec_regexes() should return a list."""
        mock_lovely.return_value = {}
        mock_devin.return_value = ["^git", "^npm"]

        manager = PermissionsManager(str(mock_project))

        regexes = manager.get_devin_exec_regexes()
        assert isinstance(regexes, list)
        assert regexes == ["^git", "^npm"]

    @patch("lovely_bash_permissions.config.manager.load_permissions_config")
    @patch("lovely_bash_permissions.config.manager.load_devin_exec_regexes")
    def test_is_valid_and_get_error(self, mock_devin: MagicMock, mock_lovely: MagicMock, mock_project: Path) -> None:
        """is_valid() and get_error() should be consistent."""
        mock_lovely.return_value = {"read": {"permission": "ask"}}
        mock_devin.return_value = []

        manager = PermissionsManager(str(mock_project))

        assert manager.is_valid()
        assert manager.get_error() is None

        mock_lovely.side_effect = Exception("config error")
        manager.reload()

        assert not manager.is_valid()
        assert manager.get_error() == "config error"


class TestPermissionsManagerEndToEnd:
    """End-to-end tests with real config files."""

    def test_empty_project(self, mock_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Empty project (no config files) raises when all loaders fail."""
        devin_global = tempfile.mkdtemp()
        monkeypatch.setenv("DEVIN_GLOBAL_CONFIG_DIR", devin_global)

        with patch(
            "lovely_bash_permissions.config.manager.load_devin_exec_regexes",
            return_value=[],
        ):
            manager = PermissionsManager(str(mock_project))

        assert not manager.is_valid()
        with pytest.raises(ValueError, match="no valid lovely-permissions config found"):
            manager.get_lovely_config()

    def test_with_lovely_permissions_config(self, mock_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test with a lovely-permissions config file."""
        devin_global = tempfile.mkdtemp()
        monkeypatch.setenv("DEVIN_GLOBAL_CONFIG_DIR", devin_global)
        # Create project lovely-permissions.jsonc
        config_path = mock_project / ".devin" / "lovely-permissions.jsonc"
        config_data = {"bash": {"permission": "allow", "allowed_cmds_regex": ["^git"]}}
        with open(config_path, "w") as f:
            json.dump(config_data, f)

        manager = PermissionsManager(str(mock_project))

        assert manager.is_valid()
        assert "bash" in manager.get_lovely_config()
        bash_cfg = manager.get_lovely_config()["bash"]
        assert bash_cfg["permission"] == "allow"
        assert bash_cfg["allowed_cmds_regex"] == ["^git"]

    def test_config_file_paths_generated_correctly(self, mock_project: Path) -> None:
        """Test that config file paths are generated correctly."""
        paths = get_permissions_config_file_paths(str(mock_project))
        assert len(paths) == 3
        assert str(mock_project) in paths[1]
        assert str(mock_project) in paths[2]
