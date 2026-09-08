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
    def validate_regexes(cls, v: list[str], info: ValidationInfo) -> list[str]:
        """Validate that each pattern compiles as a regex.

        Patterns are used as-written — no stripping or mutation.
        """
        result: list[str] = []
        for p in v:
            try:
                compiled = re.compile(p)
            except re.error as exc:
                raise ValueError(f'pattern "{p}": invalid regex: {exc}') from exc
            result.append(compiled.pattern)
        return result


_TOOL_RECOGNIZED_FIELDS = frozenset(
    (
        "permission",
        "perm",
        "blocked_paths_regex",
        "allowed_cmds_regex",
        "allow",
        "deny",
        "prompt",
        "*",
        "subshell",
        "output_redirection",
        "input_redirection",
        "background_execution",
    )
)


class PermissionsConfig(BaseModel):
    model_config = {"extra": "allow", "str_strip_whitespace": True}

    version: int = 1

    @model_validator(mode="before")
    @classmethod
    def _check_version(cls, data: object) -> object:
        if isinstance(data, dict):
            v = data.get("version")
            if v is not None and v != 1:
                raise ValueError(f"unknown schema version: {v}")
        return data

    @model_validator(mode="before")
    @classmethod
    def _check_top_level_keys(cls, data: object) -> object:
        if isinstance(data, dict):
            known_tool_keys = {k for k, v in data.items() if k not in ("version", "*") and isinstance(v, dict)}
            for key in data:
                if key == "version":
                    continue
                if key == "*":
                    continue
                if data[key] is None:
                    continue  # null tool entries are valid, handled by _check_tool_dicts
                if key in known_tool_keys:
                    continue
                raise ValueError(f"unknown config key: '{key}'")
        return data

    @model_validator(mode="before")
    @classmethod
    def _check_tool_dicts(cls, data: object) -> object:
        if isinstance(data, dict):
            for key, value in data.items():
                if key == "version":
                    continue
                if value is None:
                    continue
                if not isinstance(value, dict):
                    raise ValueError(f"tool '{key}': expected object or null")  # noqa: TRY004
                unrecognized = set(value.keys()) - _TOOL_RECOGNIZED_FIELDS
                if unrecognized:
                    fields = ", ".join(sorted(unrecognized))
                    raise ValueError(f"tool '{key}': unrecognized fields: {fields}")
                try:
                    ToolConfig.model_validate(value)
                except (ValueError, re.error) as exc:
                    raise ValueError(f"tool '{key}': {exc}") from exc
        return data
