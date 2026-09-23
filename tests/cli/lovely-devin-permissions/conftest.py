"""Shared fixtures for lovely-devin-permissions CLI tests."""

import json
from pathlib import Path

import pytest


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """Create a temporary project directory."""
    project_dir = tmp_path / "test-project"
    project_dir.mkdir()
    return Path(project_dir)


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
    with open(devin_dir / "lovely-permissions.local.jsonc", "w") as f:
        json.dump({}, f)
    with open(devin_dir / "lovely-permissions.jsonc", "w") as f:
        json.dump(config, f)
    with open(devin_dir / "lovely-permissions.local.jsonc", "w") as f:
        json.dump({}, f)
    return Path(project_dir)
