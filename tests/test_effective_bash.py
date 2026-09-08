"""Tests for lovely-bash-permissions effective bash config.

Verifies that blocked_paths_regex from config is loaded correctly,
including merging with deny list items.
"""

from lovely_bash_permissions.config.effective_bash import (
    HOOK_LABEL_REGEX,
    get_effective_bash_config,
)
from lovely_bash_permissions.rules import deny_item_to_pattern


class TestDenyItemToPattern:
    """Tests for deny_item_to_pattern — the shared conversion function (issue #3)."""

    def test_bare_command(self) -> None:
        assert deny_item_to_pattern("curl") == "^curl$"

    def test_command_with_spaces(self) -> None:
        assert deny_item_to_pattern("rm -rf /") == "^rm(\\s.*)?$"

    def test_quoted_single(self) -> None:
        assert deny_item_to_pattern("'curl'") == "^curl$"

    def test_quoted_double(self) -> None:
        assert deny_item_to_pattern('"curl"') == "^curl$"

    def test_escaped_chars(self) -> None:
        assert deny_item_to_pattern("rm -rf /") == "^rm(\\s.*)?$"
        # Space-containing items split on first space, escaping only command name
        assert deny_item_to_pattern("cmd [arg]") == "^cmd(\\s.*)?$"

    def test_stripped(self) -> None:
        assert deny_item_to_pattern("  git  ") == "^git$"


class TestDenyItemEquivalence:
    """Verify deny list items and raw blocked_paths_regex behave identically (issue #3)."""

    def test_deny_and_raw_match_same(self) -> None:
        deny_pattern = deny_item_to_pattern("curl")
        assert deny_pattern == "^curl$"

    def test_deny_and_raw_match_same_path(self) -> None:
        deny_pattern = deny_item_to_pattern("/etc/passwd")
        assert deny_pattern == "^/etc/passwd$"


class TestGetEffectiveBashConfig:
    """Tests for get_effective_bash_config."""

    def test_no_raw_bash(self) -> None:
        """No raw bash config -> ask mode, hook label regex only."""

        result = get_effective_bash_config(None, "/project")

        assert result == {"*": "ask", "allowed_cmds_regex": [HOOK_LABEL_REGEX], "blocked_paths_regex": []}

    def test_raw_bash_empty(self) -> None:
        """Empty bash config -> ask, no patterns."""

        result = get_effective_bash_config({}, "/project")

        assert result["*"] == "ask"
        assert result["allowed_cmds_regex"] == [HOOK_LABEL_REGEX]

    def test_bash_config_with_deny(self) -> None:
        """Deny list items are converted to regex patterns."""

        raw = {"*": "deny", "deny": ["curl", "wget"]}
        result = get_effective_bash_config(raw, "/project")

        assert result["*"] == "deny"
        denied = result["blocked_paths_regex"]
        assert "^curl$" in denied
        assert "^wget$" in denied

    def test_bash_config_with_blocked_paths_regex(self) -> None:
        """blocked_paths_regex from config is loaded (the bug fix)."""

        raw = {"*": "ask", "blocked_paths_regex": ["^/tmp/", "^/etc/"]}
        result = get_effective_bash_config(raw, "/project")

        assert result["*"] == "ask"
        blocked = result["blocked_paths_regex"]
        assert "^/tmp/" in blocked
        assert "^/etc/" in blocked

    def test_blocked_paths_regex_merged_with_deny(self) -> None:
        """blocked_paths_regex and deny list are merged together."""

        raw = {
            "*": "ask",
            "blocked_paths_regex": ["^/tmp/"],
            "deny": ["curl"],
        }
        result = get_effective_bash_config(raw, "/project")

        blocked = result["blocked_paths_regex"]
        assert "^/tmp/" in blocked
        assert "^curl$" in blocked

    def test_deny_list_only_no_blocked_paths_regex(self) -> None:
        """Deny list alone works when blocked_paths_regex absent."""

        raw = {"deny": ["rm"]}
        result = get_effective_bash_config(raw, "/project")

        blocked = result["blocked_paths_regex"]
        assert "^rm$" in blocked

    def test_quoted_deny_item(self) -> None:
        """Quoted deny items are stripped to bare patterns."""

        raw = {"deny": ['"curl"', "'wget'"]}
        result = get_effective_bash_config(raw, "/project")

        blocked = result["blocked_paths_regex"]
        assert "^curl$" in blocked
        assert "^wget$" in blocked

    def test_hook_label_always_present(self) -> None:
        """Hook label regex is always included in allowed patterns."""

        result = get_effective_bash_config(None, "/project")
        assert HOOK_LABEL_REGEX in result["allowed_cmds_regex"]

    def test_allowed_patterns_from_allow_and_allowed_cmds_regex(self) -> None:
        """Both allow list and allowed_cmds_regex contribute patterns."""

        raw = {"allow": ["ls", "cat"], "allowed_cmds_regex": ["^git"]}
        result = get_effective_bash_config(raw, "/project")

        allowed = result["allowed_cmds_regex"]
        assert "^ls$" in allowed
        assert "^cat$" in allowed
        assert "^git" in allowed

    def test_deny_items_not_in_allowed_patterns(self) -> None:
        """Deny items become blocked patterns, not allowed ones."""

        raw = {"deny": ["curl"], "allowed_cmds_regex": ["^git"]}
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
