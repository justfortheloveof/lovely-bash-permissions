"""In-process contract tests for Copilot configuration diagnostics."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.usefixtures("isolate_copilot_process")


class TestCopilotCliDiagnostics:
    @pytest.fixture(autouse=True)
    def _install_helpers(self, copilot_test_helpers: SimpleNamespace) -> None:
        self.helpers = copilot_test_helpers

    def test_show_config_reports_policy_sources_approvals_and_effective_bash_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        copilot_home = tmp_path / "copilot-home"
        self.helpers.policy(copilot_home, {"*": "deny", "bash": {"allowed_cmds_regex": ["^echo policy$"]}})
        monkeypatch.setenv("COPILOT_HOME", str(copilot_home))
        self.helpers.saved_approvals(
            copilot_home,
            {str(tmp_path): {"tool_approvals": [{"kind": "commands", "commandIdentifiers": ["git status"]}]}},
        )

        status, output, stderr = self.helpers.invoke_cli(monkeypatch, "", args=["--show-config"])

        assert status == 0
        assert stderr == ""
        result = json.loads(output)
        assert result["policySources"] == [
            {
                "scope": "global",
                "path": str(copilot_home / "lovely-permissions.jsonc"),
                "exists": True,
            },
            {
                "scope": "project",
                "path": str(tmp_path / ".github" / "copilot" / "lovely-permissions.jsonc"),
                "exists": False,
            },
            {
                "scope": "local",
                "path": str(tmp_path / ".github" / "copilot" / "lovely-permissions.local.jsonc"),
                "exists": False,
            },
        ]
        assert result["savedApprovalSource"] == {
            "path": str(copilot_home / "permissions-config.json"),
            "exists": True,
        }
        assert result["permissionLocation"] == str(tmp_path)
        assert result["importedApprovals"] == ["git status"]
        effective = result["effectiveBashConfig"]
        assert effective["*"] == "deny"
        assert effective["error"] == "deny"
        assert effective["background_execution"] == "deny"
        assert effective["allowed_cmds_regex"] == ["^echo policy$", "^(?!\\b\\B)git\\ status\\Z"]
        assert effective["blocked_cmds_regex"] == []

    def test_show_config_invalid_policy_fails_without_partial_json(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        copilot_home = tmp_path / "copilot-home"
        self.helpers.policy(copilot_home, {"bash": {"*": "allow"}})
        monkeypatch.setenv("COPILOT_HOME", str(copilot_home))
        invalid_path = self.helpers.project_policy(tmp_path, {}, local=True)
        invalid_path.write_text('{"bash":{"*":"unsafe"}}', encoding="utf-8")

        status, output, stderr = self.helpers.invoke_cli(monkeypatch, "", args=["--show-config"])

        assert status != 0
        assert output == ""
        assert str(invalid_path) in stderr
        assert "invalid" in stderr.lower()
