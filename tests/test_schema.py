from pydantic import ValidationError

from lovely_bash_permissions.config.schema import (
    OutputRedirectionPolicy,
    PermissionLevel,
    PermissionsConfig,
    ToolConfig,
)


def test_valid_config() -> None:
    PermissionsConfig.model_validate({})


def test_valid_bash_config() -> None:
    config = {"bash": {"permission": "allow", "blocked_paths_regex": ["^/tmp/"]}}
    PermissionsConfig.model_validate(config)


def test_invalid_permission_value() -> None:
    config = {"bash": {"permission": "alow"}}
    try:
        PermissionsConfig.model_validate(config)
    except ValidationError as exc:
        errors = exc.errors()
        assert len(errors) == 1
        assert "allow" in errors[0]["msg"]


def test_non_dict_tool_config() -> None:
    config = {"bash": "allow"}
    try:
        PermissionsConfig.model_validate(config)
    except ValidationError as exc:
        errors = exc.errors()
        assert len(errors) == 1
        assert "expected object or null" in errors[0]["msg"]


def test_null_tool_config() -> None:
    config = {"bash": None}
    PermissionsConfig.model_validate(config)


def test_valid_regex() -> None:
    config = {"bash": {"blocked_paths_regex": ["^/tmp/"]}}
    PermissionsConfig.model_validate(config)


def test_invalid_regex() -> None:
    config = {"bash": {"blocked_paths_regex": ["["]}}
    try:
        PermissionsConfig.model_validate(config)
    except ValidationError as exc:
        errors = exc.errors()
        assert len(errors) == 1
        assert "unterminated character set" in errors[0]["msg"]


def test_valid_allowed_cmds_regex() -> None:
    config = {"bash": {"allowed_cmds_regex": ["^ls"]}}
    PermissionsConfig.model_validate(config)


def test_tool_permission_enum() -> None:
    assert ToolConfig(permission=PermissionLevel.allow).permission == PermissionLevel.allow
    assert ToolConfig(permission=PermissionLevel.deny).permission == PermissionLevel.deny
    assert ToolConfig(permission=PermissionLevel.ask).permission == PermissionLevel.ask


def test_tool_string_instead_of_object_rejected() -> None:
    config = {"bash": "allow"}
    try:
        PermissionsConfig.model_validate(config)
    except ValidationError as exc:
        errors = exc.errors()
        assert len(errors) == 1


def test_invalid_regex_rejected_with_path() -> None:
    config = {"bash": {"blocked_paths_regex": "["}}
    try:
        PermissionsConfig.model_validate(config)
    except ValidationError as exc:
        errors = exc.errors()
        assert len(errors) == 1
        # Check that tool name appears in the error message
        assert "bash" in errors[0]["msg"]


def test_tool_config_model() -> None:
    config = {"bash": {"permission": "allow", "allowed_cmds_regex": ["^ls"]}}
    ToolConfig.model_validate(config["bash"])


def test_permissions_config_model_valid() -> None:
    PermissionsConfig.model_validate({"bash": {"permission": "allow"}})


def test_permissions_config_model_invalid() -> None:
    try:
        PermissionsConfig.model_validate({"bash": "allow"})
        raise AssertionError("expected ValidationError")
    except ValidationError as exc:
        errors = exc.errors()
        assert len(errors) == 1


def test_version_must_be_1() -> None:
    config = PermissionsConfig.model_validate({"version": 1})
    assert config.version == 1


def test_unknown_version_rejected() -> None:
    try:
        PermissionsConfig.model_validate({"version": 2})
    except ValidationError as exc:
        errors = exc.errors()
        assert len(errors) == 1
        assert "unknown schema version: 2" in errors[0]["msg"]


def test_trailing_dot_unchanged() -> None:
    """Patterns are used as-written; trailing dots (escaped or bare) preserved."""
    config = ToolConfig(
        allowed_cmds_regex=[r"^git\."],
        blocked_paths_regex=["^/tmp/."],  # bare dot preserved
    )
    assert config.allowed_cmds_regex == [r"^git\."]  # escaped dot kept
    assert config.blocked_paths_regex == ["^/tmp/."]  # bare dot kept


def test_invalid_regex_rejected_at_load() -> None:
    config = {"bash": {"blocked_paths_regex": ["["]}}
    try:
        PermissionsConfig.model_validate(config)
    except ValidationError as exc:
        errors = exc.errors()
        assert len(errors) == 1
        assert "invalid regex" in errors[0]["msg"]


def test_empty_pattern_acceptable() -> None:
    config = ToolConfig(blocked_paths_regex=[""])
    assert config.blocked_paths_regex == [""]


def test_unknown_top_level_key_rejected() -> None:
    config = {"Bash": {"permission": "allow"}}  # capital B typo
    try:
        PermissionsConfig.model_validate(config)
    except ValidationError as exc:
        errors = exc.errors()
        assert len(errors) == 1
        assert "unknown config key" in errors[0]["msg"]


def test_unrecognized_tool_field_warns() -> None:
    config = {"bash": {"blocked_path_regex": ["^/tmp/"]}}  # typo: missing s
    try:
        PermissionsConfig.model_validate(config)
    except ValidationError as exc:
        errors = exc.errors()
        assert len(errors) == 1
        assert "unrecognized fields" in errors[0]["msg"]


def test_tool_config_output_redirection_string() -> None:
    """Valid string policy accepted as output_redirection."""
    config: ToolConfig = ToolConfig(
        output_redirection="allow"  # type: ignore[arg-type]
    )
    assert isinstance(config.output_redirection, PermissionLevel)
    assert config.output_redirection == PermissionLevel.allow

    config2: ToolConfig = ToolConfig(
        output_redirection="deny"  # type: ignore[arg-type]
    )
    assert config2.output_redirection == PermissionLevel.deny

    config3: ToolConfig = ToolConfig(
        output_redirection="ask"  # type: ignore[arg-type]
    )
    assert config3.output_redirection == PermissionLevel.ask


def test_tool_config_output_redirection_dict() -> None:
    """Valid dict policy accepted as output_redirection."""
    config: ToolConfig = ToolConfig(
        output_redirection={  # type: ignore[arg-type]
            "*": "allow",
            "stdout_to_dev_null": "deny",
            "stderr_to_dev_null": None,
            "stderr_to_stdout": "ask",
        }
    )
    policy = config.output_redirection
    assert isinstance(policy, OutputRedirectionPolicy)
    assert policy.star == PermissionLevel.allow
    assert policy.stdout_to_dev_null == PermissionLevel.deny
    assert policy.stderr_to_dev_null is None
    assert policy.stderr_to_stdout == PermissionLevel.ask


def test_allow_deny_shorthand_rejected() -> None:
    """Shorthand allow/deny fields are no longer recognized (explicitly removed)."""
    config = {"bash": {"allow": ["git"], "deny": ["rm"]}}
    try:
        PermissionsConfig.model_validate(config)
    except ValidationError as exc:
        errors = exc.errors()
        assert len(errors) == 1
        assert "unrecognized fields" in errors[0]["msg"]
        assert "allow" in errors[0]["msg"]


def test_tool_config_input_background_subshell_levels() -> None:
    """All four bash permission fields accept allow/ask/deny."""
    config = ToolConfig(
        input_redirection=PermissionLevel.allow,
        background_execution=PermissionLevel.ask,
        subshell=PermissionLevel.deny,
    )
    assert config.input_redirection == PermissionLevel.allow
    assert config.background_execution == PermissionLevel.ask
    assert config.subshell == PermissionLevel.deny
