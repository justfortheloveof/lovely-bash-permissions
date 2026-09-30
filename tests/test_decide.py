"""Tests for the shared decision: one command, one config, one verdict.

Two hosts call this - the Devin hook and the Pi server - so a policy change
that lands in one and misses the other is invisible from either side. The
tests here are the shared contract both are held to.
"""

from typing import Any

import pytest

from lovely_bash_permissions import decide
from lovely_bash_permissions.evaluate import evaluate_bash_command

#: A command shfmt cannot parse. Every one of the `error` policy's tests needs
#: one, and they must all use the same: the point is the routing, not the input.
UNPARSEABLE = "'unterminated"


class TestTheDecisionShape:
    def test_allow_carries_its_reason(self) -> None:
        result = decide.decide_bash_command("ls", {"*": "allow"})
        assert result["action"] == "allow"
        assert result["reason"]
        assert isinstance(result["reasons"], list)

    def test_the_shape_is_stable(self) -> None:
        """Three keys, always. A host reads them positionally or by name."""
        assert set(decide.decide_bash_command("ls", {"*": "ask"})) == {"action", "reason", "reasons"}

    def test_reasons_join_back_to_the_reason(self) -> None:
        for command, config in (("ls", {"*": "ask"}), ("rm -rf /", {"*": "deny"}), ("ls > f", {"*": "ask"})):
            result = decide.decide_bash_command(command, config)
            assert "; ".join(result["reasons"]) == result["reason"]

    def test_it_agrees_with_the_evaluator_it_wraps(self) -> None:
        """The decision adds resolution and error routing; it decides nothing else."""
        from lovely_bash_permissions.config.effective_bash import resolve_bash_config

        config = {"*": "ask", "allowed_cmds_regex": ["^ls(\\s|$)"], "blocked_cmds_regex": ["/etc/passwd"]}
        for command in ("ls", "cat /etc/passwd", "ls > f", "( ls )", "echo $(id)"):
            direct = evaluate_bash_command(command, resolve_bash_config(config))
            assert decide.decide_bash_command(command, config)["action"] == direct["status"]


class TestTheTopLevelWildcardCrossesTheSeam:
    """A block with no `*` of its own is not a policy on its own.

    The mode's wildcard is the fallback, and a process that never saw the mode
    cannot infer it. Omit `top_level` and an ``allow`` mode arrives as ``ask`` -
    quietly, because every level still resolves to something plausible.
    """

    def test_the_mode_wildcard_supplies_a_missing_star(self) -> None:
        result = decide.decide_bash_command("git status", {"allowed_cmds_regex": ["^ls"]}, "allow")
        assert result["action"] == "allow"

    def test_its_absence_falls_back_to_ask(self) -> None:
        # `git status` matches no allowed pattern, so the verdict can only come
        # from the wildcard - which is the point: the two differ, and the
        # difference is invisible in the output unless a command is left to it.
        result = decide.decide_bash_command("git status", {"allowed_cmds_regex": ["^ls"]})
        assert result["action"] == "ask"

    def test_a_block_star_beats_the_mode_wildcard(self) -> None:
        result = decide.decide_bash_command("git status", {"*": "deny"}, "allow")
        assert result["action"] == "deny"


class TestTheErrorPolicy:
    """`error` decides what happens to a command we could not analyse at all.

    It is a `NON_CONSTRUCT_KEYS` key: the evaluator's own level resolution
    never touches it, only `resolve_bash_config` populates it. So it is
    reachable only because `decide_bash_command` resolves first - and that is
    invisible when it is skipped, because the fallback chain still lands on a
    plausible level.
    """

    def test_an_unresolved_config_silently_routes_to_the_wildcard(self) -> None:
        """Why the resolution step exists, stated as a fact about the config.

        `{"*": "allow"}` with no `error` key *looks* like it allows failures.
        It does not: `error` is absent, the chain falls through to `*`, and on
        the raw block that is the only level present. Resolve it and `error`
        becomes `allow` explicitly - the same answer, reached honestly. Change
        the wildcard to `ask` and the raw block reports `ask` where the
        resolved one reports `allow`, which is the real divergence.
        """
        assert decide.decide_bash_command(UNPARSEABLE, {"*": "ask", "error": "allow"})["action"] == "allow"
        assert decide.decide_bash_command(UNPARSEABLE, {"*": "ask"})["action"] == "ask"

    def test_error_deny(self) -> None:
        result = decide.decide_bash_command(UNPARSEABLE, {"*": "allow", "error": "deny"})
        assert result["action"] == "deny"
        assert "error evaluating command" in result["reason"]
        assert "policy 'deny'" in result["reason"]

    def test_error_ask(self) -> None:
        assert decide.decide_bash_command(UNPARSEABLE, {"*": "allow", "error": "ask"})["action"] == "ask"

    def test_error_defaults_to_the_wildcard(self) -> None:
        assert decide.decide_bash_command(UNPARSEABLE, {"*": "deny"})["action"] == "deny"
        assert decide.decide_bash_command(UNPARSEABLE, {"*": "allow"})["action"] == "allow"

    def test_error_inherits_from_the_mode_wildcard(self) -> None:
        assert decide.decide_bash_command(UNPARSEABLE, {}, "deny")["action"] == "deny"

    def test_the_reason_names_the_policy_and_the_failure(self) -> None:
        result = decide.decide_bash_command(UNPARSEABLE, {"error": "deny"})
        assert result["reason"].startswith("error evaluating command (policy 'deny'): ")

    def test_no_config_at_all_asks(self) -> None:
        assert decide.decide_bash_command(UNPARSEABLE, {})["action"] == "ask"


def _no_shfmt() -> str:
    raise FileNotFoundError("shfmt binary not found. Please ensure shfmt-py is installed.")


class TestAMissingShfmtAlwaysAsks:
    """A missing shfmt is a broken install, not a command the policy can judge.

    ``error: allow`` means "run what I could not analyse"; applied here it
    approved every command, unchecked, for as long as shfmt was missing.
    """

    @pytest.mark.parametrize("config", [{"error": "allow"}, {"*": "allow"}, {"error": "deny"}, {"*": "deny"}, {}])
    def test_no_level_applies(self, config: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("lovely_bash_permissions.parser.find_shfmt", _no_shfmt)
        result = decide.decide_bash_command("rm -rf /", config)
        assert result["action"] == "ask"
        assert "shfmt is unavailable" in result["reason"]
        assert result["reasons"] == [result["reason"]]

    def test_a_shfmt_that_cannot_be_started_asks_too(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _exec_fails(*_args: object, **_kwargs: object) -> None:
            raise PermissionError("Permission denied")

        monkeypatch.setattr("lovely_bash_permissions.parser.subprocess.run", _exec_fails)
        assert decide.decide_bash_command("ls", {"error": "allow"})["action"] == "ask"

    def test_a_parse_failure_still_honours_error(self) -> None:
        """Only the install case is exempt; an unparseable command keeps its policy."""
        assert decide.decide_bash_command(UNPARSEABLE, {"error": "allow"})["action"] == "allow"
        assert decide.decide_bash_command(UNPARSEABLE, {"error": "deny"})["action"] == "deny"


class TestErrorAction:
    def test_falls_back_through_wildcard_to_ask(self) -> None:
        assert decide.error_action({"*": "deny"}, ValueError("x"))["action"] == "deny"
        assert decide.error_action({}, ValueError("x"))["action"] == "ask"

    def test_an_unparseable_level_asks_rather_than_crashing(self) -> None:
        result = decide.error_action({"error": "banana", "*": "deny"}, ValueError("x"))
        assert result["action"] == "ask"
        assert "policy 'banana'" in result["reason"]


class TestThisModuleSpeaksDeny:
    """D12, asserted rather than documented.

    `block` is Devin's wire vocabulary. This module is shared with a host that
    has never heard of it, and a `block` leaking in here would be a level the
    product does not have - invisible to the evaluator, and silently wrong on
    whichever host consumed it.
    """

    def test_no_block_in_the_code(self) -> None:
        """The word may appear in prose - here is why - but never in code.

        Comments and docstrings are excluded on purpose: this module's
        docstring exists to explain the seam, which means naming the other
        side of it. What must not exist is a *value* or an *identifier*, and
        those are what the AST walk collects.
        """
        import ast
        import pathlib

        tree = ast.parse(pathlib.Path(decide.__file__).read_text())
        docstrings = {
            id(node.body[0].value)
            for node in ast.walk(tree)
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        }
        offenders = [
            repr(node.value)
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and "block" in node.value
            and id(node) not in docstrings
        ]
        offenders += [node.id for node in ast.walk(tree) if isinstance(node, ast.Name) and "block" in node.id.lower()]
        assert offenders == [], f"decide.py must not contain Devin's wire vocabulary: {offenders}"

    @pytest.mark.parametrize(
        ("config", "action"),
        [({"*": "allow"}, "allow"), ({"*": "ask"}, "ask"), ({"*": "deny"}, "deny")],
    )
    def test_the_vocabulary_is_exactly_three_levels(self, config: dict[str, Any], action: str) -> None:
        assert set(decide.LEVEL_TO_ACTION) == {"allow", "ask", "deny"}
        assert decide.decide_bash_command("ls", config)["action"] == action


class TestTheErrorReasonIsReadable:
    """The `error` reason is a prompt bullet *and* a model-facing tool result.

    `ParseError.__str__` is a developer form: the command, an exit code, and
    shfmt's stderr repeating the message already on the first line. Reached here
    it was four lines and ~180 characters for every command the agent got
    syntactically wrong, and an embedded newline left the tail of the dump
    without its bullet. The verdict was always correct; only the explanation was
    for someone else's reader.
    """

    UNPARSEABLE = "ls > | f"  # `>` with no word

    def test_the_reason_is_one_line(self) -> None:
        reason = decide.decide_bash_command(self.UNPARSEABLE, {"*": "ask", "error": "deny"})["reason"]
        assert "\n" not in reason, reason

    def test_it_keeps_the_diagnostic(self) -> None:
        # The point of collapsing is brevity, not concealment: the user still
        # learns what is wrong with their command.
        reason = decide.decide_bash_command(self.UNPARSEABLE, {"*": "ask", "error": "deny"})["reason"]
        assert "must be followed by a word" in reason

    def test_it_drops_what_the_prompt_already_shows(self) -> None:
        reason = decide.decide_bash_command(self.UNPARSEABLE, {"*": "ask", "error": "deny"})["reason"]
        for redundant in ("Command:", "Exit code:", "Stderr:"):
            assert redundant not in reason, f"{redundant} is noise in a reason"

    def test_it_does_not_repeat_the_parser_message(self) -> None:
        # "Failed to parse: X" and "Stderr: X" is the same sentence twice.
        reason = decide.decide_bash_command(self.UNPARSEABLE, {"*": "ask", "error": "deny"})["reason"]
        assert reason.count("must be followed by a word") == 1

    def test_the_traceback_form_is_unchanged(self) -> None:
        # The verbose form is not removed, only kept away from the prompt: a
        # developer reading a traceback still wants the command and the exit code.
        from lovely_bash_permissions.parser import ParseError

        exc = ParseError("boom", command="ls > | f", returncode=1, stderr="boom again")
        assert "Command: 'ls > | f'" in str(exc)
        assert "Exit code: 1" in str(exc)
        assert "boom again" in str(exc)

    def test_an_exception_without_the_user_form_still_renders(self) -> None:
        # `error` is reached with more than ParseError - a converter failure, a
        # config problem. A missing `user_message` must not crash the reason.
        result = decide.error_action({"error": "deny"}, ValueError("something else"))
        assert "something else" in result["reason"]

    def test_an_empty_command_renders(self) -> None:
        result = decide.decide_bash_command("   ", {"*": "ask", "error": "deny"})
        assert result["action"] == "deny"
        assert "Empty command" in result["reason"]
        assert "\n" not in result["reason"]
