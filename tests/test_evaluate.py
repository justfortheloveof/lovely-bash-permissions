"""Tests for lovely-devin-permissions bash command evaluation.

Tests the evaluate_bash_command function across different rule types,
aggregation behavior, and edge cases.
"""

from lovely_bash_permissions.evaluate import evaluate_bash_command


def make_config(
    allowed: list[str] | None = None,
    blocked: list[str] | None = None,
    output: str = "allow",
    input_redir: str = "allow",
    background: str = "allow",
    wildcard: str = "ask",
) -> dict[str, list[str] | str]:
    """Helper to create test configuration."""
    config: dict[str, list[str] | str] = {"*": wildcard}
    if allowed is not None:
        config["allowed_cmds_regex"] = allowed
    if blocked is not None:
        config["blocked_paths_regex"] = blocked
    if output != "allow":
        config["output_redirection"] = output
    if input_redir != "allow":
        config["input_redirection"] = input_redir
    if background != "allow":
        config["background_execution"] = background
    return config


class TestAllowedPatterns:
    """Tests for allowed_cmds_regex evaluation."""

    def test_allowed_pattern_matches(self) -> None:
        """Command name only matches -> ask (no args pattern)."""
        result = evaluate_bash_command(
            "ls -la",
            make_config(allowed=["^ls$"]),
        )
        assert result["status"] == "ask"

    def test_allowed_pattern_no_match(self) -> None:
        """Command doesn't match any allowed pattern -> ask."""
        result = evaluate_bash_command(
            "rm -rf /",
            make_config(allowed=["^ls", "^cat"]),
        )
        assert result["status"] == "ask"

    def test_no_allowed_patterns(self) -> None:
        """No allowed_patterns with wildcard allow -> allow."""
        result = evaluate_bash_command("ls", make_config(wildcard="allow"))
        assert result["status"] == "allow"

    def test_multiple_commands_one_allowed(self) -> None:
        """Multiple commands, one matches by name only -> ask."""
        result = evaluate_bash_command(
            "ls && cat file.txt",
            make_config(allowed=["^ls", "^notcat"]),
        )
        assert result["status"] == "ask"

    def test_multiple_commands_none_allowed(self) -> None:
        """Multiple commands, none match -> ask."""
        result = evaluate_bash_command(
            "rm -rf / && echo done",
            make_config(allowed=["^ls", "^cat"]),
        )
        assert result["status"] == "ask"

    def test_allowed_pattern_full_command_line(self) -> None:
        """Allowed pattern should match full command line including args.

        Bug: patterns like ^git\\s+(log|diff|status)(\\s+.*)?$ match "git log"
        but not just the command name "git". The Python implementation was
        matching patterns against cmd_name only, not the full command line.
        """
        # This pattern should match "git log" but not "git"
        result = evaluate_bash_command(
            "git log",
            make_config(allowed=["^git\\s+(log|diff|status)(\\s+.*)?$"]),
        )
        assert result["status"] == "allow"

    def test_allowed_pattern_mismatch_full_command_line(self) -> None:
        """Pattern requiring args should not match bare command name.

        The pattern ^git\\s+log$ requires the full "git log" command,
        so bare "git" should not match.
        """
        result = evaluate_bash_command(
            "git",
            make_config(allowed=["^git\\s+log$"]),
        )
        assert result["status"] == "ask"


class TestBlockedPatterns:
    """Tests for blocked_paths_regex evaluation."""

    def test_blocked_pattern_matches(self) -> None:
        """Argument matches blocked pattern -> deny."""
        result = evaluate_bash_command(
            "ls /etc/passwd",
            make_config(blocked=["/etc/passwd"]),
        )
        assert result["status"] == "deny"

    def test_blocked_pattern_no_match(self) -> None:
        """Argument doesn't match blocked pattern -> allow."""
        result = evaluate_bash_command(
            "ls /var/log",
            make_config(blocked=["/etc/passwd"]),
        )
        assert result["status"] == "allow"

    def test_no_blocked_patterns(self) -> None:
        """No blocked_patterns with wildcard allow -> allow."""
        result = evaluate_bash_command("ls /etc/passwd", make_config(wildcard="allow"))
        assert result["status"] == "allow"

    def test_blocked_command_name_matches(self) -> None:
        """Command name matches blocked pattern -> deny."""
        result = evaluate_bash_command(
            "curl example.com",
            make_config(blocked=["^curl$"]),
        )
        assert result["status"] == "deny"

    def test_multiple_commands_one_blocked(self) -> None:
        """Multiple commands, one blocked -> deny."""
        result = evaluate_bash_command(
            "ls && cat /etc/passwd",
            make_config(blocked=["/etc/passwd"]),
        )
        assert result["status"] == "deny"

    def test_multiple_commands_none_blocked(self) -> None:
        """Multiple commands, none blocked -> allow."""
        result = evaluate_bash_command(
            "ls && cat file.txt",
            make_config(blocked=["/etc/passwd"]),
        )
        assert result["status"] == "allow"


class TestAggregation:
    """Tests for combined allow/deny/ask aggregation."""

    def test_all_allowed(self) -> None:
        """All segments allowed by full command match -> allow."""
        result = evaluate_bash_command(
            "ls -la && cat file.txt",
            make_config(allowed=["^ls\\s+-la", "^cat\\s+file.txt"]),
        )
        assert result["status"] == "allow"

    def test_all_denied(self) -> None:
        """All segments denied -> deny."""
        result = evaluate_bash_command(
            "curl /etc/passwd",
            make_config(blocked=["^curl$", "/etc/passwd"]),
        )
        assert result["status"] == "deny"

    def test_mixed_allowed_and_denied(self) -> None:
        """Some allowed, some denied -> deny."""
        result = evaluate_bash_command(
            "ls && cat /etc/passwd",
            make_config(allowed=["^ls$", "^cat$"], blocked=["/etc/passwd"]),
        )
        assert result["status"] == "deny"

    def test_mixed_allowed_and_asking(self) -> None:
        """Some allowed, some asking -> ask."""
        result = evaluate_bash_command(
            "ls && rm -rf /",
            make_config(allowed=["^ls"]),
        )
        assert result["status"] == "ask"

    def test_all_asking(self) -> None:
        """All segments asking -> ask."""
        result = evaluate_bash_command(
            "rm -rf /",
            make_config(allowed=[]),
        )
        assert result["status"] == "ask"

    def test_deny_overrides_asking(self) -> None:
        """Deny overrides ask in aggregation."""
        result = evaluate_bash_command(
            "ls /etc/passwd && rm -rf /",
            make_config(allowed=["^ls$"], blocked=["/etc/passwd"]),
        )
        assert result["status"] == "deny"

    def test_allowed_overrides_asking(self) -> None:
        """Allowed overrides ask in aggregation (full command match)."""
        result = evaluate_bash_command(
            "ls && rm -rf /",
            make_config(allowed=["^ls", "^rm\\s+-rf\\s+/"]),
        )
        assert result["status"] == "allow"


class TestWildcardPolicy:
    """Tests for wildcard ('*') policy."""

    def test_wildcard_ask(self) -> None:
        """Wildcard ask with no other rules -> ask."""
        result = evaluate_bash_command("ls", make_config(wildcard="ask"))
        assert result["status"] == "ask"

    def test_wildcard_deny(self) -> None:
        """Wildcard deny -> deny."""
        result = evaluate_bash_command("ls", make_config(wildcard="deny"))
        assert result["status"] == "deny"

    def test_wildcard_allow(self) -> None:
        """Wildcard allow -> allow."""
        result = evaluate_bash_command("ls", make_config(wildcard="allow"))
        assert result["status"] == "allow"

    def test_wildcard_with_explicit_allow(self) -> None:
        """Wildcard ask but command explicitly allowed -> allow."""
        result = evaluate_bash_command("ls", make_config(allowed=["^ls"], wildcard="ask"))
        assert result["status"] == "allow"

    def test_wildcard_with_explicit_deny(self) -> None:
        """Wildcard allow but command explicitly denied -> deny."""
        result = evaluate_bash_command(
            "ls /etc/passwd",
            make_config(wildcard="allow", blocked=["/etc/passwd"]),
        )
        assert result["status"] == "deny"


class TestSubshellHandling:
    """Tests for subshell/command substitution handling."""

    def test_subshell_detected(self) -> None:
        """Subshell should be detected in command substitution."""
        result = evaluate_bash_command(
            "cat $(ls)",
            make_config(allowed=["^cat", "^ls"]),
        )
        # Subshell adds complexity but commands are allowed
        assert result["status"] in ["allow", "ask"]

    def test_nested_subshell(self) -> None:
        """Nested command substitution."""
        result = evaluate_bash_command(
            "echo $(cat $(ls))",
            make_config(allowed=["^echo", "^cat", "^ls"]),
        )
        assert result["status"] in ["allow", "ask"]

    def test_cmdsubst_without_allowed(self) -> None:
        """Command substitution without allowed patterns."""
        result = evaluate_bash_command(
            "cat $(ls)",
            make_config(),
        )
        # No restrictions, but subshell detected
        assert result["status"] in ["allow", "ask"]


class TestEdgeCases:
    """Tests for edge cases."""

    def test_empty_command(self) -> None:
        """Empty command."""
        result = evaluate_bash_command("", make_config())
        assert result["status"] == "allow"

    def test_whitespace_only(self) -> None:
        """Whitespace only command."""
        result = evaluate_bash_command("   ", make_config())
        assert result["status"] == "allow"

    def test_single_command(self) -> None:
        """Single command."""
        result = evaluate_bash_command("ls", make_config(allowed=["^ls"]))
        assert result["status"] == "allow"

    def test_multiple_arguments(self) -> None:
        """Multiple arguments (full command match)."""
        result = evaluate_bash_command(
            "ls -la /etc",
            make_config(allowed=["^ls\\s+-la\\s+/etc"]),
        )
        assert result["status"] == "allow"

    def test_quoted_arguments(self) -> None:
        """Quoted arguments (full command match)."""
        result = evaluate_bash_command(
            "echo 'hello world'",
            make_config(allowed=["^echo\\s+'hello\\s+world'"]),
        )
        assert result["status"] == "allow"

    def test_variables(self) -> None:
        """Shell variables (full command match)."""
        result = evaluate_bash_command(
            "ls $HOME",
            make_config(allowed=["^ls\\s+\\$HOME"]),
        )
        assert result["status"] == "allow"

    def test_complex_pipeline(self) -> None:
        """Complex pipeline with multiple rules (full command match)."""
        result = evaluate_bash_command(
            "ls | grep foo | head",
            make_config(allowed=["^ls", "^grep\\s+foo", "^head"]),
        )
        assert result["status"] == "allow"


class TestPerKindOutputRedirection:
    """Tests for per-kind output redirection policy resolution (bug fix)."""

    def test_stderr_to_dev_null_allow_with_ask_wildcard(self) -> None:
        """Bug fix: echo hi 2> /dev/null auto-approves when stderr_to_dev_null=allow."""
        result = evaluate_bash_command(
            "echo hi 2> /dev/null",
            {
                "*": "ask",
                "output_redirection": {"*": "ask", "stderr_to_dev_null": "allow"},
            },
        )
        assert result["status"] == "allow"

    def test_stderr_to_stdout_allow_with_ask_wildcard(self) -> None:
        """2>&1 auto-approves when stderr_to_stdout=allow."""
        result = evaluate_bash_command(
            "echo hi 2>&1",
            {
                "*": "ask",
                "output_redirection": {"*": "ask", "stderr_to_stdout": "allow"},
            },
        )
        assert result["status"] == "allow"

    def test_combined_op_deny_overrides(self) -> None:
        """Combined op >& /dev/null: deny kind overrides ask."""
        result = evaluate_bash_command(
            "echo hi >& /dev/null",
            {
                "*": "ask",
                "output_redirection": {"*": "allow", "stdout_to_dev_null": "allow", "stderr_to_dev_null": "deny"},
            },
        )
        assert result["status"] == "deny"

    def test_stdout_to_dev_null_allow(self) -> None:
        "> /dev/null uses stdout_to_dev_null kind."
        result = evaluate_bash_command(
            "echo hi > /dev/null",
            {
                "*": "ask",
                "output_redirection": {"*": "ask", "stdout_to_dev_null": "allow"},
            },
        )
        assert result["status"] == "allow"

    def test_other_redir_falls_back_to_wildcard(self) -> None:
        """> /tmp/out.txt uses 'other' kind, falls back to wildcard."""
        result = evaluate_bash_command(
            "echo hi > /tmp/out.txt",
            {
                "*": "ask",
                "output_redirection": {"*": "ask", "stdout_to_dev_null": "allow"},
            },
        )
        assert result["status"] == "ask"

    def test_multiple_redirs_all_allow(self) -> None:
        """Both kinds allow -> auto-approve."""
        result = evaluate_bash_command(
            "echo hi > /tmp/out.txt 2> /dev/null",
            {
                "*": "ask",
                "output_redirection": {"*": "ask", "stdout_to_dev_null": "allow", "stderr_to_dev_null": "allow"},
            },
        )
        assert result["status"] == "allow"

    def test_mixed_allow_deny_resolves_to_deny(self) -> None:
        """Deny kind overrides ask/wildcard."""
        result = evaluate_bash_command(
            "echo hi 2> /dev/null",
            {
                "*": "allow",
                "output_redirection": {"*": "allow", "stderr_to_dev_null": "deny"},
            },
        )
        assert result["status"] == "deny"

    def test_input_redirection_uses_wildcard(self) -> None:
        """Input redirection with object policy uses wildcard key."""
        result = evaluate_bash_command(
            "cat < /tmp/in.txt",
            {
                "*": "ask",
                "input_redirection": {"*": "allow"},
            },
        )
        assert result["status"] == "allow"


class TestResultStructure:
    """Tests for result dictionary structure."""

    def test_result_has_status(self) -> None:
        """Result must have 'status' field."""
        result = evaluate_bash_command("ls", make_config())
        assert "status" in result
        assert result["status"] in ["allow", "ask", "deny"]

    def test_result_has_segments(self) -> None:
        """Result must have 'segments' array."""
        result = evaluate_bash_command("ls", make_config())
        assert "segments" in result
        assert isinstance(result["segments"], list)

    def test_result_has_reason(self) -> None:
        """Result must have 'reason' string."""
        result = evaluate_bash_command("ls", make_config())
        assert "reason" in result
        assert isinstance(result["reason"], str)

    def test_segments_have_required_fields(self) -> None:
        """Each segment must have required fields."""
        result = evaluate_bash_command("ls -la", make_config())
        if result["segments"]:
            seg = result["segments"][0]
            assert "command" in seg
            assert "args" in seg
            assert "allowed" in seg
            assert "blocked" in seg
