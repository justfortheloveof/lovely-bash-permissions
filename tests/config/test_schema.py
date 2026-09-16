import pytest
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
        raise AssertionError("expected ValidationError")
    except ValidationError as exc:
        errors = exc.errors()
        assert len(errors) == 1
        assert "allow" in errors[0]["msg"]


def test_non_dict_tool_config() -> None:
    config = {"bash": "allow"}
    try:
        PermissionsConfig.model_validate(config)
        raise AssertionError("expected ValidationError")
    except ValidationError as exc:
        errors = exc.errors()
        assert len(errors) == 1
        assert "valid dictionary" in errors[0]["msg"]


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
        raise AssertionError("expected ValidationError")
    except ValidationError as exc:
        errors = exc.errors()
        assert len(errors) == 1
        assert "unterminated character set" in errors[0]["msg"]


def test_valid_allowed_cmds_regex() -> None:
    config = {"bash": {"allowed_cmds_regex": ["^ls"]}}
    PermissionsConfig.model_validate(config)


def test_tool_permission_enum() -> None:
    assert ToolConfig(permission=PermissionLevel.allow).permission == PermissionLevel.allow  # type: ignore[call-arg]
    assert ToolConfig(permission=PermissionLevel.deny).permission == PermissionLevel.deny  # type: ignore[call-arg]
    assert ToolConfig(permission=PermissionLevel.ask).permission == PermissionLevel.ask  # type: ignore[call-arg]


def test_tool_string_instead_of_object_rejected() -> None:
    config = {"bash": "allow"}
    try:
        PermissionsConfig.model_validate(config)
        raise AssertionError("expected ValidationError")
    except ValidationError as exc:
        errors = exc.errors()
        assert len(errors) == 1
        assert "valid dictionary" in errors[0]["msg"]


def test_invalid_regex_rejected_with_path() -> None:
    config = {"bash": {"blocked_paths_regex": "["}}
    try:
        PermissionsConfig.model_validate(config)
        raise AssertionError("expected ValidationError")
    except ValidationError as exc:
        errors = exc.errors()
        assert len(errors) == 1
        # Check that pattern appears in error message
        assert "pattern" in errors[0]["msg"]


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
        assert "valid dictionary" in errors[0]["msg"]


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
    )  # type: ignore[call-arg]
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
    config = ToolConfig(blocked_paths_regex=[""])  # type: ignore[call-arg]
    assert config.blocked_paths_regex == [""]


def test_unknown_top_level_key_rejected(caplog: pytest.LogCaptureFixture) -> None:
    # Unknown tool names log a warning but config still loads
    config = {"Bash": "allow"}  # unknown tool name (capital B)
    result = PermissionsConfig.model_validate(config)
    assert result is not None
    assert len(caplog.record_tuples) == 1
    assert "unknown config key" in caplog.text


def test_tool_config_error_valid() -> None:
    config = PermissionsConfig.model_validate({"bash": {"error": "deny"}})
    assert config.bash is not None
    assert config.bash.error == PermissionLevel.deny


def test_tool_config_error_allows_all_levels() -> None:
    for level in ("allow", "ask", "deny"):
        config = PermissionsConfig.model_validate({"bash": {"error": level}})
        assert config.bash is not None
        assert config.bash.error == PermissionLevel(level)


def test_tool_config_error_invalid_rejected() -> None:
    config = {"bash": {"error": "deny-all"}}
    try:
        PermissionsConfig.model_validate(config)
        raise AssertionError("expected ValidationError")
    except ValidationError as exc:
        errors = exc.errors()
        assert len(errors) == 1
        assert "allow" in errors[0]["msg"]


def test_unrecognized_tool_field_warns(caplog: pytest.LogCaptureFixture) -> None:
    config = {"bash": {"blocked_path_regex": ["^/tmp/"]}}  # typo: missing s
    result = PermissionsConfig.model_validate(config)
    assert result is not None
    assert len(caplog.record_tuples) == 1
    assert "unknown config key 'blocked_path_regex'" in caplog.text


def test_tool_config_output_redirection_string() -> None:
    """Valid string policy accepted as output_redirection."""
    config: ToolConfig = ToolConfig(
        output_redirection="allow"  # type: ignore[arg-type]
    )  # type: ignore[call-arg]
    assert isinstance(config.output_redirection, PermissionLevel)
    assert config.output_redirection == PermissionLevel.allow

    config2: ToolConfig = ToolConfig(
        output_redirection="deny"  # type: ignore[arg-type]
    )  # type: ignore[call-arg]
    assert config2.output_redirection == PermissionLevel.deny

    config3: ToolConfig = ToolConfig(
        output_redirection="ask"  # type: ignore[arg-type]
    )  # type: ignore[call-arg]
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
    )  # type: ignore[call-arg]
    policy = config.output_redirection
    assert isinstance(policy, OutputRedirectionPolicy)
    assert policy.wildcard == PermissionLevel.allow
    assert policy.stdout_to_dev_null == PermissionLevel.deny
    assert policy.stderr_to_dev_null is None
    assert policy.stderr_to_stdout == PermissionLevel.ask


def test_allow_deny_shorthand_rejected(caplog: pytest.LogCaptureFixture) -> None:
    """Shorthand allow/deny fields are unrecognized and logged as warnings."""
    config = {"bash": {"allow": ["git"], "deny": ["rm"]}}
    result = PermissionsConfig.model_validate(config)
    assert result is not None
    # Both unknown keys log warnings
    warnings = [r[2] for r in caplog.record_tuples]
    assert any("unknown config key 'allow'" in m for m in warnings)
    assert any("unknown config key 'deny'" in m for m in warnings)


def test_tool_config_input_background_subshell_levels() -> None:
    """All four bash permission fields accept allow/ask/deny."""
    config = ToolConfig(
        input_redirection=PermissionLevel.allow,
        background_execution=PermissionLevel.ask,
        subshell=PermissionLevel.deny,
    )  # type: ignore[call-arg]
    assert config.input_redirection == PermissionLevel.allow
    assert config.background_execution == PermissionLevel.ask
    assert config.subshell == PermissionLevel.deny


def test_unknown_key_logs_warning(caplog: pytest.LogCaptureFixture) -> None:
    config = {"git": "allow"}  # shorthand unknown tool
    result = PermissionsConfig.model_validate(config)
    assert result is not None
    warnings = [r[2] for r in caplog.record_tuples]
    assert any("unknown config key 'git'" in m for m in warnings)


def test_typo_key_logs_warning(caplog: pytest.LogCaptureFixture) -> None:
    config = {"blocked_path_regex": "^/tmp/"}  # typo at top level
    result = PermissionsConfig.model_validate(config)
    assert result is not None
    warnings = [r[2] for r in caplog.record_tuples]
    assert any("unknown config key 'blocked_path_regex'" in m for m in warnings)


def test_known_tool_bash_accepted() -> None:
    config = {"bash": {"permission": "allow"}}
    PermissionsConfig.model_validate(config)


def test_unknown_tool_name_rejected(caplog: pytest.LogCaptureFixture) -> None:
    config = {"git": {"permission": "allow"}}
    result = PermissionsConfig.model_validate(config)
    assert result is not None
    assert len(caplog.record_tuples) == 1
    assert "unknown config key 'git'" in caplog.text
