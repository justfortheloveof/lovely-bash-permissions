"""In-process contract tests for importing Copilot saved command approvals."""

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

pytestmark = pytest.mark.usefixtures("isolate_copilot_process")


class TestCopilotCliApprovals:
    @pytest.fixture(autouse=True)
    def _install_helpers(self, copilot_test_helpers: SimpleNamespace) -> None:
        self.helpers = copilot_test_helpers

    def test_test_mode_imports_saved_approvals_for_current_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        copilot_home = tmp_path / "copilot-home"
        monkeypatch.setenv("COPILOT_HOME", str(copilot_home))
        self.helpers.saved_approvals(
            copilot_home,
            {str(tmp_path): {"tool_approvals": [{"kind": "commands", "commandIdentifiers": ["git status"]}]}},
        )

        status, output, stderr = self.helpers.invoke_cli(monkeypatch, "", args=["--test", "git status"])

        assert status == 0
        assert stderr == ""
        _, decision = self.helpers.response_from(output)
        assert decision == {"permissionDecision": "allow"}

    def test_saved_command_approval_from_configured_home_allows_matching_command(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        copilot_home = tmp_path / "copilot-home"
        monkeypatch.setenv("COPILOT_HOME", str(copilot_home))
        copilot_home.mkdir()
        (copilot_home / "permissions-config.json").write_text(
            json.dumps(
                {
                    "locations": {
                        str(tmp_path): {"tool_approvals": [{"kind": "commands", "commandIdentifiers": ["git status"]}]}
                    }
                }
            ),
            encoding="utf-8",
        )

        status, output, stderr = self.helpers.invoke_cli(monkeypatch, json.dumps(self.helpers.event("git status")))

        assert status == 0
        assert stderr == ""
        _, decision = self.helpers.response_from(output)
        assert decision == {"permissionDecision": "allow"}

    @pytest.mark.parametrize(
        ("identifier", "command", "expected"),
        [
            ("git status", "git status", "allow"),
            ("git status", "git status --short", "ask"),
            ("git", "git status", "ask"),
            ("echo hello world", "echo 'hello world'", "allow"),
            ("echo 'hello world'", "echo 'hello world'", "ask"),
            ("git:*", "git", "allow"),
            ("git:*", "git status --short", "allow"),
            ("git:*", "git-status", "ask"),
        ],
    )
    def test_saved_command_identifiers_use_exact_and_trailing_prefix_matching(
        self,
        identifier: str,
        command: str,
        expected: str,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        copilot_home = tmp_path / "copilot-home"
        monkeypatch.setenv("COPILOT_HOME", str(copilot_home))
        self.helpers.saved_approvals(
            copilot_home,
            {str(tmp_path): {"tool_approvals": [{"kind": "commands", "commandIdentifiers": [identifier]}]}},
        )

        status, output, stderr = self.helpers.invoke_cli(monkeypatch, json.dumps(self.helpers.event(command)))

        assert status == 0
        assert stderr == ""
        _, decision = self.helpers.response_from(output)
        assert decision["permissionDecision"] == expected

    def test_saved_command_approval_matches_each_executed_compound_segment(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        copilot_home = tmp_path / "copilot-home"
        monkeypatch.setenv("COPILOT_HOME", str(copilot_home))
        self.helpers.policy(copilot_home, {"bash": {"allowed_cmds_regex": ["^echo first$"]}})
        self.helpers.saved_approvals(
            copilot_home,
            {str(tmp_path): {"tool_approvals": [{"kind": "commands", "commandIdentifiers": ["git status"]}]}},
        )

        status, output, stderr = self.helpers.invoke_cli(
            monkeypatch, json.dumps(self.helpers.event("echo first; git status"))
        )

        assert status == 0
        assert stderr == ""
        _, decision = self.helpers.response_from(output)
        assert decision == {"permissionDecision": "allow"}

    @pytest.mark.parametrize(
        ("matching_location", "approvals"),
        [
            (False, [{"kind": "commands", "commandIdentifiers": ["git status"]}]),
            (True, [{"kind": "write"}]),
        ],
        ids=["different-location", "unrelated-approval-kind"],
    )
    def test_only_matching_location_command_approvals_are_imported(
        self,
        matching_location: bool,
        approvals: list[dict[str, Any]],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        copilot_home = tmp_path / "copilot-home"
        monkeypatch.setenv("COPILOT_HOME", str(copilot_home))
        location = tmp_path if matching_location else tmp_path / "another-location"
        self.helpers.saved_approvals(copilot_home, {str(location): {"tool_approvals": approvals}})

        status, output, stderr = self.helpers.invoke_cli(monkeypatch, json.dumps(self.helpers.event("git status")))

        assert status == 0
        assert stderr == ""
        _, decision = self.helpers.response_from(output)
        assert decision["permissionDecision"] == "ask"

    def test_saved_command_approval_cannot_override_bash_policy_deny(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        copilot_home = tmp_path / "copilot-home"
        monkeypatch.setenv("COPILOT_HOME", str(copilot_home))
        self.helpers.policy(copilot_home, {"bash": {"blocked_cmds_regex": ["^git status$"]}})
        self.helpers.saved_approvals(
            copilot_home,
            {str(tmp_path): {"tool_approvals": [{"kind": "commands", "commandIdentifiers": ["git status"]}]}},
        )

        status, output, stderr = self.helpers.invoke_cli(monkeypatch, json.dumps(self.helpers.event("git status")))

        assert status == 0
        assert stderr == ""
        _, decision = self.helpers.response_from(output)
        assert decision["permissionDecision"] == "deny"

    def test_duplicate_saved_command_identifiers_are_reported_once(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        copilot_home = tmp_path / "copilot-home"
        monkeypatch.setenv("COPILOT_HOME", str(copilot_home))
        self.helpers.saved_approvals(
            copilot_home,
            {
                str(tmp_path): {
                    "tool_approvals": [{"kind": "commands", "commandIdentifiers": ["git status", "git status"]}]
                }
            },
        )

        status, output, stderr = self.helpers.invoke_cli(monkeypatch, json.dumps(self.helpers.event("git status")))

        assert status == 0
        assert stderr == ""
        progress, decision = self.helpers.response_from(output)
        assert decision == {"permissionDecision": "allow"}
        assert "allowed pattern:" in progress["message"]
        assert "allowed patterns:" not in progress["message"]

    @pytest.mark.parametrize("malformed_json", [True, False], ids=["invalid-json", "invalid-schema"])
    def test_malformed_saved_approval_data_warns_and_imports_none(
        self, malformed_json: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        copilot_home = tmp_path / "copilot-home"
        monkeypatch.setenv("COPILOT_HOME", str(copilot_home))
        copilot_home.mkdir()
        approval_file = copilot_home / "permissions-config.json"
        malformed = (
            "{invalid"
            if malformed_json
            else json.dumps(
                {
                    "locations": {
                        str(tmp_path): {"tool_approvals": [{"kind": "commands", "commandIdentifiers": ["git status"]}]},
                        "relative": {},
                    }
                }
            )
        )
        approval_file.write_text(malformed, encoding="utf-8")

        status, output, stderr = self.helpers.invoke_cli(monkeypatch, json.dumps(self.helpers.event("git status")))

        assert status == 0
        assert str(approval_file) in stderr
        _, decision = self.helpers.response_from(output)
        assert decision["permissionDecision"] == "ask"

    def test_unreadable_saved_approval_data_warns_and_imports_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        copilot_home = tmp_path / "copilot-home"
        monkeypatch.setenv("COPILOT_HOME", str(copilot_home))
        copilot_home.mkdir()
        approval_file = copilot_home / "permissions-config.json"
        approval_file.mkdir()

        status, output, stderr = self.helpers.invoke_cli(monkeypatch, json.dumps(self.helpers.event("git status")))

        assert status == 0
        assert str(approval_file) in stderr
        _, decision = self.helpers.response_from(output)
        assert decision["permissionDecision"] == "ask"

    def test_missing_saved_approval_file_is_silent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        status, output, stderr = self.helpers.invoke_cli(monkeypatch, json.dumps(self.helpers.event("git status")))

        assert status == 0
        assert stderr == ""
        _, decision = self.helpers.response_from(output)
        assert decision["permissionDecision"] == "ask"

    def test_default_home_is_used_for_saved_command_approvals(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("COPILOT_HOME", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path))
        self.helpers.saved_approvals(
            tmp_path / ".copilot",
            {str(tmp_path): {"tool_approvals": [{"kind": "commands", "commandIdentifiers": ["git status"]}]}},
        )

        status, output, stderr = self.helpers.invoke_cli(monkeypatch, json.dumps(self.helpers.event("git status")))

        assert status == 0
        assert stderr == ""
        _, decision = self.helpers.response_from(output)
        assert decision == {"permissionDecision": "allow"}
