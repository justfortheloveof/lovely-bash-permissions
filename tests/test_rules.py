"""Tests for permission rules engine."""

from lovely_bash_permissions.rules import check_allowed_patterns, check_blocked_patterns


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
    assert check_blocked_patterns(["/etc/passwd"], ["/etc/passwd"]) is True


def test_blocked_multiple_args_one_matches() -> None:
    """Multiple arguments, one matches a blocked pattern."""
    args = ["/var/log", "/etc/passwd", "/tmp"]
    patterns = ["/etc/passwd"]
    assert check_blocked_patterns(args, patterns) is True


def test_blocked_multiple_args_none_match() -> None:
    """Multiple arguments, none match any blocked pattern."""
    args = ["/var/log", "/tmp", "/usr/bin"]
    patterns = ["/etc/passwd", "/root"]
    assert check_blocked_patterns(args, patterns) is False


def test_blocked_empty_args() -> None:
    """Empty args list returns False."""
    assert check_blocked_patterns([], ["/etc/passwd"]) is False


def test_blocked_empty_patterns() -> None:
    """Empty blocked_patterns list returns False."""
    assert check_blocked_patterns(["/etc/passwd"], []) is False


def test_blocked_pattern_matches_part_of_path() -> None:
    """Pattern matches part of path (not anchored)."""
    assert check_blocked_patterns(["/etc/passwd.backup"], ["/etc/passwd"]) is True
