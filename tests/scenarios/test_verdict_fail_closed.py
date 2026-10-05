"""A verdict must never be more permissive than the reasons it prints.

Every case here is one where the *verdict* and the *reasons* could disagree:
the evaluator records why it decided something, and then decides something
else. A verdict that contradicts its own reasons is the worst failure mode this
product can have - the user reads "Blocked by bash permissions" in the prompt
or the label and concludes the command was stopped, while it runs.

The classes are named for the invariant they protect, not for the bug they were
found by, because the bugs are historical and the invariants are not.
"""

from typing import Any

from lovely_bash_permissions.evaluate import evaluate_bash_command

#: A permissive wildcard plus a block list: the shape that makes the wildcard the
#: only thing standing between a command and approval. Every config in this file
#: is a variant of it, because every bug here needs a reason to allow.
PERMISSIVE_WITH_BLOCKS: dict[str, Any] = {
    "*": "allow",
    "blocked_cmds_regex": ["/etc/passwd"],
}

#: The quote-split spelling. It matters that the block list can only ever match
#: the *executed* form: the whole-command scan reads the command as typed, where
#: the path is not contiguous, so only the per-segment scan can catch it. That is
#: what makes these cases the interesting ones rather than `cat /etc/passwd`,
#: which a later scan re-catches by accident.
BLOCKED_READ = 'cat /e"tc"/passwd'


class TestAVerdictIsNotMorePermissiveThanItsReasons:
    """An allow must never carry a reason that says the command was blocked."""

    def test_a_blocked_read_followed_by_an_assignment_is_denied(self) -> None:
        """The original bug: a trailing assignment re-opened a denied command.

        ``cat /e"tc"/passwd; x=1`` denied the blocked read on its first segment.
        The bare assignment that followed is a pseudo-command, and its
        ``variable_assignment: allow`` branch used to *assign* the verdict rather
        than leave it alone - so the whole command came back ``allow``, with
        "Blocked by bash permissions" still sitting in its own reasons. Because
        every later step can only downgrade an allow and never raise one, nothing
        put the denial back.
        """
        result = evaluate_bash_command(f"{BLOCKED_READ}; x=1", PERMISSIVE_WITH_BLOCKS)
        assert result["status"] == "deny"
        assert any("Blocked by bash permissions" in reason for reason in result["reasons"])

    def test_the_order_of_the_segments_does_not_matter(self) -> None:
        """``x=1; cat /e"tc"/passwd`` denied even before the fix.

        Kept as a pair with the test above on purpose: the bug was strictly
        order-dependent, so a fix that only tested one order would pass while the
        other still failed.
        """
        result = evaluate_bash_command(f"x=1; {BLOCKED_READ}", PERMISSIVE_WITH_BLOCKS)
        assert result["status"] == "deny"

    def test_no_assignment_shape_restores_the_verdict(self) -> None:
        """Every bare-assignment spelling after a blocked command denies.

        Array assignment, ``export``, and an assignment as a pipeline stage each
        produce a pseudo-command segment through a different branch of the
        parser, so they are three routes to the same bug rather than one.
        """
        for command in (
            f"{BLOCKED_READ}; A=(b)",
            f"{BLOCKED_READ}; export X=1",
            f"{BLOCKED_READ} | x=1",
            f"{BLOCKED_READ} && x=1",
            f"{BLOCKED_READ}; x=1 y=2",
        ):
            result = evaluate_bash_command(command, PERMISSIVE_WITH_BLOCKS)
            assert result["status"] == "deny", command

    def test_an_allowed_assignment_still_allows(self) -> None:
        """The fix must not cost the permissive verdict it was keeping.

        An allowed assignment is still not a reason to ask, and an unrelated
        command next to one still runs. Without this the fix would read as
        "assignments make everything ask", which is not what it does.
        """
        for command in ("x=1", "ls; x=1", "export FOO=bar", "ls; FOO=bar"):
            result = evaluate_bash_command(command, PERMISSIVE_WITH_BLOCKS)
            assert result["status"] == "allow", command

    def test_the_reason_survives_the_fix(self) -> None:
        """The denial still says which assignment was allowed.

        Dropping the line outright would have lost the reason too. It is the
        *verdict* the assignment may not touch; what it did is still worth
        saying.
        """
        result = evaluate_bash_command(f"{BLOCKED_READ}; x=1", PERMISSIVE_WITH_BLOCKS)
        assert any("variable assignment allowed" in reason for reason in result["reasons"])
