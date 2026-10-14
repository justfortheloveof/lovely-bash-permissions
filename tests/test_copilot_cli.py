"""In-process contract tests for the GitHub Copilot CLI hook."""

import json
import subprocess
import sys
from io import StringIO
from pathlib import Path
from typing import Any

import pytest

DEFAULT_CWD = object()


def invoke_cli(
    monkeypatch: pytest.MonkeyPatch,
    payload: str,
    *,
    args: list[str] | None = None,
) -> tuple[int | None, str, str]:
    """Call the public CLI entry point with controlled process streams."""
    from lovely_bash_permissions.copilot_cli import main

    stdout = StringIO()
    stderr = StringIO()
    monkeypatch.setattr(sys, "argv", ["lovely-copilot-permissions", *(args or [])])
    monkeypatch.setattr(sys, "stdin", StringIO(payload))
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)

    status: int | None = None
    try:
        main()
    except SystemExit as exc:
        status = exc.code if isinstance(exc.code, int) else 1
    return status, stdout.getvalue(), stderr.getvalue()


def event(
    command: object = "git status",
    *,
    tool_name: str = "bash",
    tool_args: object = None,
    cwd: object = DEFAULT_CWD,
) -> dict[str, Any]:
    """Build a native Copilot preToolUse Bash payload."""
    return {
        "cwd": str(Path.cwd()) if cwd is DEFAULT_CWD else cwd,
        "toolName": tool_name,
        "toolArgs": {"command": command} if tool_args is None else tool_args,
    }


def policy(home: Path, config: object) -> Path:
    path = home / "lovely-permissions.jsonc"
    home.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


def project_policy(project: Path, config: object, *, local: bool = False) -> Path:
    path = project / ".github" / "copilot" / ("lovely-permissions.local.jsonc" if local else "lovely-permissions.jsonc")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


def git_checkout(path: Path) -> Path:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "--quiet", str(path)], check=True, capture_output=True, text=True)
    return path


@pytest.fixture(autouse=True)
def isolate_copilot_process(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Keep hook invocations independent of a developer's Copilot setup."""
    monkeypatch.setenv("COPILOT_HOME", str(tmp_path / "copilot-home"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)


def response_from(output: str) -> tuple[dict[str, Any], dict[str, Any]]:
    lines = output.splitlines()
    assert len(lines) == 2
    progress, decision = (json.loads(line) for line in lines)
    assert progress["type"] == "progress"
    return progress, decision


class TestCopilotCliHookContract:
    def test_object_tool_args_use_global_copilot_home_policy(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        copilot_home = tmp_path / "copilot-home"
        policy(copilot_home, {"bash": {"allowed_cmds_regex": ["^git status$"]}})
        monkeypatch.setenv("COPILOT_HOME", str(copilot_home))

        status, output, stderr = invoke_cli(monkeypatch, json.dumps(event()))

        assert status == 0
        assert stderr == ""
        progress, decision = response_from(output)
        assert "allow" in progress["message"]
        assert decision == {"permissionDecision": "allow"}

    def test_json_encoded_tool_args_are_accepted(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        copilot_home = tmp_path / "copilot-home"
        policy(copilot_home, {"*": "deny"})
        monkeypatch.setenv("COPILOT_HOME", str(copilot_home))
        payload = event(tool_args=json.dumps({"command": "git status"}))

        status, output, _ = invoke_cli(monkeypatch, json.dumps(payload))

        assert status == 0
        _, decision = response_from(output)
        assert decision["permissionDecision"] == "deny"
        assert decision["permissionDecisionReason"]

    def test_other_tools_produce_no_decision(self, monkeypatch: pytest.MonkeyPatch) -> None:
        status, output, stderr = invoke_cli(monkeypatch, json.dumps(event(tool_name="read")))

        assert status == 0
        assert output == ""
        assert stderr == ""

    @pytest.mark.parametrize(
        "payload",
        [
            "not JSON",
            "[]",
            json.dumps({"toolName": "bash", "toolArgs": {}}),
            json.dumps(event(command=42)),
            json.dumps(event(tool_args="not JSON")),
            json.dumps(event(tool_args="[]")),
        ],
    )
    def test_malformed_payloads_and_commands_are_denied(self, payload: str, monkeypatch: pytest.MonkeyPatch) -> None:
        status, output, _ = invoke_cli(monkeypatch, payload)

        assert status == 0
        _, decision = response_from(output)
        assert decision["permissionDecision"] == "deny"
        assert decision["permissionDecisionReason"]

    def test_empty_command_uses_global_error_policy(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        copilot_home = tmp_path / "copilot-home"
        policy(copilot_home, {"bash": {"error": "deny"}})
        monkeypatch.setenv("COPILOT_HOME", str(copilot_home))

        status, output, _ = invoke_cli(monkeypatch, json.dumps(event(command="")))

        assert status == 0
        _, decision = response_from(output)
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
        policy(copilot_home, policy_config)
        monkeypatch.setenv("COPILOT_HOME", str(copilot_home))

        status, output, stderr = invoke_cli(monkeypatch, json.dumps(event("echo hi")))

        assert status == 0
        assert stderr == ""
        progress, decision = response_from(output)
        assert expected in progress["message"]
        assert decision["permissionDecision"] == expected
        if expected == "allow":
            assert "permissionDecisionReason" not in decision
        else:
            assert decision["permissionDecisionReason"]

    def test_missing_policy_asks_by_default(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("COPILOT_HOME", str(tmp_path / "empty-copilot-home"))

        status, output, _ = invoke_cli(monkeypatch, json.dumps(event("echo hi")))

        assert status == 0
        _, decision = response_from(output)
        assert decision["permissionDecision"] == "ask"
        assert decision["permissionDecisionReason"]

    def test_repository_and_local_policies_override_global_from_event_checkout_root(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        copilot_home = tmp_path / "copilot-home"
        policy(copilot_home, {"bash": {"*": "deny"}})
        monkeypatch.setenv("COPILOT_HOME", str(copilot_home))
        checkout = git_checkout(tmp_path / "checkout")
        nested = checkout / "src" / "nested"
        nested.mkdir(parents=True)
        project_policy(checkout, {"bash": {"*": "ask"}})
        project_policy(checkout, {"bash": {"*": "allow"}}, local=True)
        hook_process_dir = tmp_path / "unrelated"
        hook_process_dir.mkdir()
        monkeypatch.chdir(hook_process_dir)

        status, output, stderr = invoke_cli(monkeypatch, json.dumps(event("echo hi", cwd=str(nested))))

        assert status == 0
        assert stderr == ""
        _, decision = response_from(output)
        assert decision == {"permissionDecision": "allow"}

    def test_project_policy_outside_git_uses_normalized_event_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        copilot_home = tmp_path / "copilot-home"
        policy(copilot_home, {"bash": {"*": "deny"}})
        monkeypatch.setenv("COPILOT_HOME", str(copilot_home))
        outside = tmp_path / "outside"
        outside.mkdir()
        project_policy(outside, {"bash": {"*": "allow"}})
        event_dir = outside / "child"
        event_dir.mkdir()
        monkeypatch.chdir(tmp_path)

        status, output, stderr = invoke_cli(
            monkeypatch,
            json.dumps(event("echo hi", cwd=str(event_dir / ".."))),
        )

        assert status == 0
        assert stderr == ""
        _, decision = response_from(output)
        assert decision["permissionDecision"] == "allow"

    def test_allowed_patterns_from_global_and_project_policies_are_merged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        copilot_home = tmp_path / "copilot-home"
        policy(copilot_home, {"bash": {"allowed_cmds_regex": ["^echo global$"]}})
        monkeypatch.setenv("COPILOT_HOME", str(copilot_home))
        checkout = git_checkout(tmp_path / "checkout")
        nested = checkout / "nested"
        nested.mkdir()
        project_policy(checkout, {"bash": {"allowed_cmds_regex": ["^echo project$"]}})

        for command in ("echo global", "echo project"):
            status, output, stderr = invoke_cli(monkeypatch, json.dumps(event(command, cwd=str(nested))))

            assert status == 0
            assert stderr == ""
            _, decision = response_from(output)
            assert decision == {"permissionDecision": "allow"}

    @pytest.mark.parametrize("invalid_cwd", [None, "", "relative/path", "/missing/copilot/project", 42])
    def test_missing_or_invalid_event_cwd_denies_without_using_process_directory(
        self, invalid_cwd: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        copilot_home = tmp_path / "copilot-home"
        policy(copilot_home, {"bash": {"*": "allow"}})
        monkeypatch.setenv("COPILOT_HOME", str(copilot_home))
        payload = event("echo hi", cwd=invalid_cwd)

        status, output, _ = invoke_cli(monkeypatch, json.dumps(payload))

        assert status == 0
        _, decision = response_from(output)
        assert decision["permissionDecision"] == "deny"
        assert "cwd" in decision["permissionDecisionReason"]

    def test_missing_event_cwd_denies(self, monkeypatch: pytest.MonkeyPatch) -> None:
        payload = event()
        payload.pop("cwd")

        status, output, _ = invoke_cli(monkeypatch, json.dumps(payload))

        assert status == 0
        _, decision = response_from(output)
        assert decision["permissionDecision"] == "deny"
        assert "cwd" in decision["permissionDecisionReason"]

    def test_file_event_cwd_denies(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        file_cwd = tmp_path / "not-a-directory"
        file_cwd.write_text("", encoding="utf-8")

        status, output, _ = invoke_cli(monkeypatch, json.dumps(event("echo hi", cwd=str(file_cwd))))

        assert status == 0
        _, decision = response_from(output)
        assert decision["permissionDecision"] == "deny"
        assert "not a directory" in decision["permissionDecisionReason"]

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
        policy(copilot_home, {"bash": {"*": "allow"}})
        monkeypatch.setenv("COPILOT_HOME", str(copilot_home))
        checkout = git_checkout(tmp_path / "checkout")
        nested = checkout / "nested"
        nested.mkdir()
        invalid_path = project_policy(checkout, {}, local=source == "local")
        invalid_path.write_text(contents, encoding="utf-8")

        status, output, _ = invoke_cli(monkeypatch, json.dumps(event("echo hi", cwd=str(nested))))

        assert status == 0
        _, decision = response_from(output)
        assert decision["permissionDecision"] == "deny"
        assert str(invalid_path) in decision["permissionDecisionReason"]

    @pytest.mark.parametrize("source", ["project", "local"])
    def test_unreadable_repository_or_local_policy_denies(
        self, source: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        checkout = git_checkout(tmp_path / "checkout")
        nested = checkout / "nested"
        nested.mkdir()
        unreadable_path = project_policy(checkout, {}, local=source == "local")
        unreadable_path.unlink()
        unreadable_path.mkdir()

        status, output, _ = invoke_cli(monkeypatch, json.dumps(event("echo hi", cwd=str(nested))))

        assert status == 0
        _, decision = response_from(output)
        assert decision["permissionDecision"] == "deny"
        assert "cannot read" in decision["permissionDecisionReason"]
        assert str(unreadable_path) in decision["permissionDecisionReason"]

    def test_default_home_is_used_when_copilot_home_is_unset(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        policy(tmp_path / ".copilot", {"bash": {"*": "deny"}})
        monkeypatch.delenv("COPILOT_HOME", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path))

        status, output, _ = invoke_cli(monkeypatch, json.dumps(event("echo hi")))

        assert status == 0
        _, decision = response_from(output)
        assert decision["permissionDecision"] == "deny"

    @pytest.mark.parametrize("contents", ["{invalid", json.dumps({"bash": {"*": "unsafe"}})])
    def test_invalid_global_policy_denies(self, contents: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        copilot_home = tmp_path / "copilot-home"
        copilot_home.mkdir()
        (copilot_home / "lovely-permissions.jsonc").write_text(contents, encoding="utf-8")
        monkeypatch.setenv("COPILOT_HOME", str(copilot_home))

        status, output, _ = invoke_cli(monkeypatch, json.dumps(event("echo hi")))

        assert status == 0
        _, decision = response_from(output)
        assert decision["permissionDecision"] == "deny"
        assert decision["permissionDecisionReason"]

    def test_unreadable_global_policy_denies(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        copilot_home = tmp_path / "copilot-home"
        copilot_home.mkdir()
        (copilot_home / "lovely-permissions.jsonc").mkdir()
        monkeypatch.setenv("COPILOT_HOME", str(copilot_home))

        status, output, _ = invoke_cli(monkeypatch, json.dumps(event("echo hi")))

        assert status == 0
        _, decision = response_from(output)
        assert decision["permissionDecision"] == "deny"
        assert "cannot read global Lovely policy" in decision["permissionDecisionReason"]

    def test_invocation_error_without_a_verdict_exits_nonzero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        status, output, stderr = invoke_cli(monkeypatch, "", args=["--unsupported"])

        assert status != 0
        assert output == ""
        assert "usage:" in stderr
