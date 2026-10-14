"""Every fixture and helper the test suite shares, in one place.

The suite is laid out to mirror the package, so the question "where does the
test for X go" has one answer:

- ``tests/test_<module>.py`` covers ``lovely_bash_permissions/<module>.py``.
  A module whose tests split by concern gets ``test_<module>_<concern>.py``
  siblings rather than one large file - ``cli.py`` and ``rules.py`` both do.
- ``tests/config/`` covers ``lovely_bash_permissions/config/``, the same rule
  one level down.
- ``tests/scenarios/`` holds tests that span modules and exercise a whole
  permission decision end to end, so they belong to no single module.
- ``tests/tooling/`` holds checks on the repository itself rather than on the
  package.

Because the tree is split by subject rather than by audience, one root conftest
serves all of it - so anything a test can reach lives here, and there is
nowhere else to look.
"""

import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from lovely_bash_permissions.segments import parse_segments

# ---------------------------------------------------------------------------
# Copilot CLI contract-test helpers
# ---------------------------------------------------------------------------


DEFAULT_CWD = object()


def invoke_copilot_cli(
    monkeypatch: pytest.MonkeyPatch,
    payload: str,
    *,
    args: list[str] | None = None,
) -> tuple[int | None, str, str]:
    """Call the public Copilot CLI entry point with controlled process streams."""
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


def copilot_event(
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


def copilot_policy(home: Path, config: object) -> Path:
    """Write the global Copilot Lovely policy used by a CLI contract test."""
    path = home / "lovely-permissions.jsonc"
    home.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


def saved_copilot_approvals(home: Path, locations: dict[str, Any]) -> Path:
    """Write Copilot's persisted permission file for a CLI contract test."""
    path = home / "permissions-config.json"
    home.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"locations": locations}), encoding="utf-8")
    return path


def copilot_project_policy(project: Path, config: object, *, local: bool = False) -> Path:
    """Write a shared or personal-local Copilot project policy."""
    filename = "lovely-permissions.local.jsonc" if local else "lovely-permissions.jsonc"
    path = project / ".github" / "copilot" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


def git_checkout(path: Path) -> Path:
    """Create a Git checkout for Copilot location contract tests."""
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "--quiet", str(path)], check=True, capture_output=True, text=True)
    return path


def git_commit(path: Path) -> None:
    """Create an empty commit so a checkout can host a linked worktree."""
    subprocess.run(
        [
            "git",
            "-C",
            str(path),
            "-c",
            "user.name=Test User",
            "-c",
            "user.email=test@example.com",
            "commit",
            "--allow-empty",
            "--quiet",
            "-m",
            "test",
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def response_from(output: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Parse and minimally validate the hook's progress/decision response."""
    lines = output.splitlines()
    assert len(lines) == 2
    progress, decision = (json.loads(line) for line in lines)
    assert progress["type"] == "progress"
    return progress, decision


@pytest.fixture
def isolate_copilot_process(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Keep Copilot CLI tests independent of a developer's Copilot setup."""
    monkeypatch.setenv("COPILOT_HOME", str(tmp_path / "copilot-home"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def copilot_test_helpers() -> SimpleNamespace:
    """Provide shared helpers for the split Copilot CLI contract-test modules."""
    return SimpleNamespace(
        invoke_cli=invoke_copilot_cli,
        event=copilot_event,
        policy=copilot_policy,
        saved_approvals=saved_copilot_approvals,
        project_policy=copilot_project_policy,
        git_checkout=git_checkout,
        git_commit=git_commit,
        response_from=response_from,
    )


# ---------------------------------------------------------------------------
# Environment isolation
# ---------------------------------------------------------------------------


@pytest.fixture
def devin_global_config_dir(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Point DEVIN_GLOBAL_CONFIG_DIR at a random temp dir.

    Prevents tests from reading or destroying the real ~/.config/devin/config.json.
    """
    with tempfile.TemporaryDirectory(prefix="devin-global-") as tmp:
        monkeypatch.setenv("DEVIN_GLOBAL_CONFIG_DIR", tmp)
        yield tmp


# ---------------------------------------------------------------------------
# Policy configuration
# ---------------------------------------------------------------------------


def make_config(
    allowed: list[str] | None = None,
    blocked: list[str] | None = None,
    output: str = "allow",
    input_redir: str = "allow",
    background: str = "allow",
    command_substitution: str = "ask",
    subshell: str | None = None,
    wildcard: str = "ask",
    variable_assignment: str | None = None,
) -> dict[str, list[str] | str]:
    """Helper to create test configuration."""
    config: dict[str, list[str] | str] = {"*": wildcard}
    if allowed is not None:
        config["allowed_cmds_regex"] = allowed
    if blocked is not None:
        config["blocked_cmds_regex"] = blocked
    if output != "allow":
        config["output_redirection"] = output
    if input_redir != "allow":
        config["input_redirection"] = input_redir
    if background != "allow":
        config["background_execution"] = background
    if command_substitution != "ask":
        config["command_substitution"] = command_substitution
    if subshell is not None:
        config["subshell"] = subshell
    if variable_assignment is not None:
        config["variable_assignment"] = variable_assignment
    return config


# Distinguishing the three project-dir fixtures:
#   mock_project            - bare Path; `.devin/` with an EMPTY local override,
#                            so a local file cannot change the merged result.
#   tmp_project             - bare Path; NO `.devin/` at all, so tests that
#                            create one themselves own its whole contents.
#   temp_project (test_loader, stays there) - (root, .devin) PAIR, empty `.devin/`
#                            and rooted in an uncleaned `mkdtemp()`; ~40 call
#                            sites index [0]/[1] and assert on loader output.
@pytest.fixture
def mock_project(tmp_path: Path) -> Path:
    """Create a temporary project directory with .devin subdirectory."""
    devin_dir = tmp_path / ".devin"
    devin_dir.mkdir()
    with open(devin_dir / "lovely-permissions.local.jsonc", "w") as f:
        json.dump({}, f)
    return tmp_path


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """Create a temporary project directory."""
    project_dir = tmp_path / "test-project"
    project_dir.mkdir()
    return Path(project_dir)


@pytest.fixture
def bash_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A project dir whose only config is the one a test writes, plus an empty global.

    Two things are isolated, and a test that misses either one is testing the
    developer's machine rather than the code: the *global* config dir (patched
    empty, or a real ``~/.devin`` on the box would merge in) and the *project*
    dir, which the test populates itself. Yields the project dir.
    """
    empty_global = tmp_path / ".config" / "devin"
    empty_global.mkdir(parents=True)
    monkeypatch.setattr(
        "lovely_bash_permissions.config.loader.get_devin_global_config_dir",
        lambda: empty_global,
    )
    monkeypatch.setattr(
        "lovely_bash_permissions.config.devin.get_devin_global_config_dir",
        lambda: empty_global,
    )
    project = tmp_path / "proj"
    (project / ".devin").mkdir(parents=True)
    return project


@pytest.fixture
def project_with_bash_config(tmp_project: Path) -> Path:
    """Create a project directory with a devin config for bash rules."""
    project_dir = tmp_project
    devin_dir = project_dir / ".devin"
    devin_dir.mkdir()
    config = {
        "bash": {
            "allowed_cmds_regex": ["^git", "^ls", "^cat"],
            "blocked_cmds_regex": ["curl"],
        }
    }
    with open(devin_dir / "config.json", "w") as f:
        json.dump(config, f)
    with open(devin_dir / "lovely-permissions.jsonc", "w") as f:
        json.dump(config, f)
    with open(devin_dir / "lovely-permissions.local.jsonc", "w") as f:
        json.dump({}, f)
    return Path(project_dir)


# ---------------------------------------------------------------------------
# Reading parsed output back
# ---------------------------------------------------------------------------


def _commands(command: str) -> list[str]:
    """Return the command name of every segment *command* parses into.

    The list keeps the order and the cardinality :func:`parse_segments` reports,
    so a test can pin that a shape produces *no* segment at all (``[[ -d /tmp ]]``
    -> ``[]``) as well as which commands it does produce, including the empty
    command name that carries a variable assignment's operands.
    """
    return [s["command"] for s in parse_segments(command)]


def _lines(capsys: pytest.CaptureFixture[str]) -> list[str]:
    """Return the stdout captured so far, split into non-empty lines.

    Blank lines are dropped so callers can assert on order and adjacency by
    index without every assertion first having to skip the padding the CLI's
    renderer emits between sections.
    """
    return [line for line in capsys.readouterr().out.splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# Hook event builders
# ---------------------------------------------------------------------------


def _pretooluse_exec_event(command: str = "ls") -> dict[str, Any]:
    """Return a PreToolUse event for tool 'exec'."""
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": "exec",
        "tool_input": {"command": command},
    }


def _permission_request_event(command: str = "ls") -> dict[str, Any]:
    """Return a PermissionRequest event for tool 'exec'."""
    return {
        "hook_event_name": "PermissionRequest",
        "tool_name": "exec",
        "tool_input": {"command": command},
    }


# ---------------------------------------------------------------------------
# Driving the CLI end to end
# ---------------------------------------------------------------------------


def write_local_config(config: dict[str, Any], project_dir: Path) -> None:
    """Write a lovely-permissions config into an isolated project dir."""
    d = project_dir / ".devin"
    d.mkdir(parents=True, exist_ok=True)
    (d / "lovely-permissions.local.jsonc").write_text(json.dumps({"bash": config}))


def run_test(command: str, project_dir: Path, tmp_global_dir: Path) -> dict[str, Any]:
    """Run `lovely-devin-permissions --test` in an isolated environment."""
    if not (project_dir / ".devin" / "lovely-permissions.local.jsonc").exists():
        write_local_config({}, project_dir)
    env = os.environ.copy()
    env["DEVIN_PROJECT_DIR"] = str(project_dir)
    env["DEVIN_GLOBAL_CONFIG_DIR"] = str(tmp_global_dir)
    r = subprocess.run(
        ["uv", "run", "python", "-m", "lovely_bash_permissions.devin_cli", "--test", command],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
        check=False,
    )
    return json.loads(r.stdout) if r.stdout.strip() else {"error": r.stderr}


# ---------------------------------------------------------------------------
# Scratch files
# ---------------------------------------------------------------------------


def _write_temp_file(content: str, suffix: str = ".jsonc") -> str:
    """Write content to a temporary file and return its path."""
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "w") as f:
        f.write(content)
    return path


def _clean_temp_file(path: str) -> None:
    """Remove a temporary file."""
    if os.path.exists(path):
        os.remove(path)
