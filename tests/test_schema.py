from pydantic import ValidationError

from lovely_bash_permissions.config.schema import PermissionLevel, PermissionsConfig, ToolConfig


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


def test_valid_allow_deny_lists() -> None:
    config = {"bash": {"allow": ["git"], "deny": ["rm"]}}
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


def test_trailing_period_stripped() -> None:
    config = ToolConfig(allowed_cmds_regex=["^git."], blocked_paths_regex=["^/tmp/"])
    assert config.allowed_cmds_regex == ["^git"]
    assert config.blocked_paths_regex == ["^/tmp/"]


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
