"""Regex matching for the allow and block lists, in one place.

Every pattern the product matches - ``allowed_cmds_regex``,
``blocked_cmds_regex``, against a segment's command line, a whole command, a
heredoc body, a substitution's contents or a redirection target - goes through
:func:`match_texts`. There used to be two matchers, one here-shaped and one in
``rules.py``, which agreed only by coincidence on what an invalid pattern does.

Invalid patterns never match. The schema rejects them before a config is
used, but a config handed straight to the evaluator is not validated, and one
bad regex must neither crash evaluation nor silently approve a command.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from functools import lru_cache
from typing import Literal

#: Regex metacharacters (unescaped) or lone backslashes that mark a pattern
#: body as more than a plain escaped literal - i.e. not a bare-name anchor.
_BARE_NAME_META = re.compile(r"(?<!\\)[()\[\]{}.*+?|^$]|\\(?!\\)")


@lru_cache(maxsize=512)
def compile_pattern(pattern: str) -> re.Pattern[str]:
    """Compile and cache a regex pattern. Raises ValueError on invalid pattern."""
    try:
        return re.compile(pattern)
    except re.error as exc:
        raise ValueError(f"invalid pattern {pattern!r}: {exc}") from exc


def opaque_match_unreliable(pattern: str) -> bool:
    """True when an opaque ``$(...)`` argument can hide the token a pattern
    constrains, making a literal match on the placeholder unsafe to approve.

    Two pattern shapes are affected: line-spanning negative lookaheads
    (e.g. ``^find(?!.*\\s-(exec|delete|ok)...)``, whose ``(?!)`` scans the
    whole command line and cannot see tokens produced at runtime by a
    substitution) and bare-name anchors such as ``^true$`` (which accept no
    arguments, so a command whose argument list is hidden entirely behind
    ``$(...)`` must not be approved against them).
    """
    # Line-spanning negative lookahead: the guard scans the whole command
    # line, so a substitute token never appears in the matched string.
    if "(?!" in pattern:
        return True
    # Bare-name anchor (e.g. ^name$ from allowed_cmds_regex): accept no
    # arguments, so any argument hidden behind $(...) invalidates the match.
    # The body must be plain escaped text with no regex metacharacters.
    body = pattern[1:-1] if pattern.startswith("^") and pattern.endswith("$") else None
    if body is None:
        return False
    return not _BARE_NAME_META.search(body) if body else False


def match_texts(
    texts: Sequence[str],
    patterns: Sequence[str],
    *,
    opaque_guard: bool = False,
    raw_fallback: Literal["always", "only-if-no-lookahead"] = "always",
    has_opaque: bool = False,
) -> list[tuple[str, str]]:
    """Match *patterns* against *texts* - the single core behind both regex lists.

    Iteration is pattern-major (outer loop over patterns, inner over texts),
    so results come back in pattern order and at most one entry per pattern.
    ``texts[0]`` is the executed / normalized form and is always tried;
    ``texts[1:]`` is the raw form and is tried per *raw_fallback*:

    - ``"always"``: both forms are tried (OR semantics - a hit on either
      counts, which is what the denied direction wants).
    - ``"only-if-no-lookahead"``: the raw form is a fallback only for patterns
      that contain no ``(?!`` guard, because a quote-split spelling can fake
      the text a lookahead scans but cannot change a lookahead's own verdict.

    Args:
        texts: Candidate texts in match-priority order.
        patterns: Regex patterns to try, in list order.
        opaque_guard: Drop matches whose pattern is unsafe to trust when the
            command hides arguments behind ``$(...)`` (see
            :func:`opaque_match_unreliable`).
        raw_fallback: Whether and when the raw-form texts are tried.
        has_opaque: Whether the command actually holds a ``$(...)`` argument
            (only then can *opaque_guard* fire).

    Returns:
        ``(pattern, text_that_hit)`` pairs in pattern order. Invalid patterns
        are skipped rather than raised.
    """
    if not texts:
        return []
    matches: list[tuple[str, str]] = []
    for pattern in patterns:
        try:
            compiled = compile_pattern(pattern)
        except ValueError:
            continue
        candidates = texts[:1] if raw_fallback == "only-if-no-lookahead" and "(?!" in pattern else texts
        hit = next((text for text in candidates if compiled.search(text)), None)
        if hit is None:
            continue
        # The guard shape's verdict depends on tokens a substitution can hide,
        # so a match here must not stand in for approval.
        if opaque_guard and has_opaque and opaque_match_unreliable(pattern):
            continue
        matches.append((pattern, hit))
    return matches


def first_match(text: str, patterns: Sequence[str]) -> str | None:
    """The first pattern that matches *text* (unanchored search), or ``None``."""
    matches = match_texts([text], patterns)
    return matches[0][0] if matches else None
