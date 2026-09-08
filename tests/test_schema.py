from pydantic import ValidationError

from lovely_bash_permissions.config.schema import PermissionsConfig, ToolConfig, _validate_config


def test_valid_config() -> None:
    assert _validate_config({}) == []


def test_valid_bash_config() -> None:
    config = {"bash": {"permission": "allow", "blocked_paths_regex": ["^/tmp/"]}}
    assert _validate_config(config) == []


def test_invalid_permission_value() -> None:
    config = {"bash": {"permission": "alow"}}
    errors = _validate_config(config)
    assert len(errors) == 1
    assert "must be allow, deny, or ask" in errors[0]


def test_non_dict_tool_config() -> None:
    config = {"bash": "allow"}
    errors = _validate_config(config)
    assert len(errors) == 1
    assert "expected object or null, got str" in errors[0]


def test_null_tool_config() -> None:
    config = {"bash": None}
    assert _validate_config(config) == []


def test_valid_regex() -> None:
    config = {"bash": {"blocked_paths_regex": ["^/tmp/"]}}
    assert _validate_config(config) == []


def test_invalid_regex() -> None:
    config = {"bash": {"blocked_paths_regex": ["["]}}
    errors = _validate_config(config)
    assert len(errors) == 1
    assert "is invalid" in errors[0]


def test_valid_allowed_cmds_regex() -> None:
    config = {"bash": {"allowed_cmds_regex": ["^ls"]}}
    assert _validate_config(config) == []


def test_valid_allow_deny_lists() -> None:
    config = {"bash": {"allow": ["git"], "deny": ["rm"]}}
    assert _validate_config(config) == []


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


def test_trailing_period_stripped() -> None:
    config = ToolConfig(allowed_cmds_regex=["^git."], blocked_paths_regex=["^/tmp/"])
    assert config.allowed_cmds_regex == ["^git"]
    assert config.blocked_paths_regex == ["^/tmp/"]
