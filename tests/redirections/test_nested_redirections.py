"""Tests for nested command substitution redirections.

Verifies that redirections inside $() and <( )/>( ) are detected by both
the segment parser (parse_segments) and the full policy pipeline
(evaluate_bash_command).
"""

from typing import Any

from lovely_bash_permissions.evaluate import evaluate_bash_command
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
        target = redirs[0]["Target"]
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


class TestNestedRedirectionsEvaluateBashCommand:
    """Full pipeline tests: evaluate_bash_command returns ask for nested redirects.

    A nested command inside $() matching allowed patterns must not promote the
    overall verdict: the subshell check cannot override the output/input
    redirection asks.
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
        """$(ls -la) has no redirect → allow (don't over-block).

        With command_substitution policy 'allow', nested commands without redirections are allowed.
        """
        config: dict[str, Any] = {
            "allowed_cmds_regex": ["^(ls|echo)(\\s+.*)?$"],
            "output_redirection": "ask",
            "command_substitution": "allow",  # command_substitution = allow → no extra ask
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
