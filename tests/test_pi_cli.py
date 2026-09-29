"""Tests for pi_cli.py: the wire protocol, and --test.

Split in two halves on purpose. The protocol half drives `serve` and
`handle_request` in-process, so a failure points at a line rather than at a
pipe. The e2e half lives in `tests/test_protocol_e2e.py`, because the layer
this file cannot reach is the one that breaks - see that file's docstring.
"""

import io
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from lovely_bash_permissions import pi_cli

#: A command no config can parse, for the paths that must survive one.
UNPARSEABLE = "'unterminated"


def _request(**kwargs: object) -> str:
    return json.dumps(kwargs)


def _serve(*lines: str) -> list[dict[str, Any]]:
    """Run `lines` through the server loop and return the parsed responses."""
    out = io.StringIO()
    pi_cli.serve(io.StringIO("".join(f"{line}\n" for line in lines)), out)
    return [json.loads(line) for line in out.getvalue().splitlines()]


class TestFraming:
    """One response line per request line, always. The invariant everything else rests on.

    It is what lets the client count instead of correlate: no ids, no matching.
    Break it and a response written for one request is read as another's
    answer, which is silent and adversarial - a command that was never
    evaluated gets a verdict from a different command.
    """

    def test_one_response_per_request(self) -> None:
        responses = _serve(
            _request(op="evaluate", command="ls", config={"*": "ask"}, top_level="ask"),
            _request(op="validate", config={"*": "ask"}),
            _request(op="evaluate", command="ls", config={"*": "deny"}, top_level="deny"),
        )
        assert [r.get("action") or r.get("valid") for r in responses] == ["ask", True, "deny"]

    def test_responses_are_in_request_order(self) -> None:
        responses = _serve(*[_request(op="evaluate", command=f"echo {i}", config={"*": "deny"}) for i in range(6)])
        assert len(responses) == 6
        assert all(f'"echo {i}"' in r["reason"] or "echo" in r["reason"] for i, r in enumerate(responses))

    def test_a_malformed_line_desynchronises_by_exactly_one(self) -> None:
        responses = _serve(
            "this is not json",
            _request(op="evaluate", command="ls", config={"*": "ask"}, top_level="ask"),
        )
        assert len(responses) == 2
        assert "malformed request" in responses[0]["error"]
        assert responses[1]["action"] == "ask"

    def test_a_malformed_line_does_not_end_the_session(self) -> None:
        responses = _serve("{{{", "also bad", _request(op="validate", config={}))
        assert len(responses) == 3
        assert responses[-1]["valid"] is True

    def test_a_non_object_request_is_an_error_not_a_crash(self) -> None:
        responses = _serve("[1, 2, 3]", '"a string"', "null", _request(op="validate", config={}))
        assert len(responses) == 4
        assert all("malformed request" in r["error"] for r in responses[:3])
        assert responses[-1]["valid"] is True

    def test_blank_lines_are_not_requests(self) -> None:
        assert _serve("", "   ", _request(op="validate", config={})) == [{"protocol": 1, "valid": True}]

    def test_eof_returns_cleanly(self) -> None:
        assert pi_cli.serve(io.StringIO(""), io.StringIO()) == 0

    def test_protocol_is_on_every_line_not_just_validate(self) -> None:
        """So the client can assert it on the first exchange it sees, whichever op it sent."""
        for line in _serve(
            _request(op="evaluate", command="ls", config={"*": "ask"}, top_level="ask"),
            _request(op="validate", config={}),
            "garbage",
            _request(op="whatever"),
        ):
            assert line["protocol"] == pi_cli.PROTOCOL_VERSION

    def test_an_internal_error_becomes_a_response_not_a_crash(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def explode(_request: object) -> dict[str, Any]:
            raise RuntimeError("kaboom")

        monkeypatch.setattr(pi_cli, "handle_request", explode)
        responses = _serve(_request(op="validate", config={}))
        assert len(responses) == 1
        assert "kaboom" in responses[0]["error"]

    def test_the_response_is_json_serialisable(self) -> None:
        """The reason strings carry quotes, newlines and shell text; they must survive."""
        responses = _serve(_request(op="evaluate", command="echo 'a\"b'", config={"*": "deny"}))
        assert json.loads(json.dumps(responses[0])) == responses[0]


class TestEvaluateOp:
    def test_action_comes_from_the_policy(self) -> None:
        for level, action in (("allow", "allow"), ("ask", "ask"), ("deny", "deny")):
            response = pi_cli.handle_request(_parse(_request(op="evaluate", command="ls", config={"*": level})))
            assert response["action"] == action

    def test_reasons_are_carried_through(self) -> None:
        response = pi_cli.handle_request(
            _parse(_request(op="evaluate", command="ls > f", config={"*": "ask", "output_redirection": "deny"}))
        )
        assert response["action"] == "deny"
        assert len(response["reasons"]) >= 1
        assert "; ".join(response["reasons"]) == response["reason"]

    def test_a_level_is_rendered_as_a_word_not_an_enum(self) -> None:
        """`wildcard policy is PermissionLevel.deny` is a bug a test can hold still.

        The validated block is dumped for the evaluator, and dumping without
        `mode="json"` leaves the enum members in place. They compare equal to
        their string values, so every policy still resolves correctly - and
        every reason the user reads is wrong.
        """
        response = pi_cli.handle_request(_parse(_request(op="evaluate", command="ls", config={"*": "deny"})))
        assert "PermissionLevel" not in response["reason"]

    def test_an_invalid_config_denies_rather_than_evaluating(self) -> None:
        response = pi_cli.handle_request(
            _parse(_request(op="evaluate", command="ls", config={"permission": "allow"}, top_level="allow"))
        )
        assert response["action"] == "deny"
        assert "unknown bash config key 'permission'" in response["reason"]

    def test_an_invalid_config_never_reports_the_command_as_evaluated(self) -> None:
        """Fail closed: the verdict is about the config, not about the command."""
        response = pi_cli.handle_request(
            _parse(_request(op="evaluate", command="ls", config={"nonsense": 1}, top_level="allow"))
        )
        assert "ls" not in response["reason"]

    def test_a_non_string_command_denies(self) -> None:
        for command in (None, 123, ["ls"]):
            response = pi_cli.handle_request(_parse(_request(op="evaluate", command=command, config={"*": "allow"})))
            assert response["action"] == "deny"
            assert "must be a string" in response["reason"]


class TestTopLevelCarriesTheModeWildcard:
    """A block with no `*` of its own is not a policy; `top_level` is how it learns the mode's.

    The two halves below produce the same command, the same block and the same
    `reasons`; only the wildcard differs. That is the whole seam, and it is
    invisible unless a command is left to the wildcard to decide.
    """

    def test_the_mode_wildcard_supplies_a_missing_star(self) -> None:
        request = _parse(_request(op="evaluate", command="git status", config={"allowed_cmds_regex": ["^ls"]}))
        assert pi_cli.handle_request(request | {"top_level": "allow"})["action"] == "allow"

    def test_its_absence_falls_back_to_ask(self) -> None:
        request = _parse(_request(op="evaluate", command="git status", config={"allowed_cmds_regex": ["^ls"]}))
        assert pi_cli.handle_request(request)["action"] == "ask"

    def test_a_block_star_wins_over_the_mode_wildcard(self) -> None:
        request = _parse(_request(op="evaluate", command="ls", config={"*": "deny"}, top_level="allow"))
        assert pi_cli.handle_request(request)["action"] == "deny"

    def test_the_field_is_not_spliced_into_the_block(self) -> None:
        """The client sends the block as the file declares it.

        Splicing a resolved `*` in would work numerically and be wrong in
        substance: `validate` would then check a config that differs from the
        one on disk, and a user reading its error would be chasing a key they
        never typed.
        """
        assert "_top_level" not in json.dumps(
            pi_cli.handle_request(
                _parse(_request(op="evaluate", command="ls", config={"allowed_cmds_regex": ["^ls"]}, top_level="allow"))
            )
        )


class TestValidateOp:
    def test_a_good_config_validates(self) -> None:
        assert pi_cli.handle_request(_parse(_request(op="validate", config={"*": "ask", "subshell": "deny"}))) == {
            "protocol": pi_cli.PROTOCOL_VERSION,
            "valid": True,
        }

    def test_an_unknown_key_reports_the_validator_message_verbatim(self) -> None:
        response = pi_cli.handle_request(_parse(_request(op="validate", config={"permission": "allow"})))
        assert response["valid"] is False
        assert "unknown bash config key 'permission'" in response["error"]
        assert "'*'" in response["error"]

    def test_the_message_carries_no_pydantic_internals(self) -> None:
        """The extension puts this string in front of a user."""
        response = pi_cli.handle_request(_parse(_request(op="validate", config={"permission": "allow"})))
        assert "type=value_error" not in response["error"]
        assert "errors.pydantic.dev" not in response["error"]

    def test_a_missing_shfmt_is_reported(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The one failure process health cannot see. See 6.3 / the module docstring.

        `find_shfmt` is the whole probe: the server is up, the handshake
        passes, and every command would otherwise route through the `error`
        policy - which is `allow` under `{"*": "allow"}`. A live-looking
        process with a wide-open shell is the worst of the two outcomes, so
        the probe has to fail loudly.
        """
        monkeypatch.setattr(pi_cli, "find_shfmt", _raise(FileNotFoundError("shfmt binary not found.")))
        response = pi_cli.handle_request(_parse(_request(op="validate", config={"*": "ask"})))
        assert response["valid"] is False
        assert "shfmt" in response["error"]
        assert "shfmt-py" in response["error"], "the message must name the package that provides the binary"

    def test_a_missing_shfmt_is_reported_even_when_the_config_is_fine(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(pi_cli, "find_shfmt", _raise(FileNotFoundError("nope")))
        assert pi_cli.handle_request(_parse(_request(op="validate", config={})))["valid"] is False

    def test_the_probe_passes_when_the_binary_is_there(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The positive case is not enough on its own - it passed by accident for a while."""
        monkeypatch.setattr(pi_cli, "find_shfmt", lambda: "/usr/bin/shfmt")
        assert pi_cli.handle_request(_parse(_request(op="validate", config={"*": "ask"})))["valid"] is True

    def test_validate_ignores_the_top_level_field(self) -> None:
        """It validates the bash block, and says so. `top_level` is not a block key."""
        assert pi_cli.handle_request(_parse(_request(op="validate", config={"top_level": "allow"})))["valid"] is False


class TestUnknownOp:
    def test_it_is_an_error_response(self) -> None:
        response = pi_cli.handle_request(_parse(_request(op="shutdown")))
        assert response["valid"] is False
        assert "unknown op" in response["error"]

    def test_a_missing_op_is_an_error_response(self) -> None:
        assert "unknown op" in pi_cli.handle_request(_parse(_request(config={})))["error"]


class TestTestMode:
    """`--test` is a developer tool, and its one job is to answer the same question the server does."""

    def test_a_bare_block_from_stdin(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        config = tmp_path / "c.jsonc"
        config.write_text('{"*": "allow", "allowed_cmds_regex": ["^ls(\\\\s|$)"]}')
        assert _exit_code("ls -la", str(config), None) == pi_cli.EXIT_VERDICT

    def test_exit_codes_distinguish_a_verdict_from_a_broken_invocation(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        config = tmp_path / "c.jsonc"
        config.write_text('{"*": "deny"}')
        assert _exit_code("ls", str(config), None) == pi_cli.EXIT_DENY
        assert _exit_code("ls", str(tmp_path / "missing.jsonc"), None) == pi_cli.EXIT_USAGE
        assert _exit_code("ls", str(config), None) == pi_cli.EXIT_DENY

    def test_an_invalid_config_produces_no_verdict(self, tmp_path: Path) -> None:
        config = tmp_path / "c.jsonc"
        config.write_text('{"permission": "allow"}')
        assert _exit_code("ls", str(config), None) == pi_cli.EXIT_USAGE

    def test_a_mode_wrapped_file_uses_its_first_mode(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Every real Pi config file is mode-wrapped, and reading one as a bare block
        would not fail loudly - it would evaluate an empty policy and answer `ask`
        for everything, which is indistinguishable from a correct pessimistic
        policy."""
        config = tmp_path / "pi.jsonc"
        config.write_text('{"default": {"bash": {"allowed_cmds_regex": ["^ls"]}}, "strict": {"bash": {"*": "deny"}}}')
        assert _exit_code("ls", str(config), None) == pi_cli.EXIT_VERDICT
        assert "using mode 'default'" in capsys.readouterr().err

    def test_mode_selection(self, tmp_path: Path) -> None:
        config = tmp_path / "pi.jsonc"
        config.write_text('{"default": {"bash": {"*": "allow"}}, "strict": {"bash": {"*": "deny"}}}')
        assert _exit_code("ls", str(config), "strict") == pi_cli.EXIT_DENY
        assert _exit_code("ls", str(config), "default") == pi_cli.EXIT_VERDICT

    def test_a_mode_star_becomes_the_top_level_wildcard(self, tmp_path: Path) -> None:
        """6.4b rule 5, and the seam bug it prevents.

        A mode is `{"<mode>": {"*": ..., "bash": {...}}}`, and that `*` is
        exactly the fallback a bash block's own missing `*` resolves against.
        Omit it and `--test` reports `ask` where the live extension reports
        `allow` - a confident wrong answer about a policy that is in force.
        """
        config = tmp_path / "pi.jsonc"
        config.write_text('{"m": {"*": "allow", "bash": {"allowed_cmds_regex": ["^ls"]}}}')
        assert _exit_code("git status", str(config), "m") == pi_cli.EXIT_VERDICT
        # The same block without the mode's "*" is a bare ask.
        bare = tmp_path / "bare.jsonc"
        bare.write_text('{"allowed_cmds_regex": ["^ls"]}')
        assert _exit_code("git status", str(bare), None) == pi_cli.EXIT_VERDICT

    def test_a_mode_with_no_bash_block_is_an_error(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Never an empty policy. A verdict computed from nothing is the one outcome
        that must be unreachable, because it is indistinguishable from a policy."""
        config = tmp_path / "pi.jsonc"
        config.write_text('{"default": {"read": {"*": "ask"}}}')
        assert _exit_code("ls", str(config), None) == pi_cli.EXIT_USAGE
        assert "no 'bash' block" in capsys.readouterr().err

    def test_an_unknown_mode_names_the_modes_that_exist(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        config = tmp_path / "pi.jsonc"
        config.write_text('{"default": {"bash": {}}, "strict": {"bash": {}}}')
        assert _exit_code("ls", str(config), "nope") == pi_cli.EXIT_USAGE
        err = capsys.readouterr().err
        assert "unknown mode 'nope'" in err
        assert "'default'" in err and "'strict'" in err

    def test_a_single_key_dict_policy_is_not_a_mode(self, tmp_path: Path) -> None:
        """`{"output_redirection": {...}}` is one key and one dict value - a bash block.

        Detect modes by "every value is a dict" alone and this ordinary config
        becomes a mode called `output_redirection`, with no bash block in it.
        """
        config = tmp_path / "c.jsonc"
        config.write_text('{"output_redirection": {"other": "deny"}}')
        assert _exit_code("ls > f", str(config), None) == pi_cli.EXIT_DENY

    def test_a_whole_permissions_config_is_accepted(self, tmp_path: Path) -> None:
        config = tmp_path / "c.jsonc"
        config.write_text('{"version": 1, "bash": {"*": "deny"}}')
        assert _exit_code("ls", str(config), None) == pi_cli.EXIT_DENY

    def test_a_path_is_read_as_given_and_never_merged(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Config resolution belongs to the extension; a merge here would be a
        *different* config from the one in force, which is worse than none."""
        from lovely_bash_permissions.config import loader

        def explode(_project_dir: str) -> tuple[dict[str, Any], list[str], list[str]]:
            raise AssertionError("--test must not run the Devin loader")

        monkeypatch.setattr(loader, "load_permissions_config", explode)
        config = tmp_path / "c.jsonc"
        config.write_text('{"*": "deny"}')
        assert _exit_code("ls", str(config), None) == pi_cli.EXIT_DENY

    def test_stdin_is_the_fallback(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
        monkeypatch.setattr(sys, "stdin", io.StringIO('{"*": "deny"}'))
        assert _exit_code("ls", None, None) == pi_cli.EXIT_DENY

    def test_the_verdict_is_printed_with_its_reasons(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        config = tmp_path / "c.jsonc"
        config.write_text('{"*": "ask", "output_redirection": "deny"}')
        _exit_code("ls > f", str(config), None)
        out = capsys.readouterr().out.splitlines()
        assert out[-1].startswith("deny: ")
        assert any(line.startswith("- ") for line in out[:-1]), "each reason is its own bullet"


class TestTheEntryPoint:
    """`main` is where the two modes are told apart, and a mix-up there is silent."""

    def test_no_arguments_serves(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[int] = []

        def fake_serve(*_args: object, **_kwargs: object) -> int:
            calls.append(1)
            return 0

        monkeypatch.setattr(sys, "argv", ["lovely-pi-bash-permissions"])
        monkeypatch.setattr(pi_cli, "serve", fake_serve)
        with pytest.raises(SystemExit) as exit_info:
            pi_cli.main()
        assert exit_info.value.code == 0
        assert calls == [1]

    @pytest.mark.parametrize(
        "argv",
        [["--test"], ["--mode", "strict"], ["ls"], ["--mode", "strict", "ls"]],
    )
    def test_a_bare_argv_is_a_usage_error(self, argv: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
        def unreachable() -> int:
            raise AssertionError("must not serve when the invocation is not server mode")

        monkeypatch.setattr(pi_cli, "serve", unreachable)
        monkeypatch.setattr(sys, "argv", ["lovely-pi-bash-permissions", *argv])
        with pytest.raises(SystemExit) as exit_info:
            pi_cli.main()
        assert exit_info.value.code == pi_cli.EXIT_USAGE

    def test_test_flag_with_a_command_and_a_path(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """The documented form, including `--test --mode strict "cmd"`.

        With `--test` taking a value, argparse refuses the option-looking
        `--mode` as that value and errors out - the plan's own example command
        did not run.
        """
        config = tmp_path / "pi.jsonc"
        config.write_text('{"default": {"bash": {"*": "allow"}}, "strict": {"bash": {"*": "deny"}}}')
        seen: list[tuple[str, str | None, str | None]] = []

        def fake_run_test(command: str, path: str | None, mode: str | None) -> int:
            seen.append((command, path, mode))
            return 0

        monkeypatch.setattr(pi_cli, "run_test", fake_run_test)
        monkeypatch.setattr(
            sys, "argv", ["lovely-pi-bash-permissions", "--test", "--mode", "strict", "ls", str(config)]
        )
        with pytest.raises(SystemExit) as exit_info:
            pi_cli.main()
        assert exit_info.value.code == 0
        assert seen == [("ls", str(config), "strict")]

    def test_help_mentions_read_as_given(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sys, "argv", ["lovely-pi-bash-permissions", "--help"])
        with pytest.raises(SystemExit):
            pi_cli.main()
        out = capsys.readouterr().out
        assert "never located" in out
        assert "discovered" in out


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _exit_code(command: str, path: str | None, mode: str | None) -> int:
    """`pi_cli.run_test`'s exit code, whether it returns one or exits with it.

    `_fail` calls sys.exit rather than returning, because at the top level of a
    CLI they are the same thing. A test that has to wrap every call in
    `pytest.raises` stops reading the exit codes, which are the thing worth
    reading.
    """
    try:
        return pi_cli.run_test(command, path, mode)
    except SystemExit as exit_info:
        code = exit_info.code
        assert isinstance(code, int)
        return code


def _parse(line: str) -> dict[str, Any]:
    parsed = json.loads(line)
    assert isinstance(parsed, dict)
    return parsed


def _raise(exc: BaseException) -> Any:  # noqa: ANN401 - a stand-in for find_shfmt that raises
    def _inner() -> str:
        raise exc

    return _inner


class TestThePathsAUserHits:
    """The error branches, which are the ones a user actually meets.

    Each names what it could not read and exits 1, so a script can tell a
    broken invocation from a verdict - which is the distinction a CI check
    needs most and the one `--test` exists to serve.
    """

    def test_an_unreadable_file(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        assert _exit_code("ls", str(tmp_path / "nope.jsonc"), None) == pi_cli.EXIT_USAGE
        assert "cannot read config" in capsys.readouterr().err

    def test_a_file_that_is_not_jsonc(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        config = tmp_path / "c.jsonc"
        config.write_text("{ this is not jsonc")
        assert _exit_code("ls", str(config), None) == pi_cli.EXIT_USAGE
        assert "cannot read config" in capsys.readouterr().err

    def test_a_file_that_is_not_an_object(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        config = tmp_path / "c.jsonc"
        config.write_text("[1, 2, 3]")
        assert _exit_code("ls", str(config), None) == pi_cli.EXIT_USAGE
        assert "cannot read config" in capsys.readouterr().err

    def test_stdin_that_is_not_jsonc(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
        monkeypatch.setattr(sys, "stdin", io.StringIO("not jsonc at all"))
        assert _exit_code("ls", None, None) == pi_cli.EXIT_USAGE
        assert "cannot parse config" in capsys.readouterr().err

    def test_stdin_that_is_not_an_object(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(sys, "stdin", io.StringIO("[]"))
        assert _exit_code("ls", None, None) == pi_cli.EXIT_USAGE
        assert "no bash block" in capsys.readouterr().err

    def test_stdin_accepts_jsonc_exactly_as_a_file_does(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A comment and a trailing comma are legal in both routes or in neither.

        A file the user wrote may have both; a file piped to `--test` is the
        same file, and the difference would read as a bug in the tool.
        """
        text = '{\n  // a comment\n  "*": "deny",\n}\n'
        config = tmp_path / "c.jsonc"
        config.write_text(text)
        assert _exit_code("ls", str(config), None) == pi_cli.EXIT_DENY
        monkeypatch.setattr(sys, "stdin", io.StringIO(text))
        assert _exit_code("ls", None, None) == pi_cli.EXIT_DENY

    def test_a_mode_flag_on_a_bare_block(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        config = tmp_path / "c.jsonc"
        config.write_text('{"*": "deny"}')
        assert _exit_code("ls", str(config), "strict") == pi_cli.EXIT_USAGE
        assert "bare bash block" in capsys.readouterr().err

    def test_an_empty_command(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        config = tmp_path / "c.jsonc"
        config.write_text('{"*": "deny"}')
        assert _exit_code("   ", str(config), None) == pi_cli.EXIT_USAGE
        assert "no command" in capsys.readouterr().err

    def test_no_config_and_no_stdin_is_a_usage_error_not_a_hang(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A terminal with nothing piped in would block forever, reading as a hang."""
        monkeypatch.setattr(sys, "stdin", io.StringIO(""))
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)
        monkeypatch.setattr(sys, "argv", ["lovely-pi-bash-permissions", "--test", "ls"])
        with pytest.raises(SystemExit) as exit_info:
            pi_cli.main()
        assert exit_info.value.code == pi_cli.EXIT_USAGE
        assert "no config given" in capsys.readouterr().err

    def test_a_non_pydantic_validation_error_still_renders(self) -> None:
        """`error_action`'s fallbacks handle errors that are not pydantic's.

        The message has to survive that: a helper that assumed `.errors()`
        exists would raise a second error while reporting the first.
        """
        assert pi_cli._pydantic_message(ValueError("plain")) == "plain"
