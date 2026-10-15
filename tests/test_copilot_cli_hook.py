"""In-process contract tests for the Copilot hook protocol and test mode."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.usefixtures("isolate_copilot_process")


class TestCopilotCliHook:
    @pytest.fixture(autouse=True)
    def _install_helpers(self, copilot_test_helpers: SimpleNamespace) -> None:
        self.helpers = copilot_test_helpers

    @pytest.mark.parametrize(
        "verdict",
        ["allow", "ask", "deny"],
    )
    def test_test_mode_prints_same_progress_and_decision_as_hook(
        self, verdict: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        copilot_home = tmp_path / "copilot-home"
        self.helpers.policy(copilot_home, {"bash": {"*": verdict}})
        monkeypatch.setenv("COPILOT_HOME", str(copilot_home))

        hook_status, hook_output, hook_stderr = self.helpers.invoke_cli(
            monkeypatch,
            json.dumps(self.helpers.event()),
        )
        test_status, test_output, test_stderr = self.helpers.invoke_cli(monkeypatch, "", args=["--test", "git status"])

        assert hook_status == test_status == 0
        assert hook_stderr == test_stderr == ""
        assert test_output == hook_output
        _, decision = self.helpers.response_from(test_output)
        assert decision["permissionDecision"] == verdict
        if verdict == "allow":
            assert "permissionDecisionReason" not in decision
        else:
            assert decision["permissionDecisionReason"]

    def test_test_mode_evaluates_empty_command_with_configured_error_policy(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        copilot_home = tmp_path / "copilot-home"
        self.helpers.policy(copilot_home, {"bash": {"error": "deny"}})
        monkeypatch.setenv("COPILOT_HOME", str(copilot_home))

        status, output, stderr = self.helpers.invoke_cli(monkeypatch, "", args=["--test", ""])

        assert status == 0
        assert stderr == ""
        _, decision = self.helpers.response_from(output)
        assert decision["permissionDecision"] == "deny"
        assert "error evaluating command" in decision["permissionDecisionReason"]

    def test_test_mode_usage_failure_exits_nonzero_without_a_verdict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        status, output, stderr = self.helpers.invoke_cli(monkeypatch, "", args=["--test"])

        assert status != 0
        assert output == ""
        assert "usage:" in stderr

    def test_object_tool_args_use_global_copilot_home_policy(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        copilot_home = tmp_path / "copilot-home"
        self.helpers.policy(copilot_home, {"bash": {"allowed_cmds_regex": ["^git status$"]}})
        monkeypatch.setenv("COPILOT_HOME", str(copilot_home))

        status, output, stderr = self.helpers.invoke_cli(monkeypatch, json.dumps(self.helpers.event()))

        assert status == 0
        assert stderr == ""
        progress, decision = self.helpers.response_from(output)
        assert "allow" in progress["message"]
        assert decision == {"permissionDecision": "allow"}

    def test_json_encoded_tool_args_are_accepted(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        copilot_home = tmp_path / "copilot-home"
        self.helpers.policy(copilot_home, {"*": "deny"})
        monkeypatch.setenv("COPILOT_HOME", str(copilot_home))
        payload = self.helpers.event(tool_args=json.dumps({"command": "git status"}))

        status, output, _ = self.helpers.invoke_cli(monkeypatch, json.dumps(payload))

        assert status == 0
        _, decision = self.helpers.response_from(output)
        assert decision["permissionDecision"] == "deny"
        assert decision["permissionDecisionReason"]

    def test_other_tools_produce_no_decision(self, monkeypatch: pytest.MonkeyPatch) -> None:
        status, output, stderr = self.helpers.invoke_cli(monkeypatch, json.dumps(self.helpers.event(tool_name="read")))

        assert status == 0
        assert output == ""
        assert stderr == ""

    @pytest.mark.parametrize(
        "payload",
        [
            "not JSON",
            "[]",
            json.dumps({"toolName": "bash", "toolArgs": {}}),
            json.dumps({"toolName": "bash", "toolArgs": {"command": 42}}),
            json.dumps({"toolName": "bash", "toolArgs": "not JSON"}),
            json.dumps({"toolName": "bash", "toolArgs": "[]"}),
        ],
    )
    def test_malformed_payloads_and_commands_are_denied(self, payload: str, monkeypatch: pytest.MonkeyPatch) -> None:
        status, output, _ = self.helpers.invoke_cli(monkeypatch, payload)

        assert status == 0
        _, decision = self.helpers.response_from(output)
        assert decision["permissionDecision"] == "deny"
        assert decision["permissionDecisionReason"]

    def test_empty_command_uses_global_error_policy(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        copilot_home = tmp_path / "copilot-home"
        self.helpers.policy(copilot_home, {"bash": {"error": "deny"}})
        monkeypatch.setenv("COPILOT_HOME", str(copilot_home))

        status, output, _ = self.helpers.invoke_cli(monkeypatch, json.dumps(self.helpers.event(command="")))

        assert status == 0
        _, decision = self.helpers.response_from(output)
        assert decision["permissionDecision"] == "deny"
        assert "error evaluating command" in decision["permissionDecisionReason"]

    @pytest.mark.parametrize(
        ("policy_config", "expected", "expected_message", "expected_decision"),
        [
            (
                {"bash": {"*": "allow"}},
                "allow",
                "[♡ perms: 💚 auto-approved]\n- allowed by wildcard policy (allow)",
                {"permissionDecision": "allow"},
            ),
            (
                {"bash": {"*": "ask"}},
                "ask",
                '[♡ perms: 💛 REQUIRES-USER-APPROVAL]\n- "git" command is not allowlisted; wildcard policy is ask',
                {
                    "permissionDecision": "ask",
                    "permissionDecisionReason": (
                        '[♡ perms: 💛 REQUIRES-USER-APPROVAL]\n- "git" command is not allowlisted; '
                        "wildcard policy is ask"
                    ),
                },
            ),
            (
                {"bash": {"*": "deny"}},
                "deny",
                '[♡ perms: ❤️ auto-rejected]\n- "git" command is not allowlisted; wildcard policy is deny',
                {
                    "permissionDecision": "deny",
                    "permissionDecisionReason": (
                        '[♡ perms: ❤️ auto-rejected]\n- "git" command is not allowlisted; wildcard policy is deny'
                    ),
                },
            ),
        ],
    )
    def test_each_policy_verdict_has_copilot_output_framing(
        self,
        policy_config: object,
        expected: str,
        expected_message: str,
        expected_decision: dict[str, str],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        copilot_home = tmp_path / "copilot-home"
        self.helpers.policy(copilot_home, policy_config)
        monkeypatch.setenv("COPILOT_HOME", str(copilot_home))

        status, output, stderr = self.helpers.invoke_cli(monkeypatch, json.dumps(self.helpers.event()))

        assert status == 0
        assert stderr == ""
        assert len(output.splitlines()) == 2
        progress, decision = self.helpers.response_from(output)
        assert progress == {"type": "progress", "message": expected_message}
        assert decision == expected_decision
        assert decision["permissionDecision"] == expected

    def test_multiple_reasons_are_separate_bullets_in_both_output_modes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        copilot_home = tmp_path / "copilot-home"
        self.helpers.policy(
            copilot_home,
            {
                "bash": {
                    "*": "ask",
                    "allowed_cmds_regex": ["^cat$"],
                    "blocked_cmds_regex": [],
                    "input_redirection": "ask",
                    "output_redirection": "ask",
                    "background_execution": "ask",
                }
            },
        )
        monkeypatch.setenv("COPILOT_HOME", str(copilot_home))
        command = "cat < /tmp/in > /tmp/out &"

        hook_status, hook_output, hook_stderr = self.helpers.invoke_cli(
            monkeypatch,
            json.dumps(self.helpers.event(command)),
        )
        test_status, test_output, test_stderr = self.helpers.invoke_cli(
            monkeypatch,
            "",
            args=["--test", command],
        )

        expected_message = (
            "[♡ perms: 💛 REQUIRES-USER-APPROVAL]\n"
            "- output redirection requires approval\n"
            "- input redirection requires approval\n"
            "- background execution requires approval: cat"
        )
        assert hook_status == test_status == 0
        assert hook_stderr == test_stderr == ""
        assert test_output == hook_output
        assert len(hook_output.splitlines()) == 2
        progress, decision = self.helpers.response_from(hook_output)
        assert progress == {"type": "progress", "message": expected_message}
        assert decision == {
            "permissionDecision": "ask",
            "permissionDecisionReason": expected_message,
        }

    def test_invocation_error_without_a_verdict_exits_nonzero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        status, output, stderr = self.helpers.invoke_cli(monkeypatch, "", args=["--unsupported"])

        assert status != 0
        assert output == ""
        assert "usage:" in stderr
