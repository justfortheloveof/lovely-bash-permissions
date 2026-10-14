"""In-process contract tests for Copilot Git and permission-location handling."""

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.usefixtures("isolate_copilot_process")


class TestCopilotCliLocations:
    @pytest.fixture(autouse=True)
    def _install_helpers(self, copilot_test_helpers: SimpleNamespace) -> None:
        self.helpers = copilot_test_helpers

    def test_saved_approvals_use_repository_root_from_nested_event_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        copilot_home = tmp_path / "copilot-home"
        monkeypatch.setenv("COPILOT_HOME", str(copilot_home))
        checkout = self.helpers.git_checkout(tmp_path / "checkout")
        nested = checkout / "src" / "nested"
        nested.mkdir(parents=True)
        self.helpers.saved_approvals(
            copilot_home,
            {str(checkout): {"tool_approvals": [{"kind": "commands", "commandIdentifiers": ["git status"]}]}},
        )

        status, output, stderr = self.helpers.invoke_cli(
            monkeypatch, json.dumps(self.helpers.event("git status", cwd=str(nested)))
        )

        assert status == 0
        assert stderr == ""
        _, decision = self.helpers.response_from(output)
        assert decision == {"permissionDecision": "allow"}

    def test_saved_approvals_outside_git_use_normalized_event_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        copilot_home = tmp_path / "copilot-home"
        monkeypatch.setenv("COPILOT_HOME", str(copilot_home))
        outside = tmp_path / "outside"
        nested = outside / "nested"
        nested.mkdir(parents=True)
        self.helpers.saved_approvals(
            copilot_home,
            {str(outside): {"tool_approvals": [{"kind": "commands", "commandIdentifiers": ["git status"]}]}},
        )

        status, output, stderr = self.helpers.invoke_cli(
            monkeypatch,
            json.dumps(self.helpers.event("git status", cwd=str(nested / ".."))),
        )

        assert status == 0
        assert stderr == ""
        _, decision = self.helpers.response_from(output)
        assert decision == {"permissionDecision": "allow"}

    def test_saved_approvals_for_linked_worktree_use_main_repository_location(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        copilot_home = tmp_path / "copilot-home"
        monkeypatch.setenv("COPILOT_HOME", str(copilot_home))
        main_checkout = self.helpers.git_checkout(tmp_path / "main-checkout")
        self.helpers.git_commit(main_checkout)
        linked_checkout = tmp_path / "linked-checkout"
        subprocess.run(
            ["git", "-C", str(main_checkout), "worktree", "add", "--quiet", "-b", "linked", str(linked_checkout)],
            check=True,
            capture_output=True,
            text=True,
        )
        self.helpers.saved_approvals(
            copilot_home,
            {str(main_checkout): {"tool_approvals": [{"kind": "commands", "commandIdentifiers": ["git status"]}]}},
        )

        status, output, stderr = self.helpers.invoke_cli(
            monkeypatch, json.dumps(self.helpers.event("git status", cwd=str(linked_checkout)))
        )

        assert status == 0
        assert stderr == ""
        _, decision = self.helpers.response_from(output)
        assert decision == {"permissionDecision": "allow"}

    def test_saved_approvals_for_submodule_use_submodule_location(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        copilot_home = tmp_path / "copilot-home"
        monkeypatch.setenv("COPILOT_HOME", str(copilot_home))
        source = self.helpers.git_checkout(tmp_path / "submodule-source")
        self.helpers.git_commit(source)
        superproject = self.helpers.git_checkout(tmp_path / "superproject")
        self.helpers.git_commit(superproject)
        subprocess.run(
            [
                "git",
                "-c",
                "protocol.file.allow=always",
                "-C",
                str(superproject),
                "submodule",
                "add",
                "--quiet",
                str(source),
                "modules/example",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        submodule = superproject / "modules" / "example"
        self.helpers.saved_approvals(
            copilot_home,
            {str(submodule): {"tool_approvals": [{"kind": "commands", "commandIdentifiers": ["git status"]}]}},
        )

        status, output, stderr = self.helpers.invoke_cli(
            monkeypatch, json.dumps(self.helpers.event("git status", cwd=str(submodule)))
        )

        assert status == 0
        assert stderr == ""
        _, decision = self.helpers.response_from(output)
        assert decision == {"permissionDecision": "allow"}

    def test_repository_and_local_policies_override_global_from_event_checkout_root(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        copilot_home = tmp_path / "copilot-home"
        self.helpers.policy(copilot_home, {"bash": {"*": "deny"}})
        monkeypatch.setenv("COPILOT_HOME", str(copilot_home))
        checkout = self.helpers.git_checkout(tmp_path / "checkout")
        nested = checkout / "src" / "nested"
        nested.mkdir(parents=True)
        self.helpers.project_policy(checkout, {"bash": {"*": "ask"}})
        self.helpers.project_policy(checkout, {"bash": {"*": "allow"}}, local=True)
        hook_process_dir = tmp_path / "unrelated"
        hook_process_dir.mkdir()
        monkeypatch.chdir(hook_process_dir)

        status, output, stderr = self.helpers.invoke_cli(
            monkeypatch, json.dumps(self.helpers.event("echo hi", cwd=str(nested)))
        )

        assert status == 0
        assert stderr == ""
        _, decision = self.helpers.response_from(output)
        assert decision == {"permissionDecision": "allow"}

    def test_project_policy_outside_git_uses_normalized_event_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        copilot_home = tmp_path / "copilot-home"
        self.helpers.policy(copilot_home, {"bash": {"*": "deny"}})
        monkeypatch.setenv("COPILOT_HOME", str(copilot_home))
        outside = tmp_path / "outside"
        outside.mkdir()
        self.helpers.project_policy(outside, {"bash": {"*": "allow"}})
        event_dir = outside / "child"
        event_dir.mkdir()
        monkeypatch.chdir(tmp_path)

        status, output, stderr = self.helpers.invoke_cli(
            monkeypatch,
            json.dumps(self.helpers.event("echo hi", cwd=str(event_dir / ".."))),
        )

        assert status == 0
        assert stderr == ""
        _, decision = self.helpers.response_from(output)
        assert decision["permissionDecision"] == "allow"

    @pytest.mark.parametrize("invalid_cwd", [None, "", "relative/path", "/missing/copilot/project", 42])
    def test_missing_or_invalid_event_cwd_denies_without_using_process_directory(
        self, invalid_cwd: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        copilot_home = tmp_path / "copilot-home"
        self.helpers.policy(copilot_home, {"bash": {"*": "allow"}})
        monkeypatch.setenv("COPILOT_HOME", str(copilot_home))
        payload = self.helpers.event("echo hi", cwd=invalid_cwd)

        status, output, _ = self.helpers.invoke_cli(monkeypatch, json.dumps(payload))

        assert status == 0
        _, decision = self.helpers.response_from(output)
        assert decision["permissionDecision"] == "deny"
        assert "cwd" in decision["permissionDecisionReason"]

    def test_missing_event_cwd_denies(self, monkeypatch: pytest.MonkeyPatch) -> None:
        payload = self.helpers.event()
        payload.pop("cwd")

        status, output, _ = self.helpers.invoke_cli(monkeypatch, json.dumps(payload))

        assert status == 0
        _, decision = self.helpers.response_from(output)
        assert decision["permissionDecision"] == "deny"
        assert "cwd" in decision["permissionDecisionReason"]

    def test_file_event_cwd_denies(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        file_cwd = tmp_path / "not-a-directory"
        file_cwd.write_text("", encoding="utf-8")

        status, output, _ = self.helpers.invoke_cli(
            monkeypatch, json.dumps(self.helpers.event("echo hi", cwd=str(file_cwd)))
        )

        assert status == 0
        _, decision = self.helpers.response_from(output)
        assert decision["permissionDecision"] == "deny"
        assert "not a directory" in decision["permissionDecisionReason"]
