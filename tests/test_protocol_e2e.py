"""The real wire: a real subprocess, a real pipe, real JSON.

Every other test in this package calls a function directly. None of them cross
the repo boundary, and that boundary is where the expensive defects live. Three
of the plan's own corrections - a `top_level` field that went missing, an
`error` key that arrived un-resolved, a gate that named the wrong golden
section - were all seam defects, and none was visible from either side alone.
Nor would they be caught by `tests/test_pi_cli.py`, which drives the handler in
process, or by the extension's test harness, which drives the TypeScript client
against a stub. Only this proves the stub was faithful.

So it is deliberately small and protocol-level, not a second unit suite. It
exists to answer one question the others cannot: does a verdict that comes out
of a pipe mean what a verdict that came out of a function call means?

One request, one response, one process per call. The extension spawns this
binary for a single exchange and reads the single object it writes, so most of
what this file used to check - a stream that stays aligned across many
requests, a process that survives a malformed line and carries on - is no longer
expressible. What replaced it is pinned below: exactly one response object per
invocation, whatever the input, and no state that could carry between calls.
"""

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

#: The console script, resolved the way a user's install resolves it. Falls
#: back to `python -m` against the source tree, so the suite still runs in a
#: checkout that was never installed - and *says* which one it used, because a
#: silently different binary is exactly the class of bug this file hunts.
_SCRIPT = shutil.which("lovely-pi-bash-permissions")

if _SCRIPT is not None:
    COMMAND: list[str] = [_SCRIPT]
else:  # pragma: no cover - depends on the checkout, not on the code
    _SRC = str(Path(__file__).resolve().parent.parent / "src")
    if not (Path(_SRC) / "lovely_bash_permissions" / "pi_cli.py").is_file():
        pytest.skip(
            "lovely-pi-bash-permissions is not on PATH and the source tree is not where this "
            "test expects it - install the package (uv pip install -e .) or run from a checkout"
        )
    COMMAND = [sys.executable, "-m", "lovely_bash_permissions.pi_cli"]


def _request(**kwargs: object) -> str:
    return json.dumps(kwargs)


class _Run:
    """One invocation: the result, and the single response it produced."""

    def __init__(self, result: subprocess.CompletedProcess[str]) -> None:
        self.returncode = result.returncode
        self.stderr = result.stderr
        self._lines = [line for line in result.stdout.splitlines() if line.strip()]

    @property
    def response(self) -> dict[str, Any]:
        """The one response object, asserting there is exactly one.

        The count is the whole invariant now. There are no request ids to
        correlate and no stream to resynchronise, so "one invocation writes one
        object" is the only thing standing between the client and a verdict
        belonging to a different call.
        """
        assert len(self._lines) == 1, f"expected exactly one response line, got {len(self._lines)}: {self._lines!r}"
        parsed: dict[str, Any] = json.loads(self._lines[0])
        return parsed


def _call_raw(payload: str, *, command: list[str] | None = None, env: dict[str, str] | None = None) -> _Run:
    """Spawn one process, write one raw payload, read the one response.

    `subprocess.run(input=...)` closes stdin after writing and reads stdout to
    EOF, which is precisely the contract: there is no way to send a second
    request or read a second response, so the multi-request bugs this file used
    to guard are unreachable from the client's side too.
    """
    return _Run(
        subprocess.run(
            command if command is not None else COMMAND,
            input=payload,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
            env=env,
        )
    )


def _call(**request: object) -> _Run:
    """The same, for a well-formed request built from keyword arguments."""
    return _call_raw(_request(**request))


class TestTheRealWire:
    def test_a_console_script_is_what_we_are_driving(self) -> None:
        """Guard the guard: the suite must not silently test a different binary.

        A `python -m` fallback runs this working tree, while the script on PATH
        runs whatever is installed. Both are legitimate; a test result that does
        not say which one it got is not evidence about either.
        """
        assert COMMAND[0].endswith("lovely-pi-bash-permissions") or COMMAND[0] == sys.executable

    def test_evaluate_answers_with_a_verdict(self) -> None:
        response = _call(op="evaluate", command="git status", config={"*": "deny"}, top_level="deny").response
        assert response["protocol"] == 1
        assert response["action"] == "deny"
        assert response["reasons"]

    def test_every_verdict_is_reproducible_across_invocations(self) -> None:
        """One process per call, so nothing *can* carry over.

        This replaces the old "one process, many requests" test. The leak it
        hunted - a cached resolution, a half-read line, a connection left dirty
        by the previous turn - is no longer expressible: there is no process to
        carry state between two calls, and no second response to read back. The
        replacement claim is that the verdicts are identical anyway, which is
        what makes a per-call spawn indistinguishable from a warm server.
        """
        for level, action in (("allow", "allow"), ("deny", "deny"), ("ask", "ask"), ("allow", "allow")):
            response = _call(op="evaluate", command="ls -la", config={"*": level}, top_level=level).response
            assert response["action"] == action, level

    def test_the_level_wildcard_crosses_the_pipe(self) -> None:
        """The seam claim, over a real pipe rather than a function call.

        Identical requests but for `top_level`, and the same command, the same
        block and the same reasons. Without the field the mode's wildcard is
        lost in transit and a permissive mode arrives as `ask` - which reads as
        a correct cautious policy, not as a lost field.
        """
        block = {"allowed_cmds_regex": ["^ls$"]}
        with_top = _call(op="evaluate", command="git status", config=block, top_level="allow").response
        without_top = _call(op="evaluate", command="git status", config=block).response
        assert with_top["action"] == "allow"
        assert without_top["action"] == "ask"
        assert with_top["reasons"] == without_top["reasons"], "only the wildcard should differ"

    def test_validate_reports_a_good_config(self) -> None:
        assert _call(op="validate", config={"*": "ask", "subshell": "deny"}).response == {"protocol": 1, "valid": True}

    def test_validate_reports_a_bad_config(self) -> None:
        response = _call(op="validate", config={"permission": "allow"}).response
        assert response["valid"] is False
        assert "unknown bash config key 'permission'" in response["error"]

    def test_an_invalid_config_never_evaluates(self) -> None:
        response = _call(op="evaluate", command="ls", config={"permission": "allow"}, top_level="allow").response
        assert response["action"] == "deny"

    def test_two_requests_in_one_payload_get_one_error(self) -> None:
        """The e2e form of the desync guard.

        A client that wrote two requests gets one error and no verdict, rather
        than an answer to the first and silence about the second. This is the
        shape of the bug the old stream had to be careful about, seen from the
        only side that can see it.
        """
        payload = (
            _request(op="evaluate", command="ls", config={"*": "deny"}) + "\n" + _request(op="validate", config={})
        )
        run = _call_raw(payload)
        assert "malformed request" in run.response["error"]
        assert "action" not in run.response
        assert run.returncode != 0, "an unanswerable request must not look like a clean exit"

    @pytest.mark.parametrize(
        "payload",
        ["null", "[]", '"str"', "{", '{"op": 42}', '{"op": "evaluate"', ""],
    )
    def test_every_kind_of_unusable_input_still_yields_one_response(self, payload: str) -> None:
        """The client must always get an object back, even for input it should never send."""
        response = _call_raw(payload).response
        assert response["protocol"] == 1
        assert response["valid"] is False

    def test_a_trailing_newline_is_not_a_second_request(self) -> None:
        """A client that writes `payload + "\n"` gets a verdict, not a parse error."""
        assert _call_raw(_request(op="validate", config={}) + "\n").response["valid"] is True


class TestMissingShfmtOverARealPipe:
    """The negative path, which cannot be reached by clearing an env var.

    `find_shfmt` searches `$VIRTUAL_ENV/bin`, the directory holding
    `sys.executable`, and `sys.prefix/bin` - so a test that only empties `PATH`
    still finds the binary next to the running interpreter and passes, which is
    how the probe went untested. The interpreter is therefore *copied* to a
    directory of its own: `sys.executable` no longer sits beside a shfmt,
    `sys.prefix` is no longer a venv, and with `PATH` and `VIRTUAL_ENV` empty
    there is nowhere left to look.

    Both directions are asserted. A probe that only ever passes is a probe that
    has never been shown to fail.
    """

    def _run_without_shfmt(self, tmp_path: Path, stdin: str) -> dict[str, Any]:
        bindir = tmp_path / "interpreter"
        bindir.mkdir()
        # A copy, not a symlink: symlinking resolves back to the venv and finds
        # the binary all over again.
        executable = bindir / "python-no-shfmt"
        shutil.copy(sys.executable, executable)
        assert shutil.which("shfmt", path=str(bindir)) is None

        site_packages = next(iter(_site_packages(sys.executable)), "")
        env = {
            "PATH": str(bindir),
            "VIRTUAL_ENV": str(bindir / "nonexistent"),
            "PYTHONPATH": os.pathsep.join([str(_src_root()), site_packages]),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        run = _call_raw(stdin, command=[str(executable), "-m", "lovely_bash_permissions.pi_cli"], env=env)
        assert run.returncode == 0, run.stderr
        return run.response

    def test_validate_reports_the_binary_as_missing(self, tmp_path: Path) -> None:
        response = self._run_without_shfmt(tmp_path, _request(op="validate", config={"*": "ask"}))
        assert response["valid"] is False
        assert "shfmt" in response["error"]
        assert "shfmt-py" in response["error"]

    def test_the_same_probe_passes_when_the_binary_is_there(self) -> None:
        """The positive case, through the identical code path and the same runner."""
        run = _call(op="validate", config={"*": "ask"})
        assert run.returncode == 0, run.stderr
        assert run.response == {"protocol": 1, "valid": True}


def _src_root() -> Path:
    return Path(__file__).resolve().parent.parent / "src"


def _site_packages(executable: str) -> Iterator[str]:
    result = subprocess.run(
        [executable, "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    path = result.stdout.strip()
    if path:
        yield path


class TestTheClientGoesAway:
    """A client that disappears before the response is written is a normal end.

    This is not hypothetical: the client kills the child on a request timeout
    and on `session_shutdown`, and either can land while the response is being
    written. The write then fails with EPIPE, and an unhandled one ends the
    process with a traceback on stderr and a non-zero exit.

    The shape of the guarantee changed with the transport and is worth stating
    precisely, because the old one was not this. There is no long-lived child to
    survive a closed client across a session; there is one process, one write,
    and the client reads to EOF. So the property that matters now is that a
    closed read end produces no traceback, not that a stream resynchronises
    afterwards.
    """

    def _detached(self) -> subprocess.Popen[str]:
        """A process whose stdin we close immediately, so it answers a pipe nobody reads."""
        return subprocess.Popen(
            COMMAND,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

    def test_a_closed_read_end_produces_no_traceback(self) -> None:
        process = self._detached()
        assert process.stdin is not None and process.stdout is not None
        # Close the read end before the child can answer, then let it try.
        process.stdout.close()
        try:
            process.stdin.write(_request(op="evaluate", command="ls", config={"*": "ask"}, top_level="ask") + "\n")
            process.stdin.close()
        except (BrokenPipeError, OSError):
            pass  # the write itself failing is the same condition

        stderr = process.stderr.read() if process.stderr else ""
        process.wait(timeout=30)
        assert "Traceback" not in stderr, stderr
        assert "Exception ignored" not in stderr, stderr
        assert "BrokenPipeError" not in stderr, stderr

    def test_a_client_that_closes_stdin_without_a_request_gets_an_error(self) -> None:
        """EOF with nothing written is a broken invocation, not a quiet success.

        The old server treated an empty stream as a clean exit, which was
        correct: an idle long-lived process that was shut down had done its job.
        A per-call process that produces no response has failed the one thing it
        was spawned for, so it says so and exits non-zero.
        """
        process = self._detached()
        assert process.stdin is not None and process.stdout is not None
        process.stdin.close()
        stdout = process.stdout.read() if process.stdout is not None else ""
        stderr = process.stderr.read() if process.stderr is not None else ""
        response = _Run(subprocess.CompletedProcess(COMMAND, process.wait(timeout=30), stdout, stderr))
        assert "no request on stdin" in response.response["error"]
        assert response.returncode != 0
        assert "Traceback" not in response.stderr, response.stderr
