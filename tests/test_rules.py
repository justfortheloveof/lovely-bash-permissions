"""Tests for permission rules engine."""

from lovely_bash_permissions.rules import check_allowed_patterns


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
