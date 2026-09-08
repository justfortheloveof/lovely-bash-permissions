from __future__ import annotations

import re
from enum import Enum

from pydantic import BaseModel, ValidationInfo, field_validator, model_validator


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
    def strip_trailing_period(cls, v: list[str], info: ValidationInfo) -> list[str]:
        result: list[str] = []
        for p in v:
            compiled = re.compile(p.rstrip("."))
            result.append(compiled.pattern)
        return result


class PermissionsConfig(BaseModel):
    model_config = {"extra": "allow", "str_strip_whitespace": True}

    @model_validator(mode="before")
    @classmethod
    def _check_tool_dicts(cls, data: object) -> object:
        if isinstance(data, dict):
            for key, value in data.items():
                if value is None:
                    continue
                if not isinstance(value, dict):
                    raise ValueError(f"tool '{key}': expected object or null")  # noqa: TRY004
                try:
                    ToolConfig.model_validate(value)
                except (ValueError, re.error) as exc:
                    raise ValueError(f"tool '{key}': {exc}") from exc
        return data
