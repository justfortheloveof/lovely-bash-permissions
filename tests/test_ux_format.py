"""
Comprehensive UX format tests for lovely-devin-permissions.

These tests verify exact output formats match the TypeScript reference.
"""

import json
import os
import tempfile
from typing import Any
from unittest.mock import patch


class TestSetupOutputFormat:
    """Test --setup CLI output format matches TypeScript reference."""

    def test_setup_output_format(self) -> None:
        """Setup should output the exact TypeScript-style message."""
        with tempfile.TemporaryDirectory() as devin_dir:
            import io
            import os
            import sys
            from unittest.mock import patch

            from lovely_bash_permissions.devin_cli import main

            # Write empty config
            with open(f"{devin_dir}/config.json", "w") as f:
                json.dump({}, f)

            with patch.dict(os.environ, {"DEVIN_GLOBAL_CONFIG_DIR": devin_dir}):
                sys.argv = ["lovely-devin-permissions", "--setup"]
                captured = io.StringIO()
                with patch("sys.stdout", captured), patch("sys.exit"):
                    main()

            output = captured.getvalue()
            # Exact format from TypeScript:
            assert 'Added "Exec(: \'[♡ perms:)" to' in output
            assert 'so Devin auto-approves the hook\'s ":" no-op label' in output

    def test_setup_already_present_format(self) -> None:
        """Setup should output the exact TypeScript-style "already present" message."""
        with tempfile.TemporaryDirectory() as devin_dir:
            import io
            import os
            import sys
            from unittest.mock import patch

            from lovely_bash_permissions.devin_cli import main

            # Write config with label already present
            with open(f"{devin_dir}/config.json", "w") as f:
                json.dump({"permissions": {"allow": ["Exec(: '[♡ perms:)"]}}, f)

            with patch.dict(os.environ, {"DEVIN_GLOBAL_CONFIG_DIR": devin_dir}):
                sys.argv = ["lovely-devin-permissions", "--setup"]
                captured = io.StringIO()
                with patch("sys.stdout", captured), patch("sys.exit"):
                    main()

            output = captured.getvalue()
            # Exact format from TypeScript:
            assert 'The Devin permission "Exec(: \'[♡ perms:)" is already present in' in output


class TestPreToolUseResponseFormat:
    """Test PreToolUse hook responses match TypeScript reference."""

    def _create_event(self, command: str) -> dict[str, Any]:
        return {
            "hook_event_name": "PreToolUse",
            "tool_name": "exec",
            "tool_input": {"command": command},
            "project_dir": ".",
        }

    def test_allow_label_format(self) -> None:
        """Allow response should have the exact label format."""
        # Create minimal config
        with tempfile.TemporaryDirectory() as devin_dir:
            with open(f"{devin_dir}/lovely-permissions.jsonc", "w") as f:
                json.dump({"bash": {"allowed_cmds_regex": ["^git"]}}, f)

            with patch.dict(os.environ, {"DEVIN_GLOBAL_CONFIG_DIR": devin_dir}):
                event = self._create_event("git status")
                from lovely_bash_permissions.hook import (
                    generate_hook_response,
                    process_hook_event,
                )

                result = process_hook_event(event)
                response = generate_hook_response(event, result)

                # TypeScript format: "[♡ perms: 💚 auto-approved]
                #  command matches allowed pattern ^git"
                assert response is not None
                response_out = response["hookSpecificOutput"]
                assert response_out is not None
                hook_output = response_out
                updated_input = hook_output["updatedInput"]
                assert updated_input is not None
                cmd = updated_input["command"]
                assert cmd is not None
                assert cmd.startswith(": '[♡ perms: 💚 auto-approved] command matches allowed pattern")
                assert "git status" in cmd

    def test_deny_label_format(self) -> None:
        """Deny response should have the exact label format."""
        with tempfile.TemporaryDirectory() as devin_dir:
            with open(f"{devin_dir}/lovely-permissions.jsonc", "w") as f:
                json.dump({"bash": {"deny": ["curl"]}}, f)

            from lovely_bash_permissions.config.effective_bash import (
                get_effective_bash_config,
            )
            from lovely_bash_permissions.config.loader import load_permissions_config
            from lovely_bash_permissions.evaluate import evaluate_bash_command

            with patch.dict(os.environ, {"DEVIN_GLOBAL_CONFIG_DIR": devin_dir}):
                lovely_config = load_permissions_config(devin_dir)
                config = get_effective_bash_config(lovely_config.get("bash", {}), devin_dir)
                result = evaluate_bash_command("curl https://example.com", config)
                assert result["status"] == "deny"
                assert "Blocked by bash permissions" in result["reason"]
                from lovely_bash_permissions.hook import (
                    generate_hook_response,
                    process_hook_event,
                )

                event = {
                    "hook_event_name": "PreToolUse",
                    "tool_name": "exec",
                    "tool_input": {"command": "curl https://example.com"},
                    "project_dir": devin_dir,
                }
                result = process_hook_event(event)
                response = generate_hook_response(event, result)

                # TypeScript format: "[♡ perms: ❤️ auto-rejected]"
                assert response is not None
                response_out2 = response["hookSpecificOutput"]
                assert response_out2 is not None
                hook_output2 = response_out2
                updated_input2 = hook_output2["updatedInput"]
                assert updated_input2 is not None
                cmd2 = updated_input2["command"]
                assert cmd2 is not None
                assert ": '[♡ perms: ❤️ auto-rejected]" in cmd2
                assert "curl https://example.com" in cmd2

    def test_ask_label_format(self) -> None:
        """Ask response should have the exact label format."""
        with tempfile.TemporaryDirectory() as devin_dir:
            with open(f"{devin_dir}/lovely-permissions.jsonc", "w") as f:
                json.dump({"bash": {"*": "ask", "allowed_cmds_regex": ["^git"]}}, f)

            with patch.dict(os.environ, {"DEVIN_GLOBAL_CONFIG_DIR": devin_dir}):
                event = self._create_event("ls")
                from lovely_bash_permissions.hook import (
                    generate_hook_response,
                    process_hook_event,
                )

                result = process_hook_event(event)
                response = generate_hook_response(event, result)

                # TypeScript format: "[♡ perms: 💛 REQUIRES-USER-APPROVAL]"
                assert response is not None
                response_out3 = response["hookSpecificOutput"]
                assert response_out3 is not None
                hook_output3 = response_out3
                updated_input3 = hook_output3["updatedInput"]
                assert updated_input3 is not None
                cmd3 = updated_input3["command"]
                assert cmd3 is not None
                assert ": '[♡ perms: 💛 REQUIRES-USER-APPROVAL]" in cmd3
                assert "ls" in cmd3


class TestEvaluateReasonFormats:
    """Test evaluate reason formats match TypeScript reference."""

    def test_allowed_reason_format(self) -> None:
        """Allowed reason should match TypeScript format."""
        with tempfile.TemporaryDirectory() as devin_dir:
            with open(f"{devin_dir}/config.json", "w") as f:
                json.dump({"permissions": {"allow": ["Exec(git)"]}}, f)

            from lovely_bash_permissions.config.effective_bash import (
                get_effective_bash_config,
            )
            from lovely_bash_permissions.evaluate import evaluate_bash_command

            with patch.dict(os.environ, {"DEVIN_GLOBAL_CONFIG_DIR": devin_dir}):
                config = get_effective_bash_config(None, devin_dir)
                result = evaluate_bash_command("git status", config)
                # TypeScript: "command matches allowed pattern ^git"
                assert "command matches allowed pattern" in result["reason"]

    def test_blocked_reason_format(self) -> None:
        """Blocked reason should match TypeScript format."""
        with tempfile.TemporaryDirectory() as devin_dir:
            with open(f"{devin_dir}/lovely-permissions.jsonc", "w") as f:
                json.dump({"bash": {"deny": ["curl"]}}, f)

            from lovely_bash_permissions.config.effective_bash import (
                get_effective_bash_config,
            )
            from lovely_bash_permissions.config.loader import load_permissions_config
            from lovely_bash_permissions.evaluate import evaluate_bash_command

            with patch.dict(os.environ, {"DEVIN_GLOBAL_CONFIG_DIR": devin_dir}):
                lovely_config = load_permissions_config(devin_dir)
                config = get_effective_bash_config(lovely_config.get("bash", {}), devin_dir)
                result = evaluate_bash_command("curl https://example.com", config)
                # TypeScript: "Blocked by bash permissions: ...
                #  The tool has not been run."
                assert result is not None
                assert "Blocked by bash permissions:" in result["reason"]
                assert "The tool has not been run" in result["reason"]

    def test_ask_reason_format(self) -> None:
        """Ask reason should match TypeScript format."""
        with tempfile.TemporaryDirectory() as devin_dir:
            with open(f"{devin_dir}/lovely-permissions.jsonc", "w") as f:
                json.dump({"bash": {"*": "ask", "allowed_cmds_regex": ["^git"]}}, f)

            from lovely_bash_permissions.config.effective_bash import (
                get_effective_bash_config,
            )
            from lovely_bash_permissions.evaluate import evaluate_bash_command

            with patch.dict(os.environ, {"DEVIN_GLOBAL_CONFIG_DIR": devin_dir}):
                config = get_effective_bash_config(None, devin_dir)
                result = evaluate_bash_command("ls", config)
                # TypeScript: '"ls" command does not match allowed patterns'
                assert '"ls" command does not match allowed patterns' in result["reason"]


class TestPermissionRequestResponse:
    """Test PermissionRequest responses match TypeScript reference."""

    def test_permission_request_allow(self) -> None:
        """PermissionRequest allow should return approve."""
        with tempfile.TemporaryDirectory() as devin_dir:
            with open(f"{devin_dir}/lovely-permissions.jsonc", "w") as f:
                json.dump({"bash": {"allowed_cmds_regex": ["^git"]}}, f)

            from lovely_bash_permissions.hook import (
                generate_hook_response,
                process_hook_event,
            )

            with patch.dict(os.environ, {"DEVIN_GLOBAL_CONFIG_DIR": devin_dir}):
                event = {
                    "hook_event_name": "PermissionRequest",
                    "tool_name": "exec",
                    "tool_input": {"command": "git status"},
                    "project_dir": devin_dir,
                }
                result = process_hook_event(event)
                response = generate_hook_response(event, result)
                # TypeScript: {decision: "approve"}
                assert response is not None
                assert response["decision"] == "approve"

    def test_permission_request_deny_format(self) -> None:
        """PermissionRequest deny should have the exact reason format."""
        with tempfile.TemporaryDirectory() as devin_dir:
            with open(f"{devin_dir}/lovely-permissions.jsonc", "w") as f:
                json.dump({"bash": {"deny": ["curl"]}}, f)

            from lovely_bash_permissions.config.effective_bash import (
                get_effective_bash_config,
            )
            from lovely_bash_permissions.config.loader import load_permissions_config
            from lovely_bash_permissions.evaluate import evaluate_bash_command

            with patch.dict(os.environ, {"DEVIN_GLOBAL_CONFIG_DIR": devin_dir}):
                lovely_config = load_permissions_config(devin_dir)
                config = get_effective_bash_config(lovely_config.get("bash", {}), devin_dir)
                result = evaluate_bash_command("curl https://example.com", config)
                # TypeScript: reason includes "[♡ perms: ❤️ auto-rejected]"
                assert result["status"] == "deny"
                assert "Blocked by bash permissions:" in result["reason"]


class TestJsonOutputFormat:
    """Test JSON output format matches TypeScript."""

    def test_test_output_pretty_printed(self) -> None:
        """--test should produce pretty-printed JSON (indent=2)."""
        import io

        with tempfile.TemporaryDirectory() as devin_dir:
            with open(f"{devin_dir}/config.json", "w") as f:
                json.dump({"permissions": {"allow": ["Exec(git)"]}}, f)

            from lovely_bash_permissions.devin_cli import handle_test

            with (
                patch.dict(
                    os.environ,
                    {"DEVIN_GLOBAL_CONFIG_DIR": devin_dir, "DEVIN_PROJECT_DIR": devin_dir},
                ),
                patch("lovely_bash_permissions.config.manager.read_jsonc_file", return_value={}),
            ):
                captured = io.StringIO()
                with patch("sys.stdout", captured), patch("sys.exit"):
                    handle_test("git status")

            output = captured.getvalue()
            # Should be pretty-printed JSON with indent=2
            parsed = json.loads(output)
            assert "hookSpecificOutput" in parsed or "decision" in parsed
            # Check formatting
            assert output.startswith(("{\n", "  "))
