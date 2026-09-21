from __future__ import annotations

import logging
import re
from enum import Enum

from pydantic import BaseModel, Field, ValidationInfo, field_validator, model_validator

log = logging.getLogger(__name__)


class PermissionLevel(str, Enum):
    allow = "allow"
    deny = "deny"
    ask = "ask"


class OutputRedirectionPolicy(BaseModel):
    """Policy for output redirection.

    Accepts either a plain ``PermissionLevel`` string (\"allow\", \"deny\", \"ask\")
    or a dict with optional keys:

    - ``*`` - wildcard/default for any redirection not otherwise matched
    - ``stdout_to_dev_null`` - level for ``>/dev/null``-style discards
    - ``stderr_to_dev_null`` - level for ``2>/dev/null``-style discards
    - ``stderr_to_stdout`` - level for ``2>&1``-style fd duplication
    """

    wildcard: PermissionLevel | None = Field(None, alias="*")
    stdout_to_dev_null: PermissionLevel | None = None
    stderr_to_dev_null: PermissionLevel | None = None
    stderr_to_stdout: PermissionLevel | None = None


class ToolConfig(BaseModel):
    model_config = {"extra": "allow"}

    permission: PermissionLevel | None = None

    @model_validator(mode="after")
    def _warn_extra_fields(self) -> ToolConfig:
        for key in self.model_extra or {}:
            if key in ("allow", "deny"):
                raise ValueError(
                    f"config key '{key}' is not supported - "
                    f"use {('allowed_cmds_regex' if key == 'allow' else 'blocked_paths_regex')} instead"
                )
            log.warning("unknown config key '%s' - unrecognized tool field or typo?", key)
        return self

    wildcard: PermissionLevel | None = Field(None, alias="*")  # default permission for unmatched tools
    #: Policy applied when a command cannot be analysed (parse/shfmt/config
    #: failure).  Defaults to the wildcard (bash `*`) when unset.
    error: PermissionLevel | None = None
    blocked_paths_regex: list[str] = []
    allowed_cmds_regex: list[str] = []
    output_redirection: OutputRedirectionPolicy | PermissionLevel | None = None
    input_redirection: PermissionLevel | None = None
    background_execution: PermissionLevel | None = None
    subshell: PermissionLevel | None = None
    variable_assignment: PermissionLevel | None = None

    @field_validator("blocked_paths_regex", "allowed_cmds_regex", mode="before")
    @classmethod
    def validate_regexes(cls, v: list[str], info: ValidationInfo) -> list[str]:
        """Validate that each pattern compiles as a regex.

        Patterns are used as-written - no stripping or mutation.
        """
        result: list[str] = []
        for p in v:
            try:
                compiled = re.compile(p)
            except re.error as exc:
                raise ValueError(f'pattern "{p}": invalid regex: {exc}') from exc
            result.append(compiled.pattern)
        return result


KNOWN_TOOLS = frozenset({"bash"})


class PermissionsConfig(BaseModel):
    model_config = {"extra": "allow", "str_strip_whitespace": True}

    version: int = 1
    wildcard: PermissionLevel | None = Field(None, alias="*")
    bash: ToolConfig | None = None

    @model_validator(mode="before")
    @classmethod
    def _check_version(cls, data: object) -> object:
        if isinstance(data, dict):
            v = data.get("version")
            if v is not None and v != 1:
                raise ValueError(f"unknown schema version: {v}")
        return data

    @model_validator(mode="after")
    def _warn_unknown_keys(self) -> PermissionsConfig:
        """Log warnings for unrecognized keys (typos, unknown tool names)."""
        known = {"version", "wildcard"} | KNOWN_TOOLS
        for key in self.model_extra or {}:
            if key not in known:
                log.warning("unknown config key '%s' - unrecognized tool name or typo?", key)
        return self
