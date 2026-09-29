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
    config = {"bash": {"*": "allow", "blocked_cmds_regex": ["^/tmp/"]}}
    PermissionsConfig.model_validate(config)


def test_invalid_permission_value() -> None:
    config = {"bash": {"*": "alow"}}
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
    config = {"bash": {"blocked_cmds_regex": ["^/tmp/"]}}
    PermissionsConfig.model_validate(config)


def test_invalid_regex() -> None:
    config = {"bash": {"blocked_cmds_regex": ["["]}}
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


def test_tool_wildcard_enum() -> None:
    for level in (PermissionLevel.allow, PermissionLevel.deny, PermissionLevel.ask):
        assert ToolConfig.model_validate({"*": level}).wildcard == level


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
    # A list, not a bare string: a string would be iterated into characters,
    # which is what would make this test pass at all.
    config = {"bash": {"blocked_cmds_regex": ["["]}}
    try:
        PermissionsConfig.model_validate(config)
        raise AssertionError("expected ValidationError")
    except ValidationError as exc:
        errors = exc.errors()
        assert len(errors) == 1
        # Check that pattern appears in error message
        assert "pattern" in errors[0]["msg"]


def test_tool_config_model() -> None:
    config = {"bash": {"*": "allow", "allowed_cmds_regex": ["^ls"]}}
    ToolConfig.model_validate(config["bash"])


def test_permissions_config_model_valid() -> None:
    PermissionsConfig.model_validate({"bash": {"*": "allow"}})


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
        blocked_cmds_regex=["^/tmp/."],  # bare dot preserved
    )  # type: ignore[call-arg]
    assert config.allowed_cmds_regex == [r"^git\."]  # escaped dot kept
    assert config.blocked_cmds_regex == ["^/tmp/."]  # bare dot kept


def test_invalid_regex_rejected_at_load() -> None:
    config = {"bash": {"blocked_cmds_regex": ["["]}}
    try:
        PermissionsConfig.model_validate(config)
    except ValidationError as exc:
        errors = exc.errors()
        assert len(errors) == 1
        assert "invalid regex" in errors[0]["msg"]


def test_empty_pattern_acceptable() -> None:
    config = ToolConfig(blocked_cmds_regex=[""])  # type: ignore[call-arg]
    assert config.blocked_cmds_regex == [""]


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


def test_allow_deny_shorthand_rejected() -> None:
    """The allow/deny shortcut fields are rejected as config errors."""
    with pytest.raises(ValueError, match="config key 'allow' is not supported.*allowed_cmds_regex"):
        PermissionsConfig.model_validate({"bash": {"allow": ["git"]}})
    with pytest.raises(ValueError, match="config key 'deny' is not supported.*blocked_cmds_regex"):
        PermissionsConfig.model_validate({"bash": {"deny": ["rm"]}})


def test_permission_key_rejected() -> None:
    """`permission` is rejected: it is validated but never read.

    It looks like it sets the tool's default level, but nothing consults it:
    `{"bash": {"permission": "allow"}}` must not validate, because a
    ``"bash"`` block whose wildcard is absent has nothing that could set a
    per-tool default.  A key that reads as "configured" while
    changing nothing is worse than an unknown key, which at least warns, so it
    joins `allow` / `deny` in the rejection list.  The message points at `*`,
    the wildcard that does set a per-tool default and is inherited.
    """
    with pytest.raises(ValueError, match=r"config key 'permission' is not supported - use \* instead"):
        PermissionsConfig.model_validate({"bash": {"permission": "allow"}})


def test_permission_key_rejected_at_every_level() -> None:
    """The rejection is about the key, not the value - any level is refused."""
    for level in ("allow", "deny", "ask", "bogus", None, True):
        with pytest.raises(ValueError, match="config key 'permission' is not supported"):
            PermissionsConfig.model_validate({"bash": {"permission": level}})


def test_permission_key_rejection_precedes_unknown_key_warning(caplog: pytest.LogCaptureFixture) -> None:
    """`permission` raises; it must not fall through to the unknown-key warning path."""
    with pytest.raises(ValueError, match="config key 'permission' is not supported"):
        PermissionsConfig.model_validate({"bash": {"permission": "allow"}})
    assert not [r for r in caplog.record_tuples if "unknown config key 'permission'" in r[2]]


def test_wildcard_is_not_rejected() -> None:
    """Guard against over-rejection: `*` is the documented replacement and still works."""
    config = PermissionsConfig.model_validate({"bash": {"*": "allow"}})
    assert config.bash is not None
    assert config.bash.wildcard == PermissionLevel.allow


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


def test_renamed_blocked_key_ignored_with_warning(caplog: pytest.LogCaptureFixture) -> None:
    """The old `blocked_paths_regex` key is an ordinary unknown key: warned, not read."""
    config = ToolConfig.model_validate({"blocked_paths_regex": ["^/etc"]})
    assert config.blocked_cmds_regex == []
    warnings = [r[2] for r in caplog.record_tuples]
    assert any("unknown config key 'blocked_paths_regex'" in m for m in warnings)


def test_known_tool_bash_accepted() -> None:
    config = {"bash": {"*": "allow"}}
    PermissionsConfig.model_validate(config)


def test_unknown_tool_name_rejected(caplog: pytest.LogCaptureFixture) -> None:
    config = {"git": {"*": "allow"}}
    result = PermissionsConfig.model_validate(config)
    assert result is not None
    assert len(caplog.record_tuples) == 1
    assert "unknown config key 'git'" in caplog.text


class TestRegexListMustBeAList:
    """A bare string must not be iterated into single-character patterns.

    ``validate_regexes`` runs ``mode="before"``, so pydantic never got to
    reject a non-list. A string is iterable, so ``"not-a-list"`` became
    ``['n','o','t','-','a','-','l','i','s','t']`` - and most single characters
    appear in almost any command line. The result was a policy-inverting
    fail-open: ``"*" : "deny"`` with ``allowed_cmds_regex: "not-a-list"``
    approved ``ls``, matching the pattern ``l``.
    """

    @pytest.mark.parametrize("key", ["allowed_cmds_regex", "blocked_cmds_regex"])
    @pytest.mark.parametrize("value", ["not-a-list", "ls", "^ls$", "etc", ""])
    def test_bare_string_rejected(self, key: str, value: str) -> None:
        with pytest.raises(ValidationError) as exc:
            PermissionsConfig.model_validate({"bash": {key: value}})
        assert "must be a list of regex patterns" in exc.value.errors()[0]["msg"]

    def test_bare_string_never_becomes_char_patterns(self) -> None:
        with pytest.raises(ValidationError):
            PermissionsConfig.model_validate({"bash": {"allowed_cmds_regex": "not-a-list"}})
        # The inverse hazard, for contrast: a list entry stays one pattern.
        parsed = ToolConfig.model_validate({"allowed_cmds_regex": ["n", "o", "t"]})
        assert parsed.allowed_cmds_regex == ["n", "o", "t"]

    @pytest.mark.parametrize("value", [{"a": "b"}, 123, 1.5, None, True])
    def test_other_non_list_types_rejected(self, value: object) -> None:
        with pytest.raises(ValidationError) as exc:
            PermissionsConfig.model_validate({"bash": {"allowed_cmds_regex": value}})
        assert "must be a list of regex patterns" in exc.value.errors()[0]["msg"]

    def test_error_names_the_fix(self) -> None:
        with pytest.raises(ValidationError) as exc:
            PermissionsConfig.model_validate({"bash": {"blocked_cmds_regex": "/etc"}})
        msg = exc.value.errors()[0]["msg"]
        assert "blocked_cmds_regex" in msg
        assert "Wrap a single pattern in a list" in msg

    @pytest.mark.parametrize(
        "value",
        [[], ["^ls$"], ["^ls(\\s+.*)?$", "^git\\s+status$"], ["^echo$"]],
    )
    def test_valid_lists_still_accepted(self, value: list[str]) -> None:
        parsed = PermissionsConfig.model_validate({"bash": {"allowed_cmds_regex": value}})
        assert parsed.bash is not None
        assert parsed.bash.allowed_cmds_regex == value

    def test_invalid_regex_inside_a_list_still_rejected(self) -> None:
        with pytest.raises(ValidationError) as exc:
            PermissionsConfig.model_validate({"bash": {"blocked_cmds_regex": ["[", "^ok$"]}})
        assert "unterminated character set" in exc.value.errors()[0]["msg"]


class TestMalformedRegexListCannotInvertPolicy:
    """End to end: a malformed list blocks instead of approving."""

    def test_wildcard_deny_not_overridden_by_char_patterns(self) -> None:
        config = {"bash": {"*": "deny", "allowed_cmds_regex": "not-a-list"}}
        with pytest.raises(ValidationError):
            PermissionsConfig.model_validate(config)

    def test_char_patterns_would_have_matched(self) -> None:
        """Documents that single-character patterns are a real fail-open, not cosmetic."""
        from lovely_bash_permissions.evaluate import evaluate_bash_command

        result = evaluate_bash_command("ls", {"*": "deny", "allowed_cmds_regex": ["l", "s"]})
        assert result["status"] == "allow"
        assert "l" in result["reason"]


# ---------------------------------------------------------------------------
# Every declared key is a key the evaluator enforces
# ---------------------------------------------------------------------------

#: Each construct the evaluator can gate, with a command that contains it.
#: A new policy key must be added here together with a probe showing it changes
#: a verdict; :func:`test_every_declared_key_is_enforced` fails until it is.
#: That is the whole point - a key added to the schema and nowhere else is
#: accepted by the config and silently changes no verdict.
POLICY_PROBES: list[tuple[str, str]] = [
    ("output_redirection", "ls > /tmp/f"),
    ("input_redirection", "cat < /etc/hostname"),
    ("background_execution", "sleep 1 &"),
    ("command_substitution", "echo $(id)"),
    ("process_substitution", "ls <(id)"),
    ("subshell", "( id )"),
    ("variable_assignment", "X=1 ls"),
]

#: Config keys that are not per-construct policies: the two regex lists, the
#: wildcard, and ``error`` - which is resolved here but read by the hook when a
#: command cannot be analysed at all, not by the evaluator.
NON_POLICY_KEYS = frozenset({"allowed_cmds_regex", "blocked_cmds_regex", "wildcard", "error"})


@pytest.mark.parametrize(("key", "probe"), POLICY_PROBES)
def test_declared_policy_key_changes_a_verdict(key: str, probe: str) -> None:
    """A declared policy key must be load-bearing, not merely accepted.

    The probe has to be permitted by the wildcard on its own, so a flip to
    ``deny`` can only be the key acting.
    """
    from lovely_bash_permissions.evaluate import evaluate_bash_command

    permissive = {"*": "allow"}
    assert evaluate_bash_command(probe, dict(permissive))["status"] == "allow", (
        f"probe for {key!r} is not allowed by the wildcard, so it proves nothing"
    )
    result = evaluate_bash_command(probe, {**permissive, key: "deny"})
    assert result["status"] == "deny", f"{key!r} did not deny {probe!r}: {result['reason']}"


def test_every_declared_key_is_enforced() -> None:
    """The probe table must cover every policy key the schema declares.

    Without this, a key could be dropped from the table to silence the test
    above. It also catches the reverse drift: a key the evaluator gates but the
    schema does not accept, which would be a key nobody can set.
    """
    declared = set(ToolConfig.model_fields) - NON_POLICY_KEYS
    probed = {key for key, _ in POLICY_PROBES}
    assert probed == declared, f"policy keys and probes disagree: {probed ^ declared}"


class TestDenyIsAbsoluteOnEveryKey:
    """`deny` blocks regardless of what the wildcard already decided.

    ``test_evaluate.TestDenyIsAbsolute`` covers the three construct keys, which
    are the three that were the bug. These cover all seven, because the docs
    promise absoluteness for every level-bearing key and a `deny` that only
    applies while the verdict is still ``allow`` is inert under the default
    ``"*"``: "ask"``.
    """

    @pytest.mark.parametrize(("key", "probe"), POLICY_PROBES)
    def test_deny_blocks_under_both_permissive_wildcards(self, key: str, probe: str) -> None:
        from lovely_bash_permissions.evaluate import evaluate_bash_command

        for wildcard in ("ask", "allow"):
            result = evaluate_bash_command(probe, {"*": wildcard, key: "deny"})
            assert result["status"] == "deny", (key, wildcard, result["reason"])


class TestOutputRedirectionKindsMustExist:
    """A redirection kind the evaluator cannot produce is a config error.

    The evaluator classifies a write into one of four kinds and then looks up
    the policy for each kind it found. A key that is not one of the four can
    never be consulted, so accepting it means a policy that reads as configured
    and governs nothing: `{"stderr_to_devnull": "deny"}` looks like it blocks
    stderr discards and silently permits every one of them.
    """

    @pytest.mark.parametrize("kind", ["stdout_to_dev_null", "stderr_to_dev_null", "stderr_to_stdout", "other"])
    def test_every_declared_kind_is_accepted(self, kind: str) -> None:
        PermissionsConfig.model_validate({"bash": {"output_redirection": {kind: "deny"}}})

    @pytest.mark.parametrize("kind", ["stderr_to_devnull", "nonsense", "STDERR_TO_DEV_NULL", "stdout_to_null"])
    def test_unknown_kind_is_rejected(self, kind: str) -> None:
        with pytest.raises(ValidationError) as exc:
            PermissionsConfig.model_validate({"bash": {"output_redirection": {kind: "deny"}}})
        assert "unknown output_redirection kind" in exc.value.errors()[0]["msg"]
        assert kind in exc.value.errors()[0]["msg"]

    def test_wildcard_is_still_accepted(self) -> None:
        PermissionsConfig.model_validate({"bash": {"output_redirection": {"*": "deny"}}})

    def test_a_misspelled_kind_does_not_silently_permit_the_redirect(self) -> None:
        """End to end: the typo fails closed rather than allowing the write."""
        from lovely_bash_permissions.evaluate import evaluate_bash_command

        with pytest.raises(ValidationError):
            PermissionsConfig.model_validate({"bash": {"output_redirection": {"stderr_to_devnull": "deny"}}})
        # With the correct spelling the same policy is honoured, so the typo was
        # losing a real decision rather than describing an absent one.
        assert (
            evaluate_bash_command(
                "ls 2> /dev/null", {"*": "allow", "output_redirection": {"stderr_to_dev_null": "deny"}}
            )["status"]
            == "deny"
        )
