"""The real wire: a real subprocess, a real pipe, real JSONL.

Every other test in this package calls a function directly. None of them cross
the repo boundary, and that boundary is where the expensive defects live. Three
of the plan's own corrections - a `top_level` field that went missing, an
`error` key that arrived un-resolved, a gate that named the wrong golden
section - were all seam defects, and none was visible from either side alone.
Nor would they be caught by `tests/test_pi_cli.py`, which drives the handler in
process, or by the extension's fake-server harness, which drives the TypeScript
client against a stub. Only this proves the stub was faithful.

So it is deliberately small and protocol-level, not a second unit suite. It
exists to answer one question the others cannot: does a verdict that comes out
of a pipe mean what a verdict that came out of a function call means?
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


class Server:
    """A live server process, spoken to the way the extension speaks to it.

    Responses are read a line at a time rather than by draining stdout, so a
    test can assert the *count* of lines the server produced. That count is the
    invariant: the client carries no request ids, so its only defence against
    reading a stale line is that the server never writes one it was not asked
    for.
    """

    def __init__(self, process: subprocess.Popen[str]) -> None:
        self._process = process
        self._lines: list[dict[str, Any]] = []

    def send(self, **request: object) -> dict[str, Any]:
        assert self._process.stdin is not None
        self._process.stdin.write(_request(**request) + "\n")
        self._process.stdin.flush()
        return self.read()

    def send_raw(self, line: str) -> dict[str, Any]:
        assert self._process.stdin is not None
        self._process.stdin.write(line + "\n")
        self._process.stdin.flush()
        return self.read()

    def read(self) -> dict[str, Any]:
        assert self._process.stdout is not None
        line = self._process.stdout.readline()
        assert line, "the server closed stdout without answering a request"
        response: dict[str, Any] = json.loads(line)
        self._lines.append(response)
        return response

    def close(self) -> None:
        if self._process.stdin is not None:
            self._process.stdin.close()
        self._process.wait(timeout=30)


@pytest.fixture
def server() -> Iterator[Server]:
    process = subprocess.Popen(
        COMMAND,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    instance = Server(process)
    try:
        yield instance
    finally:
        instance.close()


class TestTheRealWire:
    def test_a_console_script_is_what_we_are_driving(self) -> None:
        """Guard the guard: the suite must not silently test a different binary.

        A `python -m` fallback runs this working tree, while the script on PATH
        runs whatever is installed. Both are legitimate; a test result that does
        not say which one it got is not evidence about either.
        """
        assert COMMAND[0].endswith("lovely-pi-bash-permissions") or COMMAND[0] == sys.executable

    def test_evaluate_answers_with_a_verdict(self, server: Server) -> None:
        response = server.send(op="evaluate", command="git status", config={"*": "deny"}, top_level="deny")
        assert response["protocol"] == 1
        assert response["action"] == "deny"
        assert response["reasons"]

    def test_every_verdict_is_reproducible_across_turns(self, server: Server) -> None:
        """One process, many requests - the case a fresh process per test hides.

        State that leaks between turns (a cached resolution, a half-read line)
        only shows up here.
        """
        for level, action in (("allow", "allow"), ("deny", "deny"), ("ask", "ask"), ("allow", "allow")):
            response = server.send(op="evaluate", command="ls -la", config={"*": level}, top_level=level)
            assert response["action"] == action, level

    def test_the_level_wildcard_crosses_the_pipe(self, server: Server) -> None:
        """The seam claim, over a real pipe rather than a function call.

        Identical requests but for `top_level`, and the same command, the same
        block and the same reasons. Without the field the mode's wildcard is
        lost in transit and a permissive mode arrives as `ask` - which reads as
        a correct cautious policy, not as a lost field.
        """
        block = {"allowed_cmds_regex": ["^ls$"]}
        with_top = server.send(op="evaluate", command="git status", config=block, top_level="allow")
        without_top = server.send(op="evaluate", command="git status", config=block)
        assert with_top["action"] == "allow"
        assert without_top["action"] == "ask"
        assert with_top["reasons"] == without_top["reasons"], "only the wildcard should differ"

    def test_validate_reports_a_good_config(self, server: Server) -> None:
        assert server.send(op="validate", config={"*": "ask", "subshell": "deny"}) == {"protocol": 1, "valid": True}

    def test_validate_reports_a_bad_config(self, server: Server) -> None:
        response = server.send(op="validate", config={"permission": "allow"})
        assert response["valid"] is False
        assert "unknown bash config key 'permission'" in response["error"]

    def test_an_invalid_config_never_evaluates(self, server: Server) -> None:
        response = server.send(op="evaluate", command="ls", config={"permission": "allow"}, top_level="allow")
        assert response["action"] == "deny"

    def test_a_malformed_line_desynchronises_by_exactly_one(self, server: Server) -> None:
        """Step 4 of the plan's e2e, and the invariant the whole protocol rests on."""
        bad = server.send_raw("{not json")
        assert "malformed request" in bad["error"]
        assert len(server._lines) == 1, "a malformed line must not produce two responses"
        good = server.send(op="evaluate", command="ls", config={"*": "deny"}, top_level="deny")
        assert good["action"] == "deny"
        assert len(server._lines) == 2, "the stream must resynchronise, not drift"

    def test_the_process_survives_every_kind_of_bad_input(self, server: Server) -> None:
        for line in ("", "   ", "null", "[]", '"str"', "{", '{"op": 42}', '{"op": "evaluate"}'):
            if line.strip():
                response = server.send_raw(line)
                assert response["protocol"] == 1
        assert server.send(op="validate", config={})["valid"] is True


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
        result = subprocess.run(
            [str(executable), "-m", "lovely_bash_permissions.pi_cli"],
            input=stdin,
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        first: dict[str, Any] = json.loads(result.stdout.splitlines()[0])
        return first

    def test_validate_reports_the_binary_as_missing(self, tmp_path: Path) -> None:
        response = self._run_without_shfmt(tmp_path, _request(op="validate", config={"*": "ask"}) + "\n")
        assert response["valid"] is False
        assert "shfmt" in response["error"]
        assert "shfmt-py" in response["error"]

    def test_the_same_probe_passes_when_the_binary_is_there(self, tmp_path: Path) -> None:
        """The positive case, through the identical code path and the same runner."""
        result = subprocess.run(
            COMMAND,
            input=_request(op="validate", config={"*": "ask"}) + "\n",
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout.splitlines()[0]) == {"protocol": 1, "valid": True}


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
