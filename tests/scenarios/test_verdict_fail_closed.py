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

import pytest

from lovely_bash_permissions.decide import decide_bash_command
from lovely_bash_permissions.evaluate import evaluate_bash_command
from lovely_bash_permissions.rules import _resolve_output_level

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

    def test_the_denial_names_only_the_refusal(self) -> None:
        """The assignment's approval is no longer listed beside the block.

        It used to be, and the fix for the verdict left it: the reason says the
        assignment was allowed, and the command was refused, and both were true.
        A reason now carries the level it argues for and only the level that was
        reached is shown, so a refusal cannot end by mentioning something that was
        approved - which is what a user reads the label to find out.
        """
        result = evaluate_bash_command(f"{BLOCKED_READ}; x=1", PERMISSIVE_WITH_BLOCKS)
        assert result["reasons"]
        assert all(reason.startswith("Blocked by bash permissions") for reason in result["reasons"])

    def test_the_assignment_is_still_named_when_it_decided_the_verdict(self) -> None:
        """Dropping an approval from a refusal must not drop it from an approval.

        Under the same config, without the blocked command, the assignment is the
        only thing that ran and the reason is the one the user needs.
        """
        result = evaluate_bash_command("x=1", PERMISSIVE_WITH_BLOCKS)
        assert result["status"] == "allow"
        assert result["reasons"] == ["variable assignment allowed: ['x=1']"]


class TestAWildcardDenyIsNotSpentByAnEarlierAsk:
    """A construct that asks must not turn a command the wildcard refused into a
    question.

    ``{"*": "deny", "output_redirection": "ask"}`` reads as "refuse everything,
    but ask about redirections". ``nosuch --x > /tmp/f`` came back ``ask``: the
    redirection policies run before the wildcard resolution and turn an ``allow``
    into an ``ask``, and the wildcard's guard - ``status == "allow"`` - then found
    nothing left to turn into a denial. The ask consumed the allow the wildcard
    was about to overrule.

    This is the same shape as the assignment bug above: a decision made by one
    step is destroyed by a step that ran earlier. Deny is the strictest level in
    the product and is documented as winning over the wildcard, so a construct
    asking is not a licence to overrule it.
    """

    #: Construct policies that ask, and a command carrying each construct.
    ASKING_CONSTRUCTS: tuple[tuple[str, dict[str, Any], str], ...] = (
        ("nosuch --x > /tmp/f", {"*": "deny", "output_redirection": "ask"}, "output redirection"),
        ("nosuch --x < in", {"*": "deny", "input_redirection": "ask"}, "input redirection"),
        ("nosuch --x &", {"*": "deny", "background_execution": "ask"}, "background execution"),
    )

    def test_a_wildcard_deny_beats_a_construct_ask(self) -> None:
        for command, config, _ in self.ASKING_CONSTRUCTS:
            result = evaluate_bash_command(command, config)
            assert result["status"] == "deny", f"{command!r} under {config}"
            assert any("wildcard policy is deny" in reason for reason in result["reasons"]), (command, config)

    def test_the_construct_reason_is_not_what_the_refusal_says(self) -> None:
        """The refusal names the wildcard; the construct's ask is not quoted at it.

        Both are recorded - the construct did occur and did ask - but only the one
        that justifies the verdict is shown. Quoting the ask inside the refusal
        would tell the user their redirection needs approval, which is the
        opposite of what happened.
        """
        command, config, expected_reason = self.ASKING_CONSTRUCTS[0]
        result = evaluate_bash_command(command, config)
        assert not any(expected_reason in reason for reason in result["reasons"]), result["reasons"]

    def test_a_construct_allow_still_overrides_a_wildcard_deny_for_an_allowlisted_command(self) -> None:
        """The fix must not make the wildcard deny things the allow-list matched.

        A matched pattern is a more specific decision than a wildcard, so it
        stands: with ``ls`` allowlisted and its redirect allowed, ``*: deny`` has
        nothing left to refuse.
        """
        result = evaluate_bash_command(
            "ls -la > /tmp/f",
            {"*": "deny", "output_redirection": "allow", "allowed_cmds_regex": [r"^ls(\s|$)"]},
        )
        assert result["status"] == "allow"

    def test_a_construct_deny_is_unaffected(self) -> None:
        """A construct that refuses was already correct, and stays correct."""
        for command, config, key in self.ASKING_CONSTRUCTS:
            result = evaluate_bash_command(command, {**config, key: "deny"})
            assert result["status"] == "deny", (command, config)


class TestAPolicyKeyCoversEveryShapeItNames:
    """A key must govern every construct shape a user might write, not only the
    ones that happen to carry a command name.

    ``background_execution`` collected the command names of backgrounded
    statements, and decided from the collection being non-empty. Three shapes
    carry no name, so all three reported "no background execution" and a
    user-written ``deny`` allowed them: an assignment-only ``CallExpr`` (it has
    ``Assigns`` where a command has ``Args``), a ``DeclClause`` (``export``,
    ``declare``, ``local``, ``readonly`` — not a ``CallExpr`` at all), and any
    compound built only from those.
    """

    #: Backgrounded statements that run no command, and what each is called.
    UNNAMED: tuple[tuple[str, str], ...] = (
        ("x=1 &", "a variable assignment"),
        ("export FOO=bar &", "an export or declaration statement"),
        ("( x=1 ) &", "a statement with no command name"),
        ("declare -a B &", "an export or declaration statement"),
    )

    @pytest.mark.parametrize(("command", "named"), UNNAMED)
    def test_a_deny_refuses_a_backgrounded_statement_with_no_command_name(self, command: str, named: str) -> None:
        for level in ("deny", "ask", "allow"):
            result = evaluate_bash_command(command, {"*": "allow", "background_execution": level})
            assert result["status"] == level, (command, level, result)
            assert any(named in reason for reason in result["reasons"]), (command, level, result["reasons"])

    @pytest.mark.parametrize(("command", "named"), UNNAMED)
    def test_an_unset_policy_still_inherits_the_wildcard(self, command: str, named: str) -> None:
        """The fix must not make a backgrounded assignment prompt on its own.

        With no ``background_execution`` key the resolved level is the wildcard,
        so this is decided entirely by ``*`` - as every other construct key is.
        Were it not, a permissive config would start asking about ``x=1 &`` for
        no reason the user wrote.
        """
        for wildcard in ("allow", "ask", "deny"):
            result = evaluate_bash_command(command, {"*": wildcard})
            assert result["status"] == wildcard, (command, wildcard, result)

    def test_a_statement_that_is_not_backgrounded_is_untouched(self) -> None:
        """The shape that exposed the gap must not start firing without ``&``."""
        result = evaluate_bash_command("x=1", {"*": "allow", "background_execution": "deny"})
        assert result["status"] == "allow"
        assert not any("background" in reason for reason in result["reasons"]), result["reasons"]

    def test_a_named_background_command_still_reports_its_name(self) -> None:
        """The existing behaviour is unchanged; only the empty case is new."""
        result = evaluate_bash_command("sleep 5 &", {"*": "allow", "background_execution": "deny"})
        assert result["reasons"] == ["background execution denied: sleep"]


class TestALevelNobodyWroteIsNeverAllow:
    """An unrecognised level must fail closed, everywhere a level is read.

    Both hosts validate a config against the schema before evaluating it, so
    none of this is reachable through a CLI. It is reachable through
    :func:`~lovely_bash_permissions.evaluate.evaluate_bash_command` and
    :func:`~lovely_bash_permissions.decide.decide_bash_command`, which are
    documented public entry points taking a config dict, and through
    ``evaluate_bash_command``'s own docstring promise that a caller may pass one
    it never validated.

    ``"block"`` is in the list deliberately: it is *Devin's* wire word for a
    refusal, so it is the level a config author is most likely to reach for from
    the wrong vocabulary.
    """

    #: Levels no ``PermissionLevel`` admits, plus the empty ones that
    #: ``resolve_level``'s falsiness fallback already treats as unset.
    UNRECOGNISED: tuple[Any, ...] = ("ALLOW", "block", "yes", "", True, None, ["allow"])

    def test_the_dict_form_output_redirection_denies_an_unrecognised_level(self) -> None:
        """The one resolver that failed open now denies.

        ``_resolve_output_level`` read ``deny -> ask -> else allow``, so every
        level it did not recognise - and ``"block"`` most of all - came back
        ``allow``. Its three siblings all ended in ``deny``; this one sat next
        to them disagreeing.
        """
        for level in self.UNRECOGNISED:
            result = evaluate_bash_command(
                "ls > /tmp/f", {"output_redirection": {"*": level}, "blocked_cmds_regex": []}
            )
            assert result["status"] != "allow", level

    def test_an_unrecognised_level_on_one_kind_denies_the_whole_command(self) -> None:
        """One bad level is enough; a good level beside it does not rescue it."""
        result = evaluate_bash_command(
            "ls > /tmp/f > /tmp/g",
            {"output_redirection": {"stdout_to_dev_null": "allow", "other": "ALLOW"}},
        )
        assert result["status"] == "deny"

    def test_the_three_real_levels_keep_their_precedence(self) -> None:
        """deny beats ask beats allow, exactly as before.

        The fix must not have reordered anything: a mixed command whose kinds
        resolve to different levels is decided by the strictest one, and the
        schema's documented distinction between ``other: allow`` and ``*: deny``
        has to survive it.
        """
        assert (
            _resolve_output_level(["stdout_to_dev_null", "other"], {"stdout_to_dev_null": "allow", "other": "allow"})
            == "allow"
        )
        assert (
            _resolve_output_level(["stdout_to_dev_null", "other"], {"stdout_to_dev_null": "allow", "*": "deny"})
            == "deny"
        )
        assert (
            _resolve_output_level(["stdout_to_dev_null", "other"], {"stdout_to_dev_null": "allow", "other": "ask"})
            == "ask"
        )

    def test_the_decision_layer_asks_rather_than_raising(self) -> None:
        """An unrecognised level out of the evaluator becomes ``ask``.

        ``decide_bash_command`` looked the status up with ``[...]`` while its own
        ``error_action`` used ``.get(level, "ask")``, so the same nonsense config
        asked on the error path and raised ``KeyError`` on the success path. A
        list is here because a dict lookup cannot even hash it.
        """
        for level in self.UNRECOGNISED:
            decision = decide_bash_command("ls", {"*": level})
            assert decision["action"] == "ask", level

    def test_a_written_allow_still_allows(self) -> None:
        """The guard is on the level, not on the shape of the config."""
        assert decide_bash_command("ls", {"*": "allow"})["action"] == "allow"
