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
    subshell: str = "ask",
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
    if subshell != "ask":
        config["subshell"] = subshell
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

    def test_declclause_export_segment_extracted(self) -> None:
        """DeclClause export with a real command arg should extract it."""
        result = evaluate_bash_command(
            "export BOGUS=true bogus",
            make_config(allowed=["^bogus"]),
        )
        assert result["status"] == "allow"  # now matches allowed pattern instead of wildcard ask

    def test_for_clause_extracted(self) -> None:
        """For loop body commands should be extracted."""
        result = evaluate_bash_command("for i in 1 2; do echo; done", make_config(allowed=["^echo$"]))
        assert result["status"] == "allow"  # 'echo' matches pattern

    def test_subshell_extracted(self) -> None:
        """Commands inside parentheses (...) are extracted."""
        result = evaluate_bash_command(
            "( ls )",
            make_config(allowed=["^ls$"]),
        )
        assert result["status"] == "allow"  # 'ls' inside parens matches pattern


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
        """Subshell should be detected and require approval."""
        result = evaluate_bash_command(
            "cat $(ls)",
            make_config(allowed=["^cat", "^ls"]),
        )
        assert result["status"] == "ask"

    def test_nested_subshell(self) -> None:
        """Nested command substitution requires approval."""
        result = evaluate_bash_command(
            "echo $(cat $(ls))",
            make_config(allowed=["^echo", "^cat", "^ls"]),
        )
        assert result["status"] == "ask"

    def test_cmdsubst_without_allowed(self) -> None:
        """Command substitution without allowed patterns requires approval."""
        result = evaluate_bash_command(
            "cat $(ls)",
            make_config(),
        )
        assert result["status"] == "ask"

    def test_subshell_reason(self) -> None:
        """Subshell reason matches TS format."""
        result = evaluate_bash_command(
            "cat $(ls)",
            make_config(),
        )
        assert result["reason"] == "subshell or command substitution requires approval."

    def test_subshell_blocked_path(self) -> None:
        """Dangerous commands inside subshells are blocked."""
        result = evaluate_bash_command(
            "echo $(cat /etc/passwd)",
            make_config(blocked=["^/etc/passwd$"]),
        )
        assert result["status"] == "deny"

    def test_subshell_no_block(self) -> None:
        """Subshell with no blocked paths asks."""
        result = evaluate_bash_command(
            "echo $(cat /etc/passwd)",
            make_config(),
        )
        assert result["status"] == "ask"

    def test_subshell_nested_in_quotes_blocked(self) -> None:
        """Blocked paths inside substitutions within quotes must be caught.

        Regression test for issue #5: CmdSubst nodes nested inside
        DblQuoted/SglQuoted parts were previously missed by the raw-JSON
        visitor, allowing blocked paths hidden inside quoted substitutions.
        """
        result = evaluate_bash_command(
            'echo "$(cat /etc/passwd)"',
            make_config(blocked=["^/etc/passwd$"]),
        )
        assert result["status"] == "deny"

    def test_subshell_deeply_nested_in_quotes_blocked(self) -> None:
        """3-deep nested substitutions inside quotes are also checked."""
        result = evaluate_bash_command(
            'echo "$(a $(b $(cat /etc/passwd)))"',
            make_config(blocked=["^/etc/passwd$"]),
        )
        assert result["status"] == "deny"

    def test_subshell_process_substitution_blocked(self) -> None:
        """Process substitution <(...) also checked against blocked paths."""
        result = evaluate_bash_command(
            "cat <(/etc/passwd)",
            make_config(blocked=["^/etc/passwd$"]),
        )
        assert result["status"] == "deny"

    def test_subshell_deeply_nested_unquoted_blocked(self) -> None:
        """Deep nesting outside quotes also catches blocked paths."""
        result = evaluate_bash_command(
            "echo $(a $(b $(cat /etc/passwd)))",
            make_config(blocked=["^/etc/passwd$"]),
        )
        assert result["status"] == "deny"

    def test_subshell_policy_allow(self) -> None:
        """subshell=allow auto-approves command substitutions."""
        result = evaluate_bash_command(
            "ls $(ls)",
            make_config(subshell="allow"),
        )
        assert result["status"] == "allow"

    def test_subshell_policy_deny(self) -> None:
        """subshell=deny forces denial regardless of wildcard."""
        result = evaluate_bash_command(
            "ls $(ls)",
            make_config(wildcard="allow", subshell="deny"),
        )
        assert result["status"] == "deny"

    def test_subshell_blocked_path_overrides_allow(self) -> None:
        """Blocked paths inside subshell still deny even with allow policy."""
        result = evaluate_bash_command(
            'echo "$(cat /etc/passwd)"',
            make_config(subshell="allow", blocked=["^/etc/passwd$"]),
        )
        assert result["status"] == "deny"


class TestEdgeCases:
    """Tests for edge cases."""

    def test_empty_command(self) -> None:
        """Empty command goes through approval flow (default wildcard=ask)."""
        result = evaluate_bash_command("", make_config())
        assert result["status"] == "ask"

    def test_whitespace_only(self) -> None:
        """Whitespace-only command goes through approval flow (default wildcard=ask)."""
        result = evaluate_bash_command("   ", make_config())
        assert result["status"] == "ask"

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
        """Wildcard ask, specific kinds allow -> any-asks returns ask."""
        result = evaluate_bash_command(
            "echo hi > /tmp/out.txt 2> /dev/null",
            {
                "*": "ask",
                "output_redirection": {"*": "ask", "stdout_to_dev_null": "allow", "stderr_to_dev_null": "allow"},
            },
        )
        assert result["status"] == "ask"

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

    def test_heredoc_input_redirection_ask(self) -> None:
        """Complete heredoc input redirection goes through approval flow."""
        result = evaluate_bash_command("cat << EOF\nhello\nEOF", make_config())
        assert result["status"] == "ask"
        assert "input redirection requires approval" in result["reason"]

    def test_incomplete_heredoc_ask(self) -> None:
        """Incomplete heredoc (unclosed) goes through approval flow."""
        result = evaluate_bash_command("cat << EOF", make_config())
        assert result["status"] == "ask"

    def test_input_redirect_to_blocked_path_denied(self) -> None:
        """Input redirect to blocked path is denied."""
        result = evaluate_bash_command(
            "cat < /etc/passwd",
            make_config(blocked=["^/etc/"]),
        )
        assert result["status"] == "deny"

    def test_input_redirect_allowed_when_policy_allow(self) -> None:
        """Input redirection allowed when input_redirection=allow."""
        result = evaluate_bash_command(
            "cat < /tmp/in.txt",
            {"*": "ask", "input_redirection": "allow"},
        )
        assert result["status"] == "allow"

    def test_input_redirect_ask_when_policy_ask(self) -> None:
        """Input redirection asks when input_redirection=ask."""
        result = evaluate_bash_command(
            "cat < /tmp/in.txt",
            {"*": "ask", "input_redirection": "ask"},
        )
        assert result["status"] == "ask"

    def test_input_redirect_deny_when_policy_deny(self) -> None:
        """Input redirection denied when input_redirection=deny."""
        result = evaluate_bash_command(
            "cat < /tmp/in.txt",
            {"*": "ask", "input_redirection": "deny"},
        )
        assert result["status"] == "deny"

    def test_empty_segments_with_allowed_patterns_asks(self) -> None:
        """Empty segments with allowed patterns → ask (bug 1 fix)."""
        result = evaluate_bash_command("export BOGUS=true bogus", make_config(allowed=["^ls"]))
        assert result["status"] == "ask"

    def test_empty_segments_wildcard_allow(self) -> None:
        """Empty segments with wildcard=allow → allow."""
        result = evaluate_bash_command("export BOGUS=true bogus", make_config(allowed=["^ls"], wildcard="allow"))
        assert result["status"] == "allow"

    def test_empty_segments_wildcard_deny(self) -> None:
        """Empty segments with wildcard=deny → deny."""
        result = evaluate_bash_command("export BOGUS=true bogus", make_config(allowed=["^ls"], wildcard="deny"))
        assert result["status"] == "deny"

    def test_export_segment_extracted_no_patterns(self) -> None:
        """Export with naked word produces segment; no patterns → ask."""
        result = evaluate_bash_command("export BOGUS=true bogus", make_config())
        assert result["status"] == "ask"

    def test_export_segment_no_patterns_allows(self) -> None:
        """Export segment matches wildcard allow → allow."""
        result = evaluate_bash_command("export BOGUS=true bogus", make_config(wildcard="allow"))
        assert result["status"] == "allow"

    def test_export_segment_reason_shows_pattern(self) -> None:
        """Export segment reason contains matching pattern info."""
        result = evaluate_bash_command("export BOGUS=true bogus", make_config(allowed=["^ls"]))
        assert "bogus" in result["reason"]

    def test_allow_reason_shows_patterns(self) -> None:
        """Matching command reason contains actual pattern(s)."""
        result = evaluate_bash_command("ls -la", make_config(allowed=["^ls", "^-la$"]))
        assert "pattern" in result["reason"] or "patterns" in result["reason"]

    def test_empty_segment_reason_not_generic(self) -> None:
        """Empty segments reason NOT generic 'matches allowed pattern'."""
        result = evaluate_bash_command("export BOGUS=true bogus", make_config(allowed=["^ls"]))
        assert "matches allowed pattern" not in result["reason"]

    def test_bogus_command_rejected(self) -> None:
        """'bogus' with allowed patterns → ask (existing behavior)."""
        result = evaluate_bash_command("bogus", make_config(allowed=["^ls"]))
        assert result["status"] == "ask"

    def test_export_bogus_rejected(self) -> None:
        """'export BOGUS=true bogus' → ask (regression for bug 1: empty segments wildcard policy)."""
        result = evaluate_bash_command("export BOGUS=true bogus", make_config(allowed=["^ls"]))
        assert result["status"] == "ask"

    def test_export_bogus_reason_not_auto_approved(self) -> None:
        """Reason should NOT contain 'auto-approved' (regression for bug 2)."""
        result = evaluate_bash_command("export BOGUS=true bogus", make_config(allowed=["^ls"]))
        reason = result["reason"].lower()
        assert "auto-approved" not in reason, f"Reason should not contain 'auto-approved': {reason}"

    def test_case_clause_extracted(self) -> None:
        """Case statement commands are extracted from branch bodies."""
        result = evaluate_bash_command(
            "case x in a) ls;; b) cp src dst;; esac",
            make_config(allowed=["^ls$", "^cp\\s+src\\s+dst$"]),
        )
        assert result["status"] == "allow"  # both commands match patterns
