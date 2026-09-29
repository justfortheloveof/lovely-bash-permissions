"""Tests for lovely-bash-permissions effective bash config.

Verifies that blocked_cmds_regex from config is loaded correctly.
"""

import pytest

from lovely_bash_permissions.config.effective_bash import (
    get_effective_bash_config,
    resolve_bash_config,
)
from lovely_bash_permissions.policy import NON_CONSTRUCT_KEYS, POLICY_KEYS

pytestmark = pytest.mark.usefixtures("devin_global_config_dir")


class TestGetEffectiveBashConfig:
    """Tests for get_effective_bash_config."""

    def test_no_raw_bash(self) -> None:
        """No raw bash config -> ask mode, no allowed patterns."""

        result = get_effective_bash_config(None, "/project")

        assert result == {
            "*": "ask",
            "error": "ask",
            "allowed_cmds_regex": [],
            "blocked_cmds_regex": [],
        }

    def test_raw_bash_empty(self) -> None:
        """Empty bash config -> ask, no patterns."""

        result = get_effective_bash_config({}, "/project")

        assert result["*"] == "ask"
        assert result["allowed_cmds_regex"] == []

    def test_blocked_cmds_regex_loaded(self) -> None:
        """blocked_cmds_regex from config is loaded directly."""

        raw = {"*": "ask", "blocked_cmds_regex": ["^/tmp/", "^/etc/"]}
        result = get_effective_bash_config(raw, "/project")

        assert result["*"] == "ask"
        blocked = result["blocked_cmds_regex"]
        assert "^/tmp/" in blocked
        assert "^/etc/" in blocked

    def test_blocked_cmds_regex_kept_as_is(self) -> None:
        """blocked_cmds_regex patterns are passed through unmodified."""

        raw = {"blocked_cmds_regex": ["^/tmp/", "cat", "\\.env$"]}
        result = get_effective_bash_config(raw, "/project")

        assert result["blocked_cmds_regex"] == ["^/tmp/", "cat", "\\.env$"]

    def test_hook_label_regex_not_injected(self) -> None:
        """The hook `:` label is recognized structurally by the evaluator, not
        via a quote-anchored regex in allowed patterns."""

        result = get_effective_bash_config(None, "/project")
        assert not any("♡ perms" in p for p in result["allowed_cmds_regex"])

    def test_allowed_cmds_regex_contributes_patterns(self) -> None:
        """allowed_cmds_regex patterns contribute to allowed patterns."""

        raw = {"allowed_cmds_regex": ["^ls$", "^cat$", "^git"]}
        result = get_effective_bash_config(raw, "/project")

        allowed = result["allowed_cmds_regex"]
        assert "^ls$" in allowed
        assert "^cat$" in allowed
        assert "^git" in allowed

    def test_blocked_paths_not_in_allowed_patterns(self) -> None:
        """blocked_cmds_regex becomes blocked patterns, not allowed ones."""

        raw = {"blocked_cmds_regex": ["^curl$"], "allowed_cmds_regex": ["^git"]}
        result = get_effective_bash_config(raw, "/project")

        assert "^curl$" not in result["allowed_cmds_regex"]
        assert "^curl$" in result["blocked_cmds_regex"]

    def test_wildcard_allow(self) -> None:
        """Config with '*' = 'allow' produces effective '*' == 'allow'."""
        raw = {"*": "allow"}
        result = get_effective_bash_config(raw, "/project")

        assert result["*"] == "allow"

    def test_wildcard_deny(self) -> None:
        """Config with '*' = 'deny' produces effective '*' == 'deny'."""
        raw = {"*": "deny"}
        result = get_effective_bash_config(raw, "/project")

        assert result["*"] == "deny"

    def test_wildcard_ask(self) -> None:
        """Config with '*' = 'ask' produces effective '*' == 'ask'."""
        raw = {"*": "ask"}
        result = get_effective_bash_config(raw, "/project")

        assert result["*"] == "ask"

    def test_root_wildcard_propagates_without_bash(self) -> None:
        """Top-level wildcard flows into the effective '*' when bash block is absent."""
        result = get_effective_bash_config(None, "/project", top_level_wildcard="deny")

        assert result["*"] == "deny"

    def test_root_wildcard_fallback_without_bash(self) -> None:
        """Absent bash '*' falls back to the top-level wildcard, then to ask."""
        assert (
            get_effective_bash_config({"allowed_cmds_regex": ["^ls"]}, "/project", top_level_wildcard="deny")["*"]
            == "deny"
        )
        assert get_effective_bash_config({"allowed_cmds_regex": ["^ls"]}, "/project")["*"] == "ask"

    def test_bash_star_overrides_root_wildcard(self) -> None:
        """bash.* takes precedence over the top-level wildcard."""
        raw = {"*": "deny"}
        result = get_effective_bash_config(raw, "/project", top_level_wildcard="allow")

        assert result["*"] == "deny"

    def test_options_inherit_resolved_star(self) -> None:
        """Options absent from the bash block inherit the effective '*' value."""
        raw = {"*": "deny"}
        result = get_effective_bash_config(raw, "/project")

        assert result["subshell"] == "deny"
        assert result["variable_assignment"] == "deny"
        assert result["input_redirection"] == "deny"
        assert result["background_execution"] == "deny"
        assert result["output_redirection"] == "deny"

    def test_substitution_keys_all_resolved(self) -> None:
        """All three substitution/subshell keys resolve: explicit wins, omitted inherit '*'."""
        raw = {"*": "deny", "command_substitution": "allow"}
        result = get_effective_bash_config(raw, "/project")

        assert result["command_substitution"] == "allow"  # explicit
        assert result["process_substitution"] == "deny"  # inherited from '*'
        assert result["subshell"] == "deny"  # inherited from '*'

    def test_explicit_option_beats_star(self) -> None:
        """An explicitly set option keeps its value over an inherited '*'."""
        raw = {"*": "deny", "subshell": "ask", "output_redirection": {"stderr_to_dev_null": "allow"}}
        result = get_effective_bash_config(raw, "/project")

        assert result["subshell"] == "ask"
        assert result["output_redirection"] == {"*": "deny", "stderr_to_dev_null": "allow"}

    def test_output_redirection_dict_gets_star(self) -> None:
        """Dict-form output_redirection receives the resolved '*' for its kinds."""
        raw = {"*": "ask", "output_redirection": {"stdout_to_dev_null": "deny"}}
        result = get_effective_bash_config(raw, "/project")

        assert result["output_redirection"] == {"stdout_to_dev_null": "deny", "*": "ask"}

    def test_error_defaults_to_resolved_star(self) -> None:
        """'error' absent -> inherits the effective '*' value."""
        raw = {"*": "deny"}
        result = get_effective_bash_config(raw, "/project")

        assert result["error"] == "deny"

    def test_explicit_error_beats_star(self) -> None:
        """Explicit bash 'error' overrides the wildcard."""
        raw = {"*": "ask", "error": "deny"}
        result = get_effective_bash_config(raw, "/project")

        assert result["error"] == "deny"

    def test_error_root_wildcard_without_bash(self) -> None:
        """Without a bash block, 'error' mirrors the top-level wildcard."""
        result = get_effective_bash_config(None, "/project", top_level_wildcard="deny")

        assert result["error"] == "deny"


class TestResolveBashConfig:
    """The host-agnostic half, on its own.

    ``resolve_bash_config`` exists so a host with no Devin ``Exec()`` concept
    can resolve a block. The tests below are therefore also the evidence that
    the split is a split: the wrapper is this plus a merge, nothing else.
    """

    def test_matches_the_devin_wrapper_where_devin_adds_nothing(self) -> None:
        for raw in (None, {}, {"*": "ask"}, {"*": "allow", "allowed_cmds_regex": ["^ls"]}):
            assert resolve_bash_config(raw) == get_effective_bash_config(raw, "/project")

    def test_absent_and_empty_take_the_same_branch(self) -> None:
        """`if not raw_bash:`, not `if raw_bash is None:` - see resolve's docstring.

        An empty block is a documented no-op, so it must return the bare
        four-key default and never be spread or resolved. The natural-looking
        `is None` would resolve every policy key against the wildcard and
        change the output here, which is the drift the refactor exists to
        prevent.
        """
        assert resolve_bash_config({}) == resolve_bash_config(None)
        assert resolve_bash_config({}) == {
            "*": "ask",
            "error": "ask",
            "allowed_cmds_regex": [],
            "blocked_cmds_regex": [],
        }

    def test_empty_block_ignores_the_top_level_wildcard_for_its_keys(self) -> None:
        """`{}` returns the default under the *default* wildcard, not the mode's."""
        assert resolve_bash_config({}, "allow") == {
            "*": "allow",
            "error": "allow",
            "allowed_cmds_regex": [],
            "blocked_cmds_regex": [],
        }

    def test_every_policy_key_is_resolved_against_the_wildcard(self) -> None:
        result = resolve_bash_config({"blocked_cmds_regex": ["/etc/passwd"]}, "deny")
        for key in (*POLICY_KEYS, *NON_CONSTRUCT_KEYS):
            assert result[key] == "deny", key

    def test_an_explicit_key_beats_the_wildcard(self) -> None:
        assert resolve_bash_config({"*": "deny", "subshell": "allow"})["subshell"] == "allow"

    def test_a_dict_policy_gets_the_wildcard_as_its_own(self) -> None:
        result = resolve_bash_config({"*": "deny", "output_redirection": {"other": "allow"}})
        assert result["output_redirection"] == {"other": "allow", "*": "deny"}

    def test_unknown_keys_pass_through(self) -> None:
        """The `{**bash}` spread is load-bearing and is preserved byte for byte.

        After Phase 1 the validated path cannot carry an unknown key, but this
        function is still called directly with raw dicts by ``--show-config``
        and by the golden harness. A host that resolved a block itself and
        lost a key it passed on would be a different function, not a refactor.
        """
        result = resolve_bash_config({"*": "ask", "nonsense": 1})
        assert result["nonsense"] == 1

    def test_the_wrapper_only_adds_devin_patterns(self) -> None:
        """The Devin half is the resolution plus a merge - nothing more."""
        raw = {"*": "ask", "allowed_cmds_regex": ["^ls"], "blocked_cmds_regex": ["/etc/shadow"]}
        resolved = resolve_bash_config(raw)
        merged = get_effective_bash_config(raw, "/project")
        assert set(merged) == set(resolved)
        assert {k: v for k, v in merged.items() if k != "allowed_cmds_regex"} == {
            k: v for k, v in resolved.items() if k != "allowed_cmds_regex"
        }
        assert merged["allowed_cmds_regex"][:1] == ["^ls"]
