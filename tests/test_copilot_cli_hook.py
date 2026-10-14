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
    def test_test_mode_prints_one_final_decision_without_progress(
        self, verdict: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        copilot_home = tmp_path / "copilot-home"
        self.helpers.policy(copilot_home, {"bash": {"*": verdict}})
        monkeypatch.setenv("COPILOT_HOME", str(copilot_home))

        status, output, stderr = self.helpers.invoke_cli(monkeypatch, "", args=["--test", "git status"])

        assert status == 0
        assert stderr == ""
        lines = output.splitlines()
        assert len(lines) == 1
        decision = json.loads(lines[0])
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
        decision = json.loads(output)
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
        ("policy_config", "expected"),
        [
            ({"bash": {"*": "allow"}}, "allow"),
            ({"bash": {"*": "ask"}}, "ask"),
            ({"bash": {"*": "deny"}}, "deny"),
        ],
    )
    def test_each_policy_verdict_has_copilot_output_framing(
        self,
        policy_config: object,
        expected: str,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        copilot_home = tmp_path / "copilot-home"
        self.helpers.policy(copilot_home, policy_config)
        monkeypatch.setenv("COPILOT_HOME", str(copilot_home))

        status, output, stderr = self.helpers.invoke_cli(monkeypatch, json.dumps(self.helpers.event("echo hi")))

        assert status == 0
        assert stderr == ""
        progress, decision = self.helpers.response_from(output)
        assert expected in progress["message"]
        assert decision["permissionDecision"] == expected
        if expected == "allow":
            assert "permissionDecisionReason" not in decision
        else:
            assert decision["permissionDecisionReason"]

    def test_invocation_error_without_a_verdict_exits_nonzero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        status, output, stderr = self.helpers.invoke_cli(monkeypatch, "", args=["--unsupported"])

        assert status != 0
        assert output == ""
        assert "usage:" in stderr
