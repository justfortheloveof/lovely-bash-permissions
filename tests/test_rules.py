"""Tests for permission rules engine."""

from lovely_bash_permissions.parser import parse
from lovely_bash_permissions.rules import (
    check_allowed_patterns,
    check_background_execution,
    check_blocked_patterns,
    check_input_redirection,
    check_output_redirection,
)


def test_matches_first_pattern() -> None:
    """Command matches the first pattern in the list."""
    patterns = ["^ls", "^grep", "^cat"]
    assert check_allowed_patterns("ls", patterns) is True


def test_matches_last_pattern() -> None:
    """Command matches the last pattern in the list."""
    patterns = ["^ls", "^grep", "^cat"]
    assert check_allowed_patterns("cat", patterns) is True


def test_matches_none() -> None:
    """Command matches none of the patterns."""
    patterns = ["^ls", "^grep", "^cat"]
    assert check_allowed_patterns("rm", patterns) is False


def test_empty_patterns() -> None:
    """Empty patterns list returns False."""
    assert check_allowed_patterns("ls", []) is False


def test_exact_match_pattern() -> None:
    """Exact match pattern works."""
    assert check_allowed_patterns("ls", ["^ls$"]) is True
    assert check_allowed_patterns("listing", ["^ls$"]) is False


def test_wildcard_pattern() -> None:
    """Wildcard pattern matches any character."""
    assert check_allowed_patterns("ls", ["^l.*"]) is True
    assert check_allowed_patterns("ls", ["^g.*"]) is False


# Tests for check_blocked_patterns


def test_blocked_single_arg_matches() -> None:
    """Single argument matches a blocked pattern."""
    matched, _, value = check_blocked_patterns("cmd", ["/etc/passwd"], ["/etc/passwd"])
    assert matched is True
    assert value == "/etc/passwd"


def test_blocked_multiple_args_one_matches() -> None:
    """Multiple arguments, one matches a blocked pattern."""
    args = ["/var/log", "/etc/passwd", "/tmp"]
    patterns = ["/etc/passwd"]
    matched, _, value = check_blocked_patterns("cmd", args, patterns)
    assert matched is True
    assert value == "/etc/passwd"


def test_blocked_multiple_args_none_match() -> None:
    """Multiple arguments, none match any blocked pattern."""
    args = ["/var/log", "/tmp", "/usr/bin"]
    patterns = ["/etc/passwd", "/root"]
    matched, _, _ = check_blocked_patterns("cmd", args, patterns)
    assert matched is False


def test_blocked_empty_args() -> None:
    """Empty args list returns False."""
    matched, _, _ = check_blocked_patterns("cmd", [], ["/etc/passwd"])
    assert matched is False


def test_blocked_empty_patterns() -> None:
    """Empty blocked_patterns list returns False."""
    matched, _, _ = check_blocked_patterns("cmd", ["/etc/passwd"], [])
    assert matched is False


def test_blocked_pattern_matches_part_of_path() -> None:
    """Pattern matches part of path (not anchored)."""
    matched, _, value = check_blocked_patterns("cmd", ["/etc/passwd.backup"], ["/etc/passwd"])
    assert matched is True
    assert value == "/etc/passwd.backup"


# Tests for check_output_redirection


def test_no_redirection_allowed() -> None:
    """Command with no output redirection is allowed regardless of rules."""
    tree = parse("ls -la")
    result = check_output_redirection(tree, {"output_redirection": "deny"})
    assert result["status"] == "allow"
    assert result["reason"] == "no output redirection"


def test_allowed_redirection_simple() -> None:
    """Simple output redirection is allowed when policy is allow."""
    tree = parse("echo hello > /tmp/out.txt")
    result = check_output_redirection(tree, {"output_redirection": "allow"})
    assert result["status"] == "allow"
    assert "/tmp/out.txt" in result["reason"]


def test_denied_redirection_simple() -> None:
    """Simple output redirection is denied when policy is deny."""
    tree = parse("echo hello > /tmp/out.txt")
    result = check_output_redirection(tree, {"output_redirection": "deny"})
    assert result["status"] == "deny"
    assert "/tmp/out.txt" in result["reason"]


def test_ask_redirection() -> None:
    """Output redirection triggers ask when policy is ask."""
    tree = parse("echo hello > /tmp/out.txt")
    result = check_output_redirection(tree, {"output_redirection": "ask"})
    assert result["status"] == "ask"
    assert result["reason"] == "output redirection requires approval"


def test_append_redirection_allowed() -> None:
    """Append redirection (>>) is allowed when policy is allow."""
    tree = parse("echo hello >> /tmp/out.txt")
    result = check_output_redirection(tree, {"output_redirection": "allow"})
    assert result["status"] == "allow"
    assert "/tmp/out.txt" in result["reason"]


def test_append_redirection_denied() -> None:
    """Append redirection (>>) is denied when policy is deny."""
    tree = parse("echo hello >> /tmp/out.txt")
    result = check_output_redirection(tree, {"output_redirection": "deny"})
    assert result["status"] == "deny"
    assert "/tmp/out.txt" in result["reason"]


def test_mixed_rules_some_allow_some_deny() -> None:
    """Mixed redirections: allow policy lets all through, deny blocks all."""
    # With allow policy
    tree = parse("echo hello > /tmp/out.txt")
    result_allow = check_output_redirection(tree, {"output_redirection": "allow"})
    assert result_allow["status"] == "allow"

    # With deny policy
    tree2 = parse("echo hello >> /tmp/log.txt")
    result_deny = check_output_redirection(tree2, {"output_redirection": "deny"})
    assert result_deny["status"] == "deny"


def test_multiple_redirections_allowed() -> None:
    """Multiple output redirections are allowed when policy is allow."""
    tree = parse("echo hello > /tmp/out.txt 2> /tmp/err.txt")
    result = check_output_redirection(tree, {"output_redirection": "allow"})
    assert result["status"] == "allow"
    assert "/tmp/out.txt" in result["reason"]
    assert "/tmp/err.txt" in result["reason"]


def test_multiple_redirections_denied() -> None:
    """Multiple output redirections are denied when policy is deny."""
    tree = parse("echo hello > /tmp/out.txt 2> /tmp/err.txt")
    result = check_output_redirection(tree, {"output_redirection": "deny"})
    assert result["status"] == "deny"
    assert "/tmp/out.txt" in result["reason"]
    assert "/tmp/err.txt" in result["reason"]


def test_default_policy_is_allow() -> None:
    """When rules dict has no output_redirection key, default is allow."""
    tree = parse("echo hello > /tmp/out.txt")
    result = check_output_redirection(tree, {})
    assert result["status"] == "allow"


def test_object_form_policy_wildcard() -> None:
    """Object form policy uses wildcard level for basic redirections."""
    tree = parse("echo hello > /tmp/out.txt")
    rules = {"output_redirection": {"*": "deny"}}
    result = check_output_redirection(tree, rules)
    assert result["status"] == "deny"


def test_per_kind_stderr_to_dev_null_allow() -> None:
    """stderr > /dev/null uses stderr_to_dev_null kind key."""
    tree = parse("echo hi 2> /dev/null")
    rules = {"output_redirection": {"*": "ask", "stderr_to_dev_null": "allow"}}
    result = check_output_redirection(tree, rules)
    assert result["status"] == "allow"


def test_per_kind_stderr_to_stdout_allow() -> None:
    """2>&1 uses stderr_to_stdout kind key."""
    tree = parse("echo hi 2>&1")
    rules = {"output_redirection": {"*": "ask", "stderr_to_stdout": "allow"}}
    result = check_output_redirection(tree, rules)
    assert result["status"] == "allow"


def test_per_kind_stdout_to_dev_null() -> None:
    """> /dev/null uses stdout_to_dev_null kind key."""
    tree = parse("echo hi > /dev/null")
    rules = {"output_redirection": {"*": "ask", "stdout_to_dev_null": "allow"}}
    result = check_output_redirection(tree, rules)
    assert result["status"] == "allow"


def test_per_kind_deny_overrides_ask() -> None:
    """Deny overrides ask when any kind has deny."""
    tree = parse("echo hi 2> /dev/null")
    rules = {"output_redirection": {"*": "allow", "stderr_to_dev_null": "deny"}}
    result = check_output_redirection(tree, rules)
    assert result["status"] == "deny"


def test_per_kind_combined_op_two_kinds() -> None:
    """Combined op >& /dev/null triggers both stdout+stderr kinds."""
    tree = parse("echo hi >& /dev/null")
    rules = {"output_redirection": {"*": "ask", "stdout_to_dev_null": "allow", "stderr_to_dev_null": "deny"}}
    result = check_output_redirection(tree, rules)
    assert result["status"] == "deny"


def test_per_kind_other_falls_back_to_wildcard() -> None:
    """Non-special write redirections fall back to wildcard."""
    tree = parse("echo hi > /tmp/out.txt")
    rules = {"output_redirection": {"*": "ask", "stdout_to_dev_null": "allow"}}
    result = check_output_redirection(tree, rules)
    assert result["status"] == "ask"


def test_per_kind_multiple_redirs_mixed() -> None:
    """Multiple redirections: wildcard ask, specific kinds allow -> any-asks returns ask."""
    tree = parse("echo hi > /tmp/out.txt 2> /dev/null")
    rules = {"output_redirection": {"*": "ask", "stdout_to_dev_null": "allow", "stderr_to_dev_null": "allow"}}
    result = check_output_redirection(tree, rules)
    assert result["status"] == "ask"


def test_per_kind_input_redirection_wildcard() -> None:
    """Input redirection with object policy uses wildcard key."""
    tree = parse("cat < /tmp/in.txt")
    rules = {"input_redirection": {"*": "ask"}}
    result = check_input_redirection(tree, rules)
    assert result["status"] == "ask"


def test_per_kind_input_redirection_deny() -> None:
    """Input redirection with deny wildcard."""
    tree = parse("cat < /tmp/in.txt")
    rules = {"input_redirection": {"*": "deny"}}
    result = check_input_redirection(tree, rules)
    assert result["status"] == "deny"


def test_per_kind_input_redirection_allow() -> None:
    """Input redirection with allow wildcard."""
    tree = parse("cat < /tmp/in.txt")
    rules = {"input_redirection": {"*": "allow"}}
    result = check_input_redirection(tree, rules)
    assert result["status"] == "allow"


# Tests for check_input_redirection


def test_no_input_redirection_allowed() -> None:
    """Command with no input redirection is allowed regardless of rules."""
    tree = parse("ls -la")
    result = check_input_redirection(tree, {"input_redirection": "deny"})
    assert result["status"] == "allow"
    assert result["reason"] == "no input redirection"


def test_allowed_input_redirection_simple() -> None:
    """Simple input redirection is allowed when policy is allow."""
    tree = parse("cat < /tmp/in.txt")
    result = check_input_redirection(tree, {"input_redirection": "allow"})
    assert result["status"] == "allow"
    assert "/tmp/in.txt" in result["reason"]


def test_denied_input_redirection_simple() -> None:
    """Simple input redirection is denied when policy is deny."""
    tree = parse("cat < /tmp/in.txt")
    result = check_input_redirection(tree, {"input_redirection": "deny"})
    assert result["status"] == "deny"
    assert "/tmp/in.txt" in result["reason"]


def test_ask_input_redirection() -> None:
    """Input redirection triggers ask when policy is ask."""
    tree = parse("cat < /tmp/in.txt")
    result = check_input_redirection(tree, {"input_redirection": "ask"})
    assert result["status"] == "ask"
    assert result["reason"] == "input redirection requires approval"


def test_heredoc_input_redirection_allowed() -> None:
    """Heredoc input redirection (<<) is allowed when policy is allow."""
    tree = parse("cat << EOF\nhello\nEOF")
    result = check_input_redirection(tree, {"input_redirection": "allow"})
    assert result["status"] == "allow"
    assert "EOF" in result["reason"]


def test_heredoc_input_redirection_denied() -> None:
    """Heredoc input redirection (<<) is denied when policy is deny."""
    tree = parse("cat << EOF\nhello\nEOF")
    result = check_input_redirection(tree, {"input_redirection": "deny"})
    assert result["status"] == "deny"
    assert "EOF" in result["reason"]


def test_mixed_input_output_rules() -> None:
    """Input and output redirection rules are independent."""
    # Input allowed, output denied
    tree = parse("cat < /tmp/in.txt > /tmp/out.txt")
    rules = {
        "input_redirection": "allow",
        "output_redirection": "deny",
    }
    result_input = check_input_redirection(tree, rules)
    result_output = check_output_redirection(tree, rules)
    assert result_input["status"] == "allow"
    assert result_output["status"] == "deny"


def test_multiple_input_redirections_allowed() -> None:
    """Multiple input redirections are allowed when policy is allow."""
    tree = parse("cat < /tmp/in1.txt > /tmp/out.txt")
    result = check_input_redirection(tree, {"input_redirection": "allow"})
    assert result["status"] == "allow"
    assert "/tmp/in1.txt" in result["reason"]


def test_default_input_policy_is_allow() -> None:
    """When rules dict has no input_redirection key, default is allow."""
    tree = parse("cat < /tmp/in.txt")
    result = check_input_redirection(tree, {})
    assert result["status"] == "allow"


def test_object_form_input_policy_wildcard() -> None:
    """Object form policy uses wildcard level for basic input redirections."""
    tree = parse("cat < /tmp/in.txt")
    rules = {"input_redirection": {"*": "deny"}}
    result = check_input_redirection(tree, rules)
    assert result["status"] == "deny"


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


def test_default_background_policy_is_allow() -> None:
    """When rules dict has no background_execution key, default is allow."""
    tree = parse("sleep 5 &")
    result = check_background_execution(tree, {})
    assert result["status"] == "allow"


def test_object_form_background_policy_wildcard() -> None:
    """Object form policy uses wildcard level for background execution."""
    tree = parse("sleep 5 &")
    rules = {"background_execution": {"*": "deny"}}
    result = check_background_execution(tree, rules)
    assert result["status"] == "deny"


# Tests for pipe redirections (regression tests for BinaryCmd traversal)


def test_pipe_output_redirection_ask() -> None:
    """Output redirection inside a pipe triggers ask."""
    tree = parse("ls | grep bla > /tmp/deleteme")
    result = check_output_redirection(tree, {"output_redirection": "ask"})
    assert result["status"] == "ask"
    assert result["reason"] == "output redirection requires approval"


def test_pipe_output_redirection_deny() -> None:
    """Output redirection inside a pipe is denied."""
    tree = parse("ls | grep bla > /tmp/deleteme")
    result = check_output_redirection(tree, {"output_redirection": "deny"})
    assert result["status"] == "deny"
    assert "/tmp/deleteme" in result["reason"]


def test_pipe_output_redirection_no_redir() -> None:
    """Pipe with no redirection is allowed."""
    tree = parse("ls | grep bla")
    result = check_output_redirection(tree, {"output_redirection": "deny"})
    assert result["status"] == "allow"
    assert result["reason"] == "no output redirection"


def test_triple_pipe_output_redirection() -> None:
    """Redirections across a three-segment pipe are all found."""
    tree = parse("a > 1 | b > 2 | c > 3")
    result = check_output_redirection(tree, {"output_redirection": "ask"})
    assert result["status"] == "ask"


def test_pipe_input_redirection_ask() -> None:
    """Input redirection inside a pipe triggers ask."""
    tree = parse("grep bla < /tmp/input")
    result = check_input_redirection(tree, {"input_redirection": "ask"})
    assert result["status"] == "ask"


def test_pipe_input_redirection_no_redir() -> None:
    """Pipe with no input redirection is allowed."""
    tree = parse("grep bla")
    result = check_input_redirection(tree, {"input_redirection": "deny"})
    assert result["status"] == "allow"
    assert result["reason"] == "no input redirection"


def test_mixed_pipe_input_output_redirection() -> None:
    """Pipe with both input and output redirection."""
    tree = parse("cat < /tmp/in.txt | grep pattern > /tmp/out.txt")
    rules = {
        "input_redirection": "ask",
        "output_redirection": "deny",
    }
    result_input = check_input_redirection(tree, rules)
    result_output = check_output_redirection(tree, rules)
    assert result_input["status"] == "ask"
    assert result_output["status"] == "deny"
    assert "/tmp/out.txt" in result_output["reason"]


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
