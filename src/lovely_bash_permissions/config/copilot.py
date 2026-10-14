"""Global Lovely policy discovery for the GitHub Copilot CLI host.

Ticket 01 deliberately supports only Copilot's global policy. Later policy
scopes can be added here without making the shared decision engine host-aware.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ..errors import user_message
from ..policy import DEFAULT_LEVEL, wildcard_level
from .jsonc import parse_jsonc
from .schema import PermissionsConfig


class CopilotPolicyError(ValueError):
    """A present Copilot Lovely policy could not be used safely."""


def get_copilot_home() -> Path:
    """Return ``COPILOT_HOME``, or Copilot CLI's default ``~/.copilot``."""
    return Path(os.environ.get("COPILOT_HOME") or Path.home() / ".copilot")


def get_copilot_policy_path() -> Path:
    """Return the supported global policy file path."""
    return get_copilot_home() / "lovely-permissions.jsonc"


def load_copilot_policy() -> tuple[dict[str, Any], str]:
    """Load the global policy, returning its raw config and root wildcard.

    A missing policy is the normal first-run state and defaults to ``ask``.
    Any present policy that cannot be read, parsed, or validated is an error;
    it must never be treated as an absent policy or partially applied.
    """
    path = get_copilot_policy_path()
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        if path.is_symlink():
            raise CopilotPolicyError(f"cannot read global Lovely policy {path}: {exc}") from exc
        return {}, DEFAULT_LEVEL
    except (OSError, UnicodeDecodeError) as exc:
        raise CopilotPolicyError(f"cannot read global Lovely policy {path}: {exc}") from exc

    try:
        raw = parse_jsonc(text)
    except ValueError as exc:
        raise CopilotPolicyError(f"global Lovely policy {path} is malformed: {exc}") from exc

    try:
        validated = PermissionsConfig.model_validate(raw)
    except ValueError as exc:
        raise CopilotPolicyError(f"global Lovely policy {path} is invalid: {user_message(exc)}") from exc

    config = validated.model_dump(mode="json", by_alias=True, exclude_none=True)
    return config, wildcard_level(config)
