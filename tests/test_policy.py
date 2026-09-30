"""Tests for the policy vocabulary's accessors."""

import pytest

from lovely_bash_permissions.policy import resolve_level, wildcard_level


class TestPolicyResolveLevel:
    """The one resolution rule both the config builder and the evaluator use."""

    def test_explicit_level_wins(self) -> None:
        assert resolve_level({"subshell": "deny"}, "subshell", "allow") == "deny"

    @pytest.mark.parametrize("value", [None, ""])
    def test_unset_or_empty_inherits_the_wildcard(self, value: object) -> None:
        assert resolve_level({"subshell": value}, "subshell", "allow") == "allow"
        assert resolve_level({}, "subshell", "allow") == "allow"

    def test_dict_form_gets_its_missing_wildcard(self) -> None:
        block = {"output_redirection": {"other": "deny"}}
        assert resolve_level(block, "output_redirection", "ask") == {"other": "deny", "*": "ask"}

    def test_dict_form_keeps_its_own_wildcard(self) -> None:
        block = {"output_redirection": {"*": "allow"}}
        assert resolve_level(block, "output_redirection", "deny") == {"*": "allow"}


class TestPolicyWildcardLevel:
    def test_absent_wildcard_is_ask(self) -> None:
        assert wildcard_level({}) == "ask"

    def test_present_wildcard_is_returned_as_written(self) -> None:
        assert wildcard_level({"*": "deny"}) == "deny"
