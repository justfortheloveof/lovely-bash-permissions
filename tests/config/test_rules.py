"""Tests for permission rules engine."""

from typing import cast

import pytest

from lovely_bash_permissions.converter import node_from_json
from lovely_bash_permissions.evaluate import (
    _match_allowed_patterns,
    _match_blocked_patterns,
    _match_texts,
    _texts_for,
    evaluate_bash_command,
)
from lovely_bash_permissions.parser import parse
from lovely_bash_permissions.rules import (
    _compile_pattern,
    _redir_target,
    check_background_execution,
)
from lovely_bash_permissions.segments import SegmentRedirection, _segments_from_ast, parse_segments

# Tests for _compile_pattern


def test_compile_pattern_caches() -> None:
    """Same pattern compiled twice returns the same cached object."""
    p1 = _compile_pattern("^hello$")
    p2 = _compile_pattern("^hello$")
    assert p1 is p2


def test_compile_pattern_invalid_raises() -> None:
    """Invalid regex pattern raises ValueError with descriptive message."""
    with pytest.raises(ValueError):
        _compile_pattern("[invalid")


def test_compile_pattern_invalid_raises_message() -> None:
    """Invalid regex pattern ValueError message includes pattern and error."""

    exc = pytest.raises(ValueError, lambda: _compile_pattern("[invalid"))
    assert "invalid pattern" in str(exc.value)


# Tests for _match_blocked_patterns (joined-line semantics)


def test_blocked_single_arg_matches() -> None:
    """Single argument matches a blocked pattern."""
    matched, _, value = _match_blocked_patterns("cmd", ["/etc/passwd"], ["/etc/passwd"])
    assert matched is True
    assert value == "cmd /etc/passwd"


def test_blocked_multiple_args_one_matches() -> None:
    """Multiple arguments, one matches a blocked pattern."""
    args = ["/var/log", "/etc/passwd", "/tmp"]
    patterns = ["/etc/passwd"]
    matched, _, value = _match_blocked_patterns("cmd", args, patterns)
    assert matched is True
    assert value == "cmd /var/log /etc/passwd /tmp"


def test_blocked_multiple_args_none_match() -> None:
    """Multiple arguments, none match any blocked pattern."""
    args = ["/var/log", "/tmp", "/usr/bin"]
    patterns = ["/etc/passwd", "/root"]
    matched, _, _ = _match_blocked_patterns("cmd", args, patterns)
    assert matched is False


def test_blocked_empty_args() -> None:
    """Empty args list returns False."""
    matched, _, _ = _match_blocked_patterns("cmd", [], ["/etc/passwd"])
    assert matched is False


def test_blocked_empty_patterns() -> None:
    """Empty blocked_patterns list returns False."""
    matched, _, _ = _match_blocked_patterns("cmd", ["/etc/passwd"], [])
    assert matched is False


def test_blocked_pattern_matches_part_of_path() -> None:
    """Pattern matches part of path (not anchored)."""
    matched, _, value = _match_blocked_patterns("cmd", ["/etc/passwd.backup"], ["/etc/passwd"])
    assert matched is True
    assert value == "cmd /etc/passwd.backup"


def test_blocked_end_anchor_honored_literally() -> None:
    """End-anchored pattern does not fire mid-line on the joined command line."""
    matched, _, _ = _match_blocked_patterns("echo", ["foo.env", "bar"], [r"\.env$"])
    assert matched is False
    matched, _, value = _match_blocked_patterns("echo", ["foo.env", "bar"], [r"\.env"])
    assert matched is True
    assert value == "echo foo.env bar"


def test_blocked_norm_hit_raw_miss_reports_norm() -> None:
    """OR semantics: a hit on the executed form denies even when raw misses."""
    matched, pattern, value = _match_blocked_patterns("cat", ['/e"tc"/passwd'], [r"\/etc"], ["/etc/passwd"])
    assert (matched, pattern, value) == (True, r"\/etc", "cat /etc/passwd")


def test_blocked_raw_hit_norm_miss_reports_raw() -> None:
    """OR semantics (mirror): a raw-only hit denies with the raw joined line."""
    matched, pattern, value = _match_blocked_patterns("cat", ['/e"tc"/passwd'], [r'/e"tc"'], ["/etc/passwd"])
    assert (matched, pattern, value) == (True, r'/e"tc"', 'cat /e"tc"/passwd')


def test_blocked_both_hit_prefers_norm() -> None:
    """When both forms hit, the reported value is the normalized joined line."""
    matched, pattern, value = _match_blocked_patterns("cat", ['/e"tc"/passwd'], ["cat"], ["/etc/passwd"])
    assert (matched, pattern, value) == (True, "cat", "cat /etc/passwd")


def test_blocked_no_norm_args_uses_raw() -> None:
    """Without normalized args only the raw joined line is checked."""
    matched, _, value = _match_blocked_patterns("cat", ["/etc/passwd"], [r"\/etc"], None)
    assert matched is True
    assert value == "cat /etc/passwd"
    assert _match_blocked_patterns("cat", ["/tmp/x"], [r"\/etc"], None) == (False, None, None)


def test_blocked_first_matching_pattern_wins() -> None:
    """Patterns are tried in order; the first hit is reported."""
    args, norm = ['/e"tc"/passwd'], ["/etc/passwd"]
    assert _match_blocked_patterns("cat", args, ["cat", r"\/etc"], norm)[1] == "cat"
    assert _match_blocked_patterns("cat", args, [r"\/etc", "cat"], norm)[1] == r"\/etc"


# Tests for _texts_for (the shared candidate-text builder)


def test_texts_for_normalized_first_then_raw() -> None:
    """The executed join is the priority text; the raw join is the fallback."""
    assert _texts_for("cat", ['/e"tc"/passwd'], ["/etc/passwd"]) == ["cat /etc/passwd", 'cat /e"tc"/passwd']


def test_texts_for_dedupes_identical_forms() -> None:
    """Identical raw and normalized joins collapse to one candidate text."""
    assert _texts_for("ls", ["-la"], ["-la"]) == ["ls -la"]


def test_texts_for_no_normalized_args_is_raw_only() -> None:
    """Without normalized args the raw join is the sole candidate."""
    assert _texts_for("cat", ['/e"tc"/passwd'], None) == ['cat /e"tc"/passwd']


def test_texts_for_strips_join_space_of_nameless_segment() -> None:
    """A nameless segment is joined with a leading space; it is stripped."""
    assert _texts_for("", ["/etc/passwd"], None) == ["/etc/passwd"]
    assert _texts_for("", ["A=(...)"], ["A=(/etc/passwd)"]) == ["A=(/etc/passwd)", "A=(...)"]


# Tests for _match_texts (the shared core behind allowed_cmds_regex and
# blocked_cmds_regex - both lists differ only in the flags they pass in)


def test_core_single_text_shape() -> None:
    """A one-element text list is the plain search shape."""
    assert _match_texts(["cat /etc/passwd"], [r"\/etc"]) == [(r"\/etc", "cat /etc/passwd")]
    assert _match_texts(["cat /etc/passwd"], [r"^/etc"]) == []


def test_core_two_text_shape_prefers_first_text() -> None:
    """With two texts, the first (executed) form wins and is reported."""
    texts = ["cat /etc/passwd", 'cat /e"tc"/passwd']
    assert _match_texts(texts, ["cat"]) == [("cat", "cat /etc/passwd")]


def test_core_reports_the_text_that_hit() -> None:
    """A pattern matching only the second text reports that text."""
    texts = ["cat /etc/passwd", 'cat /e"tc"/passwd']
    assert _match_texts(texts, [r'/e"tc"']) == [(r'/e"tc"', 'cat /e"tc"/passwd')]


def test_core_is_pattern_major_not_text_major() -> None:
    """Results follow pattern order, and each pattern reports at most one hit."""
    assert _match_texts(["ab", "ab"], ["b", "a"]) == [("b", "ab"), ("a", "ab")]


def test_core_raw_fallback_always_uses_second_text() -> None:
    """`raw_fallback="always"`: both texts are tried, even for a guard pattern."""
    texts = ["find /tmp -exec rm", 'find /tmp -"exec" rm']
    assert _match_texts(texts, [r"^find(?!.*\s-exec).*$"], raw_fallback="always") == [
        (r"^find(?!.*\s-exec).*$", 'find /tmp -"exec" rm')
    ]


def test_core_raw_fallback_only_if_no_lookahead_skips_raw_for_guards() -> None:
    """A `(?!` pattern never sees the raw form, so a quoted flag cannot fake it."""
    texts = ["find /tmp -exec rm", 'find /tmp -"exec" rm']
    assert _match_texts(texts, [r"^find(?!.*\s-exec).*$"], raw_fallback="only-if-no-lookahead") == []


def test_core_raw_fallback_only_if_no_lookahead_honors_plain_patterns() -> None:
    """A pattern with no guard still gets its raw-form fallback."""
    texts = ["cat /etc/passwd", 'cat /e"tc"/passwd']
    assert _match_texts(texts, [r'/e"tc"'], raw_fallback="only-if-no-lookahead") == [(r'/e"tc"', 'cat /e"tc"/passwd')]


def test_core_opaque_guard_drops_bare_name_anchor_match() -> None:
    """`opaque_guard` + `has_opaque`: `^true$` cannot approve a `$(...)` command."""
    assert _match_texts(["true"], ["^true$"], opaque_guard=True, has_opaque=True) == []
    assert _match_texts(["true"], ["^true$"], opaque_guard=True, has_opaque=False) == [("^true$", "true")]


def test_core_opaque_guard_drops_lookahead_match() -> None:
    """The guard also drops a line-spanning-lookahead match under `$(...)`."""
    pattern = r"^find(?!.*\s-(exec|delete|ok)\b).*$"
    assert _match_texts(["find . -name x"], [pattern], opaque_guard=True, has_opaque=True) == []


def test_core_opaque_guard_off_by_default() -> None:
    """`has_opaque` alone never suppresses a match; the guard flag is required."""
    assert _match_texts(["true"], ["^true$"], has_opaque=True) == [("^true$", "true")]


def test_core_opaque_guard_keeps_free_tail_patterns() -> None:
    """A pattern that accepts arbitrary arguments survives the opaque guard."""
    pattern = r"^echo(\s+.*)?$"
    assert _match_texts(["echo hi"], [pattern], opaque_guard=True, has_opaque=True) == [(pattern, "echo hi")]


def test_core_invalid_pattern_is_skipped_not_raised() -> None:
    """A bad regex is treated as "no match"; later patterns still run."""
    assert _match_texts(["cat /etc"], ["[invalid", r"\/etc"]) == [(r"\/etc", "cat /etc")]


def test_core_no_texts_returns_no_matches() -> None:
    """An empty text list can never match."""
    assert _match_texts([], ["^cat"]) == []


def test_core_no_patterns_returns_no_matches() -> None:
    """An empty pattern list returns nothing."""
    assert _match_texts(["cat /etc"], []) == []


def test_allowed_invalid_pattern_skipped_does_not_raise() -> None:
    """An invalid allowed regex is "no match" rather than a re.error."""
    assert _match_allowed_patterns("cat", ["/etc/passwd"], ["[invalid"]) == []
    assert _match_allowed_patterns("cat", ["/etc/passwd"], ["[invalid", "^cat"]) == ["^cat"]


def test_blocked_invalid_pattern_skipped_does_not_raise() -> None:
    """An invalid blocked regex is "no match" rather than a ValueError."""
    assert _match_blocked_patterns("cat", ["/etc/passwd"], ["[invalid"]) == (False, None, None)
    assert _match_blocked_patterns("cat", ["/etc/passwd"], ["[invalid", r"\/etc"])[1] == r"\/etc"


def test_both_wrappers_share_the_core_shape() -> None:
    """Both public wrappers are thin views over the same pattern-major core."""
    texts = ["cat /etc/passwd", 'cat /e"tc"/passwd']
    assert _match_texts(texts, [r"\/etc", r'/e"tc"']) == [
        (r"\/etc", "cat /etc/passwd"),
        (r'/e"tc"', 'cat /e"tc"/passwd'),
    ]
    # allowed reports every match; blocked reports only the first.
    assert _match_allowed_patterns("cat", ['/e"tc"/passwd'], [r"\/etc", r'/e"tc"'], ["/etc/passwd"]) == [
        r"\/etc",
        r'/e"tc"',
    ]
    assert _match_blocked_patterns("cat", ['/e"tc"/passwd'], [r"\/etc", r'/e"tc"'], ["/etc/passwd"]) == (
        True,
        r"\/etc",
        "cat /etc/passwd",
    )


# Tests for check_background_execution


def test_no_background_execution_allowed() -> None:
    """Command with no background execution is allowed regardless of rules."""
    tree = parse("ls -la")
    result = check_background_execution(tree, {"background_execution": "deny"})
    assert result["status"] == "allow"
    assert result["reason"] == "no background execution"


def test_allowed_background_execution_simple() -> None:
    """Simple background execution is allowed when policy is allow."""
    tree = parse("sleep 5 &")
    result = check_background_execution(tree, {"background_execution": "allow"})
    assert result["status"] == "allow"
    assert "sleep" in result["reason"]


def test_denied_background_execution_simple() -> None:
    """Simple background execution is denied when policy is deny."""
    tree = parse("sleep 5 &")
    result = check_background_execution(tree, {"background_execution": "deny"})
    assert result["status"] == "deny"
    assert "sleep" in result["reason"]


def test_ask_background_execution() -> None:
    """Background execution triggers ask when policy is ask."""
    tree = parse("sleep 5 &")
    result = check_background_execution(tree, {"background_execution": "ask"})
    assert result["status"] == "ask"
    assert "sleep" in result["reason"]


def test_background_execution_distinct_from_and_chaining() -> None:
    """Background execution (&) is distinct from and-chaining (&&)."""
    # && chaining is not background execution
    tree = parse("ls && grep pattern")
    result = check_background_execution(tree, {"background_execution": "deny"})
    assert result["status"] == "allow"
    assert result["reason"] == "no background execution"


def test_multiple_background_execution_allowed() -> None:
    """Multiple background executions are allowed when policy is allow."""
    tree = parse("sleep 5 & bg_task &")
    result = check_background_execution(tree, {"background_execution": "allow"})
    assert result["status"] == "allow"
    assert "sleep" in result["reason"]
    assert "bg_task" in result["reason"]


def test_multiple_background_execution_denied() -> None:
    """Multiple background executions are denied when policy is deny."""
    tree = parse("sleep 5 & bg_task &")
    result = check_background_execution(tree, {"background_execution": "deny"})
    assert result["status"] == "deny"
    assert "sleep" in result["reason"]
    assert "bg_task" in result["reason"]


def test_default_background_policy_is_ask() -> None:
    """When rules dict has no background_execution key, default is ask."""
    tree = parse("sleep 5 &")
    result = check_background_execution(tree, {})
    assert result["status"] == "ask"


def test_object_form_background_policy_wildcard() -> None:
    """Object form policy uses wildcard level for background execution."""
    tree = parse("sleep 5 &")
    rules = {"background_execution": {"*": "deny"}}
    result = check_background_execution(tree, rules)
    assert result["status"] == "deny"


def test_coproc_named_background_denied() -> None:
    """named coproc block is background execution."""
    tree = parse("coproc myproc { echo hi; }")
    result = check_background_execution(tree, {"background_execution": "deny"})
    assert result["status"] == "deny"
    assert "echo" in result["reason"]


def test_coproc_anonymous_background_denied() -> None:
    """anonymous coproc block is background execution."""
    tree = parse("coproc { echo hi; }")
    result = check_background_execution(tree, {"background_execution": "deny"})
    assert result["status"] == "deny"
    assert "echo" in result["reason"]


def test_coproc_single_command_background_denied() -> None:
    """single-command coproc form is background execution."""
    tree = parse("coproc echo hi")
    result = check_background_execution(tree, {"background_execution": "deny"})
    assert result["status"] == "deny"
    assert "echo" in result["reason"]


def test_coproc_background_ask() -> None:
    """coproc triggers ask when policy is ask."""
    tree = parse("coproc myproc { echo hi; }")
    result = check_background_execution(tree, {"background_execution": "ask"})
    assert result["status"] == "ask"
    assert "echo" in result["reason"]


def test_coproc_background_allowed() -> None:
    """coproc is allowed when policy is allow."""
    tree = parse("coproc myproc { echo hi; }")
    result = check_background_execution(tree, {"background_execution": "allow"})
    assert result["status"] == "allow"
    assert "echo" in result["reason"]


def test_coproc_background_default_ask() -> None:
    """default background policy is ask for coproc."""
    tree = parse("coproc myproc { echo hi; }")
    result = check_background_execution(tree, {})
    assert result["status"] == "ask"


def test_block_background_denied() -> None:
    """Compound block with trailing & is background execution."""
    tree = parse("{ echo hi; } &")
    result = check_background_execution(tree, {"background_execution": "deny"})
    assert result["status"] == "deny"
    assert "echo" in result["reason"]


def test_subshell_background_denied() -> None:
    """Subshell with trailing & is background execution."""
    tree = parse("( echo hi ) &")
    result = check_background_execution(tree, {"background_execution": "deny"})
    assert result["status"] == "deny"
    assert "echo" in result["reason"]


def test_if_clause_background_denied() -> None:
    """If-clause with trailing & is background execution."""
    tree = parse("if true; then echo hi; fi &")
    result = check_background_execution(tree, {"background_execution": "deny"})
    assert result["status"] == "deny"
    assert "echo" in result["reason"]


def test_for_clause_background_denied() -> None:
    """For-loop with trailing & is background execution."""
    tree = parse("for x in 1 2; do echo $x; done &")
    result = check_background_execution(tree, {"background_execution": "deny"})
    assert result["status"] == "deny"
    assert "echo" in result["reason"]


def test_while_clause_background_denied() -> None:
    """While-loop with trailing & is background execution."""
    tree = parse("while true; do echo hi; done &")
    result = check_background_execution(tree, {"background_execution": "deny"})
    assert result["status"] == "deny"
    assert "echo" in result["reason"]


# Tests for pipe redirections (BinaryCmd traversal)


def test_pipe_background_execution_ask() -> None:
    """Background execution inside a pipe triggers ask."""
    tree = parse("ls | grep bla &")
    result = check_background_execution(tree, {"background_execution": "ask"})
    assert result["status"] == "ask"
    assert "ls" in result["reason"]
    assert "grep" in result["reason"]


def test_pipe_background_execution_deny() -> None:
    """Background execution inside a pipe is denied."""
    tree = parse("ls | grep bla &")
    result = check_background_execution(tree, {"background_execution": "deny"})
    assert result["status"] == "deny"


def test_no_pipe_background_execution() -> None:
    """Pipe without & is not background execution."""
    tree = parse("ls | grep bla")
    result = check_background_execution(tree, {"background_execution": "deny"})
    assert result["status"] == "allow"
    assert result["reason"] == "no background execution"


def test_pipe_chain_with_background() -> None:
    """Multi-segment pipe with background flag."""
    tree = parse("a > 1 | b &")
    result = check_background_execution(tree, {"background_execution": "ask"})
    assert result["status"] == "ask"
    assert "a" in result["reason"]
    assert "b" in result["reason"]


# Tests for multi-part redirection targets


def test_multipart_target_variable_in_reason() -> None:
    """Quoted-var + lit target is reported in full, not truncated to first part."""
    result = evaluate_bash_command('echo hi > "$DIR/out.txt"', {"*": "allow", "output_redirection": "allow"})
    assert result["status"] == "allow"
    assert "$DIR/out.txt" in result["reason"]


def test_multipart_target_consecutive_quoted() -> None:
    """Two adjacent quoted parts are joined into one target."""
    result = evaluate_bash_command('echo hi > "a""b"', {"*": "allow", "output_redirection": "allow"})
    assert result["status"] == "allow"
    assert "ab" in result["reason"]


def test_multipart_target_dev_null_allows_kind_policy() -> None:
    """2>/dev/null spelled as two quoted parts is recognized as dev-null."""
    result = evaluate_bash_command(
        'echo hi 2>"/dev""/null"',
        {"*": "allow", "output_redirection": {"*": "ask", "stderr_to_dev_null": "allow"}},
    )
    assert result["status"] == "allow"


def test_multipart_target_blocked_path_denied() -> None:
    """Quote-split /etc path in an output redirection matches blocked_cmds_regex."""
    result = evaluate_bash_command(
        'echo hi > /e"tc"/x',
        {"*": "allow", "blocked_cmds_regex": ["\\/etc"], "output_redirection": "allow"},
    )
    assert result["status"] == "deny"


def test_multipart_input_target_blocked_path_denied() -> None:
    """Quote-split /etc path in an input redirection matches blocked_cmds_regex."""
    result = evaluate_bash_command(
        'cat <<< /e"tc"/shadow',
        {"*": "allow", "input_redirection": "allow", "blocked_cmds_regex": ["\\/etc"]},
    )
    assert result["status"] == "deny"


def test_multipart_target_cmdsubst_in_reason() -> None:
    """Command-substitution prefix target is reported as $(...)/file, not truncated."""
    result = evaluate_bash_command("echo hi > $(pwd)/out.txt", {"*": "allow", "output_redirection": "allow"})
    assert result["status"] == "allow"
    assert "$(...)/out.txt" in result["reason"]


# Tests for the typed segment boundary


def test_redir_target_reads_only_the_executed_target() -> None:
    """_redir_target takes Target verbatim, which is the executed form.

    ``Target`` is the string bash actually opens - every word part joined, with
    quotes removed and backslashes unescaped.  An earlier segment shape also
    carried a part-wise ``Word`` projection that was lossy by construction; it
    has been removed, so ``Target`` is the only spelling policy sees.
    """
    (seg,) = parse_segments('echo hi > /e"tc"/out')
    (redir,) = seg["redirections"] or []
    assert redir["Target"] == "/etc/out"
    assert _redir_target(redir) == redir["Target"]


def test_redir_target_is_empty_when_target_missing() -> None:
    """A record with no Target contributes no target rather than crashing."""
    assert _redir_target(cast("SegmentRedirection", {"Op": ">", "N": {}})) == ""


def test_segments_from_ast_matches_parse_segments() -> None:
    """Reusing an already-converted AST yields exactly parse_segments' output."""
    for command in ("ls > f", "a | b && c", "x=$(y > /etc/z)", "cat < in <<EOF\nhi\nEOF", "ls"):
        raw = parse(command)
        ast = node_from_json(raw)
        assert ast is not None
        assert _segments_from_ast(ast) == parse_segments(command)
