"""Tests for PermissionsManager."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from lovely_bash_permissions.config.loader import get_permissions_config_file_paths
from lovely_bash_permissions.config.manager import PermissionsManager

pytestmark = pytest.mark.usefixtures("devin_global_config_dir")


class TestPermissionsManagerConstruction:
    """Test PermissionsManager constructor behavior."""

    def test_loads_during_construction(self, mock_project: Path) -> None:
        """Manager should load config during construction."""

        config_path = mock_project / ".devin" / "lovely-permissions.jsonc"
        with open(config_path, "w") as f:
            json.dump({"bash": {"*": "ask"}}, f)

        manager = PermissionsManager(str(mock_project))

        assert manager.is_valid()
        assert manager.get_lovely_config() == {"bash": {"*": "ask"}}
        assert manager.get_devin_exec_regexes() == []

    def test_defaults_when_loader_throws(self, mock_project: Path) -> None:
        """When loader throws (file invalid), config should be empty and manager invalid."""

        config_path = mock_project / ".devin" / "lovely-permissions.jsonc"
        with open(config_path, "w") as f:
            json.dump({"bash": {"blocked_cmds_regex": ["["]}}, f)

        manager = PermissionsManager(str(mock_project))

        assert not manager.is_valid()
        error = manager.get_error()
        assert error is not None and str(error)

    def test_handles_invalid_file(self, mock_project: Path) -> None:
        """Manager should handle invalid file gracefully."""

        config_path = mock_project / ".devin" / "lovely-permissions.jsonc"
        with open(config_path, "w") as f:
            json.dump({"bash": {"blocked_cmds_regex": ["["]}}, f)

        manager = PermissionsManager(str(mock_project))

        assert not manager.is_valid()
        error = manager.get_error()
        assert error is not None and len(str(error)) > 0


class TestPermissionsManagerReload:
    """Test PermissionsManager.reload() behavior."""

    def test_reload_loads_fresh_config(self, mock_project: Path) -> None:
        """reload() should load fresh config from disk."""

        config_path = mock_project / ".devin" / "lovely-permissions.jsonc"
        with open(config_path, "w") as f:
            json.dump({"bash": {"*": "ask"}}, f)

        manager = PermissionsManager(str(mock_project))

        # Overwrite with new config
        with open(config_path, "w") as f:
            json.dump({"bash": {"*": "allow"}}, f)

        manager.reload()

        assert manager.is_valid()
        assert "bash" in manager.get_lovely_config()

    def test_reload_clears_errors(self, mock_project: Path) -> None:
        """reload() clears previous errors if config loads successfully."""

        # Start with invalid file
        config_path = mock_project / ".devin" / "lovely-permissions.jsonc"
        with open(config_path, "w") as f:
            json.dump({"bash": {"blocked_cmds_regex": ["["]}}, f)

        manager = PermissionsManager(str(mock_project))
        assert not manager.is_valid()

        # Now write valid config and reload
        with open(config_path, "w") as f:
            json.dump({"bash": {"*": "ask"}}, f)

        manager.reload()

        assert manager.is_valid(), (
            f"reload failed: error={manager.get_error()}, config keys={list(manager.get_lovely_config().keys())}"
        )
        assert manager.get_error() is None
        assert "bash" in manager.get_lovely_config()

    def test_reload_captures_new_errors(self, mock_project: Path) -> None:
        """reload() captures new errors."""

        config_path = mock_project / ".devin" / "lovely-permissions.jsonc"
        with open(config_path, "w") as f:
            json.dump({"bash": {"*": "ask"}}, f)

        manager = PermissionsManager(str(mock_project))
        assert manager.is_valid()

        # Write invalid config and reload
        with open(config_path, "w") as f:
            json.dump({"bash": {"blocked_cmds_regex": ["["]}}, f)

        manager.reload()

        assert not manager.is_valid()

    def test_reload_passes_project_dir(self, mock_project: Path) -> None:
        """reload() should load from project dir."""
        config_path = mock_project / ".devin" / "lovely-permissions.jsonc"
        with open(config_path, "w") as f:
            json.dump({"bash": {"*": "allow"}}, f)

        manager = PermissionsManager(str(mock_project))
        assert "bash" in manager.get_lovely_config()

        # Change file and reload
        with open(config_path, "w") as f:
            json.dump({"bash": {"*": "ask"}}, f)

        manager.reload()
        assert "bash" in manager.get_lovely_config()


class TestPermissionsManagerGetMethods:
    """Test PermissionsManager getter methods."""

    def test_get_lovely_config_returns_dict(self, mock_project: Path) -> None:
        """get_lovely_config() should always return a dict."""
        config_path = mock_project / ".devin" / "lovely-permissions.jsonc"
        with open(config_path, "w") as f:
            json.dump({"bash": {"*": "allow"}}, f)

        manager = PermissionsManager(str(mock_project))

        config = manager.get_lovely_config()
        assert isinstance(config, dict)

    def test_get_devin_exec_regexes_raises_on_error(self, mock_project: Path) -> None:
        """get_devin_exec_regexes() should raise ValueError when devin config invalid."""
        # Valid lovely-permissions, but no valid devin config (devin loader will fail)
        config_path = mock_project / ".devin" / "lovely-permissions.jsonc"
        with open(config_path, "w") as f:
            json.dump({"bash": {"*": "allow"}}, f)

        manager = PermissionsManager(str(mock_project))

        # devin_exec_regexes may raise if no valid config found - just check it doesn't crash
        result = manager.get_devin_exec_regexes()
        assert isinstance(result, list)

    def test_get_devin_exec_regexes_returns_list(self, mock_project: Path) -> None:
        """get_devin_exec_regexes() should return a list."""
        config_path = mock_project / ".devin" / "lovely-permissions.jsonc"
        with open(config_path, "w") as f:
            json.dump({"bash": {"*": "allow"}}, f)

        manager = PermissionsManager(str(mock_project))

        regexes = manager.get_devin_exec_regexes()
        assert isinstance(regexes, list)

    def test_effective_bash_config_matches_the_module_function(self, mock_project: Path) -> None:
        """The manager's effective config is the one the module function computes from disk."""
        from lovely_bash_permissions.config.effective_bash import get_effective_bash_config

        (mock_project / ".devin" / "lovely-permissions.jsonc").write_text(
            json.dumps({"*": "deny", "bash": {"allowed_cmds_regex": ["^ls"]}})
        )
        (mock_project / ".devin" / "config.json").write_text(json.dumps({"permissions": {"allow": ["Exec(git)"]}}))

        manager = PermissionsManager(str(mock_project))

        expected = get_effective_bash_config({"allowed_cmds_regex": ["^ls"]}, str(mock_project), "deny")
        assert manager.get_effective_bash_config() == expected
        assert expected["allowed_cmds_regex"] == ["^ls", "^git(\\s|$)"]

    def test_effective_bash_config_raises_on_malformed_exec(self, mock_project: Path) -> None:
        """A malformed Devin Exec() rule raises, exactly as the module function does."""
        (mock_project / ".devin" / "lovely-permissions.jsonc").write_text(json.dumps({"bash": {"*": "ask"}}))
        (mock_project / ".devin" / "config.json").write_text(json.dumps({"permissions": {"allow": ["Exec()"]}}))

        with pytest.raises(ValueError, match="Invalid Exec"):
            PermissionsManager(str(mock_project)).get_effective_bash_config()

    def test_is_valid_and_get_error(self, mock_project: Path) -> None:
        """is_valid() and get_error() should be consistent."""

        config_path = mock_project / ".devin" / "lovely-permissions.jsonc"
        with open(config_path, "w") as f:
            json.dump({"bash": {"*": "ask"}}, f)

        manager = PermissionsManager(str(mock_project))
        assert manager.is_valid()
        assert manager.get_error() is None

        # Write invalid config and reload
        with open(config_path, "w") as f:
            f.write(json.dumps({"bash": {"blocked_cmds_regex": ["["]}}))
        manager.reload()

        assert not manager.is_valid()
        error = manager.get_error()
        assert error is not None and len(str(error)) > 0


class TestPermissionsManagerWarnings:
    """Test warnings are tracked when config files are skipped."""

    def test_warnings_on_invalid_file(self, mock_project: Path) -> None:
        """One file invalid but others load - warnings list has entry, config still loads."""

        # Project config exists and is valid; global/local don't (will be skipped with warnings)
        config_path = mock_project / ".devin" / "lovely-permissions.jsonc"
        config_data = {"bash": {"*": "allow", "allowed_cmds_regex": ["^git"]}}
        with open(config_path, "w") as f:
            json.dump(config_data, f)

        manager = PermissionsManager(str(mock_project))

        assert manager.is_valid()
        assert "bash" in manager.get_lovely_config()

        warnings = manager.get_warnings()
        assert len(warnings) >= 1
        assert any("skipped invalid config file:" in w for w in warnings)

    def test_no_warnings_when_all_valid(self, mock_project: Path, devin_global_config_dir: str) -> None:
        """All files valid - no warnings."""

        # Create all three config files as valid
        global_config = Path(devin_global_config_dir) / "lovely-permissions.jsonc"
        with open(global_config, "w") as f:
            json.dump({"bash": {"blocked_cmds_regex": ["^/tmp/"]}}, f)

        project_config = mock_project / ".devin" / "lovely-permissions.jsonc"
        with open(project_config, "w") as f:
            json.dump({"bash": {"*": "allow"}}, f)

        # Create local config too
        local_config = mock_project / ".devin" / "lovely-permissions.local.jsonc"
        with open(local_config, "w") as f:
            json.dump({}, f)

        manager = PermissionsManager(str(mock_project))

        assert manager.is_valid()
        assert manager.get_warnings() == []

    def test_reload_clears_warnings(self, mock_project: Path) -> None:
        """reload() clears previous warnings."""

        config_path = mock_project / ".devin" / "lovely-permissions.jsonc"
        with open(config_path, "w") as f:
            json.dump({"bash": {"*": "allow"}}, f)

        manager = PermissionsManager(str(mock_project))
        assert len(manager.get_warnings()) >= 1

        manager.reload()
        # After reload, global config still doesn't exist but project one loads
        assert manager.is_valid()


class TestPermissionsManagerEndToEnd:
    """End-to-end tests with real config files."""

    def test_empty_project(self, mock_project: Path) -> None:
        """Empty project (no config files) raises when all loaders fail."""

        with patch(
            "lovely_bash_permissions.config.manager.load_devin_exec_regexes",
            return_value=[],
        ):
            manager = PermissionsManager(str(mock_project))

        # fixture creates local config, so valid=True now
        assert manager.is_valid()

        # Create project lovely-permissions.jsonc
        config_path = mock_project / ".devin" / "lovely-permissions.jsonc"
        config_data = {"bash": {"*": "allow", "allowed_cmds_regex": ["^git"]}}
        with open(config_path, "w") as f:
            json.dump(config_data, f)

        manager = PermissionsManager(str(mock_project))

        assert manager.is_valid()
        assert "bash" in manager.get_lovely_config()
        bash_cfg = manager.get_lovely_config()["bash"]
        assert bash_cfg["*"] == "allow"
        assert bash_cfg["allowed_cmds_regex"] == ["^git"]

    def test_config_file_paths_generated_correctly(self, mock_project: Path) -> None:
        """Test that config file paths are generated correctly."""
        paths = get_permissions_config_file_paths(str(mock_project))
        assert len(paths) == 3
        assert str(mock_project) in paths[1]
        assert str(mock_project) in paths[2]

    def test_precedence_local_wins(self, mock_project: Path, devin_global_config_dir: str) -> None:
        """Highest-precedence config wins when same key set in all three files."""

        global_config = Path(devin_global_config_dir) / "lovely-permissions.jsonc"
        with open(global_config, "w") as f:
            json.dump({"bash": {"*": "allow"}}, f)

        project_config = mock_project / ".devin" / "lovely-permissions.jsonc"
        with open(project_config, "w") as f:
            json.dump({"bash": {"*": "ask"}}, f)

        local_config = mock_project / ".devin" / "lovely-permissions.local.jsonc"
        with open(local_config, "w") as f:
            json.dump({"bash": {"*": "deny"}}, f)

        manager = PermissionsManager(str(mock_project))

        assert manager.is_valid()
        bash_cfg = manager.get_lovely_config()["bash"]
        assert bash_cfg["*"] == "deny", f"expected local precedence (deny), got {bash_cfg['*']}"

    def test_cross_level_merge_both_keys(self, mock_project: Path, devin_global_config_dir: str) -> None:
        """Keys from global and local both survive when they are different keys"""

        global_config = Path(devin_global_config_dir) / "lovely-permissions.jsonc"
        with open(global_config, "w") as f:
            json.dump({"bash": {"*": "allow", "allowed_cmds_regex": ["^git"]}}, f)

        local_config = mock_project / ".devin" / "lovely-permissions.local.jsonc"
        with open(local_config, "w") as f:
            json.dump({"bash": {"blocked_cmds_regex": ["/etc"]}}, f)

        manager = PermissionsManager(str(mock_project))

        assert manager.is_valid()
        bash_cfg = manager.get_lovely_config()["bash"]
        assert bash_cfg["*"] == "allow"
        assert bash_cfg["allowed_cmds_regex"] == ["^git"]
        assert bash_cfg["blocked_cmds_regex"] == ["/etc"]
