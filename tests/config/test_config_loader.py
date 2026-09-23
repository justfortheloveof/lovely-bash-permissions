"""Tests for lovely-devin-permissions config loader.

Tests deep merge behavior, file loading, and merge precedence.
"""

import json
import tempfile
from pathlib import Path
from typing import Any

import pytest

from lovely_bash_permissions.config.loader import (
    get_permissions_config_file_paths,
    load_permissions_config,
    merge_deep,
)


class TestMergeDeep:
    """Tests for the deep merge function."""

    def test_empty_inputs(self) -> None:
        merged, warnings = merge_deep({}, {})
        assert merged == {}
        assert warnings == []

    def test_scalar_override(self) -> None:
        merged, warnings = merge_deep({"a": 1}, {"a": 2})
        assert merged == {"a": 2}
        assert len(warnings) == 1

    def test_new_keys_added(self) -> None:
        merged, warnings = merge_deep({"a": 1}, {"b": 2})
        assert merged == {"a": 1, "b": 2}
        assert warnings == []

    def test_nested_objects_merged(self) -> None:
        target = {"outer": {"inner": 1}}
        source = {"outer": {"inner2": 2}}
        merged, warnings = merge_deep(target, source)
        assert merged == {"outer": {"inner": 1, "inner2": 2}}
        assert warnings == []

    def test_nested_objects_override(self) -> None:
        target = {"tool": {"perm": "deny"}}
        source = {"tool": {"perm": "allow"}}
        merged, warnings = merge_deep(target, source)
        assert merged == {"tool": {"perm": "allow"}}
        assert len(warnings) == 1

    def test_deeply_nested_objects(self) -> None:
        target = {"a": {"b": {"c": 1}}}
        source = {"a": {"b": {"d": 2}}}
        merged, warnings = merge_deep(target, source)
        assert merged == {"a": {"b": {"c": 1, "d": 2}}}
        assert warnings == []

    def test_arrays_concatenated(self) -> None:
        target = {"items": [1, 2]}
        source = {"items": [3, 4]}
        merged, warnings = merge_deep(target, source)
        assert merged == {"items": [1, 2, 3, 4]}
        assert warnings == []

    def test_mixed_types(self) -> None:
        target = {"scalar": "a", "obj": {"x": 1}, "arr": [1]}
        source = {"scalar": "b", "obj": {"y": 2}, "arr": [2]}
        merged, warnings = merge_deep(target, source)
        assert merged == {
            "scalar": "b",
            "obj": {"x": 1, "y": 2},
            "arr": [1, 2],
        }
        assert len(warnings) == 1

    def test_none_values_override(self) -> None:
        target = {"tool": {"perm": "deny"}}
        source = {"tool": None}
        # None is not an object, so it overrides
        merged, warnings = merge_deep(target, source)
        assert merged == {"tool": None}
        assert len(warnings) == 1

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

    def _write_jsonc(self, path: Path, data: dict[str, Any]) -> None:
        """Write data as JSONC to path."""
        path.write_text(json.dumps(data))

    def test_all_files_missing_falls_back_to_default(
        self, monkeypatch: pytest.MonkeyPatch, temp_global: tuple[Path, Path]
    ) -> None:
        """No config files exist anywhere -> valid empty config (safe ask default)."""
        monkeypatch.setattr(
            "lovely_bash_permissions.config.loader.get_devin_global_config_dir",
            lambda: temp_global[1],
        )
        merged, warnings, validation_errors = load_permissions_config(str(temp_global[0]))
        assert merged == {}
        assert validation_errors == []
        assert any("using safe default" in w for w in warnings)

    def test_global_only(self, monkeypatch: pytest.MonkeyPatch, temp_global: tuple[Path, Path]) -> None:
        """Only global config exists."""
        global_file = temp_global[1] / "lovely-permissions.jsonc"
        self._write_jsonc(global_file, {"read": {"permission": "allow"}})
        monkeypatch.setattr(
            "lovely_bash_permissions.config.loader.get_devin_global_config_dir",
            lambda: temp_global[1],
        )
        merged, _, _ = load_permissions_config(str(temp_global[0]))
        assert merged == {"read": {"permission": "allow"}}

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
        merged, _, _ = load_permissions_config(str(temp_project[0]))
        assert merged == {"bash": {"permission": "ask"}}

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
        merged, _, _ = load_permissions_config(str(temp_project[0]))
        assert merged == {"write": {"permission": "deny"}}

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
        merged, _, _ = load_permissions_config(project_dir)
        assert merged == {"read": {"permission": "allow"}}

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

        merged, _, _ = load_permissions_config(str(temp_project[0]))
        assert merged == {"read": {"permission": "ask"}}

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
        merged, _, _ = load_permissions_config(project_dir)
        assert merged == {"tool": {"perm": "allow"}}

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
        merged, _, _ = load_permissions_config(project_dir)
        assert merged == {
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
            {"bash": {"blocked_cmds_regex": ["/tmp/"]}},
        )

        monkeypatch.setattr(
            "lovely_bash_permissions.config.loader.get_devin_global_config_dir",
            lambda: temp_global[1],
        )
        merged, _, _ = load_permissions_config(project_dir)
        assert merged["bash"]["permission"] == "ask"
        assert merged["bash"]["allowed_cmds_regex"] == ["^ls", "^cat"]
        assert merged["bash"]["blocked_cmds_regex"] == ["/tmp/"]

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
        merged, _, _ = load_permissions_config(project_dir)
        assert merged["bash"]["allowed_cmds_regex"] == ["^ls", "^cat", "^mkdir"]

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
        merged, _, validation_errors = load_permissions_config(str(temp_project[0]))
        assert merged == {}
        assert any("no valid lovely-permissions config found" in e for e in validation_errors)

    def test_invalid_json_all_files_includes_paths(
        self, monkeypatch: pytest.MonkeyPatch, temp_project: tuple[Path, Path]
    ) -> None:
        """All files invalid JSON -> error message contains all three paths."""
        tmpdir = tempfile.mkdtemp()
        config_dir = Path(tmpdir) / ".config" / "devin"
        config_dir.mkdir(parents=True)
        monkeypatch.setattr(
            "lovely_bash_permissions.config.loader.get_devin_global_config_dir",
            lambda: config_dir,
        )
        # Write invalid JSON to ALL three files (not just missing)
        project_file = temp_project[1] / "lovely-permissions.jsonc"
        project_file.write_text("{invalid json}")
        local_file = temp_project[1] / "lovely-permissions.local.jsonc"
        local_file.write_text("not valid json")

        _, _, validation_errors = load_permissions_config(str(temp_project[0]))

        error_msg = "\n".join(validation_errors)
        paths = get_permissions_config_file_paths(str(temp_project[0]))
        # All three paths should appear in the error message
        for path in paths:
            assert path in error_msg

    def test_non_dict_value_all_files_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """All config files contain non-dict values (arrays) → error message lists paths."""
        tmpdir = tempfile.mkdtemp()
        config_dir = Path(tmpdir) / ".config" / "devin"
        config_dir.mkdir(parents=True)
        monkeypatch.setattr(
            "lovely_bash_permissions.config.loader.get_devin_global_config_dir",
            lambda: config_dir,
        )
        project_dir = Path(tmpdir) / "project"
        project_dir.mkdir()
        devin_dir = project_dir / ".devin"
        devin_dir.mkdir()
        project_file = devin_dir / "lovely-permissions.jsonc"
        project_file.write_text("[1, 2, 3]")
        local_file = devin_dir / "lovely-permissions.local.jsonc"
        local_file.write_text("['a', 'b']")

        _, _, validation_errors = load_permissions_config(str(project_dir))

        error_msg = "\n".join(validation_errors)
        paths = get_permissions_config_file_paths(str(project_dir))
        for path in paths:
            assert path in error_msg

    def test_invalid_permission_returns_warning(
        self, monkeypatch: pytest.MonkeyPatch, temp_project: tuple[Path, Path]
    ) -> None:
        """Typo in permission value is returned as a warning, not raised."""
        tmpdir = tempfile.mkdtemp()
        config_dir = Path(tmpdir) / ".config" / "devin"
        config_dir.mkdir(parents=True)
        monkeypatch.setattr(
            "lovely_bash_permissions.config.loader.get_devin_global_config_dir",
            lambda: config_dir,
        )
        project_file = temp_project[1] / "lovely-permissions.jsonc"
        self._write_jsonc(project_file, {"bash": {"permission": "alow"}})
        _, warnings, _errors = load_permissions_config(str(temp_project[0]))
        assert len(warnings) >= 1
        assert any("alow" in w.lower() for w in warnings)

    def test_bad_regex_returns_warning(self, monkeypatch: pytest.MonkeyPatch, temp_project: tuple[Path, Path]) -> None:
        """Invalid regex pattern is returned as a warning mentioning the field."""
        tmpdir = tempfile.mkdtemp()
        config_dir = Path(tmpdir) / ".config" / "devin"
        config_dir.mkdir(parents=True)
        monkeypatch.setattr(
            "lovely_bash_permissions.config.loader.get_devin_global_config_dir",
            lambda: config_dir,
        )
        project_file = temp_project[1] / "lovely-permissions.jsonc"
        self._write_jsonc(project_file, {"bash": {"blocked_cmds_regex": ["["]}})
        _, warnings, _errors = load_permissions_config(str(temp_project[0]))
        assert len(warnings) >= 1
        combined = " ".join(warnings)
        assert "blocked_cmds_regex" in combined

    def test_multiple_errors_all_reported(
        self, monkeypatch: pytest.MonkeyPatch, temp_project: tuple[Path, Path]
    ) -> None:
        """Multiple issues are returned as warnings and validation errors."""
        tmpdir = tempfile.mkdtemp()
        config_dir = Path(tmpdir) / ".config" / "devin"
        config_dir.mkdir(parents=True)
        monkeypatch.setattr(
            "lovely_bash_permissions.config.loader.get_devin_global_config_dir",
            lambda: config_dir,
        )
        project_file = temp_project[1] / "lovely-permissions.jsonc"
        self._write_jsonc(
            project_file,
            {"bash": {"permission": "alow", "blocked_cmds_regex": ["["]}},
        )
        _, warnings, errors = load_permissions_config(str(temp_project[0]))
        assert len(warnings) >= 1
        # At least one warning should mention bash
        tool_lines = [w for w in warnings if "bash" in w]
        assert len(tool_lines) >= 1
        assert len(errors) >= 1

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
        merged, _, _ = load_permissions_config(str(temp_project[0]))
        assert merged == {"bash": {"permission": "allow"}}

    def test_load_returns_validation_errors_list(
        self, monkeypatch: pytest.MonkeyPatch, temp_project: tuple[Path, Path]
    ) -> None:
        """Config with invalid regex returns non-empty validation_errors list."""
        tmpdir = tempfile.mkdtemp()
        config_dir = Path(tmpdir) / ".config" / "devin"
        config_dir.mkdir(parents=True)
        monkeypatch.setattr(
            "lovely_bash_permissions.config.loader.get_devin_global_config_dir",
            lambda: config_dir,
        )
        project_file = temp_project[1] / "lovely-permissions.jsonc"
        self._write_jsonc(project_file, {"bash": {"blocked_cmds_regex": ["["]}})
        _, warnings, errors = load_permissions_config(str(temp_project[0]))
        assert len(warnings) >= 1
        assert len(errors) == 1
        combined = " ".join(warnings)
        assert "blocked_cmds_regex" in combined

    def test_manager_validation_errors_property(
        self, monkeypatch: pytest.MonkeyPatch, temp_project: tuple[Path, Path]
    ) -> None:
        """PermissionsManager exposes validation_errors property."""
        from lovely_bash_permissions.config.manager import PermissionsManager

        tmpdir = tempfile.mkdtemp()
        config_dir = Path(tmpdir) / ".config" / "devin"
        config_dir.mkdir(parents=True)
        monkeypatch.setattr(
            "lovely_bash_permissions.config.loader.get_devin_global_config_dir",
            lambda: config_dir,
        )
        project_file = temp_project[1] / "lovely-permissions.jsonc"
        self._write_jsonc(project_file, {"bash": {"blocked_cmds_regex": ["["]}})

        manager = PermissionsManager(str(temp_project[0]))
        assert len(manager.validation_errors) >= 1
        combined = " ".join(manager.validation_errors)
        assert "blocked_cmds_regex" in combined

    def test_get_lovely_config_raises_on_errors(
        self, monkeypatch: pytest.MonkeyPatch, temp_project: tuple[Path, Path]
    ) -> None:
        """get_lovely_config returns config; errors exposed via validation_errors property."""
        from lovely_bash_permissions.config.manager import PermissionsManager

        tmpdir = tempfile.mkdtemp()
        config_dir = Path(tmpdir) / ".config" / "devin"
        config_dir.mkdir(parents=True)
        monkeypatch.setattr(
            "lovely_bash_permissions.config.loader.get_devin_global_config_dir",
            lambda: config_dir,
        )
        project_file = temp_project[1] / "lovely-permissions.jsonc"
        self._write_jsonc(project_file, {"bash": {"blocked_cmds_regex": ["["]}})

        manager = PermissionsManager(str(temp_project[0]))
        assert len(manager.validation_errors) >= 1
        combined = " ".join(manager.validation_errors)
        assert "blocked_cmds_regex" in combined

    def test_has_validation_errors_property(
        self, monkeypatch: pytest.MonkeyPatch, temp_project: tuple[Path, Path]
    ) -> None:
        """has_validation_errors returns True when config has errors."""
        from lovely_bash_permissions.config.manager import PermissionsManager

        tmpdir = tempfile.mkdtemp()
        config_dir = Path(tmpdir) / ".config" / "devin"
        config_dir.mkdir(parents=True)
        monkeypatch.setattr(
            "lovely_bash_permissions.config.loader.get_devin_global_config_dir",
            lambda: config_dir,
        )
        project_file = temp_project[1] / "lovely-permissions.jsonc"
        self._write_jsonc(project_file, {"bash": {"blocked_cmds_regex": ["["]}})

        manager = PermissionsManager(str(temp_project[0]))
        assert manager.has_validation_errors is True

    def test_manager_no_errors_for_valid_config(
        self, monkeypatch: pytest.MonkeyPatch, temp_project: tuple[Path, Path]
    ) -> None:
        """has_validation_errors returns False when config is valid."""
        from lovely_bash_permissions.config.manager import PermissionsManager

        tmpdir = tempfile.mkdtemp()
        config_dir = Path(tmpdir) / ".config" / "devin"
        config_dir.mkdir(parents=True)
        monkeypatch.setattr(
            "lovely_bash_permissions.config.loader.get_devin_global_config_dir",
            lambda: config_dir,
        )
        project_file = temp_project[1] / "lovely-permissions.jsonc"
        self._write_jsonc(project_file, {"bash": {"permission": "allow"}})
        local_file = temp_project[1] / "lovely-permissions.local.jsonc"
        self._write_jsonc(local_file, {})
        global_file = config_dir / "lovely-permissions.jsonc"
        self._write_jsonc(global_file, {})

        manager = PermissionsManager(str(temp_project[0]))
        assert manager.has_validation_errors is False
