from __future__ import annotations

import re
from enum import Enum

from pydantic import BaseModel, Field, ValidationInfo, field_validator, model_validator
from pydantic_core import ValidationError


class PermissionLevel(str, Enum):
    allow = "allow"
    deny = "deny"
    ask = "ask"


class OutputRedirectionPolicy(BaseModel):
    """Policy for output redirection.

    Accepts either a plain ``PermissionLevel`` string (\"allow\", \"deny\", \"ask\")
    or a dict with optional keys:

    - ``*`` — wildcard/default for any redirection not otherwise matched
    - ``stdout_to_dev_null`` — level for ``>/dev/null``-style discards
    - ``stderr_to_dev_null`` — level for ``2>/dev/null``-style discards
    - ``stderr_to_stdout`` — level for ``2>&1``-style fd duplication
    """

    star: PermissionLevel | None = Field(None, alias="*")
    stdout_to_dev_null: PermissionLevel | None = None
    stderr_to_dev_null: PermissionLevel | None = None
    stderr_to_stdout: PermissionLevel | None = None


class ToolConfig(BaseModel):
    model_config = {"extra": "forbid"}

    permission: PermissionLevel | None = None
    star: PermissionLevel | None = Field(None, alias="*")  # allow "*" inside tool configs
    blocked_paths_regex: list[str] = []
    allowed_cmds_regex: list[str] = []
    output_redirection: OutputRedirectionPolicy | PermissionLevel | None = None
    input_redirection: PermissionLevel | None = None
    background_execution: PermissionLevel | None = None
    subshell: PermissionLevel | None = None

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


class PermissionsConfig(BaseModel):
    model_config = {"extra": "allow", "str_strip_whitespace": True}

    version: int = 1
    wildcard: PermissionLevel | None = Field(None, alias="*")

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
        """Accept any extra key as a tool name; value validation is delegated to _validate_tools."""
        return data

    @model_validator(mode="after")
    def _validate_tools(self) -> PermissionsConfig:
        """Validate each tool value against ToolConfig (Pydantic native)."""
        extras = self.model_extra or {}
        all_errors: list[tuple[str, object]] = []
        for _key, value in extras.items():
            if value is None:
                continue  # null tool entries are fine
            try:
                ToolConfig.model_validate(value)
            except ValidationError as exc:
                for err in exc.errors():
                    all_errors.append((_key, err))
        if all_errors:
            msgs = [f"tool '{k}': {e['msg']}" for k, e in all_errors]  # type: ignore[index]
            raise ValueError("\n".join(msgs))
        return self
