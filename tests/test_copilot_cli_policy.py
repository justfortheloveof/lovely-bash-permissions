"""In-process contract tests for Copilot policy loading and precedence."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.usefixtures("isolate_copilot_process")


class TestCopilotCliPolicy:
    @pytest.fixture(autouse=True)
    def _install_helpers(self, copilot_test_helpers: SimpleNamespace) -> None:
        self.helpers = copilot_test_helpers

    def test_test_mode_uses_the_current_directory_for_project_policy(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        copilot_home = tmp_path / "copilot-home"
        self.helpers.policy(copilot_home, {"bash": {"*": "deny"}})
        monkeypatch.setenv("COPILOT_HOME", str(copilot_home))
        checkout = self.helpers.git_checkout(tmp_path / "checkout")
        self.helpers.project_policy(checkout, {"bash": {"*": "allow"}})
        monkeypatch.chdir(checkout)

        status, output, stderr = self.helpers.invoke_cli(monkeypatch, "", args=["--test", "git status"])

        assert status == 0
        assert stderr == ""
        _, decision = self.helpers.response_from(output)
        assert decision == {"permissionDecision": "allow"}

    def test_missing_policy_asks_by_default(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("COPILOT_HOME", str(tmp_path / "empty-copilot-home"))

        status, output, _ = self.helpers.invoke_cli(monkeypatch, json.dumps(self.helpers.event("echo hi")))

        assert status == 0
        _, decision = self.helpers.response_from(output)
        assert decision["permissionDecision"] == "ask"
        assert decision["permissionDecisionReason"]

    def test_allowed_patterns_from_global_and_project_policies_are_merged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        copilot_home = tmp_path / "copilot-home"
        self.helpers.policy(copilot_home, {"bash": {"allowed_cmds_regex": ["^echo global$"]}})
        monkeypatch.setenv("COPILOT_HOME", str(copilot_home))
        checkout = self.helpers.git_checkout(tmp_path / "checkout")
        nested = checkout / "nested"
        nested.mkdir()
        self.helpers.project_policy(checkout, {"bash": {"allowed_cmds_regex": ["^echo project$"]}})

        for command in ("echo global", "echo project"):
            status, output, stderr = self.helpers.invoke_cli(
                monkeypatch, json.dumps(self.helpers.event(command, cwd=str(nested)))
            )

            assert status == 0
            assert stderr == ""
            _, decision = self.helpers.response_from(output)
            assert decision == {"permissionDecision": "allow"}

    @pytest.mark.parametrize("source", ["project", "local"])
    @pytest.mark.parametrize("contents", ["{ malformed", '{"bash":{"*":"invalid"}}'])
    def test_invalid_repository_or_local_policy_denies_even_with_valid_global_policy(
        self,
        source: str,
        contents: str,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        copilot_home = tmp_path / "copilot-home"
        self.helpers.policy(copilot_home, {"bash": {"*": "allow"}})
        monkeypatch.setenv("COPILOT_HOME", str(copilot_home))
        checkout = self.helpers.git_checkout(tmp_path / "checkout")
        nested = checkout / "nested"
        nested.mkdir()
        invalid_path = self.helpers.project_policy(checkout, {}, local=source == "local")
        invalid_path.write_text(contents, encoding="utf-8")

        status, output, _ = self.helpers.invoke_cli(
            monkeypatch, json.dumps(self.helpers.event("echo hi", cwd=str(nested)))
        )

        assert status == 0
        _, decision = self.helpers.response_from(output)
        assert decision["permissionDecision"] == "deny"
        assert str(invalid_path) in decision["permissionDecisionReason"]

    @pytest.mark.parametrize("source", ["project", "local"])
    def test_unreadable_repository_or_local_policy_denies(
        self, source: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        checkout = self.helpers.git_checkout(tmp_path / "checkout")
        nested = checkout / "nested"
        nested.mkdir()
        unreadable_path = self.helpers.project_policy(checkout, {}, local=source == "local")
        unreadable_path.unlink()
        unreadable_path.mkdir()

        status, output, _ = self.helpers.invoke_cli(
            monkeypatch, json.dumps(self.helpers.event("echo hi", cwd=str(nested)))
        )

        assert status == 0
        _, decision = self.helpers.response_from(output)
        assert decision["permissionDecision"] == "deny"
        assert "cannot read" in decision["permissionDecisionReason"]
        assert str(unreadable_path) in decision["permissionDecisionReason"]

    def test_default_home_is_used_when_copilot_home_is_unset(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self.helpers.policy(tmp_path / ".copilot", {"bash": {"*": "deny"}})
        monkeypatch.delenv("COPILOT_HOME", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path))

        status, output, _ = self.helpers.invoke_cli(monkeypatch, json.dumps(self.helpers.event("echo hi")))

        assert status == 0
        _, decision = self.helpers.response_from(output)
        assert decision["permissionDecision"] == "deny"

    @pytest.mark.parametrize("contents", ["{invalid", json.dumps({"bash": {"*": "unsafe"}})])
    def test_invalid_global_policy_denies(self, contents: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        copilot_home = tmp_path / "copilot-home"
        copilot_home.mkdir()
        (copilot_home / "lovely-permissions.jsonc").write_text(contents, encoding="utf-8")
        monkeypatch.setenv("COPILOT_HOME", str(copilot_home))

        status, output, _ = self.helpers.invoke_cli(monkeypatch, json.dumps(self.helpers.event("echo hi")))

        assert status == 0
        _, decision = self.helpers.response_from(output)
        assert decision["permissionDecision"] == "deny"
        assert decision["permissionDecisionReason"]

    def test_unreadable_global_policy_denies(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        copilot_home = tmp_path / "copilot-home"
        copilot_home.mkdir()
        (copilot_home / "lovely-permissions.jsonc").mkdir()
        monkeypatch.setenv("COPILOT_HOME", str(copilot_home))

        status, output, _ = self.helpers.invoke_cli(monkeypatch, json.dumps(self.helpers.event("echo hi")))

        assert status == 0
        _, decision = self.helpers.response_from(output)
        assert decision["permissionDecision"] == "deny"
        assert "cannot read global Copilot policy" in decision["permissionDecisionReason"]
