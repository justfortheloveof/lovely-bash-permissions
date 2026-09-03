"""Tests for lovely-devin-permissions config loader.

Tests deep merge behavior, file loading, and merge precedence.
"""

import json
import tempfile
from pathlib import Path

import pytest

from lovely_bash_permissions.config.loader import (
    get_permissions_config_file_paths,
    load_permissions_config,
    merge_deep,
)


class TestMergeDeep:
    """Tests for the deep merge function."""

    def test_empty_inputs(self) -> None:
        assert merge_deep({}, {}) == {}

    def test_scalar_override(self) -> None:
        result = merge_deep({"a": 1}, {"a": 2})
        assert result == {"a": 2}

    def test_new_keys_added(self) -> None:
        result = merge_deep({"a": 1}, {"b": 2})
        assert result == {"a": 1, "b": 2}

    def test_nested_objects_merged(self) -> None:
        target = {"outer": {"inner": 1}}
        source = {"outer": {"inner2": 2}}
        result = merge_deep(target, source)
        assert result == {"outer": {"inner": 1, "inner2": 2}}

    def test_nested_objects_override(self) -> None:
        target = {"tool": {"perm": "deny"}}
        source = {"tool": {"perm": "allow"}}
        result = merge_deep(target, source)
        assert result == {"tool": {"perm": "allow"}}

    def test_deeply_nested_objects(self) -> None:
        target = {"a": {"b": {"c": 1}}}
        source = {"a": {"b": {"d": 2}}}
        result = merge_deep(target, source)
        assert result == {"a": {"b": {"c": 1, "d": 2}}}

    def test_arrays_concatenated(self) -> None:
        target = {"items": [1, 2]}
        source = {"items": [3, 4]}
        result = merge_deep(target, source)
        assert result == {"items": [1, 2, 3, 4]}

    def test_mixed_types(self) -> None:
        target = {"scalar": "a", "obj": {"x": 1}, "arr": [1]}
        source = {"scalar": "b", "obj": {"y": 2}, "arr": [2]}
        result = merge_deep(target, source)
        assert result == {
            "scalar": "b",
            "obj": {"x": 1, "y": 2},
            "arr": [1, 2],
        }

    def test_none_values_override(self) -> None:
        target = {"tool": {"perm": "deny"}}
        source = {"tool": None}
        # None is not an object, so it overrides
        result = merge_deep(target, source)
        assert result == {"tool": None}

    def test_original_dicts_not_mutated(self) -> None:
        target = {"a": 1, "obj": {"x": 1}}
        source = {"b": 2, "obj": {"y": 2}}
        merge_deep(target, source)
        assert target == {"a": 1, "obj": {"x": 1}}
        assert source == {"b": 2, "obj": {"y": 2}}


class TestGetPaths:
    """Tests for config file path generation."""

    def test_returns_three_paths(self) -> None:
        paths = get_permissions_config_file_paths("/project")
        assert len(paths) == 3

    def test_global_path(self) -> None:
        paths = get_permissions_config_file_paths("/project")
        assert "lovely-permissions.jsonc" in paths[0]
        assert ".config/devin" in paths[0]

    def test_project_path(self) -> None:
        paths = get_permissions_config_file_paths("/project")
        assert paths[1] == "/project/.devin/lovely-permissions.jsonc"

    def test_local_path(self) -> None:
        paths = get_permissions_config_file_paths("/project")
        assert paths[2] == "/project/.devin/lovely-permissions.local.jsonc"

    def test_trailing_slash_handled(self) -> None:
        paths = get_permissions_config_file_paths("/project/")
        assert paths[1] == "/project/.devin/lovely-permissions.jsonc"


class TestLoadPermissionsConfig:
    """Integration tests for config loading."""

    @pytest.fixture
    def temp_project(self) -> tuple[Path, Path]:
        """Create a temporary project directory structure."""
        tmpdir = tempfile.mkdtemp()
        devin_dir = Path(tmpdir) / ".devin"
        devin_dir.mkdir()
        return Path(tmpdir), devin_dir

    @pytest.fixture
    def temp_global(self) -> tuple[Path, Path]:
        """Create a temporary global config directory."""
        tmpdir = tempfile.mkdtemp()
        config_dir = Path(tmpdir) / ".config" / "devin"
        config_dir.mkdir(parents=True)
        return Path(tmpdir), config_dir

    def _write_jsonc(self, path: Path, data: dict) -> None:
        """Write data as JSONC to path."""
        path.write_text(json.dumps(data))

    def test_all_files_missing_raises(self, monkeypatch: pytest.MonkeyPatch, temp_global: tuple[Path, Path]) -> None:
        """No config files exist anywhere -> raises meaningful error."""
        monkeypatch.setattr(
            "lovely_bash_permissions.config.loader.get_devin_global_config_dir",
            lambda: temp_global[1],
        )
        with pytest.raises(FileNotFoundError, match="no valid lovely-permissions config found"):
            load_permissions_config(str(temp_global[0]))

    def test_global_only(self, monkeypatch: pytest.MonkeyPatch, temp_global: tuple[Path, Path]) -> None:
        """Only global config exists."""
        global_file = temp_global[1] / "lovely-permissions.jsonc"
        self._write_jsonc(global_file, {"read": {"permission": "allow"}})
        monkeypatch.setattr(
            "lovely_bash_permissions.config.loader.get_devin_global_config_dir",
            lambda: temp_global[1],
        )
        result = load_permissions_config(str(temp_global[0]))
        assert result == {"read": {"permission": "allow"}}

    def test_project_only(self, monkeypatch: pytest.MonkeyPatch, temp_project: tuple[Path, Path]) -> None:
        """Only project config exists."""
        tmpdir = tempfile.mkdtemp()
        config_dir = Path(tmpdir) / ".config" / "devin"
        config_dir.mkdir(parents=True)
        monkeypatch.setattr(
            "lovely_bash_permissions.config.loader.get_devin_global_config_dir",
            lambda: config_dir,
        )
        project_file = temp_project[1] / "lovely-permissions.jsonc"
        self._write_jsonc(project_file, {"bash": {"permission": "ask"}})
        result = load_permissions_config(str(temp_project[0]))
        assert result == {"bash": {"permission": "ask"}}

    def test_local_only(self, monkeypatch: pytest.MonkeyPatch, temp_project: tuple[Path, Path]) -> None:
        """Only local config exists."""
        tmpdir = tempfile.mkdtemp()
        config_dir = Path(tmpdir) / ".config" / "devin"
        config_dir.mkdir(parents=True)
        monkeypatch.setattr(
            "lovely_bash_permissions.config.loader.get_devin_global_config_dir",
            lambda: config_dir,
        )
        local_file = temp_project[1] / "lovely-permissions.local.jsonc"
        self._write_jsonc(local_file, {"write": {"permission": "deny"}})
        result = load_permissions_config(str(temp_project[0]))
        assert result == {"write": {"permission": "deny"}}

    def test_project_overrides_global(self, monkeypatch: pytest.MonkeyPatch, temp_global: tuple[Path, Path]) -> None:
        """Project config overrides global per tool."""
        global_file = temp_global[1] / "lovely-permissions.jsonc"
        self._write_jsonc(global_file, {"read": {"permission": "deny"}})

        # Use a real project dir
        project_dir = tempfile.mkdtemp()
        devin_dir = Path(project_dir) / ".devin"
        devin_dir.mkdir()
        project_file = devin_dir / "lovely-permissions.jsonc"
        self._write_jsonc(project_file, {"read": {"permission": "allow"}})

        monkeypatch.setattr(
            "lovely_bash_permissions.config.loader.get_devin_global_config_dir",
            lambda: temp_global[1],
        )
        result = load_permissions_config(project_dir)
        assert result == {"read": {"permission": "allow"}}

    def test_local_overrides_project(self, monkeypatch: pytest.MonkeyPatch, temp_project: tuple[Path, Path]) -> None:
        """Local config overrides project per tool."""
        tmpdir = tempfile.mkdtemp()
        config_dir = Path(tmpdir) / ".config" / "devin"
        config_dir.mkdir(parents=True)
        monkeypatch.setattr(
            "lovely_bash_permissions.config.loader.get_devin_global_config_dir",
            lambda: config_dir,
        )
        project_file = temp_project[1] / "lovely-permissions.jsonc"
        self._write_jsonc(project_file, {"read": {"permission": "deny"}})

        local_file = temp_project[1] / "lovely-permissions.local.jsonc"
        self._write_jsonc(local_file, {"read": {"permission": "ask"}})

        result = load_permissions_config(str(temp_project[0]))
        assert result == {"read": {"permission": "ask"}}

    def test_three_level_override(self, monkeypatch: pytest.MonkeyPatch, temp_global: tuple[Path, Path]) -> None:
        """Global < project < local precedence."""
        global_file = temp_global[1] / "lovely-permissions.jsonc"
        self._write_jsonc(global_file, {"tool": {"perm": "deny"}})

        project_dir = tempfile.mkdtemp()
        devin_dir = Path(project_dir) / ".devin"
        devin_dir.mkdir()
        project_file = devin_dir / "lovely-permissions.jsonc"
        self._write_jsonc(project_file, {"tool": {"perm": "ask"}})
        local_file = devin_dir / "lovely-permissions.local.jsonc"
        self._write_jsonc(local_file, {"tool": {"perm": "allow"}})

        monkeypatch.setattr(
            "lovely_bash_permissions.config.loader.get_devin_global_config_dir",
            lambda: temp_global[1],
        )
        result = load_permissions_config(project_dir)
        assert result == {"tool": {"perm": "allow"}}

    def test_merge_different_tools(self, monkeypatch: pytest.MonkeyPatch, temp_global: tuple[Path, Path]) -> None:
        """Different tool configs from different files merge together."""
        global_file = temp_global[1] / "lovely-permissions.jsonc"
        self._write_jsonc(global_file, {"read": {"permission": "allow"}})

        project_dir = tempfile.mkdtemp()
        devin_dir = Path(project_dir) / ".devin"
        devin_dir.mkdir()
        project_file = devin_dir / "lovely-permissions.jsonc"
        self._write_jsonc(project_file, {"bash": {"permission": "ask"}})

        monkeypatch.setattr(
            "lovely_bash_permissions.config.loader.get_devin_global_config_dir",
            lambda: temp_global[1],
        )
        result = load_permissions_config(project_dir)
        assert result == {
            "read": {"permission": "allow"},
            "bash": {"permission": "ask"},
        }

    def test_deep_merge_nested_objects(self, monkeypatch: pytest.MonkeyPatch, temp_global: tuple[Path, Path]) -> None:
        """Nested objects are merged, not replaced."""
        global_file = temp_global[1] / "lovely-permissions.jsonc"
        self._write_jsonc(
            global_file,
            {"bash": {"permission": "ask", "allowed_cmds_regex": ["^ls", "^cat"]}},
        )

        project_dir = tempfile.mkdtemp()
        devin_dir = Path(project_dir) / ".devin"
        devin_dir.mkdir()
        project_file = devin_dir / "lovely-permissions.jsonc"
        self._write_jsonc(
            project_file,
            {"bash": {"blocked_paths_regex": ["/tmp/"]}},
        )

        monkeypatch.setattr(
            "lovely_bash_permissions.config.loader.get_devin_global_config_dir",
            lambda: temp_global[1],
        )
        result = load_permissions_config(project_dir)
        assert result["bash"]["permission"] == "ask"
        assert result["bash"]["allowed_cmds_regex"] == ["^ls", "^cat"]
        assert result["bash"]["blocked_paths_regex"] == ["/tmp/"]

    def test_arrays_concatenated_across_files(
        self, monkeypatch: pytest.MonkeyPatch, temp_global: tuple[Path, Path]
    ) -> None:
        """Arrays from different files are concatenated."""
        global_file = temp_global[1] / "lovely-permissions.jsonc"
        self._write_jsonc(
            global_file,
            {"bash": {"allowed_cmds_regex": ["^ls", "^cat"]}},
        )

        project_dir = tempfile.mkdtemp()
        devin_dir = Path(project_dir) / ".devin"
        devin_dir.mkdir()
        project_file = devin_dir / "lovely-permissions.jsonc"
        self._write_jsonc(
            project_file,
            {"bash": {"allowed_cmds_regex": ["^mkdir"]}},
        )

        monkeypatch.setattr(
            "lovely_bash_permissions.config.loader.get_devin_global_config_dir",
            lambda: temp_global[1],
        )
        result = load_permissions_config(project_dir)
        assert result["bash"]["allowed_cmds_regex"] == ["^ls", "^cat", "^mkdir"]

    def test_invalid_json_all_files_raises(
        self, monkeypatch: pytest.MonkeyPatch, temp_project: tuple[Path, Path]
    ) -> None:
        """All files invalid JSON -> raises meaningful error."""
        tmpdir = tempfile.mkdtemp()
        config_dir = Path(tmpdir) / ".config" / "devin"
        config_dir.mkdir(parents=True)
        monkeypatch.setattr(
            "lovely_bash_permissions.config.loader.get_devin_global_config_dir",
            lambda: config_dir,
        )
        project_file = temp_project[1] / "lovely-permissions.jsonc"
        project_file.write_text("{invalid json}")
        with pytest.raises(FileNotFoundError, match="no valid lovely-permissions config found"):
            load_permissions_config(str(temp_project[0]))

    def test_json_with_comments_works(self, monkeypatch: pytest.MonkeyPatch, temp_project: tuple[Path, Path]) -> None:
        """JSONC files with comments parse correctly."""
        tmpdir = tempfile.mkdtemp()
        config_dir = Path(tmpdir) / ".config" / "devin"
        config_dir.mkdir(parents=True)
        monkeypatch.setattr(
            "lovely_bash_permissions.config.loader.get_devin_global_config_dir",
            lambda: config_dir,
        )
        project_file = temp_project[1] / "lovely-permissions.jsonc"
        project_file.write_text('{\n  // This is a comment\n  "bash": {\n    "permission": "allow"\n  }\n}')
        result = load_permissions_config(str(temp_project[0]))
        assert result == {"bash": {"permission": "allow"}}
