"""Tests for lovely-bash-permissions effective bash config.

Verifies that blocked_paths_regex from config is loaded correctly.
"""

import pytest

from lovely_bash_permissions.config.effective_bash import (
    HOOK_LABEL_REGEX,
    get_effective_bash_config,
)

pytestmark = pytest.mark.usefixtures("devin_global_config_dir")


class TestGetEffectiveBashConfig:
    """Tests for get_effective_bash_config."""

    def test_no_raw_bash(self) -> None:
        """No raw bash config -> ask mode, hook label regex only."""

        result = get_effective_bash_config(None, "/project")

        assert result == {
            "*": "ask",
            "error": "ask",
            "allowed_cmds_regex": [HOOK_LABEL_REGEX],
            "blocked_paths_regex": [],
        }

    def test_raw_bash_empty(self) -> None:
        """Empty bash config -> ask, no patterns."""

        result = get_effective_bash_config({}, "/project")

        assert result["*"] == "ask"
        assert result["allowed_cmds_regex"] == [HOOK_LABEL_REGEX]

    def test_blocked_paths_regex_loaded(self) -> None:
        """blocked_paths_regex from config is loaded directly."""

        raw = {"*": "ask", "blocked_paths_regex": ["^/tmp/", "^/etc/"]}
        result = get_effective_bash_config(raw, "/project")

        assert result["*"] == "ask"
        blocked = result["blocked_paths_regex"]
        assert "^/tmp/" in blocked
        assert "^/etc/" in blocked

    def test_blocked_paths_regex_kept_as_is(self) -> None:
        """blocked_paths_regex patterns are passed through unmodified."""

        raw = {"blocked_paths_regex": ["^/tmp/", "cat", "\\.env$"]}
        result = get_effective_bash_config(raw, "/project")

        assert result["blocked_paths_regex"] == ["^/tmp/", "cat", "\\.env$"]

    def test_hook_label_always_present(self) -> None:
        """Hook label regex is always included in allowed patterns."""

        result = get_effective_bash_config(None, "/project")
        assert HOOK_LABEL_REGEX in result["allowed_cmds_regex"]

    def test_allowed_cmds_regex_contributes_patterns(self) -> None:
        """allowed_cmds_regex patterns contribute to allowed patterns."""

        raw = {"allowed_cmds_regex": ["^ls$", "^cat$", "^git"]}
        result = get_effective_bash_config(raw, "/project")

        allowed = result["allowed_cmds_regex"]
        assert "^ls$" in allowed
        assert "^cat$" in allowed
        assert "^git" in allowed

    def test_blocked_paths_not_in_allowed_patterns(self) -> None:
        """blocked_paths_regex becomes blocked patterns, not allowed ones."""

        raw = {"blocked_paths_regex": ["^curl$"], "allowed_cmds_regex": ["^git"]}
        result = get_effective_bash_config(raw, "/project")

        assert "^curl$" not in result["allowed_cmds_regex"]
        assert "^curl$" in result["blocked_paths_regex"]

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
