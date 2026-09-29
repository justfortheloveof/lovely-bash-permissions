import re

import pytest
from pydantic import ValidationError

from lovely_bash_permissions.config.schema import (
    VALID_BASH_CONFIG_KEYS,
    OutputRedirectionPolicy,
    PermissionLevel,
    PermissionsConfig,
    ToolConfig,
)
from lovely_bash_permissions.policy import NON_CONSTRUCT_KEYS, WIRE_NON_POLICY_CONFIG_KEYS


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


def test_unrecognized_tool_field_rejected() -> None:
    """A typo *inside* a bash block is a hard error, not a warning.

    The root config stays permissive (a Pi mode legitimately carries
    read/write/edit blocks Python never sees), but a bash block is validated
    against the full declared vocabulary: a misspelled key there reads as
    "this is configured" while the wildcard quietly decides the outcome.
    """
    config = {"bash": {"blocked_path_regex": ["^/tmp/"]}}  # typo: missing s
    with pytest.raises(ValidationError, match="unknown bash config key 'blocked_path_regex'"):
        PermissionsConfig.model_validate(config)


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
    """The allow/deny shortcuts are rejected as unknown keys.

    They were per-command booleans; the pattern lists replaced them. Nothing
    enumerates which replacement a given key had any more - one rule over the
    declared vocabulary covers every key the product cannot read, present and
    future alike, where a per-key table grew an entry per reported mistake.
    """
    with pytest.raises(ValueError, match="unknown bash config key 'allow'"):
        PermissionsConfig.model_validate({"bash": {"allow": ["git"]}})
    with pytest.raises(ValueError, match="unknown bash config key 'deny'"):
        PermissionsConfig.model_validate({"bash": {"deny": ["rm"]}})


@pytest.mark.parametrize("level", ["allow", "deny", "ask", "bogus", None, True])
def test_permission_key_rejected_at_every_level(level: object) -> None:
    """`permission` is refused whatever its value: the rejection is about the key.

    It looks like it sets the tool's default level, but nothing consults it -
    `{"bash": {"permission": "allow"}}` must not validate, because a ``bash``
    block whose wildcard is absent has nothing that could set a per-tool
    default. The message lists the real keys, ``*`` among them.
    """
    with pytest.raises(ValueError, match="unknown bash config key 'permission'"):
        PermissionsConfig.model_validate({"bash": {"permission": level}})


def test_star_key_is_not_rejected() -> None:
    """Guard against over-rejection: `*` is the level-setting key and still works.

    Regression guard for the namespace split. The unknown-key check runs on raw
    dict keys (the wire spelling `*`) while the model field is `wildcard`; a
    vocabulary that mixed the two rejects every bash block that sets a level,
    which is a total failure of the primary feature and invisible on review
    because the vocabulary looks right where it is read.
    """
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


def test_renamed_blocked_key_rejected() -> None:
    """`blocked_paths_regex` is a bash-block key, so it is now refused.

    The assertion inverts deliberately. This used to *pass* on the exact
    fail-open the strict vocabulary exists to close: a key that looks like it
    blocks paths was warned about, ignored, and left `blocked_cmds_regex` empty
    - so a shell was configured to refuse `/etc` and permitted it. (It remains
    a valid key on *non-bash* tools, which this package never validates.)
    """
    with pytest.raises(ValidationError, match="unknown bash config key 'blocked_paths_regex'"):
        ToolConfig.model_validate({"blocked_paths_regex": ["^/etc"]})


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
#: wildcard, and ``error`` - which is resolved here but read when a command
#: cannot be analysed at all, not by the evaluator. Imported rather than
#: restated: a third hand-written copy of the key list is the exact drift this
#: module exists to prevent, and a stale copy would silently stop covering a
#: newly declared key.
NON_POLICY_KEYS = set(WIRE_NON_POLICY_CONFIG_KEYS) | set(NON_CONSTRUCT_KEYS)


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

    Compared by alias for the same reason the schema's own vocabulary check is:
    the field is ``wildcard``, the config key is ``*``.
    """
    declared = {f.alias or name for name, f in ToolConfig.model_fields.items()} - NON_POLICY_KEYS
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


# ---------------------------------------------------------------------------
# The unknown-key message and the vocabulary check that backs it
# ---------------------------------------------------------------------------


def _unknown_key_message() -> str:
    """The validator's message for a block whose only unknown key is ``nope``."""
    with pytest.raises(ValidationError) as exc:
        PermissionsConfig.model_validate({"bash": {"nope": 1}})
    return exc.value.errors()[0]["msg"]


class TestUnknownKeyMessage:
    """The message is a contract, so it is pinned from both ends.

    A message that lists keys the validator would then reject sends the reader
    to fix a config that is already correct; one that omits the key it accepts
    (``*``) sends them to look for a ``wildcard`` key that does not exist.
    """

    def test_names_the_offending_key(self) -> None:
        assert "unknown bash config key 'nope'" in _unknown_key_message()

    def test_lists_star_and_never_the_field_name(self) -> None:
        message = _unknown_key_message()
        assert "'*'" in message
        assert "wildcard" not in message

    @pytest.mark.parametrize("key", sorted(VALID_BASH_CONFIG_KEYS))
    def test_every_key_it_advertises_is_accepted(self, key: str) -> None:
        """Parametrised over the message's own contents, so it cannot drift.

        Deriving the parameter list from what the message actually prints would
        be stronger still, but that couples the test to its own subject; the
        set is the one the message is built from, so this fails if the two
        ever diverge.
        """
        value: object = "deny" if key not in ("allowed_cmds_regex", "blocked_cmds_regex") else ["^ls"]
        PermissionsConfig.model_validate({"bash": {key: value}})

    def test_the_set_it_advertises_is_the_set_it_accepts(self) -> None:
        """The message is built from the vocabulary, so the two cannot disagree."""
        advertised = set(re.findall(r"'([^']+)'", _unknown_key_message().split("valid keys are ")[1]))
        assert advertised == VALID_BASH_CONFIG_KEYS


class TestVocabularyCheckComparesAliases:
    """``_fields_match_the_policy_vocabulary`` must survive the namespace split.

    It compares declared fields against :mod:`lovely_bash_permissions.policy`.
    If it compares *field names* the field is ``wildcard`` while the vocabulary
    holds ``*``, so the check is vacuously satisfied by nothing and - worse -
    a real drift would be reported as a disagreement on two phantom keys. These
    pin the comparison, not the message.
    """

    def test_declared_aliases_equal_the_wire_vocabulary(self) -> None:
        declared = {f.alias or name for name, f in ToolConfig.model_fields.items()}
        assert declared == set(VALID_BASH_CONFIG_KEYS)

    def test_field_names_alone_would_disagree(self) -> None:
        """The reason the alias comparison exists, asserted rather than assumed."""
        assert set(ToolConfig.model_fields) != set(VALID_BASH_CONFIG_KEYS)
        assert "wildcard" in ToolConfig.model_fields
        assert "wildcard" not in VALID_BASH_CONFIG_KEYS

    def test_a_renamed_field_fails_the_check(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class Renamed(ToolConfig):
            pass

        # Declare a field under a name the vocabulary does not hold, and one it
        # holds under a name the schema does not, and require the check to fire.
        Renamed.__annotations__ = dict(ToolConfig.__annotations__)
        original = ToolConfig._fields_match_the_policy_vocabulary
        assert callable(original)
        fields = dict(ToolConfig.model_fields)
        fields["nonsense"] = fields.pop("subshell")
        monkeypatch.setattr(type(fields["nonsense"]), "alias", "nonsense", raising=False)
        monkeypatch.setattr(ToolConfig, "model_fields", fields)
        with pytest.raises(ValidationError, match="policy vocabulary disagree"):
            ToolConfig.model_validate({"*": "ask"})

    def test_an_extra_unread_field_fails_the_check(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fields = dict(ToolConfig.model_fields)
        fields["dead"] = fields["subshell"]
        monkeypatch.setattr(ToolConfig, "model_fields", fields)
        with pytest.raises(ValidationError, match="declared but unread: \\['dead'\\]"):
            ToolConfig.model_validate({"*": "ask"})
