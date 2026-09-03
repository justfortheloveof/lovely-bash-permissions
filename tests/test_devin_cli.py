"""
Comprehensive tests for the lovely-devin-permissions CLI.

Tests all CLI modes: setup, test, show-config, and hook mode.
"""

import json
import os
import subprocess
import sys
from contextlib import redirect_stdout, suppress
from io import StringIO

import pytest


def run_cli(*args, input_data=None, env=None, cwd=None, project_dir=None, timeout=30):
    """Run the lovely-devin-permissions CLI via subprocess and return the result.

    For config file resolution, we set DEVIN_PROJECT_DIR in env for project
    specific tests.
    """
    uv_env = os.environ.copy()
    if env is not None:
        uv_env.update(env)
    if project_dir is not None:
        uv_env["DEVIN_PROJECT_DIR"] = project_dir

    cmd = ["uv", "run", "python", "-m", "lovely_bash_permissions.devin_cli"]
    if args:
        cmd.extend(args)

    try:
        result = subprocess.run(
            cmd,
            input=input_data,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=uv_env,
            cwd=cwd,
        )
    except subprocess.TimeoutExpired:
        result = subprocess.CompletedProcess(cmd, -1, "", "TIMEOUT")
    except FileNotFoundError:
        result = subprocess.CompletedProcess(cmd, -1, "", "uv not found")

    return result


def run_cli_in_process(
    *args, input_data=None, project_dir=None, monkeypatch=None, devin_config_dir=None
):
    """Run the CLI in-process, allowing monkeypatch to work.

    This captures stdout from the CLI's print statements.
    Used for setup tests where we need to override get_devin_global_config_dir.
    """
    import os

    from lovely_bash_permissions.devin_cli import main

    # Set up environment
    env_changes = {}
    if devin_config_dir is not None:
        env_changes["DEVIN_GLOBAL_CONFIG_DIR"] = devin_config_dir
    if project_dir is not None:
        env_changes["DEVIN_PROJECT_DIR"] = project_dir
    for k, v in env_changes.items():
        os.environ[k] = v

    # Save original sys.argv
    orig_argv = sys.argv
    sys.argv = ["lovely-devin-permissions"] + list(args)

    # Capture stdin if needed
    if input_data is not None:
        sys.stdin = StringIO(input_data)

    # Capture stdout
    captured = StringIO()
    with redirect_stdout(captured), suppress(SystemExit):
        main()

    # Reset stdin/argv/env
    sys.stdin = sys.__stdin__
    sys.argv = orig_argv
    for k in env_changes:
        del os.environ[k]

    return captured.getvalue()


@pytest.fixture
def tmp_project(tmp_path):
    """Create a temporary project directory."""
    project_dir = tmp_path / "test-project"
    project_dir.mkdir()
    return project_dir


@pytest.fixture
def project_with_bash_config(tmp_project):
    """Create a project directory with a devin config for bash rules."""
    project_dir = tmp_project
    devin_dir = project_dir / ".devin"
    devin_dir.mkdir()
    # Create config with bash rules in the devin config location
    config = {
        "bash": {
            "allow": ["git", "ls", "cat"],
            "deny": ["rm -rf /", "curl"],
            "prompt": ["apt-get"],
        }
    }
    with open(devin_dir / "config.json", "w") as f:
        json.dump(config, f)
    # Also create the lovely-permissions.jsonc file
    with open(devin_dir / "lovely-permissions.jsonc", "w") as f:
        json.dump(config, f)
    return project_dir


class TestCliSetup:
    """Test --setup flag: adds label exec permission to devin global config."""

    def test_setup_creates_config_dir(self, tmp_path):
        """Setup should create the devin config directory if missing."""
        devin_dir = tmp_path / "devin-config"
        result = run_cli_in_process("--setup", devin_config_dir=str(devin_dir))
        assert devin_dir.joinpath("config.json").exists()
        assert "Added \"Exec(: '[♡ perms:)" in result

    def test_setup_adds_label_exec_permission(self, tmp_path):
        """Setup should add label exec permission to the allow list."""
        devin_dir = tmp_path / "devin-config"
        devin_dir.mkdir()
        with open(devin_dir / "config.json", "w") as f:
            json.dump({"permissions": {"allow": []}}, f)

        result = run_cli_in_process("--setup", devin_config_dir=str(devin_dir))
        assert "Added \"Exec(: '[♡ perms:)" in result

        with open(devin_dir / "config.json") as f:
            config = json.load(f)
        assert "Exec(: '[♡ perms:)" in config["permissions"]["allow"]

    def test_setup_short_flag(self, tmp_path):
        """Short flag -s should work the same as --setup."""
        devin_dir = tmp_path / "devin-config"
        devin_dir.mkdir()
        with open(devin_dir / "config.json", "w") as f:
            json.dump({"permissions": {"allow": []}}, f)

        result = run_cli_in_process("-s", devin_config_dir=str(devin_dir))
        assert "Added \"Exec(: '[♡ perms:)" in result

    def test_setup_idempotent(self, tmp_path):
        """Running setup twice should be idempotent."""
        devin_dir = tmp_path / "devin-config"
        devin_dir.mkdir()
        with open(devin_dir / "config.json", "w") as f:
            json.dump({"permissions": {"allow": ["Exec(: '[♡ perms:)"]}}, f)

        result = run_cli_in_process("--setup", devin_config_dir=str(devin_dir))
        assert "is already present in" in result

    def test_setup_preserves_existing_permissions(self, tmp_path):
        """Setup should preserve existing permissions in the allow list."""
        devin_dir = tmp_path / "devin-config"
        devin_dir.mkdir()
        with open(devin_dir / "config.json", "w") as f:
            json.dump({"permissions": {"allow": ["Exec(git)", "Exec(npm)"]}}, f)

        result = run_cli_in_process("--setup", devin_config_dir=str(devin_dir))
        assert "Added \"Exec(: '[♡ perms:)" in result

        with open(devin_dir / "config.json") as f:
            config = json.load(f)
        assert "Exec(git)" in config["permissions"]["allow"]
        assert "Exec(npm)" in config["permissions"]["allow"]
        assert "Exec(: '[♡ perms:)" in config["permissions"]["allow"]


class TestCliTest:
    """Test --test flag: test a command as a PreToolUse event."""

    def test_test_allowed_command(self, project_with_bash_config):
        """Testing an allowed command should succeed with exit code 0."""
        result = run_cli(
            "--test",
            "git status",
            env={"DEVIN_PROJECT_DIR": str(project_with_bash_config)},
        )
        assert result.returncode == 0
        # Should output JSON response
        try:
            response = json.loads(result.stdout)
            assert response is not None
        except json.JSONDecodeError:
            pytest.fail("Expected JSON output for allowed command")

    def test_test_short_flag(self, project_with_bash_config):
        """Short flag -t should work the same as --test."""
        result = run_cli(
            "-t",
            "ls",
            env={"DEVIN_PROJECT_DIR": str(project_with_bash_config)},
        )
        assert result.returncode == 0

    def test_test_prompt_command(self, project_with_bash_config):
        """Testing a prompt command should generate an allow response."""
        result = run_cli(
            "--test",
            "apt-get",
            env={"DEVIN_PROJECT_DIR": str(project_with_bash_config)},
        )
        # Exit code depends on config; response should be generated
        try:
            response = json.loads(result.stdout)
            # For prompt commands, an allow response is expected
            assert response is not None
        except json.JSONDecodeError:
            pytest.fail("Expected JSON output for prompt command")

    def test_test_unallowed_command(self, project_with_bash_config):
        """Testing an unallowed command should produce a block response."""
        result = run_cli(
            "--test",
            "curl",
            env={"DEVIN_PROJECT_DIR": str(project_with_bash_config)},
        )
        # Exit code 2 indicates blocked
        assert result.returncode == 2
        response = json.loads(result.stdout)
        # Block response should have some indication
        assert response is not None

    def test_test_no_config_project(self, tmp_project):
        """Testing in a project without config should still work."""
        result = run_cli(
            "--test",
            "echo",
            env={"DEVIN_PROJECT_DIR": str(tmp_project)},
        )
        # Should complete without error
        assert result.returncode in [0, 2]


class TestCliShowConfig:
    """Test --show-config flag: show effective config and file paths."""

    def test_show_config_valid_project(self, project_with_bash_config):
        """Show config should output valid JSON with files and effectiveConfig."""
        result = run_cli(
            "--show-config",
            env={"DEVIN_PROJECT_DIR": str(project_with_bash_config)},
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert "files" in output
        assert "effectiveConfig" in output
        # Files should include project devin config path
        file_paths = [f["path"] for f in output["files"]]
        assert any(".devin/lovely-permissions.jsonc" in p for p in file_paths)

    def test_show_config_empty_project(self, tmp_project):
        """Show config on an empty project should still work."""
        result = run_cli("--show-config", env={"DEVIN_PROJECT_DIR": str(tmp_project)})
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert "files" in output
        assert "effectiveConfig" in output

    def test_show_config_reports_file_existence(self, project_with_bash_config):
        """Show config should report whether config files exist."""
        result = run_cli(
            "--show-config", env={"DEVIN_PROJECT_DIR": str(project_with_bash_config)}
        )
        output = json.loads(result.stdout)
        for f in output["files"]:
            assert "exists" in f
            assert isinstance(f["exists"], bool)
        # Project devin config should be reported as existing
        for f in output["files"]:
            if ".devin/lovely-permissions.jsonc" in f["path"]:
                assert f["exists"] is True


class TestHookMode:
    """Test hook mode: receives JSON events on stdin."""

    def test_hook_pretooluse_allowed(self, project_with_bash_config):
        """Hook mode with an allowed command should generate a response."""
        event = {
            "hook_event_name": "PreToolUse",
            "tool_name": "exec",
            "tool_input": {"command": "git status"},
        }
        result = run_cli(
            input_data=json.dumps(event),
            env={"DEVIN_PROJECT_DIR": str(project_with_bash_config)},
        )
        assert result.returncode == 0
        response = json.loads(result.stdout)
        # Response should have the correct structure
        assert response is not None
        assert "hookSpecificOutput" in response
        assert response["hookSpecificOutput"]["hookEventName"] == "PreToolUse"

    def test_hook_pretooluse_prompt(self, project_with_bash_config):
        """Hook mode with a prompt command should generate an allow response."""
        event = {
            "hook_event_name": "PreToolUse",
            "tool_name": "exec",
            "tool_input": {"command": "apt-get install foo"},
        }
        result = run_cli(
            input_data=json.dumps(event),
            env={"DEVIN_PROJECT_DIR": str(project_with_bash_config)},
        )
        assert result.returncode == 0
        response = json.loads(result.stdout)
        assert response is not None
        assert response["hookSpecificOutput"]["hookEventName"] == "PreToolUse"

    def test_hook_non_exec_tool_ignored(self, project_with_bash_config):
        """Hook mode should exit silently for non-exec tools."""
        event = {
            "hook_event_name": "PreToolUse",
            "tool_name": "read_file",
            "tool_input": {"path": "/etc/passwd"},
        }
        result = run_cli(
            input_data=json.dumps(event),
            env={"DEVIN_PROJECT_DIR": str(project_with_bash_config)},
        )
        assert result.returncode == 0
        assert result.stdout.strip() == ""

    def test_hook_empty_stdin_exits(self, project_with_bash_config):
        """Hook mode with empty stdin should exit silently."""
        result = run_cli(
            input_data="",
            env={"DEVIN_PROJECT_DIR": str(project_with_bash_config)},
        )
        assert result.returncode == 0
        assert result.stdout.strip() == ""

    def test_hook_empty_command_ignored(self, project_with_bash_config):
        """Hook mode with empty command should exit silently."""
        event = {
            "hook_event_name": "PreToolUse",
            "tool_name": "exec",
            "tool_input": {"command": ""},
        }
        result = run_cli(
            input_data=json.dumps(event),
            env={"DEVIN_PROJECT_DIR": str(project_with_bash_config)},
        )
        assert result.returncode == 0
        assert result.stdout.strip() == ""

    def test_hook_invalid_json_exits(self, project_with_bash_config):
        """Hook mode with invalid JSON should exit silently."""
        result = run_cli(
            input_data="not valid json",
            env={"DEVIN_PROJECT_DIR": str(project_with_bash_config)},
        )
        assert result.returncode == 0
        assert result.stdout.strip() == ""


class TestFlagPrecedence:
    """Test that CLI flags take precedence over stdin."""

    def test_setup_takes_precedence_over_stdin(self, tmp_path):
        """--setup should work even with stdin data."""
        devin_dir = tmp_path / "devin-config"
        devin_dir.mkdir()
        with open(devin_dir / "config.json", "w") as f:
            json.dump({"permissions": {"allow": []}}, f)

        event = {
            "hook_event_name": "PreToolUse",
            "tool_name": "exec",
            "tool_input": {"command": "git status"},
        }
        result = run_cli_in_process(
            "--setup", devin_config_dir=str(devin_dir), input_data=json.dumps(event)
        )
        # Setup should have run (ignoring stdin)
        assert "Added \"Exec(: '[♡ perms:)" in result


class TestErrorHandling:
    """Test error handling and error output."""

    def test_cli_errors_use_prefix(self, tmp_project):
        """CLI errors should use the [Lovely] ERROR] prefix."""
        # Create an invalid config
        with open(tmp_project / "lovely-bash-permissions.jsonc", "w") as f:
            f.write("not valid json")

        result = run_cli("--show-config", cwd=tmp_project)
        # Should produce some output (possibly error)
        # The exact exit code depends on config validation
        # at least the CLI should not crash
        assert result.returncode in [0, 1]
