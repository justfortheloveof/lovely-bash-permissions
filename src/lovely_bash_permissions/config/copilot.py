"""Copilot Bash policy discovery for the GitHub Copilot CLI host.

Copilot keeps its global, shared project, and personal local policy files in a
Copilot-specific namespace. The shared evaluator remains host-agnostic.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ..errors import user_message
from ..policy import DEFAULT_LEVEL, wildcard_level
from .jsonc import parse_jsonc
from .loader import merge_deep
from .schema import PermissionsConfig


class CopilotPolicyError(ValueError):
    """A present Copilot policy could not be used safely."""


def get_copilot_home() -> Path:
    """Return ``COPILOT_HOME``, or Copilot CLI's default ``~/.copilot``."""
    return Path(os.environ.get("COPILOT_HOME") or Path.home() / ".copilot")


def get_copilot_policy_paths(project_dir: Path | str) -> tuple[tuple[str, Path], ...]:
    """Return global, shared project, and personal local policy sources."""
    project = Path(project_dir)
    copilot_project_dir = project / ".github" / "copilot"
    return (
        ("global", get_copilot_home() / "lovely-permissions.jsonc"),
        ("project", copilot_project_dir / "lovely-permissions.jsonc"),
        ("local", copilot_project_dir / "lovely-permissions.local.jsonc"),
    )


def _load_policy_source(path: Path, level: str) -> dict[str, Any] | None:
    """Read and validate one source, returning None only when it is absent."""
    label = f"{level} Copilot policy"
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        if path.is_symlink():
            raise CopilotPolicyError(f"cannot read {label} {path}: {exc}") from exc
        return None
    except (OSError, UnicodeDecodeError) as exc:
        raise CopilotPolicyError(f"cannot read {label} {path}: {exc}") from exc

    try:
        raw = parse_jsonc(text)
    except ValueError as exc:
        raise CopilotPolicyError(f"{label} {path} is malformed: {exc}") from exc

    try:
        validated = PermissionsConfig.model_validate(raw)
    except ValueError as exc:
        raise CopilotPolicyError(f"{label} {path} is invalid: {user_message(exc)}") from exc

    return validated.model_dump(mode="json", by_alias=True, exclude_none=True)


def load_copilot_policy(project_dir: Path | str) -> tuple[dict[str, Any], str]:
    """Load and merge Copilot policy sources, returning config and root wildcard.

    The order is global, shared project, then personal local, with each later
    source overriding earlier scalar values and concatenating arrays. Every
    present source must be readable, parseable, and valid on its own; the final
    merged config is validated too. Missing files are ignored, and no files
    means an empty policy that safely defaults to ``ask``.
    """
    merged: dict[str, Any] = {}
    origins: dict[tuple[str, ...], str] = {}
    loaded_any = False

    for level, path in get_copilot_policy_paths(project_dir):
        source = _load_policy_source(path, level)
        if source is None:
            continue
        loaded_any = True
        merged, _ = merge_deep(merged, source, source_level=level, origins=origins)

    if not loaded_any:
        return {}, DEFAULT_LEVEL

    try:
        validated = PermissionsConfig.model_validate(merged)
    except ValueError as exc:
        raise CopilotPolicyError(f"merged Copilot policy is invalid: {user_message(exc)}") from exc

    config = validated.model_dump(mode="json", by_alias=True, exclude_none=True)
    return config, wildcard_level(config)
