"""Direct unit tests for the LIVE redirection-policy functions in ``rules.py``.

The tree-based entry points (``check_output_redirection`` /
``check_input_redirection``) are not what production calls; production calls
only the segment-based ones
(:func:`check_output_redirections` / :func:`check_input_redirections`)
plus the shared helpers :func:`classify_output_redirection`,
:func:`_resolve_output_level` and :func:`check_background_execution`.

This module pins the live path, which is the only one the production hook
exercises.  Status is the contract under test; reason strings are
only checked for loose substrings (the target / command name, or the verb), so
a future rewording of a message does not break the suite.
"""

from typing import Any, cast

import pytest

from lovely_bash_permissions.parser import parse
from lovely_bash_permissions.rules import (
    INPUT_REDIRECT_OPS,
    WRITE_REDIRECT_OPS,
    _resolve_output_level,
    check_background_execution,
    check_input_redirections,
    check_output_redirections,
    classify_output_redirection,
)
from lovely_bash_permissions.segments import Segment, SegmentRedirection, parse_segments

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def redir(op: str, target: str, fd: str | None = None) -> SegmentRedirection:
    """Build a segment-shaped redirection record (``Op``/``N``/``Target``)."""
    return {
        "Op": op,
        "N": {"Value": fd} if fd is not None else {},
        "Target": target,
    }


def segment(*redirs: SegmentRedirection, command: str = "echo") -> Segment:
    """Build a segment dict carrying the given redirections."""
    return {
        "command": command,
        "arguments": [],
        "normalized_arguments": [],
        "redirections": list(redirs),
    }


# ---------------------------------------------------------------------------
# classify_output_redirection
# ---------------------------------------------------------------------------


class TestClassifyOutputRedirection:
    """classify_output_redirection maps one write redirection to policy kinds."""

    @pytest.mark.parametrize("op", ["<", "<<", "<<<", "<&", "|&"])
    def test_non_write_op_yields_no_kinds(self, op: str) -> None:
        """An input-side operator is not an output redirection at all."""
        assert classify_output_redirection(redir(op, "/tmp/in")) == []

    def test_missing_op_yields_no_kinds(self) -> None:
        """A redirection record with no ``Op`` key classifies to nothing."""
        assert (
            classify_output_redirection(cast(SegmentRedirection, {"Word": {"Parts": [{"Value": "/dev/null"}]}})) == []
        )

    def test_stdout_to_dev_null(self) -> None:
        """``> /dev/null`` (default fd) is stdout_to_dev_null."""
        assert classify_output_redirection(redir(">", "/dev/null")) == ["stdout_to_dev_null"]

    def test_stderr_to_dev_null(self) -> None:
        """``2> /dev/null`` is stderr_to_dev_null, not stdout."""
        assert classify_output_redirection(redir(">", "/dev/null", "2")) == ["stderr_to_dev_null"]

    def test_stderr_to_stdout(self) -> None:
        """``2>&1`` is the fd-duplication kind."""
        assert classify_output_redirection(redir(">&", "1", "2")) == ["stderr_to_stdout"]

    def test_stderr_to_stdout_needs_both_fds(self) -> None:
        """``>&1`` without the ``2`` prefix is an ordinary write to fd 1."""
        assert classify_output_redirection(redir(">&", "1")) == ["other"]

    @pytest.mark.parametrize("op", ["&>", "&>>", ">&"])
    def test_combined_op_to_dev_null_is_both_kinds(self, op: str) -> None:
        """A combined op aimed at /dev/null redirects stdout *and* stderr."""
        assert classify_output_redirection(redir(op, "/dev/null")) == [
            "stdout_to_dev_null",
            "stderr_to_dev_null",
        ]

    def test_plain_file_target_is_other(self) -> None:
        """A write to an ordinary file is the catch-all ``other`` kind."""
        assert classify_output_redirection(redir(">", "/tmp/out.txt")) == ["other"]

    def test_append_to_dev_null_is_stdout_kind(self) -> None:
        """``>> /dev/null`` is still the stdout kind (append does not change it)."""
        assert classify_output_redirection(redir(">>", "/dev/null")) == ["stdout_to_dev_null"]

    def test_multi_part_target_is_classified_as_one_string(self) -> None:
        """A multi-part ``Target`` is classified as a single whole string."""
        segs = parse_segments('echo hi > "$DIR/out.txt"')
        redirs = segs[0]["redirections"]
        assert len(redirs) == 1
        assert redirs[0]["Target"] == "$DIR/out.txt"
        assert classify_output_redirection(redirs[0]) == ["other"]

    def test_quote_split_target_keeps_every_part(self) -> None:
        """A quote-split path is rejoined into the executed-form target."""
        segs = parse_segments('echo hi > /e"tc"/out')
        redirs = segs[0]["redirections"]
        assert redirs[0]["Target"] == "/etc/out", "quote-split parts must be rejoined"
        assert classify_output_redirection(redirs[0]) == ["other"]

    def test_quote_split_dev_null_via_segments(self) -> None:
        """A quote-split ``"/dev""/null"`` target is still recognised."""
        segs = parse_segments('echo hi 2>"/dev""/null"')
        (only,) = segs
        redirs = only["redirections"]
        assert len(redirs) == 1
        assert redirs[0]["Target"] == "/dev/null"
        assert classify_output_redirection(redirs[0]) == ["stderr_to_dev_null"]

    def test_quote_split_normal_file_is_other(self) -> None:
        """A quote-split ordinary path is the catch-all kind, reported whole."""
        segs = parse_segments('echo hi > "out"".txt"')
        redirs = segs[0]["redirections"]
        assert redirs[0]["Target"] == "out.txt"
        assert classify_output_redirection(redirs[0]) == ["other"]


# ---------------------------------------------------------------------------
# _resolve_output_level
# ---------------------------------------------------------------------------


class TestResolveOutputLevel:
    """_resolve_output_level turns per-kind hits into one allow/ask/deny level."""

    def test_wildcard_fallback_when_kind_absent(self) -> None:
        """A kind with no policy key falls back to the wildcard level."""
        policy = {"*": "ask", "stdout_to_dev_null": "allow"}
        assert _resolve_output_level(["other"], policy) == "ask"
        assert _resolve_output_level(["stdout_to_dev_null"], policy) == "allow"

    def test_per_kind_independence(self) -> None:
        """One kind's allow does not leak into another kind's resolution."""
        policy = {"*": "allow", "stderr_to_stdout": "ask"}
        assert _resolve_output_level(["stdout_to_dev_null"], policy) == "allow"
        assert _resolve_output_level(["stderr_to_stdout"], policy) == "ask"

    def test_deny_overrides_ask_across_kinds(self) -> None:
        """Any kind at deny outranks any kind at ask."""
        policy = {"*": "allow", "a": "deny", "b": "ask"}
        assert _resolve_output_level(["b", "a"], policy) == "deny"
        assert _resolve_output_level(["a", "b"], policy) == "deny"

    def test_all_allow_resolves_allow(self) -> None:
        """Every kind explicitly allowed resolves to allow."""
        policy = {"*": "ask", "stdout_to_dev_null": "allow", "stderr_to_dev_null": "allow"}
        assert _resolve_output_level(["stdout_to_dev_null", "stderr_to_dev_null"], policy) == "allow"

    def test_empty_kinds_resolves_allow(self) -> None:
        """No kinds means nothing triggered the policy, so it resolves allow."""
        assert _resolve_output_level([], {"*": "ask"}) == "allow"
        assert _resolve_output_level([], {"*": "deny"}) == "allow"

    def test_wildcard_defaults_to_ask(self) -> None:
        """A policy dict with neither the kind nor ``*`` defaults to ask."""
        assert _resolve_output_level(["other"], {}) == "ask"
        assert _resolve_output_level(["other"], {"stdout_to_dev_null": "allow"}) == "ask"

    def test_combined_kinds_resolve_together(self) -> None:
        """The two kinds of one combined redirection are resolved independently."""
        policy = {"*": "allow", "stdout_to_dev_null": "allow", "stderr_to_dev_null": "deny"}
        assert _resolve_output_level(["stdout_to_dev_null", "stderr_to_dev_null"], policy) == "deny"
        policy_ok = {"*": "ask", "stdout_to_dev_null": "allow", "stderr_to_dev_null": "allow"}
        assert _resolve_output_level(["stdout_to_dev_null", "stderr_to_dev_null"], policy_ok) == "allow"


# ---------------------------------------------------------------------------
# check_output_redirections
# ---------------------------------------------------------------------------


class TestSegmentsOutputRedirs:
    """check_output_redirections evaluates segment redirections."""

    def test_no_redirections_is_unmatched_allow(self) -> None:
        """Nothing to evaluate reports matched=False even under a deny policy."""
        result = check_output_redirections([segment()], {"output_redirection": "deny"})
        assert result["status"] == "allow"
        assert result["matched"] is False
        assert result["reason"] == "no output redirection"

    def test_empty_segment_list_is_unmatched_allow(self) -> None:
        """An empty segment list is the same as "no redirections"."""
        result = check_output_redirections([], {"output_redirection": "deny"})
        assert result["status"] == "allow"
        assert result["matched"] is False

    def test_output_only_redirections_are_not_input(self) -> None:
        """An output-looking op never counts as an output redirection here."""
        # "<" is not in WRITE_REDIRECT_OPS, so the check reports nothing found.
        result = check_output_redirections([segment(redir("<", "/tmp/in"))], {"output_redirection": "deny"})
        assert result["status"] == "allow"
        assert result["matched"] is False

    @pytest.mark.parametrize(
        ("policy", "expected"),
        [("allow", "allow"), ("ask", "ask"), ("deny", "deny")],
    )
    def test_level_comes_from_policy(self, policy: str, expected: str) -> None:
        """A plain string policy maps straight onto the returned status."""
        segs = [segment(redir(">", "/tmp/out.txt"))]
        result = check_output_redirections(segs, {"output_redirection": policy})
        assert result["status"] == expected

    def test_allow_reason_names_the_target(self) -> None:
        """The allow reason names the redirection target."""
        segs = [segment(redir(">", "/tmp/out.txt"))]
        result = check_output_redirections(segs, {"output_redirection": "allow"})
        assert "/tmp/out.txt" in result["reason"]

    def test_deny_reason_names_the_target(self) -> None:
        """The deny reason names the redirection target."""
        segs = [segment(redir(">", "/tmp/out.txt"))]
        result = check_output_redirections(segs, {"output_redirection": "deny"})
        assert "/tmp/out.txt" in result["reason"]

    def test_ask_reason_asks_for_approval(self) -> None:
        """The ask reason says the redirection requires approval."""
        segs = [segment(redir(">", "/tmp/out.txt"))]
        result = check_output_redirections(segs, {"output_redirection": "ask"})
        assert "approval" in result["reason"]

    def test_default_policy_is_ask(self) -> None:
        """A rules dict with no ``output_redirection`` key defaults to ask."""
        segs = [segment(redir(">", "/tmp/out.txt"))]
        assert check_output_redirections(segs, {})["status"] == "ask"

    def test_dict_form_wildcard(self) -> None:
        """The dict policy form uses ``*`` for kinds it does not name."""
        segs = [segment(redir(">", "/tmp/out.txt"))]
        rules = {"output_redirection": {"*": "deny"}}
        assert check_output_redirections(segs, rules)["status"] == "deny"

    @pytest.mark.parametrize(
        ("command", "kind"),
        [
            ("echo hi > /dev/null", "stdout_to_dev_null"),
            ("echo hi 2> /dev/null", "stderr_to_dev_null"),
            ("echo hi 2>&1", "stderr_to_stdout"),
        ],
    )
    def test_dict_form_per_kind_allow(self, command: str, kind: str) -> None:
        """Naming the triggered kind allows it while ``*`` still asks."""
        rules = {"output_redirection": {"*": "ask", kind: "allow"}}
        result = check_output_redirections(parse_segments(command), rules)
        assert result["status"] == "allow"

    def test_dict_form_per_kind_deny(self) -> None:
        """Naming the triggered kind denies it even when ``*`` allows."""
        rules = {"output_redirection": {"*": "allow", "stderr_to_dev_null": "deny"}}
        result = check_output_redirections(parse_segments("echo hi 2> /dev/null"), rules)
        assert result["status"] == "deny"

    def test_dict_form_two_kinds_deny_overrides_allow(self) -> None:
        """Two redirections of different kinds resolve to the strictest."""
        rules = {
            "output_redirection": {
                "*": "allow",
                "stdout_to_dev_null": "deny",
                "stderr_to_stdout": "allow",
            }
        }
        result = check_output_redirections(parse_segments("echo hi > /dev/null 2>&1"), rules)
        assert result["status"] == "deny"

    def test_dict_form_ask_and_allow_resolves_ask(self) -> None:
        """ask on one kind plus allow on another still resolves to ask."""
        rules = {
            "output_redirection": {
                "*": "allow",
                "stdout_to_dev_null": "allow",
                "stderr_to_stdout": "ask",
            }
        }
        result = check_output_redirections(parse_segments("echo hi > /dev/null 2>&1"), rules)
        assert result["status"] == "ask"

    def test_dict_form_all_allow_resolves_allow(self) -> None:
        """A wildcard-only allow policy lets every kind through."""
        segs = parse_segments("echo hi > /dev/null 2>&1")
        assert check_output_redirections(segs, {"output_redirection": {"*": "allow"}})["status"] == "allow"


class TestSegmentsOutputRedirsBlockedPaths:
    """blocked_cmds_regex escalates a redirect target to deny at any level."""

    @pytest.mark.parametrize("policy", ["allow", "ask", "deny"])
    def test_blocked_target_denies_even_under_allow(self, policy: str) -> None:
        """SECURITY: a blocked target denies even when the level is allow."""
        segs = [segment(redir(">", "/etc/shadow"))]
        rules: dict[str, Any] = {"output_redirection": policy, "blocked_cmds_regex": [r"\/etc"]}
        result = check_output_redirections(segs, rules)
        assert result["status"] == "deny"
        assert "/etc/shadow" in result["reason"]

    def test_blocked_target_beats_dict_kind_allow(self) -> None:
        """SECURITY: a per-kind allow does not override a blocked target."""
        segs = [segment(redir(">", "/etc/shadow"))]
        rules = {
            "output_redirection": {"*": "allow", "other": "allow"},
            "blocked_cmds_regex": [r"\/etc"],
        }
        assert check_output_redirections(segs, rules)["status"] == "deny"

    def test_unblocked_target_is_not_escalated(self) -> None:
        """A non-matching target still follows its level."""
        segs = [segment(redir(">", "/tmp/out.txt"))]
        rules = {"output_redirection": "allow", "blocked_cmds_regex": [r"\/etc"]}
        assert check_output_redirections(segs, rules)["status"] == "allow"

    def test_quote_split_blocked_target_denies(self) -> None:
        """The executed-form target is matched, not just the literal spelling."""
        result = check_output_redirections(
            parse_segments('echo hi > /e"tc"/x'),
            {"output_redirection": "allow", "blocked_cmds_regex": [r"\/etc"]},
        )
        assert result["status"] == "deny"

    def test_blocked_target_among_several_denies(self) -> None:
        """One blocked target anywhere in the set denies the whole command."""
        segs = [segment(redir(">", "/tmp/out.txt")), segment(redir(">", "/etc/shadow"), command="tee")]
        rules = {"output_redirection": "allow", "blocked_cmds_regex": [r"\/etc"]}
        assert check_output_redirections(segs, rules)["status"] == "deny"

    def test_invalid_blocked_pattern_is_skipped_not_raised(self) -> None:
        """A malformed blocked regex is "no match" rather than a ValueError."""
        segs = [segment(redir(">", "/tmp/out.txt"))]
        rules = {"output_redirection": "allow", "blocked_cmds_regex": ["[invalid"]}
        assert check_output_redirections(segs, rules)["status"] == "allow"


class TestSegmentsOutputRedirsDedupe:
    """Compound-command redirections are attributed to every inner segment."""

    def test_same_redirection_across_segments_counted_once(self) -> None:
        """The same (Op, fd, target) on three segments is one redirection."""
        target = "/tmp/dedupe-target"
        segs = [segment(redir(">", target)), segment(redir(">", target)), segment(redir(">", target))]
        result = check_output_redirections(segs, {"output_redirection": "allow"})
        assert result["status"] == "allow"
        assert result["reason"].count(target) == 1

    def test_brace_block_redirection_counted_once(self) -> None:
        """`{ a; b; } > out` attributes the block redirect to both inner segments."""
        target = "/tmp/brace-target"
        segs = parse_segments("{ echo a; echo b; } > " + target)
        assert len(segs) == 2
        result = check_output_redirections(segs, {"output_redirection": "allow"})
        assert result["reason"].count(target) == 1

    def test_distinct_fds_are_kept_separate(self) -> None:
        """Same op and target but a different fd is a distinct descriptor."""
        segs = [segment(redir(">", "/tmp/o")), segment(redir(">", "/tmp/o", "2"), command="tee")]
        result = check_output_redirections(segs, {"output_redirection": "allow"})
        assert result["reason"].count("/tmp/o") == 2

    def test_distinct_targets_are_kept_separate(self) -> None:
        """Different targets on different segments are both reported."""
        segs = [segment(redir(">", "/tmp/a")), segment(redir(">", "/tmp/b"), command="tee")]
        result = check_output_redirections(segs, {"output_redirection": "allow"})
        assert "/tmp/a" in result["reason"]
        assert "/tmp/b" in result["reason"]

    def test_distinct_ops_are_kept_separate(self) -> None:
        """Same target under different ops stays two redirections."""
        segs = [segment(redir(">", "/tmp/o")), segment(redir(">>", "/tmp/o"), command="tee")]
        result = check_output_redirections(segs, {"output_redirection": "allow"})
        assert result["reason"].count("/tmp/o") == 2


# ---------------------------------------------------------------------------
# check_input_redirections
# ---------------------------------------------------------------------------


class TestSegmentsInputRedirs:
    """check_input_redirections evaluates segment input redirections."""

    def test_no_redirections_is_unmatched_allow(self) -> None:
        """Nothing to evaluate reports matched=False even under a deny policy."""
        result = check_input_redirections([segment()], {"input_redirection": "deny"})
        assert result["status"] == "allow"
        assert result["matched"] is False
        assert result["reason"] == "no input redirection"

    def test_empty_segment_list_is_unmatched_allow(self) -> None:
        """An empty segment list is the same as "no redirections"."""
        result = check_input_redirections([], {"input_redirection": "deny"})
        assert result["status"] == "allow"
        assert result["matched"] is False

    def test_output_only_redirections_are_not_input(self) -> None:
        """A write operator is invisible to the input-redirection policy."""
        segs = [segment(redir(">", "/tmp/out.txt"))]
        result = check_input_redirections(segs, {"input_redirection": "deny"})
        assert result["status"] == "allow"
        assert result["matched"] is False

    @pytest.mark.parametrize(
        ("policy", "expected"),
        [("allow", "allow"), ("ask", "ask"), ("deny", "deny")],
    )
    def test_level_comes_from_policy(self, policy: str, expected: str) -> None:
        """A plain string policy maps straight onto the returned status."""
        segs = [segment(redir("<", "/tmp/in.txt"), command="cat")]
        result = check_input_redirections(segs, {"input_redirection": policy})
        assert result["status"] == expected

    def test_allow_reason_names_the_target(self) -> None:
        """The allow reason names the redirection target."""
        segs = [segment(redir("<", "/tmp/in.txt"), command="cat")]
        result = check_input_redirections(segs, {"input_redirection": "allow"})
        assert "/tmp/in.txt" in result["reason"]

    def test_deny_reason_names_the_target(self) -> None:
        """The deny reason names the redirection target."""
        segs = [segment(redir("<", "/tmp/in.txt"), command="cat")]
        result = check_input_redirections(segs, {"input_redirection": "deny"})
        assert "/tmp/in.txt" in result["reason"]

    def test_ask_reason_asks_for_approval(self) -> None:
        """The ask reason says the redirection requires approval."""
        segs = [segment(redir("<", "/tmp/in.txt"), command="cat")]
        result = check_input_redirections(segs, {"input_redirection": "ask"})
        assert "approval" in result["reason"]

    def test_default_policy_is_ask(self) -> None:
        """A rules dict with no ``input_redirection`` key defaults to ask."""
        segs = [segment(redir("<", "/tmp/in.txt"), command="cat")]
        assert check_input_redirections(segs, {})["status"] == "ask"

    def test_empty_rules_default_to_ask(self) -> None:
        """An empty rules dict is treated as an ask policy."""
        segs = [segment(redir("<", "/tmp/in.txt"), command="cat")]
        assert check_input_redirections(segs, {})["status"] == "ask"

    def test_dict_form_wildcard(self) -> None:
        """The dict policy form resolves through the ``*`` key."""
        segs = [segment(redir("<", "/tmp/in.txt"), command="cat")]
        rules: dict[str, Any] = {"input_redirection": {"*": "deny"}}
        assert check_input_redirections(segs, rules)["status"] == "deny"

    def test_dict_form_named_kinds_do_not_apply(self) -> None:
        """Input redirection resolves on ``*`` only; other kind keys are inert."""
        segs = [segment(redir("<", "/tmp/in.txt"), command="cat")]
        rules = {"input_redirection": {"*": "ask", "stderr_to_dev_null": "deny"}}
        assert check_input_redirections(segs, rules)["status"] == "ask"

    def test_dict_form_defaults_to_ask(self) -> None:
        """A dict policy with no ``*`` key falls back to ask."""
        segs = [segment(redir("<", "/tmp/in.txt"), command="cat")]
        rules = {"input_redirection": {"stdout_to_dev_null": "allow"}}
        assert check_input_redirections(segs, rules)["status"] == "ask"

    @pytest.mark.parametrize(
        ("command", "expected_target"),
        [
            ("cat < /tmp/in.txt", "/tmp/in.txt"),
            ("cat << EOF\nhello\nEOF", "EOF"),
            ("echo hello <<< world", "world"),
            ("cat <&2", "2"),
        ],
    )
    def test_all_input_ops_are_evaluated(self, command: str, expected_target: str) -> None:
        """`<`, `<<`, `<<<` and `<&` are all input redirections."""
        rules = {"input_redirection": "deny"}
        result = check_input_redirections(parse_segments(command), rules)
        assert result["status"] == "deny"
        assert expected_target in result["reason"]

    def test_strip_tabs_heredoc_is_gated_as_input(self) -> None:
        """`<<-` is gated by the input policy, exactly as `<<` is.

        The tab-stripping here-document feeds the command's stdin just as `<<`
        does, so it must not be able to read an arbitrary file with no policy
        consulted.
        """
        segs = parse_segments("cat <<- EOF\n\thello\nEOF")
        assert segs[0]["redirections"][0]["Op"] == "<<-"
        result = check_input_redirections(segs, {"input_redirection": "deny"})
        assert result["status"] == "deny"

    def test_every_emitted_redirection_op_is_classified(self) -> None:
        """The write and input op sets between them cover every operator.

        An operator in neither set would bypass both redirection policies, so
        this guards the two sets against a newly-supported operator slipping
        through unclassified.
        """
        emitted = {">", ">>", ">|", "&>", ">&", "&>>", "<>", "<", "<<", "<<-", "<<<", "<&"}
        assert emitted - (WRITE_REDIRECT_OPS | INPUT_REDIRECT_OPS) == set()

    def test_input_and_output_policies_are_independent(self) -> None:
        """The two segment checks answer independently for the same segments."""
        segs = [segment(redir("<", "/tmp/in.txt"), redir(">", "/tmp/out.txt"), command="cat")]
        rules: dict[str, Any] = {"input_redirection": "allow", "output_redirection": "deny"}
        assert check_input_redirections(segs, rules)["status"] == "allow"
        assert check_output_redirections(segs, rules)["status"] == "deny"


class TestSegmentsInputRedirsBlockedPaths:
    """blocked_cmds_regex escalates an input redirect target to deny."""

    @pytest.mark.parametrize("policy", ["allow", "ask", "deny"])
    def test_blocked_target_denies_even_under_allow(self, policy: str) -> None:
        """SECURITY: a blocked target denies even when the level is allow."""
        segs = [segment(redir("<", "/etc/shadow"), command="cat")]
        rules: dict[str, Any] = {"input_redirection": policy, "blocked_cmds_regex": [r"\/etc"]}
        result = check_input_redirections(segs, rules)
        assert result["status"] == "deny"
        assert "/etc/shadow" in result["reason"]

    def test_blocked_target_beats_dict_wildcard_allow(self) -> None:
        """SECURITY: a wildcard allow does not override a blocked target."""
        segs = [segment(redir("<<<", "/etc/shadow"), command="cat")]
        rules = {"input_redirection": {"*": "allow"}, "blocked_cmds_regex": [r"\/etc"]}
        assert check_input_redirections(segs, rules)["status"] == "deny"

    def test_unblocked_target_is_not_escalated(self) -> None:
        """A non-matching target still follows its level."""
        segs = [segment(redir("<", "/tmp/in.txt"), command="cat")]
        rules = {"input_redirection": "allow", "blocked_cmds_regex": [r"\/etc"]}
        assert check_input_redirections(segs, rules)["status"] == "allow"

    def test_quote_split_blocked_target_denies(self) -> None:
        """The executed-form target is matched, not just the literal spelling."""
        result = check_input_redirections(
            parse_segments('cat <<< /e"tc"/shadow'),
            {"input_redirection": "allow", "blocked_cmds_regex": [r"\/etc"]},
        )
        assert result["status"] == "deny"

    def test_blocked_target_among_several_denies(self) -> None:
        """One blocked target anywhere in the set denies the whole command."""
        segs = [segment(redir("<", "/tmp/in.txt"), command="cat"), segment(redir("<<<", "/etc/shadow"))]
        rules = {"input_redirection": "allow", "blocked_cmds_regex": [r"\/etc"]}
        assert check_input_redirections(segs, rules)["status"] == "deny"

    def test_invalid_blocked_pattern_is_skipped_not_raised(self) -> None:
        """A malformed blocked regex is "no match" rather than a ValueError."""
        segs = [segment(redir("<", "/tmp/in.txt"), command="cat")]
        rules = {"input_redirection": "allow", "blocked_cmds_regex": ["[invalid"]}
        assert check_input_redirections(segs, rules)["status"] == "allow"


class TestSegmentsInputRedirsDedupe:
    """Input redirections are deduped by (op, target)."""

    def test_same_redirection_across_segments_counted_once(self) -> None:
        """The same (op, target) on three segments is one redirection."""
        target = "/tmp/dedupe-input"
        segs = [segment(redir("<", target), command="cat") for _ in range(3)]
        result = check_input_redirections(segs, {"input_redirection": "allow"})
        assert result["status"] == "allow"
        assert result["reason"].count(target) == 1

    def test_brace_block_redirection_counted_once(self) -> None:
        """A block-level `< in` is attributed to every inner segment, once."""
        target = "/tmp/brace-input"
        segs = parse_segments("{ cat a; cat b; } < " + target)
        assert len(segs) == 2
        result = check_input_redirections(segs, {"input_redirection": "allow"})
        assert result["reason"].count(target) == 1

    def test_distinct_targets_are_kept_separate(self) -> None:
        """Different targets are both reported."""
        segs = [segment(redir("<", "/tmp/a"), command="cat"), segment(redir("<", "/tmp/b"), command="cat")]
        result = check_input_redirections(segs, {"input_redirection": "allow"})
        assert "/tmp/a" in result["reason"]
        assert "/tmp/b" in result["reason"]

    def test_same_target_distinct_ops_are_kept_separate(self) -> None:
        """The dedupe key includes the op, so `<` and `<<<` stay separate."""
        segs = [segment(redir("<", "/tmp/o"), command="cat"), segment(redir("<<<", "/tmp/o"), command="echo")]
        result = check_input_redirections(segs, {"input_redirection": "allow"})
        assert result["reason"].count("/tmp/o") == 2


# ---------------------------------------------------------------------------
# check_background_execution (raw shfmt tree)
# ---------------------------------------------------------------------------


class TestBackgroundExecution:
    """check_background_execution walks the raw shfmt JSON tree."""

    def test_no_background_is_unmatched_allow(self) -> None:
        """Nothing backgrounded reports matched=False even under a deny policy."""
        result = check_background_execution(parse("ls -la"), {"background_execution": "deny"})
        assert result["status"] == "allow"
        assert result["matched"] is False
        assert result["reason"] == "no background execution"

    def test_and_chaining_is_not_background(self) -> None:
        """`&&` is chaining, not a trailing `&`."""
        result = check_background_execution(parse("ls && grep pattern"), {"background_execution": "deny"})
        assert result["status"] == "allow"
        assert result["matched"] is False

    def test_pipeline_without_ampersand_is_not_background(self) -> None:
        """A plain pipe has no background flag anywhere."""
        result = check_background_execution(parse("ls | grep bla"), {"background_execution": "deny"})
        assert result["status"] == "allow"
        assert result["matched"] is False

    @pytest.mark.parametrize(
        ("policy", "expected"),
        [("allow", "allow"), ("ask", "ask"), ("deny", "deny")],
    )
    def test_level_comes_from_policy(self, policy: str, expected: str) -> None:
        """A plain string policy maps straight onto the returned status."""
        result = check_background_execution(parse("sleep 5 &"), {"background_execution": policy})
        assert result["status"] == expected

    def test_default_policy_is_ask(self) -> None:
        """A rules dict with no ``background_execution`` key defaults to ask."""
        assert check_background_execution(parse("sleep 5 &"), {})["status"] == "ask"

    def test_dict_form_wildcard(self) -> None:
        """The dict policy form resolves through the ``*`` key."""
        rules = {"background_execution": {"*": "deny"}}
        assert check_background_execution(parse("sleep 5 &"), rules)["status"] == "deny"

    def test_dict_form_named_kinds_do_not_apply(self) -> None:
        """Background execution resolves on ``*`` only; other keys are inert."""
        rules = {"background_execution": {"*": "ask", "subshell": "deny"}}
        assert check_background_execution(parse("sleep 5 &"), rules)["status"] == "ask"

    def test_dict_form_defaults_to_ask(self) -> None:
        """A dict policy with no ``*`` key falls back to ask."""
        rules = {"background_execution": {"coproc": "deny"}}
        assert check_background_execution(parse("sleep 5 &"), rules)["status"] == "ask"

    @pytest.mark.parametrize("command", ["sleep 5 &", "( echo hi ) &", "{ echo hi; } &"])
    def test_reason_names_the_background_command(self, command: str) -> None:
        """The reason reports the command that was backgrounded."""
        result = check_background_execution(parse(command), {"background_execution": "deny"})
        assert result["status"] == "deny"
        assert "echo" in result["reason"] or "sleep" in result["reason"]

    def test_multiple_background_commands_are_reported(self) -> None:
        """Each backgrounded command name appears in the reason."""
        result = check_background_execution(parse("sleep 5 & bg_task &"), {"background_execution": "ask"})
        assert result["status"] == "ask"
        assert "sleep" in result["reason"]
        assert "bg_task" in result["reason"]

    def test_duplicate_command_names_are_deduped(self) -> None:
        """The same backgrounded name twice is reported once."""
        result = check_background_execution(parse("sleep 5 & sleep 5 &"), {"background_execution": "deny"})
        assert result["reason"].count("sleep") == 1


class TestBackgroundExecutionNesting:
    """A background flag is found wherever it hides in the tree."""

    @pytest.mark.parametrize("command", ["( echo hi & )", "x=$(echo hi &)"])
    def test_nested_background_is_detected(self, command: str) -> None:
        """An inner `&` is background execution even when the outer stmt is not."""
        result = check_background_execution(parse(command), {"background_execution": "deny"})
        assert result["status"] == "deny"
        assert "echo" in result["reason"]

    @pytest.mark.parametrize("command", ["( echo hi & )", "x=$(echo hi &)"])
    def test_nested_background_allow(self, command: str) -> None:
        """The nested case honours an allow policy like any other."""
        result = check_background_execution(parse(command), {"background_execution": "allow"})
        assert result["status"] == "allow"
        assert "echo" in result["reason"]

    @pytest.mark.parametrize(
        "command",
        [
            "coproc myproc { echo hi; }",
            "coproc { echo hi; }",
            "coproc echo hi",
        ],
    )
    def test_coproc_is_background_execution(self, command: str) -> None:
        """Named, anonymous and single-command coprocs are all backgrounded."""
        result = check_background_execution(parse(command), {"background_execution": "deny"})
        assert result["status"] == "deny"
        assert "echo" in result["reason"]

    @pytest.mark.parametrize(
        "command",
        [
            "if true; then echo hi; fi &",
            "for x in 1 2; do echo $x; done &",
            "while true; do echo hi; done &",
        ],
    )
    def test_compound_clause_with_trailing_ampersand(self, command: str) -> None:
        """A compound command with a trailing `&` is background execution."""
        result = check_background_execution(parse(command), {"background_execution": "ask"})
        assert result["status"] == "ask"
        assert "echo" in result["reason"]

    def test_backgrounded_pipeline_reports_every_side(self) -> None:
        """Both sides of a backgrounded pipeline are reported."""
        result = check_background_execution(parse("ls | grep bla &"), {"background_execution": "deny"})
        assert result["status"] == "deny"
        assert "ls" in result["reason"]
        assert "grep" in result["reason"]

    def test_redirection_only_statement_is_not_background(self) -> None:
        """A bare redirection carries no background flag."""
        result = check_background_execution(parse("> /tmp/out.txt"), {"background_execution": "deny"})
        assert result["status"] == "allow"
        assert result["matched"] is False
