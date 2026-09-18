"""Tests for nested command substitution redirections (Issue #1).

Verifies that redirections inside $() and <( )/>( ) are detected by both
the segment parser (parse_segments → rules) and the tree-based output-redirection
checker (check_output_redirection).
"""

from typing import Any

from lovely_bash_permissions.evaluate import evaluate_bash_command
from lovely_bash_permissions.parser import parse
from lovely_bash_permissions.rules import (
    check_output_redirection,
)
from lovely_bash_permissions.segments import parse_segments


class TestNestedRedirectionsParseSegments:
    """Segment-level tests: redirections inside $() are extracted."""

    def test_nested_command_subst_redirection(self) -> None:
        """> /tmp/deleteme inside $(ls > …) is extracted as a segment redirection."""
        segs = parse_segments("echo $(ls > /tmp/deleteme)")
        # Two segments: echo and ls; ls segment has the redirection
        assert len(segs) == 2
        call_seg, nested_seg = segs
        assert call_seg["command"] == "echo"
        assert len(nested_seg["redirections"]) == 1
        redirs = nested_seg["redirections"]
        assert redirs[0]["Op"] == ">"
        target = redirs[0].get("Word", {}).get("Parts", [{}])[0].get("Value", "")
        assert "/tmp/deleteme" in target

    def test_nested_process_subst_redirection(self) -> None:
        """> inside >(ls > …) is extracted via the segment parser."""
        segs = parse_segments("cat >(ls > /tmp/out.txt)")
        assert len(segs) == 2
        call_seg, nested_seg = segs
        assert call_seg["command"] == "cat"
        redirs = nested_seg["redirections"]
        assert len(redirs) == 1

    def test_plain_redirection_still_works(self) -> None:
        """Plain ls > /tmp/deleteme still extracts redirections correctly."""
        segs = parse_segments("ls > /tmp/deleteme")
        assert len(segs) == 1
        redirs = segs[0]["redirections"]
        assert len(redirs) == 1
        assert redirs[0]["Op"] == ">"


class TestNestedRedirectionsOutputPolicy:
    """Tree-level tests: nested redirections are checked against output_redirection policy."""

    def test_nested_stdout_redirect_ask(self) -> None:
        """> /tmp/deleteme inside $(…) asks under ask policy."""
        tree = parse("echo $(ls > /tmp/deleteme)")
        rules = {"output_redirection": "ask"}
        result = check_output_redirection(tree, rules)
        assert result["status"] == "ask"

    def test_nested_stdout_to_dev_null_allow(self) -> None:
        """> /dev/null inside $(…) allows under per-kind policy (stdout_to_dev_null = allow)."""
        tree = parse("echo $(ls > /dev/null)")
        rules = {"output_redirection": {"*": "ask", "stdout_to_dev_null": "allow"}}
        result = check_output_redirection(tree, rules)
        assert result["status"] == "allow"

    def test_plain_redirect_ask(self) -> None:
        """Plain ls > /tmp/deleteme asks under ask policy (regression check)."""
        tree = parse("ls > /tmp/deleteme")
        rules = {"output_redirection": "ask"}
        result = check_output_redirection(tree, rules)
        assert result["status"] == "ask"

    def test_nested_process_subst_ask(self) -> None:
        """> inside >(…) asks under ask policy."""
        tree = parse("cat >(ls > /tmp/out.txt)")
        rules = {"output_redirection": "ask"}
        result = check_output_redirection(tree, rules)
        assert result["status"] == "ask"

    def test_no_nested_redirection(self) -> None:
        """$(ls -la) has no output redirection → allow."""
        tree = parse("echo $(ls -la)")
        rules = {"output_redirection": "ask"}
        result = check_output_redirection(tree, rules)
        assert result["status"] == "allow"


class TestNestedRedirectionsEvaluateBashCommand:
    """Full pipeline tests: evaluate_bash_command returns ask for nested redirects.

    Regression test for Issue #1 — previously, if nested commands inside $()
    matched allowed patterns, the unconditional override at line ~210
    set overall_status = "allow", swallowing output/input redirection asks.
    """

    def test_nested_redirect_requires_approval(self) -> None:
        """Nested redirect inside $(…) requires approval, even when cmd matches allowed patterns.

        This was the original bug: subshell check unconditionally overrode ask→allow,
        causing echo $(ls > /tmp/deleteme) to auto-approve instead of asking.
        """
        config: dict[str, Any] = {
            "allowed_cmds_regex": ["^(ls|echo)(\\s+.*)?$"],
            "output_redirection": "ask",
        }
        result = evaluate_bash_command("echo $(ls > /tmp/deleteme)", config)
        assert result["status"] == "ask"

    def test_nested_redirect_with_deny_policy(self) -> None:
        """Nested redirect with deny policy returns deny."""
        config: dict[str, Any] = {
            "allowed_cmds_regex": ["^(ls|echo)(\\s+.*)?$"],
            "output_redirection": "deny",
        }
        result = evaluate_bash_command("echo $(ls > /tmp/deleteme)", config)
        assert result["status"] == "deny"

    def test_nested_no_redirection_allows(self) -> None:
        """$(ls -la) has no redirect → allow (regression: don't over-block).

        With subshell policy 'allow', nested commands without redirections are allowed.
        """
        config: dict[str, Any] = {
            "allowed_cmds_regex": ["^(ls|echo)(\\s+.*)?$"],
            "output_redirection": "ask",
            "subshell": "allow",  # subshell policy = allow → no extra ask
        }
        result = evaluate_bash_command("echo $(ls -la)", config)
        assert result["status"] == "allow"

    def test_nested_redirect_to_dev_null_under_deny(self) -> None:
        """Nested > /dev/null with deny policy → deny."""
        config: dict[str, Any] = {
            "allowed_cmds_regex": ["^(ls|echo)(\\s+.*)?$"],
            "output_redirection": "deny",
        }
        result = evaluate_bash_command("echo $(ls > /dev/null)", config)
        assert result["status"] == "deny"

    def test_nested_process_subst_redirect_ask(self) -> None:
        """> inside >(…) requires approval."""
        config: dict[str, Any] = {
            "allowed_cmds_regex": ["^(cat|ls)(\\s+.*)?$"],
            "output_redirection": "ask",
        }
        result = evaluate_bash_command("cat >(ls > /tmp/out.txt)", config)
        assert result["status"] == "ask"

    def test_no_allowed_patterns_nested_redirect(self) -> None:
        """Without allowed patterns, nested redirect still asks."""
        config: dict[str, Any] = {
            "output_redirection": "ask",
        }
        result = evaluate_bash_command("echo $(ls > /tmp/deleteme)", config)
        assert result["status"] == "ask"
