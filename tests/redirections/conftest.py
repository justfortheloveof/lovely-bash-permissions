"""Shared helpers for output-redirection validation tests."""

import json
import os
import subprocess
from pathlib import Path
from typing import Any


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
