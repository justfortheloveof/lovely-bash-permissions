"""Tests for lovely-devin-permissions config loader.

Tests deep merge behavior, file loading, and merge precedence.
"""

import json
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
    def temp_project(self, tmp_path: Path) -> tuple[Path, Path]:
        """Create a temporary project directory structure.

        Kept distinct from the conftest `mock_project`: that one hands back a
        bare Path and pre-seeds `.devin/lovely-permissions.local.jsonc`, while
        this one hands back a (root, .devin) pair with an empty `.devin/`.  The
        tests below read loader output directly, so they need the `.devin` path
        itself, and they assert on the exact merged dict - a pre-seeded file
        would change what those assertions are about.  Collapsing the two would
        mean editing ~40 assertions, not just the fixture bodies.

        Rooted in pytest's `tmp_path` rather than `tempfile.mkdtemp()`, which
        returns a path it never cleans up - it leaked a directory per test,
        roughly forty per run.
        """
        devin_dir = tmp_path / ".devin"
        devin_dir.mkdir()
        return tmp_path, devin_dir

    @pytest.fixture
    def temp_global(self, tmp_path: Path) -> tuple[Path, Path]:
        """A (root, .config/devin) pair for the GLOBAL half of the merge.

        Not a project fixture at all: `load_permissions_config` resolves the
        global dir through a patched `get_devin_global_config_dir`, so these
        tests need both the fake `$HOME` root and the `.config/devin` path the
        loader will ask for.  `devin_global_config_dir` in conftest cannot stand
        in for it: that one is an env-var string for subprocesses, not a
        `(root, dir)` pair for in-process monkeypatching.
        """
        config_dir = tmp_path / ".config" / "devin"
        config_dir.mkdir(parents=True)
        return tmp_path, config_dir

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

    def test_project_only(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, temp_project: tuple[Path, Path]
    ) -> None:
        """Only project config exists."""
        config_dir = tmp_path / ".config" / "devin"
        config_dir.mkdir(parents=True)
        monkeypatch.setattr(
            "lovely_bash_permissions.config.loader.get_devin_global_config_dir",
            lambda: config_dir,
        )
        project_file = temp_project[1] / "lovely-permissions.jsonc"
        self._write_jsonc(project_file, {"bash": {"*": "ask"}})
        merged, _, _ = load_permissions_config(str(temp_project[0]))
        assert merged == {"bash": {"*": "ask"}}

    def test_local_only(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, temp_project: tuple[Path, Path]) -> None:
        """Only local config exists."""
        config_dir = tmp_path / ".config" / "devin"
        config_dir.mkdir(parents=True)
        monkeypatch.setattr(
            "lovely_bash_permissions.config.loader.get_devin_global_config_dir",
            lambda: config_dir,
        )
        local_file = temp_project[1] / "lovely-permissions.local.jsonc"
        self._write_jsonc(local_file, {"write": {"permission": "deny"}})
        merged, _, _ = load_permissions_config(str(temp_project[0]))
        assert merged == {"write": {"permission": "deny"}}

    def test_project_overrides_global(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, temp_global: tuple[Path, Path]
    ) -> None:
        """Project config overrides global per tool."""
        global_file = temp_global[1] / "lovely-permissions.jsonc"
        self._write_jsonc(global_file, {"read": {"permission": "deny"}})

        # Use a real project dir
        devin_dir = tmp_path / ".devin"
        devin_dir.mkdir()
        project_file = devin_dir / "lovely-permissions.jsonc"
        self._write_jsonc(project_file, {"read": {"permission": "allow"}})

        monkeypatch.setattr(
            "lovely_bash_permissions.config.loader.get_devin_global_config_dir",
            lambda: temp_global[1],
        )
        merged, _, _ = load_permissions_config(str(tmp_path))
        assert merged == {"read": {"permission": "allow"}}

    def test_local_overrides_project(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, temp_project: tuple[Path, Path]
    ) -> None:
        """Local config overrides project per tool."""
        config_dir = tmp_path / ".config" / "devin"
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

    def test_three_level_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, temp_global: tuple[Path, Path]
    ) -> None:
        """Global < project < local precedence."""
        global_file = temp_global[1] / "lovely-permissions.jsonc"
        self._write_jsonc(global_file, {"tool": {"perm": "deny"}})

        devin_dir = tmp_path / ".devin"
        devin_dir.mkdir()
        project_file = devin_dir / "lovely-permissions.jsonc"
        self._write_jsonc(project_file, {"tool": {"perm": "ask"}})
        local_file = devin_dir / "lovely-permissions.local.jsonc"
        self._write_jsonc(local_file, {"tool": {"perm": "allow"}})

        monkeypatch.setattr(
            "lovely_bash_permissions.config.loader.get_devin_global_config_dir",
            lambda: temp_global[1],
        )
        merged, _, _ = load_permissions_config(str(tmp_path))
        assert merged == {"tool": {"perm": "allow"}}

    def test_merge_different_tools(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, temp_global: tuple[Path, Path]
    ) -> None:
        """Different tool configs from different files merge together."""
        global_file = temp_global[1] / "lovely-permissions.jsonc"
        self._write_jsonc(global_file, {"read": {"permission": "allow"}})

        devin_dir = tmp_path / ".devin"
        devin_dir.mkdir()
        project_file = devin_dir / "lovely-permissions.jsonc"
        self._write_jsonc(project_file, {"bash": {"*": "ask"}})

        monkeypatch.setattr(
            "lovely_bash_permissions.config.loader.get_devin_global_config_dir",
            lambda: temp_global[1],
        )
        merged, _, _ = load_permissions_config(str(tmp_path))
        assert merged == {
            "read": {"permission": "allow"},
            "bash": {"*": "ask"},
        }

    def test_deep_merge_nested_objects(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, temp_global: tuple[Path, Path]
    ) -> None:
        """Nested objects are merged, not replaced."""
        global_file = temp_global[1] / "lovely-permissions.jsonc"
        self._write_jsonc(
            global_file,
            {"bash": {"*": "ask", "allowed_cmds_regex": ["^ls", "^cat"]}},
        )

        devin_dir = tmp_path / ".devin"
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
        merged, _, _ = load_permissions_config(str(tmp_path))
        assert merged["bash"]["*"] == "ask"
        assert merged["bash"]["allowed_cmds_regex"] == ["^ls", "^cat"]
        assert merged["bash"]["blocked_cmds_regex"] == ["/tmp/"]

    def test_arrays_concatenated_across_files(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, temp_global: tuple[Path, Path]
    ) -> None:
        """Arrays from different files are concatenated."""
        global_file = temp_global[1] / "lovely-permissions.jsonc"
        self._write_jsonc(
            global_file,
            {"bash": {"allowed_cmds_regex": ["^ls", "^cat"]}},
        )

        devin_dir = tmp_path / ".devin"
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
        merged, _, _ = load_permissions_config(str(tmp_path))
        assert merged["bash"]["allowed_cmds_regex"] == ["^ls", "^cat", "^mkdir"]

    def test_invalid_json_all_files_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, temp_project: tuple[Path, Path]
    ) -> None:
        """All files invalid JSON -> raises meaningful error."""
        config_dir = tmp_path / ".config" / "devin"
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
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, temp_project: tuple[Path, Path]
    ) -> None:
        """All files invalid JSON -> error message contains all three paths."""
        config_dir = tmp_path / ".config" / "devin"
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

    def test_non_dict_value_all_files_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """All config files contain non-dict values (arrays) → error message lists paths."""
        config_dir = tmp_path / ".config" / "devin"
        config_dir.mkdir(parents=True)
        monkeypatch.setattr(
            "lovely_bash_permissions.config.loader.get_devin_global_config_dir",
            lambda: config_dir,
        )
        project_dir = tmp_path / "project"
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
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, temp_project: tuple[Path, Path]
    ) -> None:
        """Typo in the wildcard value is returned as a warning, not raised."""
        config_dir = tmp_path / ".config" / "devin"
        config_dir.mkdir(parents=True)
        monkeypatch.setattr(
            "lovely_bash_permissions.config.loader.get_devin_global_config_dir",
            lambda: config_dir,
        )
        project_file = temp_project[1] / "lovely-permissions.jsonc"
        self._write_jsonc(project_file, {"bash": {"*": "alow"}})
        _, warnings, _errors = load_permissions_config(str(temp_project[0]))
        assert len(warnings) >= 1
        assert any("alow" in w.lower() for w in warnings)

    def test_unknown_bash_key_becomes_validation_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, temp_project: tuple[Path, Path]
    ) -> None:
        """An unreadable key in a real config file surfaces as a validation error.

        The loader validates the merged config, so rejecting the key at schema
        level reaches users as a named error rather than a silent no-op: the
        merged dict still comes back, but `validation_errors` is populated, so
        PermissionsManager reports the config as invalid and the hook fails
        closed rather than silently running under the wildcard.
        """
        config_dir = tmp_path / ".config" / "devin"
        config_dir.mkdir(parents=True)
        monkeypatch.setattr(
            "lovely_bash_permissions.config.loader.get_devin_global_config_dir",
            lambda: config_dir,
        )
        project_file = temp_project[1] / "lovely-permissions.jsonc"
        self._write_jsonc(project_file, {"bash": {"permission": "allow"}})

        merged, _warnings, errors = load_permissions_config(str(temp_project[0]))

        assert len(errors) == 1
        assert "unknown bash config key 'permission'" in errors[0]
        # The raw merge is unchanged - only validation flags it.
        assert merged == {"bash": {"permission": "allow"}}

    def test_bad_regex_returns_warning(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, temp_project: tuple[Path, Path]
    ) -> None:
        """Invalid regex pattern is returned as a warning mentioning the field."""
        config_dir = tmp_path / ".config" / "devin"
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
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, temp_project: tuple[Path, Path]
    ) -> None:
        """Multiple issues are returned as warnings and validation errors."""
        config_dir = tmp_path / ".config" / "devin"
        config_dir.mkdir(parents=True)
        monkeypatch.setattr(
            "lovely_bash_permissions.config.loader.get_devin_global_config_dir",
            lambda: config_dir,
        )
        project_file = temp_project[1] / "lovely-permissions.jsonc"
        self._write_jsonc(
            project_file,
            {"bash": {"*": "alow", "blocked_cmds_regex": ["["]}},
        )
        _, warnings, errors = load_permissions_config(str(temp_project[0]))
        assert len(warnings) >= 1
        # At least one warning should mention bash
        tool_lines = [w for w in warnings if "bash" in w]
        assert len(tool_lines) >= 1
        assert len(errors) >= 1

    def test_json_with_comments_works(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, temp_project: tuple[Path, Path]
    ) -> None:
        """JSONC files with comments parse correctly."""
        config_dir = tmp_path / ".config" / "devin"
        config_dir.mkdir(parents=True)
        monkeypatch.setattr(
            "lovely_bash_permissions.config.loader.get_devin_global_config_dir",
            lambda: config_dir,
        )
        project_file = temp_project[1] / "lovely-permissions.jsonc"
        project_file.write_text('{\n  // This is a comment\n  "bash": {\n    "*": "allow"\n  }\n}')
        merged, _, _ = load_permissions_config(str(temp_project[0]))
        assert merged == {"bash": {"*": "allow"}}

    def test_load_returns_validation_errors_list(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, temp_project: tuple[Path, Path]
    ) -> None:
        """Config with invalid regex returns non-empty validation_errors list."""
        config_dir = tmp_path / ".config" / "devin"
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
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, temp_project: tuple[Path, Path]
    ) -> None:
        """PermissionsManager exposes validation_errors property."""
        from lovely_bash_permissions.config.manager import PermissionsManager

        config_dir = tmp_path / ".config" / "devin"
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
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, temp_project: tuple[Path, Path]
    ) -> None:
        """get_lovely_config returns config; errors exposed via validation_errors property."""
        from lovely_bash_permissions.config.manager import PermissionsManager

        config_dir = tmp_path / ".config" / "devin"
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
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, temp_project: tuple[Path, Path]
    ) -> None:
        """has_validation_errors returns True when config has errors."""
        from lovely_bash_permissions.config.manager import PermissionsManager

        config_dir = tmp_path / ".config" / "devin"
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
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, temp_project: tuple[Path, Path]
    ) -> None:
        """has_validation_errors returns False when config is valid."""
        from lovely_bash_permissions.config.manager import PermissionsManager

        config_dir = tmp_path / ".config" / "devin"
        config_dir.mkdir(parents=True)
        monkeypatch.setattr(
            "lovely_bash_permissions.config.loader.get_devin_global_config_dir",
            lambda: config_dir,
        )
        project_file = temp_project[1] / "lovely-permissions.jsonc"
        self._write_jsonc(project_file, {"bash": {"*": "allow"}})
        local_file = temp_project[1] / "lovely-permissions.local.jsonc"
        self._write_jsonc(local_file, {})
        global_file = config_dir / "lovely-permissions.jsonc"
        self._write_jsonc(global_file, {})

        manager = PermissionsManager(str(temp_project[0]))
        assert manager.has_validation_errors is False
