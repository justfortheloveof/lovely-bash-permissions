from __future__ import annotations

import re
from enum import Enum
from typing import Any

from pydantic import BaseModel, field_validator


class PermissionLevel(str, Enum):
    allow = "allow"
    deny = "deny"
    ask = "ask"


class ToolConfig(BaseModel):
    permission: PermissionLevel | None = None
    blocked_paths_regex: list[str] = []
    allowed_cmds_regex: list[str] = []

    @field_validator("blocked_paths_regex", "allowed_cmds_regex", mode="before")
    @classmethod
    def strip_trailing_period(cls, v: list[str]) -> list[str]:
        return [p.rstrip(".") for p in v]


def _validate_config(config: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    for key, value in config.items():
        if value is None:
            continue

        if isinstance(value, dict):
            try:
                ToolConfig.model_validate(value)
            except ValueError as exc:
                msg = str(exc)
                if "Input should be" in msg and "'allow'" in msg:
                    errors.append("tool '" + key + "': must be allow, deny, or ask")
                else:
                    errors.append("tool '" + key + "': " + msg)

            try:
                for field_name in ("blocked_paths_regex", "allowed_cmds_regex"):
                    entries = value.get(field_name, [])
                    for entry in entries:
                        re.compile(entry)
            except re.error as exc:
                errors.append(f"tool '{key}': {field_name} pattern '{entry}' is invalid — {exc}")
        else:
            errors.append(f"tool '{key}': expected object or null, got {type(value).__name__}")

    return errors
