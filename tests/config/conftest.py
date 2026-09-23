"""Shared fixtures and helpers for config, rules, and evaluation tests."""

import json
from pathlib import Path

import pytest


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
        config["blocked_paths_regex"] = blocked
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


@pytest.fixture
def mock_project(tmp_path: Path) -> Path:
    """Create a temporary project directory with .devin subdirectory."""
    devin_dir = tmp_path / ".devin"
    devin_dir.mkdir()
    with open(devin_dir / "lovely-permissions.local.jsonc", "w") as f:
        json.dump({}, f)
    return tmp_path
