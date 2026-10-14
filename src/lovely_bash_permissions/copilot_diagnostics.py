"""Configuration diagnostics for the GitHub Copilot CLI integration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .config.copilot import get_copilot_policy_paths, load_copilot_policy
from .config.copilot_permissions import (
    apply_saved_command_approvals,
    get_copilot_permissions_path,
    load_saved_command_approvals,
)
from .config.effective_bash import resolve_bash_config


def get_copilot_diagnostics(
    project_dir: Path,
    permission_location: Path,
) -> tuple[dict[str, Any], str | None]:
    """Build config diagnostics without emitting partial output on policy errors."""
    config, top_level_wildcard = load_copilot_policy(project_dir)
    approval_ids, warning = load_saved_command_approvals(permission_location)

    bash_config = apply_saved_command_approvals(dict(config.get("bash") or {}), approval_ids)

    policy_sources = [
        {"scope": scope, "path": str(path), "exists": path.exists()}
        for scope, path in get_copilot_policy_paths(project_dir)
    ]
    approval_path = get_copilot_permissions_path()
    return (
        {
            "policySources": policy_sources,
            "savedApprovalSource": {"path": str(approval_path), "exists": approval_path.exists()},
            "permissionLocation": str(permission_location),
            "importedApprovals": approval_ids,
            "effectiveBashConfig": resolve_bash_config(bash_config, top_level_wildcard),
        },
        warning,
    )
