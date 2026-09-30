from __future__ import annotations

import logging
import re
from enum import Enum

from pydantic import BaseModel, Field, ValidationInfo, field_validator, model_validator

from ..policy import (
    NON_CONSTRUCT_KEYS,
    OUTPUT_REDIRECTION_KINDS,
    POLICY_KEYS,
    WIRE_NON_POLICY_CONFIG_KEYS,
)

log = logging.getLogger(__name__)


class PermissionLevel(str, Enum):
    allow = "allow"
    deny = "deny"
    ask = "ask"


class OutputRedirectionPolicy(BaseModel):
    """Policy for output redirection.

    Accepts either a plain ``PermissionLevel`` string ("allow", "deny", "ask")
    or a dict keyed by redirection kind:

    - ``*`` - wildcard/default for any redirection not otherwise matched
    - ``stdout_to_dev_null`` - level for ``>/dev/null``-style discards
    - ``stderr_to_dev_null`` - level for ``2>/dev/null``-style discards
    - ``stderr_to_stdout`` - level for ``2>&1``-style fd duplication
    - ``other`` - level for every other write (``> file``, ``>> file``,
      ``>| file``), i.e. anything that is not a discard or a duplication

    ``other`` is a named kind, not another name for ``*``: given
    ``ls > /dev/null 2> /tmp/f``, ``{"stdout_to_dev_null": "allow",
    "other": "allow"}`` permits both redirections, while
    ``{"stdout_to_dev_null": "allow", "*": "deny"}`` does not.
    """

    model_config = {"extra": "forbid"}

    wildcard: PermissionLevel | None = Field(None, alias="*")
    stdout_to_dev_null: PermissionLevel | None = None
    stderr_to_dev_null: PermissionLevel | None = None
    stderr_to_stdout: PermissionLevel | None = None
    other: PermissionLevel | None = None

    @model_validator(mode="before")
    @classmethod
    def _reject_unknown_kind(cls, data: object) -> object:
        """Refuse a kind the evaluator cannot produce.

        Without this, a misspelled kind is accepted, stored, and governs
        nothing: ``{"stderr_to_devnull": "deny"}`` looks like it blocks stderr
        discards and silently permits every one of them. The evaluator matches
        on the kinds it classifies, so a key that is not one of them can never
        be consulted.
        """
        if not isinstance(data, dict):
            return data
        unknown = sorted(set(data) - {"*", *OUTPUT_REDIRECTION_KINDS})
        if unknown:
            valid = ", ".join(f"'{k}'" for k in ("*", *OUTPUT_REDIRECTION_KINDS))
            raise ValueError(
                f"unknown output_redirection kind(s) {', '.join(repr(k) for k in unknown)}; valid keys are {valid}"
            )
        return data


#: Every key a ``bash`` block may legally carry, spelled as it appears in a config
#: file.  Derived from the one declared vocabulary rather than restated, so a key
#: added to :mod:`lovely_bash_permissions.policy` is accepted here automatically
#: and a key the evaluator never reads cannot slip in.
VALID_BASH_CONFIG_KEYS: frozenset[str] = frozenset(POLICY_KEYS) | set(NON_CONSTRUCT_KEYS) | WIRE_NON_POLICY_CONFIG_KEYS


class ToolConfig(BaseModel):
    # A bash block is strict: a key the product cannot read must not validate.
    # `permission`, `allow`/`deny` and `blocked_paths_regex` all used to be
    # accepted here and change no verdict - a key that reads as "configured"
    # while governing nothing is worse than a typo, because the wildcard quietly
    # decides the real outcome. The root PermissionsConfig stays permissive
    # instead: a Pi mode legitimately carries read/write/edit blocks that Python
    # never sees, and this package is not the only writer of that file.
    model_config = {"extra": "forbid"}

    @model_validator(mode="before")
    @classmethod
    def _reject_unknown_keys(cls, data: object) -> object:
        """Refuse any key outside the declared vocabulary.

        One rule over a declared set, rather than a table of keys we happen to
        have heard of being mis-spelled: the table grows a new entry every time
        someone guesses a name, and every unlisted guess still validates.
        """
        if not isinstance(data, dict):
            return data
        unknown = sorted(str(key) for key in set(data) - VALID_BASH_CONFIG_KEYS)
        if unknown:
            valid = ", ".join(f"'{key}'" for key in sorted(VALID_BASH_CONFIG_KEYS))
            raise ValueError(
                f"unknown bash config key {', '.join(repr(key) for key in unknown)}; valid keys are {valid}"
            )
        return data

    @model_validator(mode="after")
    def _fields_match_the_policy_vocabulary(self) -> ToolConfig:
        """Every declared field must be a key the product actually reads.

        A field with no reader is the failure this guards: it validates, it is
        documented as if it did something, and it changes no verdict. The
        vocabulary lives in :mod:`lovely_bash_permissions.policy` because the
        evaluator and the effective-config builder both resolve from it.

        Compared by **alias**, not by field name, so this agrees with the wire
        set :data:`VALID_BASH_CONFIG_KEYS` is built from. The two namespaces
        differ in exactly one place - the field is ``wildcard``, the config key
        is ``*`` - and comparing field names here would make the check disagree
        with the validator that enforces the same vocabulary. See D11.
        """
        expected = VALID_BASH_CONFIG_KEYS
        declared = {field.alias or name for name, field in type(self).model_fields.items()}
        if declared != expected:
            undeclared = sorted(declared - expected)
            missing = sorted(expected - declared)
            raise ValueError(
                f"ToolConfig fields and the policy vocabulary disagree; "
                f"declared but unread: {undeclared or 'none'}; "
                f"in the vocabulary but not declared: {missing or 'none'}"
            )
        return self

    wildcard: PermissionLevel | None = Field(None, alias="*")  # default permission for unmatched tools
    #: Policy applied when a command cannot be analysed (parse/shfmt/config
    #: failure).  Defaults to the wildcard (bash `*`) when unset.
    error: PermissionLevel | None = None
    blocked_cmds_regex: list[str] = []
    allowed_cmds_regex: list[str] = []
    output_redirection: OutputRedirectionPolicy | PermissionLevel | None = None
    input_redirection: PermissionLevel | None = None
    background_execution: PermissionLevel | None = None
    #: Policy for $(...) / backtick command substitutions.
    command_substitution: PermissionLevel | None = None
    #: Policy for <(...) / >(...) process substitutions.
    process_substitution: PermissionLevel | None = None
    #: Policy for ( ... ) subshell groups.
    subshell: PermissionLevel | None = None
    variable_assignment: PermissionLevel | None = None

    @field_validator("blocked_cmds_regex", "allowed_cmds_regex", mode="before")
    @classmethod
    def validate_regexes(cls, v: object, info: ValidationInfo) -> object:
        """Validate that each pattern compiles as a regex.

        Patterns are used as-written - no stripping or mutation.

        This runs *before* pydantic coerces the value to a list, so the type
        has to be checked here. A bare string is iterable, and iterating it
        would silently turn ``"not-a-list"`` into the single-character patterns
        ``['n', 'o', 't', '-', 'a', ...]``. Most single characters occur in
        almost any command line, so a malformed ``allowed_cmds_regex`` would
        approve commands the wildcard had denied - a policy-inverting fail-open
        (``"*" : "deny"`` plus ``allowed_cmds_regex: "not-a-list"`` approved
        ``ls``, matching the pattern ``l``). A dict is iterable too, and yields
        its keys. Reject both, naming the fix, as with any other malformed
        config value.
        """
        if not isinstance(v, (list, tuple)):
            key = info.field_name
            # ValueError, not TypeError: pydantic only wraps ValueError from a
            # validator into a ValidationError. TRY004 does not apply.
            raise ValueError(  # noqa: TRY004
                f"{key} must be a list of regex patterns, got {type(v).__name__}. "
                f'Wrap a single pattern in a list, e.g. {key}: ["^ls(\\\\s+.*)?$"]'
            )
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
