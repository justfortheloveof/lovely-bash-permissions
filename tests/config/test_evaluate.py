"""Tests for lovely-devin-permissions bash command evaluation.

Tests the evaluate_bash_command function across different rule types,
aggregation behavior, and edge cases.
"""

from typing import ClassVar

import pytest

from lovely_bash_permissions.errors import LovelyDevinPermissionsError
from lovely_bash_permissions.evaluate import evaluate_bash_command
from lovely_bash_permissions.hook import _hook_command
from tests.config.conftest import make_config


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

    def test_allowed_pattern_unanchored_substring(self) -> None:
        """Unanchored allowed pattern matches anywhere in the command line."""
        result = evaluate_bash_command(
            "echo git",
            make_config(allowed=["git"]),
        )
        assert result["status"] == "allow"
        assert "command matches allowed pattern: git" in result["reason"]

    def test_allowed_pattern_unanchored_absent_still_asks(self) -> None:
        """Unanchored allowed pattern still asks when it matches nowhere."""
        result = evaluate_bash_command(
            "echo hi",
            make_config(allowed=["git"]),
        )
        assert result["status"] == "ask"

    def test_declclause_export_segment_extracted(self) -> None:
        """DeclClause export is evaluated as the export command."""
        result = evaluate_bash_command(
            "export BOGUS=true bogus",
            make_config(allowed=[r"^export(\s+.*)?$"]),
        )
        assert result["status"] == "allow"

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

    def test_cstyle_loop_extracted(self) -> None:
        """C-style for loop body commands are extracted."""
        result = evaluate_bash_command(
            "for ((i=0;i<10;i++)); do echo x; done",
            make_config(allowed=["^echo\\s+x$"]),
        )
        assert result["status"] == "allow"  # 'echo x' matches pattern

    def test_cstyle_prelude_cmdsubst_not_bypassed(self) -> None:
        """C-style prelude substitutions in for ((...)) are no longer dropped.

        Before the ForClause.cstyle fix this returned allow - the rm ran in
        the loop init and every typed-AST pass (subshell policy, blocked-path
        scan, segment extraction) missed it. The foreach form
        for i in $(rm ...) was already correctly denied.
        """
        result = evaluate_bash_command(
            "for ((i=$(rm -rf /etc/passwd); i<1; i++)); do :; done",
            {"*": "allow", "subshell": "deny", "blocked_paths_regex": [r"/etc"]},
        )
        assert result["status"] == "deny"

    def test_cstyle_prelude_cmdsubst_visible_to_subshell_pass(self) -> None:
        """_has_cmd_subst sees the C-style prelude via the typed AST."""
        from lovely_bash_permissions.converter import node_from_json
        from lovely_bash_permissions.evaluate import _has_cmd_subst
        from lovely_bash_permissions.parser import parse

        raw = parse("for ((i=$(date); i<1; i++)); do :; done", "bash")
        assert node_from_json(raw) is not None
        assert _has_cmd_subst(raw) is True


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
        """No blocked match but no allow-list -> wildcard ask governs (bug #7)."""
        result = evaluate_bash_command(
            "ls /var/log",
            make_config(blocked=["/etc/passwd"]),
        )
        assert result["status"] == "ask"

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
        """Multiple commands, none blocked, no allow-list -> wildcard ask governs (bug #7)."""
        result = evaluate_bash_command(
            "ls && cat file.txt",
            make_config(blocked=["/etc/passwd"]),
        )
        assert result["status"] == "ask"


class TestWildcardIsBaseline:
    """The wildcard is the per-command baseline; specific policies add constraints only.

    A command is auto-approved only by an allowed-pattern match or an explicit
    ``"*": "allow"``. No policy (subshell, variable_assignment, redirection,
    blocked-only configs) grants a blanket allow for commands that are neither
    allow-listed nor wildcard-allowed - bug #7 and the broader fail-open class.
    """

    def test_blocked_only_config_asks_param_expansion_repro(self) -> None:
        """bug #7 repro: `${x%@/etc/*}` with blocked-only + ask now asks."""
        result = evaluate_bash_command(
            "echo ${x%@/etc/*}",
            {"*": "ask", "blocked_paths_regex": [r"/etc"]},
        )
        assert result["status"] == "ask"

    def test_blocked_only_config_asks_plain_command(self) -> None:
        """Blocked-only config under ask wildcard no longer auto-allows."""
        result = evaluate_bash_command(
            "echo hi",
            {"*": "ask", "blocked_paths_regex": [r"/etc"]},
        )
        assert result["status"] == "ask"
        assert "not allowlisted" in result["reason"]
        assert "allowed by wildcard policy" not in result["reason"]

    def test_blocked_only_config_asks_curl(self) -> None:
        """A non-blocked command still asks under blocked-only + ask."""
        result = evaluate_bash_command(
            "curl example.com",
            {"*": "ask", "blocked_paths_regex": [r"/etc"]},
        )
        assert result["status"] == "ask"

    def test_blocked_only_config_still_denies(self) -> None:
        """Blocked paths still deny under the reduced config."""
        result = evaluate_bash_command(
            "cat /etc/passwd",
            {"*": "ask", "blocked_paths_regex": [r"/etc"]},
        )
        assert result["status"] == "deny"

    def test_deny_list_via_explicit_wildcard_allow(self) -> None:
        """Explicit "*": "allow" still provides deny-list semantics."""
        config = {"*": "allow", "blocked_paths_regex": [r"/etc"]}
        assert evaluate_bash_command("echo hi", config)["status"] == "allow"
        assert evaluate_bash_command("cat /etc/passwd", config)["status"] == "deny"

    def test_subshell_allow_does_not_approve_outer_command(self) -> None:
        """`echo $(date)` + subshell=allow + ask wildcard asks for `echo`."""
        result = evaluate_bash_command(
            "echo $(date)",
            {"*": "ask", "subshell": "allow"},
        )
        assert result["status"] == "ask"

    def test_subshell_allow_with_all_listed_commands(self) -> None:
        """Subshell=allow approves when outer and inner commands are allow-listed."""
        result = evaluate_bash_command(
            "echo $(date)",
            {"*": "ask", "subshell": "allow", "allowed_cmds_regex": [r"^echo(\s+.*)?$", r"^date$"]},
        )
        assert result["status"] == "allow"

    def test_variable_assignment_allow_does_not_approve_command(self) -> None:
        """`FOO=bar curl x` + va=allow + ask wildcard asks for `curl`."""
        result = evaluate_bash_command(
            "FOO=bar curl x",
            {"*": "ask", "variable_assignment": "allow"},
        )
        assert result["status"] == "ask"
        assert '"curl" command is not allowlisted' in result["reason"]

    def test_variable_assignment_allow_standalone_truthful_reason(self) -> None:
        """Standalone `FOO=bar` with va=allow allows with a truthful reason."""
        result = evaluate_bash_command(
            "FOO=bar",
            {"*": "ask", "variable_assignment": "allow"},
        )
        assert result["status"] == "allow"
        assert "variable assignment allowed" in result["reason"]
        assert "wildcard policy" not in result["reason"]

    def test_wildcard_allow_no_patterns_truthful_reason(self) -> None:
        """Explicit wildcard allow keeps the truthful fallback reason."""
        result = evaluate_bash_command("ls", {"*": "allow"})
        assert result["status"] == "allow"
        assert result["reason"] == "allowed by wildcard policy (allow)"

    def test_empty_segment_wildcard_ask(self) -> None:
        """No-segment commands under "*": "ask" fall back to the wildcard (ask)."""
        result = evaluate_bash_command(
            "[[ -f x ]]",
            {"*": "ask"},
        )
        assert result["status"] == "ask"
        assert "wildcard policy (ask)" in result["reason"]

    def test_cmdsubst_in_test_clause_resolves_to_real_segment(self) -> None:
        """bug #2/#6: test-operand command substitution now yields a real cat segment.

        Verdict is unchanged (ask under "*": "ask"), but the reason now names
        the real command instead of falling through the empty-segment path.
        """
        result = evaluate_bash_command(
            "[[ $(cat /etc/passwd) == x ]]",
            {"*": "ask"},
        )
        assert result["status"] == "ask"
        assert '"cat" command is not allowlisted' in result["reason"]

    def test_empty_segment_blocked_subshell_denied(self) -> None:
        """bug #2: blocked-path scan denies before the empty-segment return.

        Post bug #6 fix this now fires via the real cat segment
        blocked-path check rather than the empty-segment subshell scan -
        verdict and reason are unchanged.
        """
        result = evaluate_bash_command(
            "[[ $(cat /etc/passwd) == x ]]",
            {"*": "ask", "blocked_paths_regex": [r"/etc"]},
        )
        assert result["status"] == "deny"


class TestBlockedReasonDedup:
    """Blocked-path reason messages must not repeat (bug #8).

    The same blocked path was reported once per pass: the segment loop and the
    subshell-contents pass each appended the identical message, so the final
    reason repeated it once per nesting level. These tests assert it appears
    exactly once.
    """

    BLOCKED: ClassVar[list[str]] = [r"\/etc"]
    MESSAGE = "Blocked by bash permissions"

    def test_blocked_reason_dedup_subshell(self) -> None:
        """`echo $(cat /etc/passwd)` reports the blocked path once (was ×2)."""
        result = evaluate_bash_command(
            "echo $(cat /etc/passwd)",
            make_config(blocked=self.BLOCKED),
        )
        assert result["status"] == "deny"
        assert result["reason"].count(self.MESSAGE) == 1
        assert r"\/etc" in result["reason"]

    def test_blocked_reason_dedup_variable_assignment(self) -> None:
        """`export FOO=$(cat /etc/passwd)` reports the blocked path once (was ×3)."""
        result = evaluate_bash_command(
            "export FOO=$(cat /etc/passwd)",
            make_config(blocked=self.BLOCKED),
        )
        assert result["status"] == "deny"
        assert result["reason"].count(self.MESSAGE) == 1

    def test_blocked_reason_dedup_deeply_nested(self) -> None:
        """Deeply nested subshells do not multiply the blocked-path reason."""
        result = evaluate_bash_command(
            "echo $(echo $(echo $(cat /etc/passwd)))",
            make_config(blocked=self.BLOCKED),
        )
        assert result["status"] == "deny"
        assert result["reason"].count(self.MESSAGE) == 1

    def test_blocked_reason_dedup_same_path_multiple_flags(self) -> None:
        """Distinct blocked paths are each reported once (no cross re-dup)."""
        result = evaluate_bash_command(
            "echo $(cat /etc/passwd) $(cat /etc/shadow)",
            make_config(blocked=[r"\/etc/passwd", r"\/etc/shadow"]),
        )
        assert result["status"] == "deny"
        assert result["reason"].count(self.MESSAGE) == 2


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

    def test_multiple_ask_reasons_all_reported(self) -> None:
        """All ask-level rule reasons are reported, not just the first."""
        result = evaluate_bash_command(
            "ls > /tmp/out &",
            make_config(allowed=["^ls"], output="ask", background="ask"),
        )
        assert result["status"] == "ask"
        assert "output redirection requires approval" in result["reason"]
        assert "background execution requires approval: ls" in result["reason"]

    def test_multiple_ask_reasons_three_ways(self) -> None:
        """Ask reasons for output, input, and background redirection all appear."""
        result = evaluate_bash_command(
            "cat < /tmp/in > /tmp/out &",
            make_config(allowed=["^cat"], output="ask", input_redir="ask", background="ask"),
        )
        assert result["status"] == "ask"
        assert "output redirection requires approval" in result["reason"]
        assert "input redirection requires approval" in result["reason"]
        assert "background execution requires approval: cat" in result["reason"]

    def test_allow_shows_pattern_and_redirection_reasons(self) -> None:
        """Auto-approve includes both pattern-match and redirection-allowed reasons."""
        result = evaluate_bash_command(
            "ls > /tmp/out",
            {"*": "allow", "allowed_cmds_regex": ["^ls"], "output_redirection": "allow"},
        )
        assert result["status"] == "allow"
        assert "command matches allowed pattern" in result["reason"]
        assert "output redirection allowed to /tmp/out" in result["reason"]

    def test_allow_shows_pattern_and_background_reasons(self) -> None:
        """Auto-approve includes both pattern-match and background-allowed reasons."""
        result = evaluate_bash_command(
            "ls &",
            {"*": "allow", "allowed_cmds_regex": ["^ls"], "background_execution": "allow"},
        )
        assert result["status"] == "allow"
        assert "command matches allowed pattern" in result["reason"]
        assert "background execution allowed: ls" in result["reason"]

    def test_allow_omits_sentinel_when_no_redirection(self) -> None:
        """No 'no output redirection' clutter when there is nothing to check."""
        result = evaluate_bash_command(
            "ls",
            {"*": "allow", "allowed_cmds_regex": ["^ls"], "output_redirection": "allow"},
        )
        assert result["status"] == "allow"
        assert "command matches allowed pattern" in result["reason"]
        assert "no output redirection" not in result["reason"]

    def test_allow_shows_all_four_reasons(self) -> None:
        """All applicable allow reasons appear alongside the pattern-match reason."""
        result = evaluate_bash_command(
            "cat < /tmp/in > /tmp/out &",
            {
                "*": "allow",
                "allowed_cmds_regex": ["^cat"],
                "output_redirection": "allow",
                "input_redirection": "allow",
                "background_execution": "allow",
            },
        )
        assert result["status"] == "allow"
        for fragment in (
            "command matches allowed pattern",
            "output redirection allowed to /tmp/out",
            "input redirection allowed from /tmp/in",
            "background execution allowed: cat",
        ):
            assert fragment in result["reason"]


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


class TestInheritance:
    """Options inherit their immediate wildcard parent, falling back to '*' (default ask)."""

    def test_subshell_inherits_wildcard_deny(self) -> None:
        """Deny '*' denies a command substitution."""
        result = evaluate_bash_command("echo $(cat x)", make_config(wildcard="deny"))
        assert result["status"] == "deny"

    def test_subshell_inherits_wildcard_allow(self) -> None:
        """Allow '*' lets a command substitution run."""
        result = evaluate_bash_command("echo $(cat x)", make_config(wildcard="allow"))
        assert result["status"] == "allow"

    def test_variable_assignment_inherits_wildcard_deny(self) -> None:
        """Deny '*' denies a standalone variable assignment."""
        result = evaluate_bash_command("FOO=bar", make_config(wildcard="deny"))
        assert result["status"] == "deny"

    def test_variable_assignment_inherits_wildcard_allow(self) -> None:
        """Allow '*' allows a standalone variable assignment."""
        result = evaluate_bash_command("FOO=bar", make_config(wildcard="allow"))
        assert result["status"] == "allow"

    def test_output_redirection_inherits_wildcard_deny(self) -> None:
        """Deny '*' denies output redirection."""
        result = evaluate_bash_command("echo hi > /tmp/out", make_config(wildcard="deny"))
        assert result["status"] == "deny"

    def test_input_redirection_inherits_wildcard_deny(self) -> None:
        """Deny '*' denies input redirection."""
        result = evaluate_bash_command("cat < /tmp/in", make_config(wildcard="deny"))
        assert result["status"] == "deny"

    def test_background_execution_inherits_wildcard_deny(self) -> None:
        """Deny '*' denies background execution."""
        result = evaluate_bash_command("sleep 1 &", make_config(wildcard="deny"))
        assert result["status"] == "deny"

    def test_output_redirection_kind_inherits_wildcard(self) -> None:
        """A kind omitted from output_redirection inherits the wildcard."""
        result = evaluate_bash_command(
            "echo hi > /dev/null",
            {"*": "deny", "output_redirection": {"stderr_to_dev_null": "ask"}},
        )
        assert result["status"] == "deny"

    def test_explicit_option_overrides_wildcard(self) -> None:
        """An explicit option beats an inherited allow."""
        result = evaluate_bash_command(
            "echo $(cat x)",
            make_config(wildcard="allow", subshell="deny"),
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
        """Subshell reason matches TS format when commands are otherwise approved."""
        result = evaluate_bash_command(
            "cat $(ls)",
            make_config(allowed=[r"^cat(\s+.*)?$", r"^ls(\s+.*)?$"]),
        )
        assert result["reason"] == "subshell or command substitution requires approval"

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
        """Process substitution <(...) also checked against blocked paths.

        The previous literal `<( /etc/passwd )` form relied on the path appearing
        verbatim in the AST; the new form `<(cat /etc/passwd)` tests the same
        traversal with realistic bash (a command whose argument is the blocked path).
        """
        result = evaluate_bash_command(
            "cat <(cat /etc/passwd)",
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

    def test_subshell_policy_allow_does_not_blanket_approve(self) -> None:
        """subshell=allow permits the subshell construct, not unapproved commands."""
        result = evaluate_bash_command(
            "ls $(ls)",
            make_config(subshell="allow"),
        )
        assert result["status"] == "ask"

    def test_subshell_policy_allow_with_approved_commands(self) -> None:
        """subshell=allow approves the substitution when the commands are approved."""
        result = evaluate_bash_command(
            "ls $(ls)",
            make_config(subshell="allow", wildcard="allow"),
        )
        assert result["status"] == "allow"

    def test_subshell_matched_pattern_listed_once(self) -> None:
        """A command matched by both the segment loop and the AST walk counts once.

        Regression: `echo $(ls -l)` previously listed `^ls` twice - once from
        the flattened segment and once from the AST traversal of the same call.
        """
        result = evaluate_bash_command(
            "echo $(ls -l)",
            make_config(allowed=[r"^echo(\s+.*)?$", r"^ls(\s+.*)?$"], subshell="allow"),
        )
        assert result["status"] == "allow"
        assert result["reason"].count(r"^echo(\s+.*)?$") == 1
        assert result["reason"].count(r"^ls(\s+.*)?$") == 1

    def test_subshell_matched_pattern_counted_per_occurrence(self) -> None:
        """Two distinct `ls` commands list `^ls` twice (no de-duplication)."""
        result = evaluate_bash_command(
            "ls --color $(ls -a)",
            make_config(allowed=[r"^ls(\s+.*)?$"], subshell="allow"),
        )
        assert result["status"] == "allow"
        assert result["reason"].count(r"^ls(\s+.*)?$") == 2

    def test_subshell_matched_pattern_kept_for_assignment_value(self) -> None:
        """Commands inside assignment values keep their matched pattern in the label."""
        result = evaluate_bash_command(
            "echo $(ls); x=$(cat /tmp/ed)",
            make_config(
                allowed=[r"^echo(\s+.*)?$", r"^ls(\s+.*)?$", r"^cat(\s+.*)?$"],
                subshell="allow",
                variable_assignment="allow",
            ),
        )
        assert result["status"] == "allow"
        assert result["reason"].count(r"^echo(\s+.*)?$") == 1
        assert result["reason"].count(r"^ls(\s+.*)?$") == 1
        assert result["reason"].count(r"^cat(\s+.*)?$") == 1

    def test_export_matched_pattern_listed_once(self) -> None:
        """`export FOO` matches the export pattern and lists it once."""
        result = evaluate_bash_command(
            "export FOO",
            make_config(allowed=[r"^export(\s+.*)?$"]),
        )
        assert result["status"] == "allow"
        assert result["reason"].count(r"^export(\s+.*)?$") == 1

    def test_declclause_substitution_value_inherits_wildcard_allow(self) -> None:
        """Nested substitution in a decl variant value inherits wildcard allow."""
        result = evaluate_bash_command(
            "declare FOO=$(cat x)",
            make_config(wildcard="allow"),
        )
        assert result["status"] == "allow"

    def test_declclause_substitution_value_not_silently_allowed(self) -> None:
        """Nested substitution in a decl variant value asks when subshell=ask."""
        config = make_config(wildcard="allow")
        config["subshell"] = "ask"
        result = evaluate_bash_command("declare FOO=$(cat x)", config)
        assert result["status"] == "ask"

    def test_declclause_substitution_blocked_path_denied(self) -> None:
        """Blocked path inside a decl variant value denies even with wildcard allow."""
        result = evaluate_bash_command(
            "local PATH=$(cat /etc/passwd)",
            make_config(blocked=[r"^/etc/passwd$"], wildcard="allow", subshell="allow"),
        )
        assert result["status"] == "deny"

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


class TestParamExpansionSubstitutions:
    """Substitutions inside parameter expansions are enforced (bugs 1 & 3).

    Previously `${var/pat/$(cmd)}` (and `${var:-$(cmd)}`, `${var%$(cmd)}`,
    `${var:offset:$(cmd)}`) were invisible to the subshell, allowed-pattern,
    and blocked-path passes, so the inner command was auto-approved.
    """

    def test_repl_replacement_subshell_denied(self) -> None:
        """Bug 1: substitution in replacement part abides by subshell=deny."""
        result = evaluate_bash_command(
            "echo ${x//a/$(rm -rf x)}",
            make_config(allowed=[r"^echo(\s+.*)?$"], subshell="deny"),
        )
        assert result["status"] == "deny"

    def test_repl_pattern_subshell_denied(self) -> None:
        """Bug 1: substitution in the pattern part abides by subshell=deny."""
        result = evaluate_bash_command(
            "echo ${x//$(recon_cmd)/y}",
            make_config(allowed=[r"^echo(\s+.*)?$"], subshell="deny"),
        )
        assert result["status"] == "deny"

    def test_repl_replacement_blocked_path_denied(self) -> None:
        """Bug 1: blocked path read via the replacement part is denied."""
        result = evaluate_bash_command(
            "echo ${x//a/$(cat /etc/passwd)}",
            make_config(blocked=["^/etc/passwd$"], wildcard="ask"),
        )
        assert result["status"] == "deny"

    def test_repl_replacement_inner_command_not_allow_listed(self) -> None:
        """Bug 1: inner command can't ride the outer echo allow pattern."""
        result = evaluate_bash_command(
            "echo ${x//a/$(rm -rf x)}",
            make_config(allowed=[r"^echo(\s+.*)?$"]),
        )
        assert result["status"] == "ask"

    def test_exp_default_subshell_denied(self) -> None:
        """Bug 3: substitution in ${var:-...} abides by subshell=deny."""
        result = evaluate_bash_command(
            'echo "${y:-$(rm -rf x)}"',
            make_config(allowed=[r"^echo(\s+.*)?$"], subshell="deny"),
        )
        assert result["status"] == "deny"

    def test_exp_trim_subshell_denied(self) -> None:
        """Bug 3: substitution in ${var%...} abides by subshell=deny."""
        result = evaluate_bash_command(
            'echo "${z%$(rm -rf x)}"',
            make_config(allowed=[r"^echo(\s+.*)?$"], subshell="deny"),
        )
        assert result["status"] == "deny"

    def test_exp_default_blocked_path_denied(self) -> None:
        """Bug 3: blocked path in ${var:-...} is denied."""
        result = evaluate_bash_command(
            'echo "${w:-$(cat /etc/passwd)}"',
            make_config(blocked=["^/etc/passwd$"], wildcard="ask"),
        )
        assert result["status"] == "deny"

    def test_slice_subshell_denied(self) -> None:
        """Bug 3: substitution in ${var:offset} abides by subshell=deny."""
        result = evaluate_bash_command(
            "echo ${x:0:$(rm -rf x)}",
            make_config(allowed=[r"^echo(\s+.*)?$"], subshell="deny"),
        )
        assert result["status"] == "deny"


class TestOpaqueSubstitutionPatternGuard:
    """Opaque `$(...)` args must not slip past restrictive allow patterns.

    Regression: `find . $(echo -delete)` was auto-approved because the outer
    command was matched as `find . $(...)` (the negative lookahead never saw
    `-delete`), while the inner `echo -delete` was individually approved -
    even though the command line that actually runs is `find . -delete`.
    """

    def test_lookahead_pattern_bypass_not_allowed(self) -> None:
        cfg = make_config(allowed=[r"^find(?!.*\s-(exec|delete|ok)(\s|;|$)).*$"], subshell="allow")
        assert evaluate_bash_command("find . -delete", cfg)["status"] == "ask"
        assert evaluate_bash_command("find . $(echo -delete)", cfg)["status"] == "ask"
        assert evaluate_bash_command(r"find . $(echo -exec rm {} \;)", cfg)["status"] == "ask"

    def test_git_output_guard_bypass_not_allowed(self) -> None:
        cfg = make_config(
            allowed=[r"^git\s+(?!.*--output\b)(-C\s+[\w./\\\\-]+\s+)?(log|diff|show)(\s+.*)?$"], subshell="allow"
        )
        assert evaluate_bash_command("git diff --output=/tmp/x", cfg)["status"] == "ask"
        assert evaluate_bash_command("git diff $(echo --output=/tmp/x)", cfg)["status"] == "ask"
        # Legit git invocations without a substitution still auto-approve.
        assert evaluate_bash_command("git diff --cached", cfg)["status"] == "allow"
        assert evaluate_bash_command("git status", cfg)["status"] == "ask"

    def test_bare_name_anchor_not_bypassed(self) -> None:
        cfg = make_config(allowed=["^true$"], subshell="allow")
        assert evaluate_bash_command("true", cfg)["status"] == "allow"
        assert evaluate_bash_command("true --flag", cfg)["status"] == "ask"
        assert evaluate_bash_command("true $(echo --flag)", cfg)["status"] == "ask"

    def test_free_tail_pattern_still_allows_substitution(self) -> None:
        """Patterns that accept arbitrary arguments are unaffected."""
        cfg = make_config(allowed=[r"^echo(\s+.*)?$", r"^ls(\s+.*)?$"], subshell="allow")
        assert evaluate_bash_command("echo $(echo hi)", cfg)["status"] == "allow"
        assert evaluate_bash_command("echo $(echo $(echo hi))", cfg)["status"] == "allow"
        assert evaluate_bash_command("ls $(echo -la)", cfg)["status"] == "allow"


class TestEdgeCases:
    """Tests for edge cases."""

    def test_empty_command(self) -> None:
        """Empty command cannot be parsed → raises, routed via error policy."""
        with pytest.raises(LovelyDevinPermissionsError):
            evaluate_bash_command("", make_config())

    def test_whitespace_only(self) -> None:
        """Whitespace-only command cannot be parsed → raises."""
        with pytest.raises(LovelyDevinPermissionsError):
            evaluate_bash_command("   ", make_config())

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
        """Quoted arguments match after quote stripping (full command match)."""
        result = evaluate_bash_command(
            "echo 'hello world'",
            make_config(allowed=["^echo\\s+hello\\s+world$"]),
        )
        assert result["status"] == "allow"

    def test_single_quoted_flag_bypasses_negative_lookahead(self) -> None:
        """find '-exec' must NOT bypass the ^find(...-(exec|delete|ok)...) pattern."""
        result = evaluate_bash_command(
            "find . '-exec' rm {} +",
            make_config(allowed=["^find(?!.*\\s-(exec|delete|ok)(\\s|;|$)).*$"]),
        )
        # The negative lookahead should block this (it would be unquoted -exec)
        assert result["status"] != "allow"

    def test_double_quoted_flag_bypasses_negative_lookahead(self) -> None:
        """sort "-o" must NOT bypass the ^sort(?!\\s+(-o|--output)\\b).*$ pattern."""
        result = evaluate_bash_command(
            'sort "-o" /tmp/out /tmp/in',
            make_config(allowed=["^sort(?!\\s+(-o|--output)\\b).*$"]),
        )
        assert result["status"] != "allow"

    def test_single_quoted_fd_flag_bypasses_negative_lookahead(self) -> None:
        """fd '-X' must NOT bypass the ^fd(?!.*\\s+(-x|-X)).*$ pattern."""
        result = evaluate_bash_command(
            "fd '-X' rm {}",
            make_config(allowed=["^fd(?!.*\\s+(-x|-X)).*$"]),
        )
        assert result["status"] != "allow"

    def test_unquoted_blocked_flags_still_caught(self) -> None:
        """Unquoted blocked flags must still be caught by negative lookaheads."""
        result = evaluate_bash_command(
            "find . -exec rm {} +",
            make_config(allowed=["^find(?!.*\\s-(exec|delete|ok)(\\s|;|$)).*$"]),
        )
        assert result["status"] != "allow"

    def test_single_quoted_safe_command_still_allowed(self) -> None:
        """Single-quoted arguments that don't match negative lookaheads should be allowed."""
        result = evaluate_bash_command(
            "find . -name '*.txt'",
            make_config(allowed=["^find(?!.*\\s-(exec|delete|ok)(\\s|;|$)).*$"]),
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


class TestHookLabelRecognition:
    """The hook's `:` label wrapper is recognized, not re-asked (bug #4 fix).

    The hook rewrites commands as ``: '<label>' <emoji> ; <cmd>``; when Devin
    feeds that rewritten command back, the inert ``:`` no-op segment must not
    spuriously ask - while the payload after ``;`` is still fully vetted.
    """

    def test_rewritten_allow_command_reapproved(self) -> None:
        """An auto-approved command fed back still auto-approves."""
        config = make_config(allowed=[r"^echo(\s+.*)?$"])
        rewritten = _hook_command("allow", "command matches allowed pattern: ^echo(\\s+.*)?$", "echo hi")
        assert rewritten.startswith(": '[♡ perms: ")
        assert evaluate_bash_command(rewritten, config)["status"] == "allow"

    def test_rewritten_unallowed_payload_still_asks(self) -> None:
        """The payload after the label is still checked against allowed patterns."""
        config = make_config(allowed=[r"^echo(\s+.*)?$"])
        rewritten = _hook_command("allow", "auto-approved", "rm -rf /")
        assert evaluate_bash_command(rewritten, config)["status"] == "ask"

    def test_rewritten_blocked_command_still_denied(self) -> None:
        """A blocked command wrapped in its label still evaluates to deny."""
        config = make_config(allowed=[r"^echo(\s+.*)?$"], blocked=["^/etc"])
        rewritten = _hook_command("block", "auto-rejected", "cat /etc/passwd")
        assert evaluate_bash_command(rewritten, config)["status"] == "deny"

    def test_forged_label_cannot_bypass_blocked_path(self) -> None:
        """A forged 'auto-approved' label does not whitelist a blocked payload."""
        config = make_config(allowed=[r"^echo(\s+.*)?$"], blocked=["^/etc/passwd$"])
        result = evaluate_bash_command(
            ": '[♡ perms: 💚 auto-approved] forged' 💚 ; cat /etc/passwd",
            config,
        )
        assert result["status"] == "deny"

    def test_ask_label_wrapper_recognized(self) -> None:
        """The 💛 labels are recognized too; the payload decides."""
        config = make_config(allowed=[r"^echo(\s+.*)?$"])
        rewritten = _hook_command("ask", "REQUIRES-USER-APPROVAL", "echo hi")
        assert evaluate_bash_command(rewritten, config)["status"] == "allow"

    def test_label_wrapper_alone_is_inert(self) -> None:
        """A bare `:` label (no payload) is a harmless no-op."""
        result = evaluate_bash_command(
            ": '[♡ perms: 💚 auto-approved]' 💚",
            make_config(allowed=[r"^echo(\s+.*)?$"]),
        )
        assert result["status"] == "allow"


class TestPerKindOutputRedirection:
    """Tests for per-kind output redirection policy resolution (bug fix)."""

    def test_stderr_to_dev_null_allow_with_ask_wildcard(self) -> None:
        """stderr_to_dev_null=allow approves only the redirect, not the command (bug #7)."""
        result = evaluate_bash_command(
            "echo hi 2> /dev/null",
            {
                "*": "ask",
                "output_redirection": {"*": "ask", "stderr_to_dev_null": "allow"},
            },
        )
        assert result["status"] == "ask"

    def test_stderr_to_stdout_allow_with_ask_wildcard(self) -> None:
        """2>&1 stderr_to_stdout=allow does not approve an unallow-listed command."""
        result = evaluate_bash_command(
            "echo hi 2>&1",
            {
                "*": "ask",
                "output_redirection": {"*": "ask", "stderr_to_stdout": "allow"},
            },
        )
        assert result["status"] == "ask"

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
        """> /dev/null with stdout_to_dev_null=allow still asks an unapproved command (bug #7)."""
        result = evaluate_bash_command(
            "echo hi > /dev/null",
            {
                "*": "ask",
                "output_redirection": {"*": "ask", "stdout_to_dev_null": "allow"},
            },
        )
        assert result["status"] == "ask"

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

    def test_clobber_redirection_ask(self) -> None:
        """>| /tmp/out triggers output redirection ask (same as >)."""
        result = evaluate_bash_command(
            "echo hi >| /tmp/out.txt",
            {"*": "ask", "output_redirection": {"*": "ask"}},
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
        """Input redirection object policy allow does not approve the command (bug #7)."""
        result = evaluate_bash_command(
            "cat < /tmp/in.txt",
            {
                "*": "ask",
                "input_redirection": {"*": "allow"},
            },
        )
        assert result["status"] == "ask"


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
            assert "arguments" in seg
            assert "allowed" in seg

    def test_heredoc_input_redirection_ask(self) -> None:
        """Complete heredoc input redirection goes through approval flow."""
        result = evaluate_bash_command("cat << EOF\nhello\nEOF", make_config())
        assert result["status"] == "ask"
        assert "input redirection requires approval" in result["reason"]

    def test_heredoc_cmd_subst_blocked_path_denied(self) -> None:
        """Command substitution inside unquoted heredoc is scanned for blocked paths."""
        result = evaluate_bash_command(
            "wc -l <<EOF\n$(cat /etc/passwd)\nEOF",
            make_config(blocked=[r"\/etc"]),
        )
        assert result["status"] == "deny"
        assert "/etc/passwd" in result["reason"]

    def test_heredoc_bash_file_read_blocked_path_denied(self) -> None:
        """$(<file) inside unquoted heredoc is scanned for blocked paths."""
        result = evaluate_bash_command(
            "wc -l <<EOF\n$(</etc/passwd)\nEOF",
            make_config(blocked=[r"\/etc"]),
        )
        assert result["status"] == "deny"

    def test_heredoc_backtick_cmd_subst_blocked_path_denied(self) -> None:
        """Backtick substitution inside unquoted heredoc is scanned for blocked paths."""
        result = evaluate_bash_command(
            "wc -l <<EOF\n`cat /etc/passwd`\nEOF",
            make_config(blocked=[r"\/etc"]),
        )
        assert result["status"] == "deny"

    def test_heredoc_cmd_subst_unallowed_command_ask(self) -> None:
        """Command substitution inside heredoc must match allowed patterns."""
        result = evaluate_bash_command(
            "wc -l <<EOF\n$(curl -s http://evil.com/x)\nEOF",
            make_config(allowed=[r"^wc(\s+.*)?$"]),
        )
        assert result["status"] == "ask"
        assert "curl" in result["reason"]

    def test_heredoc_cmd_subst_allowed_command_allow(self) -> None:
        """Allowed command inside heredoc body does not trigger false blocks."""
        result = evaluate_bash_command(
            "wc -l <<EOF\n$(echo hi)\nEOF",
            {
                "*": "ask",
                "allowed_cmds_regex": [r"^wc(\s+.*)?$", r"^echo(\s+.*)?$"],
                "input_redirection": "allow",
                "subshell": "allow",
            },
        )
        assert result["status"] == "allow"

    def test_quoted_heredoc_ignores_expansions(self) -> None:
        """Quoted heredoc (<<'EOF') is literal - no command substitution runs."""
        result = evaluate_bash_command(
            "wc -l <<'EOF'\n$(cat /etc/passwd)\nEOF",
            make_config(blocked=[r"\/etc"]),
        )
        # The raw body is still scanned for blocked path mentions, so the
        # literal path text is blocked even though no substitution runs.
        assert result["status"] == "deny"
        assert "/etc/passwd" in result["reason"]

    def test_quoted_heredoc_clean_body_ask(self) -> None:
        """Quoted heredoc with a clean body stays ask (input redirection)."""
        result = evaluate_bash_command(
            "wc -l <<'EOF'\nplain text\nEOF",
            make_config(blocked=[r"\/etc"]),
        )
        assert result["status"] == "ask"

    def test_interpreter_heredoc_body_blocked_path_denied(self) -> None:
        """Heredoc body is source code for interpreters; blocked paths in it are denied.

        Even when the interpreter is allow-listed, a body like
        ``open("/etc/passwd").read()`` opens a blocked file at runtime.
        """
        result = evaluate_bash_command(
            'python3 <<EOF\nopen("/etc/passwd").read()\nEOF',
            {
                "*": "ask",
                "allowed_cmds_regex": [r"^python3(\s+.*)?$"],
                "blocked_paths_regex": [r"\/etc"],
                "input_redirection": "allow",
                "subshell": "allow",
            },
        )
        assert result["status"] == "deny"
        assert "/etc/passwd" in result["reason"]

    def test_interpreter_heredoc_body_clean_allow(self) -> None:
        """Allow-listed interpreter heredoc with a clean body is approved."""
        result = evaluate_bash_command(
            'python3 <<EOF\nprint("hi")\nEOF',
            {
                "*": "ask",
                "allowed_cmds_regex": [r"^python3(\s+.*)?$"],
                "blocked_paths_regex": [r"\/etc"],
                "input_redirection": "allow",
                "subshell": "allow",
            },
        )
        assert result["status"] == "allow"

    def test_heredoc_body_line_env_path_denied(self) -> None:
        """End-anchored blocked pattern matches a path on its own body line."""
        result = evaluate_bash_command(
            "wc -l <<EOF\n/home/alx/.env\nEOF",
            {
                "*": "ask",
                "allowed_cmds_regex": [r"^wc(\s+.*)?$"],
                "blocked_paths_regex": [r"\.env$"],
                "input_redirection": "allow",
                "subshell": "allow",
            },
        )
        assert result["status"] == "deny"

    def test_multiline_heredoc_body_blocked_line_denied(self) -> None:
        """Blocked path in the middle of a multi-line heredoc body is denied."""
        result = evaluate_bash_command(
            "wc -l <<EOF\nfirst line\n/etc/passwd\nlast line\nEOF",
            make_config(allowed=[r"^wc(\s+.*)?$"], blocked=[r"\/etc"]),
        )
        assert result["status"] == "deny"
        assert "/etc/passwd" in result["reason"]

    def test_multiline_heredoc_body_clean_allow(self) -> None:
        """Clean multi-line heredoc body does not trigger the blocked scan."""
        result = evaluate_bash_command(
            "wc -l <<EOF\nfirst line\nsecond line\nEOF",
            {
                "*": "ask",
                "allowed_cmds_regex": [r"^wc(\s+.*)?$"],
                "blocked_paths_regex": [r"\/etc"],
                "input_redirection": "allow",
                "subshell": "allow",
            },
        )
        assert result["status"] == "allow"

    def test_here_string_input_redirection_ask(self) -> None:
        """Here-string (<<<) input redirection goes through approval flow."""
        result = evaluate_bash_command(
            "echo hello <<< 'world'",
            make_config(input_redir="ask"),
        )
        assert result["status"] == "ask"
        assert "input redirection requires approval" in result["reason"]

    def test_here_string_not_bypassed_by_allowed_pattern(self) -> None:
        """Here-string (<<<) still requires approval even with a matching allowed pattern."""
        result = evaluate_bash_command(
            "echo hello <<< 'world'",
            {
                "*": "ask",
                "input_redirection": "ask",
                "allowed_cmds_regex": [r"^echo(\s+.*)?$"],
            },
        )
        assert result["status"] == "ask"
        assert "input redirection requires approval" in result["reason"]

    def test_dup_input_redirection_ask(self) -> None:
        """Input fd duplication (cat <&2) goes through approval flow."""
        result = evaluate_bash_command(
            "cat <&2",
            {"*": "ask", "input_redirection": "ask"},
        )
        assert result["status"] == "ask"
        assert "input redirection requires approval" in result["reason"]

    def test_dup_input_redirection_allowed_when_policy_allow(self) -> None:
        """Input fd duplication allowed only for the redirect, not the command (bug #7)."""
        result = evaluate_bash_command(
            "cat <&2",
            {"*": "ask", "input_redirection": "allow"},
        )
        assert result["status"] == "ask"

    def test_dup_input_redirection_deny_when_policy_deny(self) -> None:
        """Input fd duplication denied when input_redirection=deny."""
        result = evaluate_bash_command(
            "cat <&2",
            {"*": "ask", "input_redirection": "deny"},
        )
        assert result["status"] == "deny"
        assert "input redirection denied from" in result["reason"]

    def test_incomplete_heredoc_raises(self) -> None:
        """Incomplete heredoc (unclosed) cannot be parsed → raises (bug #2 fix)."""
        with pytest.raises(LovelyDevinPermissionsError):
            evaluate_bash_command("cat << EOF", make_config())

    def test_input_redirect_to_blocked_path_denied(self) -> None:
        """Input redirect to blocked path is denied."""
        result = evaluate_bash_command(
            "cat < /etc/passwd",
            make_config(blocked=["^/etc/"]),
        )
        assert result["status"] == "deny"

    def test_input_redirect_allowed_when_policy_allow(self) -> None:
        """Input redirection=allow approves only the redirect, not the command (bug #7)."""
        result = evaluate_bash_command(
            "cat < /tmp/in.txt",
            {"*": "ask", "input_redirection": "allow"},
        )
        assert result["status"] == "ask"

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

    def test_output_redirect_to_blocked_path_denied(self) -> None:
        """Output redirection to a blocked path is denied (issue #1)."""
        result = evaluate_bash_command(
            "echo hi > /etc/passwd",
            make_config(blocked=["^/etc/"]),
        )
        assert result["status"] == "deny"
        assert "blocked path pattern" in result["reason"]

    def test_output_redirect_append_to_blocked_path_denied(self) -> None:
        """Append output redirection to a blocked path is denied."""
        result = evaluate_bash_command(
            "echo hi >> /etc/shells",
            make_config(blocked=["/etc/shells"]),
        )
        assert result["status"] == "deny"

    def test_output_redirect_to_blocked_path_denied_even_when_policy_ask(self) -> None:
        """Blocked output targets deny regardless of the redirection policy."""
        result = evaluate_bash_command(
            "echo hi > /etc/passwd",
            make_config(blocked=["^/etc/"], output="ask"),
        )
        assert result["status"] == "deny"

    def test_output_redirect_to_unblocked_path_allowed(self) -> None:
        """Output redirection to a non-blocked path is not denied."""
        result = evaluate_bash_command(
            "echo hi > /tmp/out.txt",
            {"*": "allow", "output_redirection": "allow", "blocked_paths_regex": ["^/etc/"]},
        )
        assert result["status"] == "allow"

    def test_output_redirect_no_target_not_blocked(self) -> None:
        """FD-clobbering redirects without a target path are not affected."""
        result = evaluate_bash_command(
            "echo hi 2>&1",
            {"*": "allow", "output_redirection": "allow", "blocked_paths_regex": ["^/etc/"]},
        )
        assert result["status"] == "allow"

    def test_block_output_redirection_denied(self) -> None:
        """Block-level output redirection to a blocked path denies (issue #1)."""
        result = evaluate_bash_command(
            "{ echo hi; } > /etc/passwd",
            make_config(blocked=["^/etc/"]),
        )
        assert result["status"] == "deny"

    def test_subshell_output_redirection_denied(self) -> None:
        """Subshell output redirection to a blocked path denies."""
        result = evaluate_bash_command(
            "( echo hi ) > /etc/passwd",
            make_config(blocked=["^/etc/"]),
        )
        assert result["status"] == "deny"

    def test_pipe_output_redirection_to_blocked_path_denied(self) -> None:
        """Pipe with a trailing output redirection to a blocked path denies."""
        result = evaluate_bash_command(
            "echo hi | cat > /etc/passwd",
            make_config(blocked=["^/etc/"]),
        )
        assert result["status"] == "deny"

    def test_empty_segments_with_allowed_patterns_asks(self) -> None:
        """Unmatched export command with allowed patterns → ask (bug 1 fix)."""
        result = evaluate_bash_command("export BOGUS=true bogus", make_config(allowed=["^ls"]))
        assert result["status"] == "ask"

    def test_empty_segments_wildcard_allow(self) -> None:
        """Unmatched export command with wildcard=allow → allow."""
        result = evaluate_bash_command("export BOGUS=true bogus", make_config(allowed=["^ls"], wildcard="allow"))
        assert result["status"] == "allow"

    def test_empty_segments_wildcard_deny(self) -> None:
        """Unmatched export command with wildcard=deny → deny."""
        result = evaluate_bash_command("export BOGUS=true bogus", make_config(allowed=["^ls"], wildcard="deny"))
        assert result["status"] == "deny"

    def test_export_segment_extracted_no_patterns(self) -> None:
        """Export produces a segment; no patterns → ask."""
        result = evaluate_bash_command("export BOGUS=true bogus", make_config())
        assert result["status"] == "ask"

    def test_export_segment_no_patterns_allows(self) -> None:
        """Export segment matches wildcard allow → allow."""
        result = evaluate_bash_command("export BOGUS=true bogus", make_config(wildcard="allow"))
        assert result["status"] == "allow"

    def test_export_segment_reason_shows_command(self) -> None:
        """Unmatched export reason names the export command."""
        result = evaluate_bash_command("export BOGUS=true bogus", make_config(allowed=["^ls"]))
        assert "export" in result["reason"]

    def test_allow_reason_shows_patterns(self) -> None:
        """Matching command reason contains actual pattern(s)."""
        result = evaluate_bash_command("ls -la", make_config(allowed=["^ls", "^-la$"]))
        assert "pattern" in result["reason"] or "patterns" in result["reason"]

    def test_empty_segment_reason_not_generic(self) -> None:
        """Unmatched segment reason NOT generic 'matches allowed pattern'."""
        result = evaluate_bash_command("export BOGUS=true bogus", make_config(allowed=["^ls"]))
        assert "matches allowed pattern" not in result["reason"]

    def test_bogus_command_rejected(self) -> None:
        """'bogus' with allowed patterns → ask (existing behavior)."""
        result = evaluate_bash_command("bogus", make_config(allowed=["^ls"]))
        assert result["status"] == "ask"

    def test_export_bogus_rejected(self) -> None:
        """'export BOGUS=true bogus' → ask (regression for bug 1: unmatched segment wildcard policy)."""
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

    def test_testclause_extracted(self) -> None:
        """TestClause ([[ ]]) body commands are extracted."""
        result = evaluate_bash_command(
            "[[ -d /tmp && ls ]]",
            make_config(allowed=["^ls$"]),
        )
        assert result["status"] == "allow"
        commands = [s["command"] for s in result["segments"]]
        assert "ls" in commands  # 'ls' inside [[ ]] is extracted

    def test_time_clause_extracted(self) -> None:
        """time <cmd> extracts the command from inside."""
        result = evaluate_bash_command(
            "time sleep 1",
            make_config(allowed=["^sleep\\s+1$"]),
        )
        assert result["status"] == "allow"

    def test_coproc_extracted(self) -> None:
        """coprocess extracts command from stmt."""
        result = evaluate_bash_command(
            "coproc mycmd arg",
            {"*": "ask", "allowed_cmds_regex": ["^mycmd\\s+arg$"], "background_execution": "allow"},
        )
        assert result["status"] == "allow"


class TestTestClausePolicies:
    """[[ ]] with attached redirections must honor redirection policies."""

    def test_testclause_output_redirection_denied(self) -> None:
        result = evaluate_bash_command(
            "[[ -f file ]] > /tmp/out",
            make_config(wildcard="allow", output="deny"),
        )
        assert result["status"] == "deny"
        assert "output redirection denied" in result["reason"]

    def test_testclause_output_redirection_append_denied(self) -> None:
        result = evaluate_bash_command(
            "[[ -f file ]] >> /tmp/out",
            make_config(wildcard="allow", output="deny"),
        )
        assert result["status"] == "deny"

    def test_testclause_stderr_redirection_denied(self) -> None:
        result = evaluate_bash_command(
            "[[ -f file ]] 2> /tmp/out",
            make_config(wildcard="allow", output="deny"),
        )
        assert result["status"] == "deny"

    def test_testclause_output_redirection_asks(self) -> None:
        result = evaluate_bash_command(
            "[[ -f file ]] > /tmp/out",
            make_config(wildcard="allow", output="ask"),
        )
        assert result["status"] == "ask"
        assert "output redirection requires approval" in result["reason"]

    def test_testclause_input_redirection_denied(self) -> None:
        result = evaluate_bash_command(
            "[[ -f file ]] < /tmp/in",
            make_config(wildcard="allow", input_redir="deny"),
        )
        assert result["status"] == "deny"
        assert "input redirection denied" in result["reason"]

    def test_testclause_redirect_target_blocked(self) -> None:
        result = evaluate_bash_command(
            "[[ -f file ]] > /etc/passwd",
            make_config(blocked=["/etc"]),
        )
        assert result["status"] == "deny"
        assert "blocked path" in result["reason"]

    def test_testclause_redir_with_command_body_denied(self) -> None:
        result = evaluate_bash_command(
            "[[ -d /tmp && ls ]] > /tmp/out",
            make_config(wildcard="allow", output="deny"),
        )
        assert result["status"] == "deny"
        assert "output redirection denied" in result["reason"]

    def test_regex_rhs_no_false_phantom_command(self) -> None:
        """=~ regex RHS must not be reported as an unmatched command."""
        result = evaluate_bash_command(
            "[[ $var =~ pat ]] > /tmp/out",
            make_config(allowed=["^ls$"], wildcard="allow", output="deny"),
        )
        assert result["status"] == "deny"
        assert '"pat" command does not match' not in result["reason"]

    def test_regex_rhs_redirection_still_denied(self) -> None:
        result = evaluate_bash_command(
            "[[ $var =~ pat ]] > /tmp/out",
            make_config(wildcard="allow", output="deny"),
        )
        assert result["status"] == "deny"
        assert "output redirection denied" in result["reason"]


class TestVariableAssignment:
    """Tests for variable_assignment policy (standalone vs command-prefixed assignments)."""

    def test_standalone_variable_assignment_requires_approval(self) -> None:
        """Standalone variable assignment (FOO=bar) requires approval by default."""
        result = evaluate_bash_command("FOO=bar", make_config())
        assert result["status"] == "ask"
        assert "variable assignment" in result["reason"]

    def test_variable_assignment_before_command_requires_approval(self) -> None:
        """Variable assignment before command (FOO=bar ls) requires approval by default."""
        result = evaluate_bash_command("FOO=bar ls", make_config())
        assert result["status"] == "ask"
        assert "variable assignment" in result["reason"]

    def test_variable_assignment_before_command_and_command_both_need_approval(self) -> None:
        """FOO=bar ls with only ls allowed still asks due to variable_assignment."""
        result = evaluate_bash_command(
            "FOO=bar ls",
            make_config(allowed=["^ls$"]),
        )
        # variable_assignment is default "ask", so this should ask
        assert result["status"] == "ask"

    def test_variable_assignment_allow_policy(self) -> None:
        """variable_assignment=allow auto-approves standalone assignments."""
        result = evaluate_bash_command(
            "FOO=bar",
            make_config(variable_assignment="allow"),
        )
        assert result["status"] == "allow"

    def test_variable_assignment_deny_policy(self) -> None:
        """variable_assignment=deny auto-denies standalone assignments."""
        result = evaluate_bash_command(
            "FOO=bar",
            make_config(variable_assignment="deny"),
        )
        assert result["status"] == "deny"

    def test_variable_assignment_before_command_with_allow(self) -> None:
        """variable_assignment=allow auto-approves FOO=bar ls (both segments)."""
        result = evaluate_bash_command(
            "FOO=bar ls",
            make_config(allowed=["^ls$"], variable_assignment="allow"),
        )
        assert result["status"] == "allow"

    def test_variable_assignment_before_command_with_deny(self) -> None:
        """variable_assignment=deny denies FOO=bar ls even if ls is allowed."""
        result = evaluate_bash_command(
            "FOO=bar ls",
            make_config(allowed=["^ls$"], variable_assignment="deny"),
        )
        assert result["status"] == "deny"

    def test_variable_assignment_and_command_separate_segments(self) -> None:
        """FOO=bar ls produces two segments: variable assignment + command."""
        result = evaluate_bash_command(
            "FOO=bar ls",
            make_config(allowed=["^ls$"], variable_assignment="ask"),
        )
        # Should be ask due to variable_assignment, not due to ls being unknown
        assert result["status"] == "ask"

    def test_variable_assignment_in_separate_statement(self) -> None:
        """FOO=bar ; ls produces two separate statements."""
        result = evaluate_bash_command(
            "FOO=bar ; ls",
            make_config(allowed=["^ls$"], variable_assignment="allow"),
        )
        assert result["status"] == "allow"

    def test_export_still_treated_as_command(self) -> None:
        """export FOO=bar is a command (export), not a variable assignment."""
        result = evaluate_bash_command(
            "export FOO=bar",
            make_config(allowed=[r"^export(\s+.*)?$"], variable_assignment="deny"),
        )
        # export is allowed, so it should pass regardless of variable_assignment
        assert result["status"] == "allow"

    def test_local_still_treated_as_command(self) -> None:
        """local FOO=bar is a command (local), not a variable assignment."""
        result = evaluate_bash_command(
            "local FOO=bar",
            make_config(allowed=[r"^local(\s+.*)?$"], variable_assignment="deny"),
        )
        # local is allowed, so it should pass regardless of variable_assignment
        assert result["status"] == "allow"

    def test_multiple_variable_assignments_before_command(self) -> None:
        """Multiple variable assignments before command all get checked."""
        result = evaluate_bash_command(
            "FOO=bar BAZ=qux ls",
            make_config(allowed=["^ls$"], variable_assignment="allow"),
        )
        assert result["status"] == "allow"

    def test_variable_assignment_with_command_substitution_deny(self) -> None:
        """x=$(cmd) is a variable assignment - variable_assignment=deny should deny it."""
        result = evaluate_bash_command(
            "x=$(cat file.txt)",
            make_config(allowed=["^cat$"], subshell="allow", variable_assignment="deny"),
        )
        assert result["status"] == "deny"

    def test_variable_assignment_with_command_substitution_allow(self) -> None:
        """x=$(cmd) with variable_assignment=allow and subshell=allow auto-approves."""
        result = evaluate_bash_command(
            "x=$(cat file.txt)",
            make_config(allowed=[r"^cat(\s+.*)?$"], subshell="allow", variable_assignment="allow"),
        )
        assert result["status"] == "allow"

    def test_assignment_subshell_redir_blocked_path_denied(self) -> None:
        """A blocked-path write inside a `x=$(...)` substitution is denied.

        Regression: `x=$(echo hi > /etc/passwd)` was auto-approved because the
        standalone-assignment branch never flattened the inner command, so its
        redirection target was invisible to the blocked-path check.
        """
        result = evaluate_bash_command(
            "x=$(echo hi > /etc/passwd)",
            make_config(blocked=[r"^/etc/passwd$"], subshell="allow", variable_assignment="allow"),
        )
        assert result["status"] == "deny"
        assert "matches blocked path pattern" in result["reason"]

    def test_assignment_subshell_output_redir_policy_applies(self) -> None:
        """The output-redirection policy applies inside `x=$(...)` substitutions.

        Regression: `x=$(echo hi > /tmp/out)` was approved even with
        output_redirection=ask, because the inner segment (with its redirection)
        was never surfaced.
        """
        result = evaluate_bash_command(
            "x=$(echo hi > /tmp/out)",
            make_config(allowed=[r"^echo(\s+.*)?$"], output="ask", subshell="allow", variable_assignment="allow"),
        )
        assert result["status"] == "ask"
        assert "output redirection requires approval" in result["reason"]

    def test_assignment_subshell_input_redir_blocked_path_denied(self) -> None:
        """A blocked-path read inside `x=$(...)` substitutions is denied."""
        result = evaluate_bash_command(
            "x=$(cat </etc/passwd)",
            make_config(blocked=[r"^/etc/passwd$"], subshell="allow", variable_assignment="allow"),
        )
        assert result["status"] == "deny"

    def test_assignment_subshell_no_redir_still_allowed(self) -> None:
        """Plain `x=$(cmd)` assignments stay allowed with allow policies."""
        result = evaluate_bash_command(
            "x=$(echo hi)",
            make_config(allowed=[r"^echo(\s+.*)?$"], subshell="allow", variable_assignment="allow"),
        )
        assert result["status"] == "allow"


class TestBackgroundExecutionCompound:
    """background_execution policy covers coproc and compound & forms.

    Configs are built inline because make_config() only emits
    background_execution when it differs from the "allow" default.
    """

    def test_coproc_denied(self) -> None:
        result = evaluate_bash_command(
            "coproc myproc { echo hi; }",
            {"*": "allow", "allowed_cmds_regex": ["^echo"], "background_execution": "deny"},
        )
        assert result["status"] == "deny"
        assert "background execution denied" in result["reason"]

    def test_coproc_ask(self) -> None:
        result = evaluate_bash_command(
            "coproc myproc { echo hi; }",
            {"*": "allow", "allowed_cmds_regex": ["^echo"], "background_execution": "ask"},
        )
        assert result["status"] == "ask"

    def test_coproc_allowed(self) -> None:
        result = evaluate_bash_command(
            "coproc myproc { echo hi; }",
            {"*": "allow", "allowed_cmds_regex": ["^echo"], "background_execution": "allow"},
        )
        assert result["status"] == "allow"

    def test_compound_block_denied(self) -> None:
        result = evaluate_bash_command(
            "{ echo hi; } &",
            {"*": "allow", "allowed_cmds_regex": ["^echo"], "background_execution": "deny"},
        )
        assert result["status"] == "deny"

    def test_compound_if_denied(self) -> None:
        result = evaluate_bash_command(
            "if true; then echo hi; fi &",
            {"*": "allow", "allowed_cmds_regex": ["^echo"], "background_execution": "deny"},
        )
        assert result["status"] == "deny"

    def test_subshell_inner_background_denied(self) -> None:
        """`(echo hi &)` backgrounds the inner command - policy applies."""
        result = evaluate_bash_command(
            "(echo hi &)",
            {"*": "allow", "allowed_cmds_regex": ["^echo"], "background_execution": "deny"},
        )
        assert result["status"] == "deny"

    def test_subshell_inner_background_ask(self) -> None:
        result = evaluate_bash_command(
            "(echo hi &)",
            {"*": "allow", "allowed_cmds_regex": ["^echo"], "background_execution": "ask"},
        )
        assert result["status"] == "ask"

    def test_assignment_substitution_background_denied(self) -> None:
        """`x=$(echo hi &)` backgrounds a command inside a substitution."""
        result = evaluate_bash_command(
            "x=$(echo hi &)",
            {
                "*": "allow",
                "allowed_cmds_regex": ["^echo"],
                "background_execution": "deny",
                "variable_assignment": "allow",
                "subshell": "allow",
            },
        )
        assert result["status"] == "deny"


class TestCompoundCommandRedirections:
    """Redirections on time/funcdef/coproc statements are not dropped.

    Regression: `time echo hi > /etc/passwd` was auto-approved because the
    converter unwrapped the inner Stmt and lost its redirections.
    """

    def test_compound_input_redirection_not_duplicated(self) -> None:
        """< file on a while loop is attributed once, not per segment."""
        result = evaluate_bash_command(
            "while :; do echo a; done < /etc/shadow",
            {"*": "allow", "input_redirection": "allow"},
        )
        assert result["status"] == "allow"
        assert result["reason"].count("/etc/shadow") == 1

    def test_time_blocked_path_denied(self) -> None:
        result = evaluate_bash_command(
            "time echo hi > /etc/passwd",
            make_config(blocked=[r"^/etc/passwd$"], subshell="allow", variable_assignment="allow"),
        )
        assert result["status"] == "deny"

    def test_time_output_redirection_asks(self) -> None:
        result = evaluate_bash_command(
            "time echo hi > /tmp/out",
            make_config(allowed=[r"^echo(\s+.*)?$"], output="ask", subshell="allow", variable_assignment="allow"),
        )
        assert result["status"] == "ask"

    def test_time_no_redirection_unaffected(self) -> None:
        result = evaluate_bash_command(
            "time echo hi",
            make_config(allowed=[r"^echo(\s+.*)?$"], subshell="allow", variable_assignment="allow"),
        )
        assert result["status"] == "allow"

    def test_funcdef_blocked_path_denied(self) -> None:
        result = evaluate_bash_command(
            "f() { echo hi; } > /etc/passwd",
            make_config(blocked=[r"^/etc/passwd$"], subshell="allow", variable_assignment="allow"),
        )
        assert result["status"] == "deny"

    def test_coproc_blocked_path_denied(self) -> None:
        result = evaluate_bash_command(
            "coproc c { echo hi; } > /etc/passwd",
            make_config(blocked=[r"^/etc/passwd$"], subshell="allow", variable_assignment="allow"),
        )
        assert result["status"] == "deny"


class TestTrickyRedirectionPatterns:
    """Tests for uncommon or ambiguous bash syntax with redirections.

    These patterns often trip up parsers with no spaces, mixed direction
    redirections, fd manipulation, and background job combinations.
    """

    def test_no_space_redirect_empty(self) -> None:
        """true>file (no space) should require approval in empty config."""
        result = evaluate_bash_command("true>file", make_config())
        assert result["status"] == "ask"

    def test_no_space_redirect_env2(self) -> None:
        """true>file (no space) should require approval in env2 (redirection requires approval)."""
        result = evaluate_bash_command("true>file", make_config())
        assert result["status"] == "ask"

    def test_partial_space_redirect_env2(self) -> None:
        """true> file (partial space) should require approval in env2."""
        result = evaluate_bash_command("true> file", make_config())
        assert result["status"] == "ask"

    def test_no_space_after_redirect_env2(self) -> None:
        """true >file (no space after) should require approval in env2."""
        result = evaluate_bash_command("true >file", make_config())
        assert result["status"] == "ask"

    def test_chained_redirect_empty(self) -> None:
        """true > file > file2 should require approval in empty config."""
        result = evaluate_bash_command("true > file > file2", make_config())
        assert result["status"] == "ask"

    def test_chained_redirect_env2(self) -> None:
        """true > file > file2 should require approval in env2."""
        result = evaluate_bash_command("true > file > file2", make_config())
        assert result["status"] == "ask"

    def test_mixed_direction_redirect_empty(self) -> None:
        """true > file < file2 should require approval in empty config."""
        result = evaluate_bash_command("true > file < file2", make_config())
        assert result["status"] == "ask"

    def test_mixed_direction_redirect_env2(self) -> None:
        """true > file < file2 should require approval in env2."""
        result = evaluate_bash_command("true > file < file2", make_config())
        assert result["status"] == "ask"

    def test_stderr_to_stdout_empty(self) -> None:
        """true > file 2>&1 should require approval in empty config."""
        result = evaluate_bash_command("true > file 2>&1", make_config())
        assert result["status"] == "ask"

    def test_stderr_to_stdout_env2(self) -> None:
        """true > file 2>&1 should require approval in env2."""
        result = evaluate_bash_command("true > file 2>&1", make_config())
        assert result["status"] == "ask"

    def test_background_empty(self) -> None:
        """true > file & should require approval in empty config."""
        result = evaluate_bash_command("true > file &", make_config())
        assert result["status"] == "ask"

    def test_background_env2(self) -> None:
        """true > file & should require approval in env2."""
        result = evaluate_bash_command("true > file &", make_config())
        assert result["status"] == "ask"

    def test_devnull_empty(self) -> None:
        """cmd > /dev/null should require approval in empty config."""
        result = evaluate_bash_command("cmd > /dev/null", make_config())
        assert result["status"] == "ask"

    def test_devnull_env2(self) -> None:
        """cmd > /dev/null should require approval in env2 (cmd not allowed)."""
        result = evaluate_bash_command("cmd > /dev/null", make_config())
        assert result["status"] == "ask"

    def test_devnull_env3(self) -> None:
        """cmd > /dev/null should require approval in env3 (cmd not allowed)."""
        result = evaluate_bash_command("cmd > /dev/null", make_config())
        assert result["status"] == "ask"

    def test_devnull_input_empty(self) -> None:
        """cmd < /dev/null should require approval in empty config."""
        result = evaluate_bash_command("cmd < /dev/null", make_config())
        assert result["status"] == "ask"

    def test_devnull_chain_empty(self) -> None:
        """true > /dev/null 2>&1 > /dev/null should require approval in empty config."""
        result = evaluate_bash_command("true > /dev/null 2>&1 > /dev/null", make_config())
        assert result["status"] == "ask"

    def test_devnull_chain_env2(self) -> None:
        """true > /dev/null 2>&1 > /dev/null should require approval in env2."""
        result = evaluate_bash_command("true > /dev/null 2>&1 > /dev/null", make_config())
        assert result["status"] == "ask"

    def test_save_fd_empty(self) -> None:
        """true 3>&1 > /dev/null should require approval in empty config."""
        result = evaluate_bash_command("true 3>&1 > /dev/null", make_config())
        assert result["status"] == "ask"

    def test_save_fd_env2(self) -> None:
        """true 3>&1 > /dev/null should require approval in env2."""
        result = evaluate_bash_command("true 3>&1 > /dev/null", make_config())
        assert result["status"] == "ask"

    def test_save_fd_after_empty(self) -> None:
        """true > /dev/null 3>&1 should require approval in empty config."""
        result = evaluate_bash_command("true > /dev/null 3>&1", make_config())
        assert result["status"] == "ask"

    def test_save_fd_after_env2(self) -> None:
        """true > /dev/null 3>&1 should require approval in env2."""
        result = evaluate_bash_command("true > /dev/null 3>&1", make_config())
        assert result["status"] == "ask"

    def test_redirect_order_empty(self) -> None:
        """true > file </dev/null should require approval in empty config."""
        result = evaluate_bash_command("true > file </dev/null", make_config())
        assert result["status"] == "ask"

    def test_redirect_order_env2(self) -> None:
        """true > file </dev/null should require approval in env2."""
        result = evaluate_bash_command("true > file </dev/null", make_config())
        assert result["status"] == "ask"

    def test_other_redirect_order_empty(self) -> None:
        """true </dev/null > file should require approval in empty config."""
        result = evaluate_bash_command("true </dev/null > file", make_config())
        assert result["status"] == "ask"

    def test_other_redirect_order_env2(self) -> None:
        """true </dev/null > file should require approval in env2."""
        result = evaluate_bash_command("true </dev/null > file", make_config())
        assert result["status"] == "ask"

    def test_complex_bg_empty(self) -> None:
        """true > file1 2>&1 & true > file2 should require approval in empty config."""
        result = evaluate_bash_command("true > file1 2>&1 & true > file2", make_config())
        assert result["status"] == "ask"

    def test_complex_bg_env2(self) -> None:
        """true > file1 2>&1 & true > file2 should require approval in env2."""
        result = evaluate_bash_command("true > file1 2>&1 & true > file2", make_config())
        assert result["status"] == "ask"


class TestNestedCompoundExpressions:
    """Tests for deeply nested and compound bash expressions with redirections.

    Verifies the tool correctly handles complex nested structures.
    """

    def test_nested_command_substitution_empty(self) -> None:
        """Nested command substitution with output redirection should ask in empty config."""
        result = evaluate_bash_command("echo $(echo $(echo $(echo hi))) > file", make_config())
        assert result["status"] == "ask"

    def test_nested_command_substitution_env2(self) -> None:
        """Nested command substitution with output redirection should ask in env2."""
        result = evaluate_bash_command("echo $(echo $(echo $(echo hi))) > file", make_config())
        assert result["status"] == "ask"

    def test_nested_command_substitution_env3(self) -> None:
        """Nested command substitution with output redirection should ask in env3."""
        result = evaluate_bash_command("echo $(echo $(echo $(echo hi))) > file", make_config())
        assert result["status"] == "ask"

    def test_pipe_chain_empty(self) -> None:
        """Pipe chain with output redirection should ask in empty config."""
        result = evaluate_bash_command("echo hi | grep hi | grep h | cat > file", make_config())
        assert result["status"] == "ask"

    def test_pipe_chain_env2(self) -> None:
        """Pipe chain with output redirection should ask in env2."""
        result = evaluate_bash_command("echo hi | grep hi | grep h | cat > file", make_config())
        assert result["status"] == "ask"

    def test_pipe_chain_env3(self) -> None:
        """Pipe chain with output redirection should ask in env3."""
        result = evaluate_bash_command("echo hi | grep hi | grep h | cat > file", make_config())
        assert result["status"] == "ask"

    def test_complex_pipeline_empty(self) -> None:
        """Complex pipeline with output redirection should ask in empty config."""
        result = evaluate_bash_command("ls | grep text | xargs cat > file", make_config())
        assert result["status"] == "ask"

    def test_complex_pipeline_env2(self) -> None:
        """Complex pipeline with output redirection should ask in env2."""
        result = evaluate_bash_command("ls | grep text | xargs cat > file", make_config())
        assert result["status"] == "ask"

    def test_complex_pipeline_env3(self) -> None:
        """Complex pipeline with output redirection should ask in env3."""
        result = evaluate_bash_command("ls | grep text | xargs cat > file", make_config())
        assert result["status"] == "ask"

    def test_nested_conditionals_empty(self) -> None:
        """Nested conditionals with output redirection should ask in empty config."""
        result = evaluate_bash_command("if [ x ]; then if [ y ]; then echo hi > file; fi; fi", make_config())
        assert result["status"] == "ask"

    def test_nested_conditionals_env2(self) -> None:
        """Nested conditionals with output redirection should ask in env2."""
        result = evaluate_bash_command("if [ x ]; then if [ y ]; then echo hi > file; fi; fi", make_config())
        assert result["status"] == "ask"

    def test_nested_conditionals_env3(self) -> None:
        """Nested conditionals with output redirection should ask in env3."""
        result = evaluate_bash_command("if [ x ]; then if [ y ]; then echo hi > file; fi; fi", make_config())
        assert result["status"] == "ask"

    def test_compound_logical_empty(self) -> None:
        """Compound logical expressions with output redirection should ask in empty config."""
        result = evaluate_bash_command("[ x ] && ([ y ] || [ z ]) > file", make_config())
        assert result["status"] == "ask"

    def test_compound_logical_env2(self) -> None:
        """Compound logical expressions with output redirection should ask in env2."""
        result = evaluate_bash_command("[ x ] && ([ y ] || [ z ]) > file", make_config())
        assert result["status"] == "ask"

    def test_compound_logical_env3(self) -> None:
        """Compound logical expressions with output redirection should ask in env3."""
        result = evaluate_bash_command("[ x ] && ([ y ] || [ z ]) > file", make_config())
        assert result["status"] == "ask"

    def test_brace_expansion_empty(self) -> None:
        """Brace expansion with output redirection should ask in empty config."""
        result = evaluate_bash_command("echo {a,b,c} > file", make_config())
        assert result["status"] == "ask"

    def test_brace_expansion_env2(self) -> None:
        """Brace expansion with output redirection should ask in env2."""
        result = evaluate_bash_command("echo {a,b,c} > file", make_config())
        assert result["status"] == "ask"

    def test_brace_expansion_env3(self) -> None:
        """Brace expansion with output redirection should ask in env3."""
        result = evaluate_bash_command("echo {a,b,c} > file", make_config())
        assert result["status"] == "ask"

    def test_nested_brace_expansion_env2(self) -> None:
        """Nested brace expansion with output redirection should ask in env2."""
        result = evaluate_bash_command("echo {a,b}{c,d} > file", make_config())
        assert result["status"] == "ask"

    def test_heredoc_with_substitution_empty(self) -> None:
        """Here-document with substitution and output redirection should ask in empty config."""
        result = evaluate_bash_command("cat <<< $(echo hi) > file", make_config())
        assert result["status"] == "ask"

    def test_heredoc_with_substitution_env2(self) -> None:
        """Here-document with substitution and output redirection should ask in env2."""
        result = evaluate_bash_command("cat <<< $(echo hi) > file", make_config())
        assert result["status"] == "ask"

    def test_heredoc_with_substitution_env3(self) -> None:
        """Here-document with substitution and output redirection should ask in env3."""
        result = evaluate_bash_command("cat <<< $(echo hi) > file", make_config())
        assert result["status"] == "ask"


class TestComplexNestedConstructs:
    """Tests for deeply nested and compound bash expressions with redirections.

    Verifies the tool correctly handles complex nested structures including
    process substitution, loops, conditionals, functions, and compound commands.
    """

    def test_if_with_cmdsub_and_pipe(self) -> None:
        """if with command substitution, here-doc, pipe, and redirection."""
        result = evaluate_bash_command('if [ $(echo hi) ]; then cat <<< "x" | grep x > file; fi', make_config())
        assert result["status"] == "ask"

    def test_for_loop_with_cmdsub(self) -> None:
        """for loop with command substitution and redirection."""
        result = evaluate_bash_command("for i in $(seq 1 3); do echo $i > file; done", make_config())
        assert result["status"] == "ask"

    def test_heredoc_with_pipe(self) -> None:
        """here-document piped to grep with output redirection."""
        result = evaluate_bash_command("cat << EOF | grep pattern > file\ncontent\nEOF", make_config())
        assert result["status"] == "ask"

    def test_if_with_procsub(self) -> None:
        """if with process substitution and nested command substitution."""
        result = evaluate_bash_command("if $(test -f <(echo hi)); then cat <<< $(echo ok) > file; fi", make_config())
        assert result["status"] == "ask"

    def test_nested_conditionals(self) -> None:
        """nested if statements with command substitution."""
        result = evaluate_bash_command(
            "if [ $(echo x) ]; then if [ $(echo y) ]; then echo both > file; fi; fi", make_config()
        )
        assert result["status"] == "ask"

    def test_while_loop(self) -> None:
        """while loop with command substitution and redirection."""
        result = evaluate_bash_command("while true; do if [ $(echo x) ]; then break; fi; done > file", make_config())
        assert result["status"] == "ask"

    def test_case_statement(self) -> None:
        """case statement with command substitution."""
        result = evaluate_bash_command("case $(echo x) in x) echo ok > file;; esac", make_config())
        assert result["status"] == "ask"

    def test_select_statement(self) -> None:
        """select statement with command substitution."""
        result = evaluate_bash_command("select opt in $(echo a b); do echo $opt > file; done", make_config())
        assert result["status"] == "ask"

    def test_compound_with_procsub(self) -> None:
        """compound command with process substitution."""
        result = evaluate_bash_command("{ cat <(echo hi); } > file", make_config())
        assert result["status"] == "ask"

    def test_subshell_with_procsub(self) -> None:
        """subshell with process substitution."""
        result = evaluate_bash_command("(cat <(echo hi)) > file", make_config())
        assert result["status"] == "ask"

    def test_function_definition(self) -> None:
        """function definition with output redirection."""
        result = evaluate_bash_command("fn() { echo hi > file; }; fn", make_config())
        assert result["status"] == "ask"

    def test_subshell_function(self) -> None:
        """subshell containing function definition."""
        result = evaluate_bash_command("(fn() { echo hi > file; }; fn)", make_config())
        assert result["status"] == "ask"


class TestAdvancedBashConstructs:
    """Tests for advanced bash constructs (process substitution, coproc, trap, functions, builtins)."""

    def test_procsub_cat_echo_empty(self) -> None:
        """Process substitution with cat should require approval in empty env."""
        result = evaluate_bash_command("cat <(echo hi)", make_config())
        assert result["status"] == "ask"

    def test_procsub_cat_echo_env2(self) -> None:
        """Process substitution with cat should require approval in env2."""
        result = evaluate_bash_command("cat <(echo hi)", make_config())
        assert result["status"] == "ask"

    def test_procsub_cat_echo_env3(self) -> None:
        """Process substitution with cat should require approval in env3."""
        result = evaluate_bash_command("cat <(echo hi)", make_config())
        assert result["status"] == "ask"

    def test_procsub_cat_echo_file2_env2(self) -> None:
        """Process substitution with cat to file should require approval in env2."""
        result = evaluate_bash_command("cat <(echo hi)", make_config())
        assert result["status"] == "ask"

    def test_diff_procsub_ls_empty(self) -> None:
        """Diff with process substitution should require approval in empty env."""
        result = evaluate_bash_command("diff <(ls file1) <(ls file2)", make_config())
        assert result["status"] == "ask"

    def test_diff_procsub_ls_env2(self) -> None:
        """Diff with process substitution should require approval in env2."""
        result = evaluate_bash_command("diff <(ls file1) <(ls file2)", make_config())
        assert result["status"] == "ask"

    def test_diff_procsub_ls_env3(self) -> None:
        """Diff with process substitution should require approval in env3."""
        result = evaluate_bash_command("diff <(ls file1) <(ls file2)", make_config())
        assert result["status"] == "ask"

    def test_coproc_echo_empty(self) -> None:
        """Coproc with echo should require approval in empty env."""
        result = evaluate_bash_command("coproc myproc { echo hi; }", make_config())
        assert result["status"] == "ask"

    def test_coproc_echo_env2(self) -> None:
        """Coproc with echo should require approval in env2 (coproc is not allowed)."""
        result = evaluate_bash_command("coproc myproc { echo hi; }", make_config())
        assert result["status"] == "ask"

    def test_coproc_echo_env3(self) -> None:
        """Coproc with echo should require approval in env3 (coproc is not allowed)."""
        result = evaluate_bash_command("coproc myproc { echo hi; }", make_config())
        assert result["status"] == "ask"

    def test_coproc_echo_file_env2(self) -> None:
        """Coproc with echo to file should require approval in env2."""
        result = evaluate_bash_command("coproc myproc { echo hi > file; }", make_config())
        assert result["status"] == "ask"

    def test_trap_echo_file_empty(self) -> None:
        """Trap with echo should require approval in empty env."""
        result = evaluate_bash_command('trap "echo trap > file" EXIT', make_config())
        assert result["status"] == "ask"

    def test_trap_echo_file_env2(self) -> None:
        """Trap with echo should require approval in env2."""
        result = evaluate_bash_command('trap "echo trap > file" EXIT', make_config())
        assert result["status"] == "ask"

    def test_fn_def_echo_file_env2(self) -> None:
        """Function definition with echo should require approval in env2."""
        result = evaluate_bash_command("fn() { echo hi > file; }", make_config())
        assert result["status"] == "ask"

    def test_fn_def_echo_file_env3(self) -> None:
        """Function definition with echo should require approval in env3."""
        result = evaluate_bash_command("fn() { echo hi > file; }", make_config())
        assert result["status"] == "ask"

    def test_fn_call_redirect_env2(self) -> None:
        """Function call with redirect should require approval in env2."""
        result = evaluate_bash_command("fn > out", make_config())
        assert result["status"] == "ask"

    def test_fn_call_redirect_env3(self) -> None:
        """Function call with redirect should require approval in env3."""
        result = evaluate_bash_command("fn > out", make_config())
        assert result["status"] == "ask"

    def test_export_var_cmdsub_redirect_env2(self) -> None:
        """Export with command substitution should require approval in env2."""
        result = evaluate_bash_command("export VAR=$(echo hi) > file", make_config())
        assert result["status"] == "ask"

    def test_export_var_cmdsub_redirect_env3(self) -> None:
        """Export with command substitution should require approval in env3."""
        result = evaluate_bash_command("export VAR=$(echo hi) > file", make_config())
        assert result["status"] == "ask"

    def test_export_path_redirect_empty(self) -> None:
        """Export with path should require approval in empty env."""
        result = evaluate_bash_command('export PATH="$PATH:/usr/local/bin" > file', make_config())
        assert result["status"] == "ask"

    def test_export_path_redirect_env2(self) -> None:
        """Export with path should require approval in env2."""
        result = evaluate_bash_command('export PATH="$PATH:/usr/local/bin" > file', make_config())
        assert result["status"] == "ask"

    def test_unset_array_redirect_empty(self) -> None:
        """Unset array should require approval in empty env."""
        result = evaluate_bash_command("unset arr[@] > file", make_config())
        assert result["status"] == "ask"

    def test_unset_array_redirect_env2(self) -> None:
        """Unset array should require approval in env2."""
        result = evaluate_bash_command("unset arr[@] > file", make_config())
        assert result["status"] == "ask"

    def test_declare_assoc_redirect_env2(self) -> None:
        """Declare associative array should require approval in env2."""
        result = evaluate_bash_command("declare -A map > file", make_config())
        assert result["status"] == "ask"

    def test_declare_assoc_redirect_env3(self) -> None:
        """Declare associative array should require approval in env3."""
        result = evaluate_bash_command("declare -A map > file", make_config())
        assert result["status"] == "ask"


class TestEmptySegmentSubshellPolicy:
    """standalone (( ... $(...) )) is gated by the subshell policy."""

    CMD = "(( x[$(rm -rf /etc/x)] ))"

    def test_allow_wildcard_deny_subshell(self) -> None:
        assert evaluate_bash_command(self.CMD, {"*": "allow", "subshell": "deny"})["status"] == "deny"

    def test_allow_wildcard_default_subshell_asks(self) -> None:
        assert evaluate_bash_command(self.CMD, {"*": "allow"})["status"] == "ask"

    def test_allow_wildcard_explicit_ask(self) -> None:
        assert evaluate_bash_command(self.CMD, {"*": "allow", "subshell": "ask"})["status"] == "ask"

    def test_allow_wildcard_explicit_subshell_allow(self) -> None:
        assert evaluate_bash_command(self.CMD, {"*": "allow", "subshell": "allow"})["status"] == "allow"

    def test_ask_wildcard_deny_subshell(self) -> None:
        assert evaluate_bash_command(self.CMD, {"*": "ask", "subshell": "deny"})["status"] == "deny"

    def test_deny_wildcard_allow_subshell(self) -> None:
        assert evaluate_bash_command(self.CMD, {"*": "deny", "subshell": "allow"})["status"] == "deny"

    def test_deny_wildcard_unset_subshell(self) -> None:
        """No downgrade: an inherited deny (unset subshell) still denies."""
        assert evaluate_bash_command(self.CMD, {"*": "deny"})["status"] == "deny"

    def test_time_wrapped_arithmetic(self) -> None:
        assert evaluate_bash_command("time (( x[$(rm z)] ))", {"*": "allow", "subshell": "deny"})["status"] == "deny"

    def test_followed_by_real_command(self) -> None:
        assert evaluate_bash_command("ls; (( x[$(rm)] ))", {"*": "allow", "subshell": "deny"})["status"] == "deny"

    def test_plus_equals_variant(self) -> None:
        assert evaluate_bash_command("(( y += $(rm z) ))", {"*": "allow", "subshell": "deny"})["status"] == "deny"

    def test_literal_arithmetic_unaffected(self) -> None:
        assert evaluate_bash_command("(( x = 5 ))", {"*": "allow", "subshell": "deny"})["status"] == "allow"


class TestDeepNestingRecursion:
    """deep nesting converts and evaluates; past the cap, fail closed."""

    def test_deep_command_substitution_evaluates_without_crash(self) -> None:
        """deep nesting converts and evaluates instead of RecursionError."""
        deep = "echo " + "$(" * 180 + "true" + ")" * 180
        result = evaluate_bash_command(deep, {"*": "allow"})
        assert result["status"] == "allow"

    def test_over_cap_command_fails_closed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """past the cap we fail closed with a parse error, never recurse-crash."""
        import lovely_bash_permissions.converter as conv

        monkeypatch.setattr(conv, "_MAX_RECURSION_LIMIT", 2000)
        deep = "echo " + "$(" * 400 + "true" + ")" * 400
        with pytest.raises(LovelyDevinPermissionsError):
            conv.parse_ast(deep)


class TestExecutedFormMatching:
    """Executed-form matching (NEW_BUGS #1): quote-split / backslash-escaped
    spellings cannot dodge blocked-path checks or guard patterns.

    Wildcard is ``ask`` (mirrors the user's real config): under
    ``"*": "allow"`` a guard-tripped command would fall through to the allow
    wildcard instead of asking, so ``*:ask`` makes the "guard-trip → not
    auto-approved → ask" intent observable.
    """

    CONFIG: ClassVar[dict[str, list[str] | str]] = make_config(
        allowed=[
            r"^cat\s+.+$",
            r"^find(?!.*\s-(exec|delete|ok)\b).*$",
            r"^fd(?!.*\s+(-x|-X)).*$",
            r"^sort(?!\s+(-o|--output)\b).*$",
        ],
        blocked=["\\/etc", r"\.env$"],
        wildcard="ask",
    )

    @pytest.mark.parametrize(
        ("command", "expected"),
        [
            # Quote-split / escaped paths caught by the blocked check on the
            # *normalized* argument (the executed path).
            ('cat /e"tc"/passwd', "deny"),
            ('ls -la /e"tc"', "deny"),  # ls not allowlisted, but /etc blocked
            ('grep x /e"tc"/passwd', "deny"),
            ('cat .e"nv"', "deny"),
            # Guard patterns evaluated on the executed form: the split or
            # escaped dangerous flag trips the negative lookahead, so the
            # command is not auto-approved and falls to the wildcard (ask).
            ('find /tmp -e"x"ec rm', "ask"),
            ('find /tmp -"exec" rm', "ask"),
            ("find /tmp -ex\\ec rm", "ask"),
            ('fd -"x" x', "ask"),
            ('sort -"o" /tmp/out x', "ask"),
            # Contrasts: plain blocked path / plain quoted arg.
            ("cat /etc/passwd", "deny"),
            ('cat "ok file"', "allow"),
            ("cat .env", "deny"),
        ],
    )
    def test_split_and_escaped_forms(self, command: str, expected: str) -> None:
        result = evaluate_bash_command(command, self.CONFIG)
        assert result["status"] == expected

    def test_heredoc_body_split_path_denied(self) -> None:
        """A quote-split path inside a heredoc body is caught by the stripped variant."""
        result = evaluate_bash_command('cat f <<EOF\nsecret /e"tc"/passwd\nEOF', self.CONFIG)
        assert result["status"] == "deny"

    def test_safe_single_quoted_find_still_allowed(self) -> None:
        """A safe single-quoted find stays auto-approved (union-regression guard)."""
        result = evaluate_bash_command("find . -name '*.txt'", self.CONFIG)
        assert result["status"] == "allow"


class TestRedirectionOnlyOperands:
    """Redirection-only operands of && / || / | must not bypass policy (NEW_BUGS #3).

    shfmt emits e.g. `> /etc/x && cat file` as an operand dict with Redirs but
    no Type and no Cmd; before the fix the redirection was silently dropped
    and slipped past all output-redirection / blocked-path checks.
    """

    CONFIG_A: ClassVar[dict[str, str | list[str]]] = {
        "*": "allow",
        "blocked_paths_regex": ["\\/etc"],
        "allowed_cmds_regex": [r"^cat\s+.+$"],
    }

    @pytest.mark.parametrize(
        "command",
        [
            "> /etc/x && cat file",
            "> /etc/x | true",
            "true | > /etc/x",
            "cat file && > /etc/y",
            "2>/etc/e | true",
        ],
    )
    def test_blocked_target_denied(self, command: str) -> None:
        result = evaluate_bash_command(command, self.CONFIG_A)
        assert result["status"] == "deny"

    def test_allowed_target_allowed(self) -> None:
        """Contrast: with output_redirection=allow, a non-blocked target is approved."""
        config = {**self.CONFIG_A, "output_redirection": "allow"}
        result = evaluate_bash_command("> /tmp/ok && cat file", config)
        assert result["status"] == "allow"

    def test_output_allow_still_blocks_blocked_path(self) -> None:
        """output_redirection=allow never waives the blocked-path security check."""
        config = {"*": "allow", "blocked_paths_regex": ["\\/etc"], "output_redirection": "allow"}
        result = evaluate_bash_command("> /etc/x && > /etc/y", config)
        assert result["status"] == "deny"
