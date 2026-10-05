"""A verdict must report exactly the reasons for that verdict, and no others.

Three properties, one per verdict, and they are what a user reads:

- an **allow** names every rule that allowed it;
- a **deny** names only why it was refused - never what was approved;
- an **ask** names only what approval is being requested for - never what was
  already approved, and never what was refused.

These live in ``scenarios/`` rather than beside ``evaluate`` because none of them
is about one module: each spans the evaluator, the reason list, and what a host
prints from it. ``test_verdict_fail_closed.py`` holds the companion property -
that a verdict is never *more* permissive than the reasons it carries - because
that one is about safety and this one is about legibility.

The three properties are the reason ``_Verdict.reasons`` carries the level each
reason argues for. They used to be attempted per step, against the status as it
stood at that step, which is why they did not hold: the status moves afterwards.
:func:`lovely_bash_permissions.evaluate.evaluate_bash_command` filters once, at
the end, so these hold by construction rather than by every step remembering to
check.

Both halves are asserted through :func:`decide_bash_command`, which is what both
CLIs call, so a test that passes here is a statement about what a user of either
host sees - not about an internal shape.
"""

from typing import Any

from lovely_bash_permissions.decide import decide_bash_command

#: A permissive wildcard, so the verdict is decided by the wildcard unless a
#: named rule says otherwise. It is the only config shape in which the reporting
#: properties are interesting: with an asking wildcard almost everything asks, and
#: an allow-shaped reason under an ask is invisible.
PERMISSIVE: dict[str, Any] = {"*": "allow"}

#: An allow-list that matches ``ls`` and nothing else, so a command beside an
#: assignment splits the two: the assignment is governed by
#: ``variable_assignment`` and the command by the list.
WITH_ALLOW_LIST: dict[str, Any] = {"*": "allow", "allowed_cmds_regex": [r"^ls(\s|$)"]}

#: Which level a reason is arguing for, read off the shape of its text. The three
#: sets are the three properties; a reason matching none of them is a sentence the
#: product does not document, and the tests below assert against the sets rather
#: than against literals so that adding a reason means adding it here too.
#:
#: Split by how they are matched: the first two open a sentence, the rest sit
#: inside one. ``denied in config`` is the reason for that - ``command
#: substitution denied in config`` ends with it and ``Redirect target ...`` starts
#: with the other one, and neither is the other.
_BLOCKED_PREFIX = ("Blocked by bash permissions", "Redirect target")
_DENIED = (
    "denied in config",
    "redirection denied to",
    "redirection denied from",
    "execution denied:",
    "assignment denied:",
    "policy 'deny'",
    "config error (blocked)",
)
_ASKED = (
    "requires approval",
    # Verb-agnostic: the frame agrees with its subject ("does not match" for one
    # command, "do not match" for several), so pinning a form would classify one
    # of the two as an approval - it contains the word "allowed" either way.
    "not match allowed patterns",
    "are not allowlisted",
    "has no command name",
    "policy 'ask'",
)
_APPROVED = (
    " allowed",
    " allowed:",
    "matches allowed pattern",
    "wildcard policy is allow",
)


def _level_of(reason: str) -> str:
    """The level *reason* argues for, from its shape alone.

    Order matters and mirrors how a reader parses the sentence: a reason that
    names its level is that level, whatever else it also says. ``"... does not
    match allowed patterns; wildcard policy is deny"`` is a denial, and reading it
    as an ask because of its first clause is the mistake this ordering prevents.
    """
    if any(marker in reason for marker in ("wildcard policy is", "policy '")):
        return reason.rsplit(" ", 1)[-1].rstrip(")").replace("'", "")
    if reason.startswith(_BLOCKED_PREFIX) or any(marker in reason for marker in _DENIED):
        return "deny"
    if any(marker in reason for marker in _ASKED):
        return "ask"
    if any(marker in reason for marker in _APPROVED):
        return "allow"
    return "unknown"


def _verdict(command: str, config: dict[str, Any]) -> tuple[str, list[str]]:
    decision = decide_bash_command(command, config)
    return decision["action"], decision["reasons"]


class TestEveryReasonJustifiesTheVerdictItIsShownWith:
    """The filter, stated as a property over the shapes rather than over cases.

    One assertion over a table of cases, because the property is what is being
    tested: a refusal that mentions an approval is wrong in the same way whether
    the approval was a redirection, an assignment or a background job, and three
    near-identical tests would let two of them rot.
    """

    #: (command, config, expected verdict). Chosen to cover the three shapes of
    #: leak: an allow-reason recorded before a downgrade, a deny-reason beside an
    #: approval, and a wildcard sentence whose level the verdict overtook.
    CASES: tuple[tuple[str, dict[str, Any], str], ...] = (
        # an approval recorded while the verdict was still allow, then downgraded
        ("ls > $(cat $(echo x))", {**PERMISSIVE, "output_redirection": "allow", "*": "ask"}, "ask"),
        ("x=1; ls > /tmp/f", {"*": "ask", "variable_assignment": "allow", "output_redirection": "allow"}, "ask"),
        # an approval recorded, then a block pattern refuses the same command
        (
            "export A=(/etc/passwd)",
            {"*": "allow", "variable_assignment": "allow", "blocked_cmds_regex": ["passwd"]},
            "deny",
        ),
        ('cat /e"tc"/passwd; x=1', {**PERMISSIVE, "blocked_cmds_regex": ["/etc/passwd"]}, "deny"),
        # a redirection allowed, and the refusal is for something else entirely
        (
            "ls > /tmp/f && cat /etc/passwd",
            {**PERMISSIVE, "output_redirection": "allow", "blocked_cmds_regex": ["/etc/passwd"]},
            "deny",
        ),
        # a background job allowed, and a nested substitution refused
        ("echo $(id) &", {**PERMISSIVE, "background_execution": "allow", "command_substitution": "deny"}, "deny"),
        # a substitution allowed, and the command itself is what is not allowlisted
        ("echo $(id) ; ls", {"*": "ask", "command_substitution": "allow", "allowed_cmds_regex": [r"^ls(\s|$)"]}, "ask"),
        # a redirection asking, under a wildcard that refuses the command
        ("nosuch --x > /tmp/f", {"*": "deny", "output_redirection": "ask"}, "deny"),
    )

    def test_no_reason_contradicts_its_verdict(self) -> None:
        for command, config, expected in self.CASES:
            action, reasons = _verdict(command, config)
            assert action == expected, f"{command!r} under {config}"
            for reason in reasons:
                assert _level_of(reason) == action, f"{command!r}: {reason!r} in a {action}"

    def test_a_non_allow_verdict_always_says_something(self) -> None:
        """The one way the filter could fail open, stated as its own test.

        A non-allow verdict with no reasons renders the last-resort ``"allowed"``
        string, so an empty list at an ``ask`` or ``deny`` would not merely read
        badly - it would claim approval. Each of these cases reaches its verdict
        through a different step, and each has to carry a reason.
        """
        for command, config, expected in self.CASES:
            if expected == "allow":
                continue
            action, reasons = _verdict(command, config)
            assert reasons, f"{command!r} under {config} reached {action} with nothing to say"


class TestAnApprovalNamesEveryRuleThatAllowedIt:
    """A. The reason list is how the user finds out which of their rules permitted
    a command, so an approval that does not name them answers nothing.
    """

    def test_each_construct_names_itself_when_it_allows(self) -> None:
        """One test per policy key, because each has its own gate.

        The substitution three, the assignment, and the three construct-shaped
        redirects all reach their verdict through different code, and each was
        silent at some point. A table keeps that visible: adding a key here adds
        the case that would have caught its silence.
        """
        cases: tuple[tuple[str, dict[str, Any], str], ...] = (
            ("echo $(cat f)", {**PERMISSIVE, "command_substitution": "allow"}, "command substitution"),
            ("diff <(sort a) <(sort b)", {**PERMISSIVE, "process_substitution": "allow"}, "process substitution"),
            ("( cd /tmp; ls )", {**PERMISSIVE, "subshell": "allow"}, "subshell"),
            ("x=1", {**PERMISSIVE, "variable_assignment": "allow"}, "variable assignment"),
            ("ls > /tmp/f", {**PERMISSIVE, "output_redirection": "allow"}, "output redirection"),
            ("cat < /etc/motd", {**PERMISSIVE, "input_redirection": "allow"}, "input redirection"),
            ("sleep 5 &", {**PERMISSIVE, "background_execution": "allow"}, "background execution"),
        )
        for command, config, expected in cases:
            action, reasons = _verdict(command, config)
            assert action == "allow", f"{command!r} under {config}"
            assert any(expected in reason for reason in reasons), f"{command!r}: {reasons}"

    def test_an_allow_names_its_rule_even_beside_an_allow_list(self) -> None:
        """The allow-list cannot see a pseudo-command, so it explains nothing here.

        ``x=1`` under an allow-list is the case that matters: no pattern matched,
        because there is no command name to match, so the list contributes no
        reason and the rule that did decide it is the only candidate.
        """
        action, reasons = _verdict("x=1", {**WITH_ALLOW_LIST, "variable_assignment": "allow"})
        assert action == "allow"
        assert reasons, "an approval with no reason answers nothing"

    def test_a_wildcard_approval_says_the_wildcard_allowed_it(self) -> None:
        """An allow-list that matched nothing leaves the wildcard to explain.

        Without the level in the sentence, a refusal under ``*: deny`` explained
        itself as a complaint about the allow-list and an approval under
        ``*: allow`` used the same sentence - neither said which level spoke.
        """
        for wildcard in ("allow", "ask", "deny"):
            command, config = "grep txt f", {**WITH_ALLOW_LIST, "*": wildcard}
            action, reasons = _verdict(command, config)
            assert action == wildcard, (command, config)
            assert any(f"wildcard policy is {wildcard}" in reason for reason in reasons), (command, config, reasons)

    def test_a_fully_matched_command_names_the_pattern_that_matched(self) -> None:
        """The other half of A: when the list decided, the list is named."""
        action, reasons = _verdict("ls -la", WITH_ALLOW_LIST)
        assert action == "allow"
        assert any("matches allowed pattern" in reason for reason in reasons)
