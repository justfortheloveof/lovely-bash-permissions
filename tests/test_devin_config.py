"""Tests for Devin config loader."""

import json
import os
import tempfile

import pytest

from lovely_bash_permissions.config.devin import (
    exec_permission_to_regex,
    get_devin_global_config_dir,
    load_devin_exec_permissions,
    load_devin_exec_regexes,
)


def _write_temp_file(content: str, suffix: str = ".json") -> str:
    """Write content to a temporary file and return its path."""
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "w") as f:
        f.write(content)
    return path


def _clean_temp_file(path: str):
    """Remove a temporary file."""
    if os.path.exists(path):
        os.remove(path)


def _create_project_with_configs(
    project_dir, global_config=None, project_config=None, local_config=None
):
    """Create a project directory with optional config files."""
    # Create project .devin directory
    devin_dir = os.path.join(project_dir, ".devin")
    os.makedirs(devin_dir, exist_ok=True)

    if global_config is not None:
        global_file = os.path.join(get_devin_global_config_dir(), "config.json")
        os.makedirs(os.path.dirname(global_file), exist_ok=True)
        with open(global_file, "w") as f:
            f.write(json.dumps(global_config))

    if project_config is not None:
        project_file = os.path.join(devin_dir, "config.json")
        with open(project_file, "w") as f:
            f.write(json.dumps(project_config))

    if local_config is not None:
        local_file = os.path.join(devin_dir, "config.local.json")
        with open(local_file, "w") as f:
            f.write(json.dumps(local_config))


class TestExecPermissionToRegex:
    """Tests for exec_permission_to_regex function."""

    def test_simple_command(self):
        assert exec_permission_to_regex("git") == "^git(\\s|$)"

    def test_command_with_args(self):
        assert exec_permission_to_regex("npm run") == "^npm run(\\s|$)"

    def test_colon_prefix(self):
        assert exec_permission_to_regex(":") == "^:(\\s|$)"

    def test_escapes_regexp_chars(self):
        assert exec_permission_to_regex("echo $HOME") == "^echo \\$HOME(\\s|$)"
        assert exec_permission_to_regex("cat file.txt") == "^cat file\\.txt(\\s|$)"
        assert exec_permission_to_regex("cmd [arg]") == "^cmd \\[arg\\](\\s|$)"

    def test_trims_whitespace(self):
        assert exec_permission_to_regex("  git  ") == "^git(\\s|$)"


class TestLoadDevinExecPermissions:
    """Tests for load_devin_exec_permissions function."""

    def test_no_config_files(self):
        with (
            tempfile.TemporaryDirectory() as project,
            tempfile.TemporaryDirectory() as devin_global,
        ):
            os.environ["DEVIN_GLOBAL_CONFIG_DIR"] = devin_global
            try:
                result = load_devin_exec_permissions(project)
                assert result["permissions"] == []
                assert result["errors"] == []
            finally:
                del os.environ["DEVIN_GLOBAL_CONFIG_DIR"]

    def test_global_config_only(self):
        with tempfile.TemporaryDirectory() as project:
            _create_project_with_configs(
                project,
                global_config={"permissions": {"allow": ["Exec(git)", "Read(**)"]}},
            )
            try:
                result = load_devin_exec_permissions(project)
                assert len(result["permissions"]) == 1
                assert result["permissions"][0]["regex"] == "^git(\\s|$)"
                assert result["errors"] == []
            finally:
                _clean_temp_file(
                    os.path.join(get_devin_global_config_dir(), "config.json")
                )

    def test_project_config_only(self):
        with tempfile.TemporaryDirectory() as project:
            _create_project_with_configs(
                project,
                project_config={
                    "permissions": {"allow": ["Exec(npm run)", "Write(src/**)"]}
                },
            )
            result = load_devin_exec_permissions(project)
            assert len(result["permissions"]) == 1
            assert result["permissions"][0]["regex"] == "^npm run(\\s|$)"
            assert result["errors"] == []

    def test_local_config_only(self):
        with tempfile.TemporaryDirectory() as project:
            _create_project_with_configs(
                project,
                local_config={"permissions": {"allow": ["Exec(docker compose)"]}},
            )
            result = load_devin_exec_permissions(project)
            assert len(result["permissions"]) == 1
            assert result["permissions"][0]["regex"] == "^docker compose(\\s|$)"
            assert result["errors"] == []

    def test_all_three_sources(self):
        with tempfile.TemporaryDirectory() as project:
            _create_project_with_configs(
                project,
                global_config={"permissions": {"allow": ["Exec(git)"]}},
                project_config={"permissions": {"allow": ["Exec(npm run)"]}},
                local_config={"permissions": {"allow": ["Exec(docker compose)"]}},
            )
            try:
                result = load_devin_exec_permissions(project)
                assert len(result["permissions"]) == 3
                regexes = [p["regex"] for p in result["permissions"]]
                assert "^git(\\s|$)" in regexes
                assert "^npm run(\\s|$)" in regexes
                assert "^docker compose(\\s|$)" in regexes
            finally:
                _clean_temp_file(
                    os.path.join(get_devin_global_config_dir(), "config.json")
                )

    def test_ignores_non_exec_entries(self):
        with tempfile.TemporaryDirectory() as project:
            _create_project_with_configs(
                project,
                project_config={
                    "permissions": {
                        "allow": [
                            "Read(**)",
                            "Exec(git)",
                            "Write(src/**)",
                            "mcp__github__list_issues",
                            123,
                            None,
                        ]
                    }
                },
            )
            result = load_devin_exec_permissions(project)
            assert len(result["permissions"]) == 1
            assert result["permissions"][0]["regex"] == "^git(\\s|$)"
            assert result["errors"] == []

    def test_reports_malformed_exec_entries(self):
        with tempfile.TemporaryDirectory() as project:
            _create_project_with_configs(
                project,
                project_config={
                    "permissions": {
                        "allow": [
                            "Exec(git)",
                            "Exec()",
                            "Exec(  )",
                            "Exec((unclosed",
                            "Exec(foo",
                            "Exec(git",
                            "Read(**)",
                        ]
                    }
                },
            )
            result = load_devin_exec_permissions(project)
            assert len(result["permissions"]) == 1
            assert result["permissions"][0]["regex"] == "^git(\\s|$)"
            assert len(result["errors"]) == 5  # The malformed ones

    def test_gracefully_handles_malformed_json(self):
        with tempfile.TemporaryDirectory() as project:
            devin_dir = os.path.join(project, ".devin")
            os.makedirs(devin_dir, exist_ok=True)
            project_file = os.path.join(devin_dir, "config.json")
            with open(project_file, "w") as f:
                f.write("{invalid json}")
            result = load_devin_exec_permissions(project)
            assert result["permissions"] == []
            assert result["errors"] == []

    def test_empty_permissions_allow(self):
        with tempfile.TemporaryDirectory() as project:
            _create_project_with_configs(
                project, project_config={"permissions": {"allow": []}}
            )
            result = load_devin_exec_permissions(project)
            assert result["permissions"] == []
            assert result["errors"] == []


class TestLoadDevinExecRegexes:
    """Tests for load_devin_exec_regexes function."""

    def test_returns_deduplicated_regexes(self):
        with tempfile.TemporaryDirectory() as project:
            _create_project_with_configs(
                project,
                project_config={"permissions": {"allow": ["Exec(git)", "Exec(git)"]}},
            )
            result = load_devin_exec_regexes(project)
            assert result == ["^git(\\s|$)"]

    def test_throws_on_malformed_entries(self):
        with tempfile.TemporaryDirectory() as project:
            _create_project_with_configs(
                project,
                project_config={"permissions": {"allow": ["Exec(git)", "Exec()"]}},
            )
            with pytest.raises(ValueError):
                load_devin_exec_regexes(project)
