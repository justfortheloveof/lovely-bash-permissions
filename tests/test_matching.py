"""Tests for the shared regex matcher behind both allow and block lists."""

import pytest

from lovely_bash_permissions.matching import compile_pattern, first_match, match_texts

# compile_pattern


def testcompile_pattern_caches() -> None:
    """Same pattern compiled twice returns the same cached object."""
    p1 = compile_pattern("^hello$")
    p2 = compile_pattern("^hello$")
    assert p1 is p2


def testcompile_pattern_invalid_raises() -> None:
    """Invalid regex pattern raises ValueError with descriptive message."""
    with pytest.raises(ValueError):
        compile_pattern("[invalid")


def testcompile_pattern_invalid_raises_message() -> None:
    """Invalid regex pattern ValueError message includes pattern and error."""

    exc = pytest.raises(ValueError, lambda: compile_pattern("[invalid"))
    assert "invalid pattern" in str(exc.value)


# Tests for match_texts (the shared core behind allowed_cmds_regex and
# blocked_cmds_regex - both lists differ only in the flags they pass in)


def test_core_single_text_shape() -> None:
    """A one-element text list is the plain search shape."""
    assert match_texts(["cat /etc/passwd"], [r"\/etc"]) == [(r"\/etc", "cat /etc/passwd")]
    assert match_texts(["cat /etc/passwd"], [r"^/etc"]) == []


def test_core_two_text_shape_prefers_first_text() -> None:
    """With two texts, the first (executed) form wins and is reported."""
    texts = ["cat /etc/passwd", 'cat /e"tc"/passwd']
    assert match_texts(texts, ["cat"]) == [("cat", "cat /etc/passwd")]


def test_core_reports_the_text_that_hit() -> None:
    """A pattern matching only the second text reports that text."""
    texts = ["cat /etc/passwd", 'cat /e"tc"/passwd']
    assert match_texts(texts, [r'/e"tc"']) == [(r'/e"tc"', 'cat /e"tc"/passwd')]


def test_core_is_pattern_major_not_text_major() -> None:
    """Results follow pattern order, and each pattern reports at most one hit."""
    assert match_texts(["ab", "ab"], ["b", "a"]) == [("b", "ab"), ("a", "ab")]


def test_core_raw_fallback_always_uses_second_text() -> None:
    """`raw_fallback="always"`: both texts are tried, even for a guard pattern."""
    texts = ["find /tmp -exec rm", 'find /tmp -"exec" rm']
    assert match_texts(texts, [r"^find(?!.*\s-exec).*$"], raw_fallback="always") == [
        (r"^find(?!.*\s-exec).*$", 'find /tmp -"exec" rm')
    ]


def test_core_raw_fallback_only_if_no_lookahead_skips_raw_for_guards() -> None:
    """A `(?!` pattern never sees the raw form, so a quoted flag cannot fake it."""
    texts = ["find /tmp -exec rm", 'find /tmp -"exec" rm']
    assert match_texts(texts, [r"^find(?!.*\s-exec).*$"], raw_fallback="only-if-no-lookahead") == []


def test_core_raw_fallback_only_if_no_lookahead_honors_plain_patterns() -> None:
    """A pattern with no guard still gets its raw-form fallback."""
    texts = ["cat /etc/passwd", 'cat /e"tc"/passwd']
    assert match_texts(texts, [r'/e"tc"'], raw_fallback="only-if-no-lookahead") == [(r'/e"tc"', 'cat /e"tc"/passwd')]


def test_core_opaque_guard_drops_bare_name_anchor_match() -> None:
    """`opaque_guard` + `has_opaque`: `^true$` cannot approve a `$(...)` command."""
    assert match_texts(["true"], ["^true$"], opaque_guard=True, has_opaque=True) == []
    assert match_texts(["true"], ["^true$"], opaque_guard=True, has_opaque=False) == [("^true$", "true")]


def test_core_opaque_guard_drops_lookahead_match() -> None:
    """The guard also drops a line-spanning-lookahead match under `$(...)`."""
    pattern = r"^find(?!.*\s-(exec|delete|ok)\b).*$"
    assert match_texts(["find . -name x"], [pattern], opaque_guard=True, has_opaque=True) == []


def test_core_opaque_guard_off_by_default() -> None:
    """`has_opaque` alone never suppresses a match; the guard flag is required."""
    assert match_texts(["true"], ["^true$"], has_opaque=True) == [("^true$", "true")]


def test_core_opaque_guard_keeps_free_tail_patterns() -> None:
    """A pattern that accepts arbitrary arguments survives the opaque guard."""
    pattern = r"^echo(\s+.*)?$"
    assert match_texts(["echo hi"], [pattern], opaque_guard=True, has_opaque=True) == [(pattern, "echo hi")]


def test_core_invalid_pattern_is_skipped_not_raised() -> None:
    """A bad regex is treated as "no match"; later patterns still run."""
    assert match_texts(["cat /etc"], ["[invalid", r"\/etc"]) == [(r"\/etc", "cat /etc")]


def test_core_no_texts_returns_no_matches() -> None:
    """An empty text list can never match."""
    assert match_texts([], ["^cat"]) == []


def test_core_no_patterns_returns_no_matches() -> None:
    """An empty pattern list returns nothing."""
    assert match_texts(["cat /etc"], []) == []


def test_first_match_returns_the_first_pattern_in_list_order() -> None:
    """``first_match`` is the one-text, first-hit view of the core."""
    assert first_match("/etc/passwd", ["shadow", r"\/etc", "passwd"]) == r"\/etc"
    assert first_match("/tmp/x", ["[invalid", "shadow"]) is None
