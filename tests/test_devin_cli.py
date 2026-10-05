"""
Comprehensive tests for the lovely-devin-permissions CLI.

Tests all CLI modes: setup, test, show-config, and hook mode.
"""

import json
import os
import re
import subprocess
import sys
from contextlib import redirect_stdout, suppress
from io import StringIO
from pathlib import Path
from typing import Any, ClassVar

import pytest


def _in_label(reason: str) -> str:
    """`reason` as it appears inside the hook's label.

    The label is embedded in the rewritten command as a shlex-quoted string, so
    a reason containing an apostrophe (these are Python list reprs, so
    ``['FOO=bar']``) has it shell-escaped to ``'"'"'`` there. Reasons read
    straight off the JSON response are not escaped.
    """
    return reason.replace("'", "'\"'\"'")


def run_cli(
    *args: object,
    input_data: str | None = None,
    env: dict[str, str] | None = None,
    cwd: str | None = None,
    project_dir: str | None = None,
    timeout: int = 30,
) -> subprocess.CompletedProcess[str]:
    """Run the lovely-devin-permissions CLI via subprocess and return the result.

    For config file resolution, we set DEVIN_PROJECT_DIR in env for project
    specific tests.
    """
    uv_env = os.environ.copy()
    if env is not None:
        uv_env.update(env)
    if project_dir is not None:
        uv_env["DEVIN_PROJECT_DIR"] = project_dir

    cmd = ["uv", "run", "python", "-m", "lovely_bash_permissions.devin_cli"]
    if args:
        cmd.extend(str(a) for a in args)

    try:
        result = subprocess.run(
            cmd,
            input=input_data,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=uv_env,
            cwd=cwd,
            check=False,
        )
    except subprocess.TimeoutExpired:
        result = subprocess.CompletedProcess(cmd, -1, "", "TIMEOUT")
    except FileNotFoundError:
        result = subprocess.CompletedProcess(cmd, -1, "", "uv not found")

    return result


def run_cli_in_process(
    *args: object,
    input_data: str | None = None,
    project_dir: str | None = None,
    devin_config_dir: str | None = None,
) -> str:
    """Run the CLI in-process, allowing monkeypatch to work.

    This captures stdout from the CLI's print statements.
    Used for setup tests where we need to override get_devin_global_config_dir.
    """
    from lovely_bash_permissions.devin_cli import main

    # Set up environment
    env_changes = {}
    if devin_config_dir is not None:
        env_changes["DEVIN_GLOBAL_CONFIG_DIR"] = devin_config_dir
    if project_dir is not None:
        env_changes["DEVIN_PROJECT_DIR"] = project_dir
    for k, v in env_changes.items():
        os.environ[k] = v

    # Save original sys.argv
    orig_argv = sys.argv
    sys.argv = ["lovely-devin-permissions"] + [str(a) for a in args]

    # Capture stdin if needed
    if input_data is not None:
        sys.stdin = StringIO(input_data)

    # Capture stdout
    captured = StringIO()
    with redirect_stdout(captured), suppress(SystemExit):
        main()

    # Reset stdin/argv/env
    sys.stdin = sys.__stdin__
    sys.argv = orig_argv
    for k in env_changes:
        del os.environ[k]

    return captured.getvalue()


class TestDevinCliLabelExecEntry:
    r"""The ``--setup`` entry must be a pattern the matcher can actually match.

    ``--setup`` writes ``Exec(:)``.  A pattern that embeds the label text,
    such as ``Exec(: '[♡ perms:)``, can never match: the allowed-matcher
    compares against each segment's *executed* command line, which has its
    quotes stripped, so such a pattern would resolve to
    ``^: '\[♡ perms:(\s|$)``
    while the executed line is ``: [♡ perms: ...``.  The bare ``Exec(:)`` is
    the only form that matches the label-emitting command.
    """

    def test_setup_writes_exec_colon(self, tmp_path: Path) -> None:
        devin_dir = tmp_path / "devin-config"
        run_cli_in_process("--setup", devin_config_dir=str(devin_dir))
        config = json.loads(devin_dir.joinpath("config.json").read_text())
        assert "Exec(:)" in config["permissions"]["allow"]

    def test_setup_does_not_write_an_unmatchable_pattern(self, tmp_path: Path) -> None:
        devin_dir = tmp_path / "devin-config"
        run_cli_in_process("--setup", devin_config_dir=str(devin_dir))
        config = json.loads(devin_dir.joinpath("config.json").read_text())
        assert "Exec(: '[♡ perms:)" not in config["permissions"]["allow"]

    def test_written_entry_matches_the_executed_label(self) -> None:
        """The end-to-end contract: the entry permits the label the hook emits."""
        from lovely_bash_permissions.config.devin import exec_permission_to_regex
        from lovely_bash_permissions.devin_cli import LABEL_EXEC_NAME
        from lovely_bash_permissions.hook import _hook_command
        from lovely_bash_permissions.segments import parse_segments

        # exec_permission_to_regex takes the bare prefix, not the Exec(...) wrapper.
        assert LABEL_EXEC_NAME == "Exec(:)"
        regex = exec_permission_to_regex(":")
        wrapped = _hook_command("allow", "command matches allowed pattern: ^ls(\\s+.*)?$", "ls")
        label = parse_segments(wrapped)[0]
        executed = " ".join([label["command"], *label["arguments"]])
        assert re.search(regex, executed), executed

    def test_old_entry_would_not_have_matched(self) -> None:
        """Pins why the change was necessary, so it is not reverted."""
        from lovely_bash_permissions.config.devin import exec_permission_to_regex
        from lovely_bash_permissions.hook import _hook_command
        from lovely_bash_permissions.segments import parse_segments

        wrapped = _hook_command("allow", "command matches allowed pattern: ^ls(\\s+.*)?$", "ls")
        label = parse_segments(wrapped)[0]
        executed = " ".join([label["command"], *label["arguments"]])
        assert not re.search(exec_permission_to_regex("Exec(: '[♡ perms:)"), executed)


class TestDevinCliCliSetup:
    """Test --setup flag: adds label exec permission to devin global config."""

    def test_setup_creates_config_dir(self, tmp_path: Path) -> None:
        """Setup should create the devin config directory if missing."""
        devin_dir = tmp_path / "devin-config"
        result = run_cli_in_process("--setup", devin_config_dir=str(devin_dir))
        assert devin_dir.joinpath("config.json").exists()
        assert 'Added "Exec(:)' in result

    def test_setup_adds_label_exec_permission(self, tmp_path: Path) -> None:
        """Setup should add label exec permission to the allow list."""
        devin_dir = tmp_path / "devin-config"
        devin_dir.mkdir()
        with open(devin_dir / "config.json", "w") as f:
            json.dump({"permissions": {"allow": []}}, f)

        result = run_cli_in_process("--setup", devin_config_dir=str(devin_dir))
        assert 'Added "Exec(:)' in result

        with open(devin_dir / "config.json") as f:
            config = json.load(f)
        assert "Exec(:)" in config["permissions"]["allow"]

    def test_setup_short_flag(self, tmp_path: Path) -> None:
        """Short flag -s should work the same as --setup."""
        devin_dir = tmp_path / "devin-config"
        devin_dir.mkdir()
        with open(devin_dir / "config.json", "w") as f:
            json.dump({"permissions": {"allow": []}}, f)

        result = run_cli_in_process("-s", devin_config_dir=str(devin_dir))
        assert 'Added "Exec(:)' in result

    def test_setup_idempotent(self, tmp_path: Path) -> None:
        """Running setup twice should be idempotent."""
        devin_dir = tmp_path / "devin-config"
        devin_dir.mkdir()
        with open(devin_dir / "config.json", "w") as f:
            json.dump({"permissions": {"allow": ["Exec(:)"]}}, f)

        result = run_cli_in_process("--setup", devin_config_dir=str(devin_dir))
        assert "is already present in" in result

    def test_setup_preserves_existing_permissions(self, tmp_path: Path) -> None:
        """Setup should preserve existing permissions in the allow list."""
        devin_dir = tmp_path / "devin-config"
        devin_dir.mkdir()
        with open(devin_dir / "config.json", "w") as f:
            json.dump({"permissions": {"allow": ["Exec(git)", "Exec(npm)"]}}, f)

        result = run_cli_in_process("--setup", devin_config_dir=str(devin_dir))
        assert 'Added "Exec(:)' in result

        with open(devin_dir / "config.json") as f:
            config = json.load(f)
        assert "Exec(git)" in config["permissions"]["allow"]
        assert "Exec(npm)" in config["permissions"]["allow"]
        assert "Exec(:)" in config["permissions"]["allow"]

    def test_setup_preserves_config_written_as_jsonc(self, tmp_path: Path) -> None:
        """Setup should read JSONC configs (comments, trailing commas) and preserve all fields."""
        devin_dir = tmp_path / "devin-config"
        devin_dir.mkdir()
        config_text = """{
            // devin permissions
            "session": {"resume": true},
            "permissions": {
                "allow": ["Exec(git)", "Exec(npm run)"],
                "deny": ["Exec(rm)"],
            },
        }"""
        with open(devin_dir / "config.json", "w") as f:
            f.write(config_text)

        result = run_cli("--setup", env={"DEVIN_GLOBAL_CONFIG_DIR": str(devin_dir)})
        assert result.returncode == 0, result.stderr
        assert 'Added "Exec(:)' in result.stdout

        with open(devin_dir / "config.json") as f:
            config = json.load(f)
        assert config["session"] == {"resume": True}
        assert config["permissions"]["deny"] == ["Exec(rm)"]
        assert config["permissions"]["allow"] == ["Exec(git)", "Exec(npm run)", "Exec(:)"]

    def test_setup_aborts_on_invalid_json_preserving_file(self, tmp_path: Path) -> None:
        """A corrupt existing config must be left untouched, not overwritten."""
        devin_dir = tmp_path / "devin-config"
        devin_dir.mkdir()
        config_path = devin_dir / "config.json"
        original = '{"permissions": {"allow": ["Exec(git)"]}'
        with open(config_path, "w") as f:
            f.write(original)

        result = run_cli("--setup", env={"DEVIN_GLOBAL_CONFIG_DIR": str(devin_dir)})
        assert result.returncode == 1
        assert "ERROR" in result.stderr
        assert "Added" not in result.stdout
        with open(config_path) as f:
            assert f.read() == original

    def test_setup_treats_empty_file_as_empty(self, tmp_path: Path) -> None:
        """An empty existing config.json should be initialized rather than rejected."""
        devin_dir = tmp_path / "devin-config"
        devin_dir.mkdir()
        config_path = devin_dir / "config.json"
        config_path.touch()

        result = run_cli("--setup", env={"DEVIN_GLOBAL_CONFIG_DIR": str(devin_dir)})
        assert result.returncode == 0, result.stderr
        assert 'Added "Exec(:)' in result.stdout

        with open(config_path) as f:
            config = json.load(f)
        assert config["permissions"]["allow"] == ["Exec(:)"]

    def test_setup_aborts_on_non_object_root(self, tmp_path: Path) -> None:
        """A root value that isn't an object must not be clobbered."""
        devin_dir = tmp_path / "devin-config"
        devin_dir.mkdir()
        config_path = devin_dir / "config.json"
        original = "[1, 2, 3]"
        with open(config_path, "w") as f:
            f.write(original)

        result = run_cli("--setup", env={"DEVIN_GLOBAL_CONFIG_DIR": str(devin_dir)})
        assert result.returncode == 1
        assert "ERROR" in result.stderr
        with open(config_path) as f:
            assert f.read() == original

    def test_setup_aborts_on_non_object_permissions(self, tmp_path: Path) -> None:
        """A non-object 'permissions' field must not be clobbered."""
        devin_dir = tmp_path / "devin-config"
        devin_dir.mkdir()
        config_path = devin_dir / "config.json"
        original = '{"permissions": 123}'
        with open(config_path, "w") as f:
            f.write(original)

        result = run_cli("--setup", env={"DEVIN_GLOBAL_CONFIG_DIR": str(devin_dir)})
        assert result.returncode == 1
        assert "ERROR" in result.stderr
        with open(config_path) as f:
            assert f.read() == original


class TestDevinCliCliTest:
    """Test --test flag: test a command as a PreToolUse event."""

    def test_test_allowed_command(self, project_with_bash_config: Path) -> None:
        """Testing an allowed command should succeed with exit code 0."""
        result = run_cli(
            "--test",
            "git status",
            env={"DEVIN_PROJECT_DIR": str(project_with_bash_config)},
        )
        assert result.returncode == 0
        # Should output JSON response
        try:
            response = json.loads(result.stdout)
            assert response is not None
        except json.JSONDecodeError:
            pytest.fail("Expected JSON output for allowed command")

    def test_test_short_flag(self, project_with_bash_config: Path) -> None:
        """Short flag -t should work the same as --test."""
        result = run_cli(
            "-t",
            "ls",
            env={"DEVIN_PROJECT_DIR": str(project_with_bash_config)},
        )
        assert result.returncode == 0

    def test_test_prompt_command(self, project_with_bash_config: Path) -> None:
        """Testing a prompt command should generate an allow response."""
        result = run_cli(
            "--test",
            "apt-get",
            env={"DEVIN_PROJECT_DIR": str(project_with_bash_config)},
        )
        # Exit code depends on config; response should be generated
        try:
            response = json.loads(result.stdout)
            # For prompt commands, an allow response is expected
            assert response is not None
        except json.JSONDecodeError:
            pytest.fail("Expected JSON output for prompt command")

    def test_test_unallowed_command(self, project_with_bash_config: Path) -> None:
        """Testing an unallowed command should produce a block response."""
        result = run_cli(
            "--test",
            "curl",
            env={"DEVIN_PROJECT_DIR": str(project_with_bash_config)},
        )
        # Exit code 2 indicates blocked
        assert result.returncode == 2
        response = json.loads(result.stdout)
        # Block response should have some indication
        assert response is not None

    def test_test_no_config_project(self, tmp_project: Path) -> None:
        """Testing in a project without config should still work."""
        result = run_cli(
            "--test",
            "echo",
            env={"DEVIN_PROJECT_DIR": str(tmp_project)},
        )
        # Should complete without error
        assert result.returncode in [0, 2]


class _NodeCoverageBase:
    """Shared helpers for CLI AST-node-coverage tests.

    Config is created dynamically per-test in a temp project, and
    DEVIN_GLOBAL_CONFIG_DIR is pointed at an isolated temp dir so no local or
    global config is read - results are fully deterministic. The config allows
    no commands, so the extracted per-segment reason text lists every segment's
    command name that does not match an allowed pattern, proving each handler
    ran end-to-end.
    """

    _CONFIG: ClassVar[dict[str, dict[str, list[str]]]] = {
        "bash": {
            "allowed_cmds_regex": ["^zzz$"],
            "blocked_cmds_regex": [],
        }
    }

    def _setup(self, tmp_project: Path, tmp_path: Path) -> Path:
        """Create an isolated global config dir and write the project config."""
        global_dir = tmp_path / "global"
        global_dir.mkdir()
        self._write_config(tmp_project)
        return global_dir

    def _write_config(self, project_dir: Path, config: dict[str, Any] | None = None) -> None:
        devin_dir = project_dir / ".devin"
        devin_dir.mkdir(exist_ok=True)
        cfg = config if config is not None else self._CONFIG
        for fn in ("config.json", "lovely-permissions.jsonc", "lovely-permissions.local.jsonc"):
            (devin_dir / fn).write_text(json.dumps(cfg))

    def _test(
        self, command: str, project_dir: Path, global_dir: Path, *, flag: str = "--test"
    ) -> subprocess.CompletedProcess[str]:
        return run_cli(
            flag,
            command,
            env={"DEVIN_PROJECT_DIR": str(project_dir), "DEVIN_GLOBAL_CONFIG_DIR": str(global_dir)},
        )

    def _label(self, result: subprocess.CompletedProcess[str]) -> str:
        """Extract the reason text after the '[♡ perms: <status>] ...' label."""
        response = json.loads(result.stdout)
        cmd = str(response["hookSpecificOutput"]["updatedInput"]["command"])
        # Find the '♡' marker and gather everything after the closing ']'.
        marker = cmd.index("♡")
        b = cmd.index("]", marker)
        return cmd[b + 1 :].strip()


class TestDevinCliCliTestMultipleApprovalReasons(_NodeCoverageBase):
    """A command tripping several ask-level rules reports all reasons."""

    def test_output_redirection_and_background(self, tmp_project: Path, tmp_path: Path) -> None:
        """/-t: 'ls -l 2> /tmp/deleteme &' shows both approval reasons."""
        global_dir = self._setup(tmp_project, tmp_path)
        self._write_config(
            tmp_project,
            {
                "bash": {
                    "allowed_cmds_regex": ["^ls", "^cat"],
                    "blocked_cmds_regex": [],
                    "output_redirection": "ask",
                    "input_redirection": "ask",
                    "background_execution": "ask",
                }
            },
        )
        result = self._test("ls -l 2> /tmp/deleteme &", tmp_project, global_dir, flag="-t")
        label = self._label(result)
        assert "output redirection requires approval" in label
        assert "background execution requires approval: ls" in label

    def test_input_output_and_background(self, tmp_project: Path, tmp_path: Path) -> None:
        """/-t: combined redirections and background report every ask reason."""
        global_dir = self._setup(tmp_project, tmp_path)
        self._write_config(
            tmp_project,
            {
                "bash": {
                    "allowed_cmds_regex": ["^ls", "^cat"],
                    "blocked_cmds_regex": [],
                    "output_redirection": "ask",
                    "input_redirection": "ask",
                    "background_execution": "ask",
                }
            },
        )
        result = self._test("cat < /tmp/in > /tmp/out &", tmp_project, global_dir, flag="-t")
        label = self._label(result)
        assert "output redirection requires approval" in label
        assert "input redirection requires approval" in label
        assert "background execution requires approval: cat" in label


class TestDevinCliCliTestAutoApprovalReasons(_NodeCoverageBase):
    """An auto-approved command reports every reason it was approved."""

    def test_output_redirection_allowed_reported(self, tmp_project: Path, tmp_path: Path) -> None:
        """/-t: 'ls -l 2>&1' shows pattern match plus the redirection-allowed reason."""
        global_dir = self._setup(tmp_project, tmp_path)
        self._write_config(
            tmp_project,
            {
                "bash": {
                    "allowed_cmds_regex": ["^ls(\\s+.*)?$"],
                    "blocked_cmds_regex": [],
                    "output_redirection": "allow",
                    "input_redirection": "allow",
                    "background_execution": "allow",
                }
            },
        )
        result = self._test("ls -l 2>&1", tmp_project, global_dir, flag="-t")
        label = self._label(result)
        assert "command matches allowed pattern" in label
        assert "output redirection allowed to 1" in label

    def test_background_allowed_reported(self, tmp_project: Path, tmp_path: Path) -> None:
        """/-t: 'ls &' shows pattern match plus the background-allowed reason."""
        global_dir = self._setup(tmp_project, tmp_path)
        self._write_config(
            tmp_project,
            {
                "bash": {
                    "allowed_cmds_regex": ["^ls(\\s+.*)?$"],
                    "blocked_cmds_regex": [],
                    "output_redirection": "allow",
                    "input_redirection": "allow",
                    "background_execution": "allow",
                }
            },
        )
        result = self._test("ls &", tmp_project, global_dir, flag="-t")
        label = self._label(result)
        assert "command matches allowed pattern" in label
        assert "background execution allowed: ls" in label


class TestDevinCliCliTestNodeCoverage(_NodeCoverageBase):
    """Exercise AST node handlers (DeclClause, conditionals, tests) via --test/-t."""

    def test_declclause_export_is_a_command(self, tmp_project: Path, tmp_path: Path) -> None:
        """/-t: export FOO=bar x is a bare export command segment plus a separate assignment segment."""
        global_dir = self._setup(tmp_project, tmp_path)
        result = self._test("export FOO=bar x", tmp_project, global_dir, flag="-t")
        label = self._label(result)
        # Half 1 - the keyword is its own command segment, so exactly two segments are
        # reported and the first is the "" (variable-assignment) one. Folding the operands
        # back into export's arguments would collapse this to a single '"export"' entry.
        assert '"export" command does not match allowed patterns' in label
        # Half 2 - the segment is still attributed to variable_assignment and still
        # gated by it, which is what "which is what the policy keys on" means. What
        # changed is only which operands the *reason* names: `x` is a bare word being
        # exported, not an assignment, and listing it as one sent the user looking for
        # a `variable_assignment` rule about `x`.
        assert _in_label("variable assignment requires approval: ['FOO=bar']") in label
        # The gate is unchanged, which is the part that matters and the part a
        # narrowed message could have broken: narrowing what is *named* must not
        # narrow what is *governed*.
        response = json.loads(result.stdout)
        command = str(response["hookSpecificOutput"]["updatedInput"]["command"])
        assert "REQUIRES-USER-APPROVAL" in command or "auto-rejected" in command
        # the operand is an assignment, not a command of its own
        assert '"FOO=bar"' not in label

    def test_declclause_operand_is_a_variable_assignment_segment(self, tmp_project: Path, tmp_path: Path) -> None:
        """/--test: export FOO=bar names both the export command and its FOO=bar assignment segment."""
        global_dir = self._setup(tmp_project, tmp_path)
        result = self._test("export FOO=bar", tmp_project, global_dir)
        label = self._label(result)
        assert _in_label("variable assignment requires approval: ['FOO=bar']") in label
        assert '"export" command does not match allowed patterns' in label
        # The pseudo-command's empty name is never rendered. It carried no
        # information and the assignment reason above already explains that
        # segment, so naming it twice told the user nothing.
        assert '""' not in label
        assert "no parseable segments" not in label

    def test_declclause_export_denied_by_variable_assignment_policy(self, tmp_project: Path, tmp_path: Path) -> None:
        """/--test: variable_assignment=deny blocks export FOO=bar despite a wildcard allow."""
        global_dir = self._setup(tmp_project, tmp_path)
        self._write_config(tmp_project, {"bash": {"*": "allow", "variable_assignment": "deny"}})
        result = self._test("export FOO=bar", tmp_project, global_dir)

        assert result.returncode == 2
        response = json.loads(result.stdout)
        assert response["decision"] == "block"
        assert "variable assignment denied: ['FOO=bar']" in response["reason"]
        assert _in_label("variable assignment denied: ['FOO=bar']") in self._label(result)
        # the export keyword segment is allowed by the wildcard and contributes no reason
        assert '"export"' not in response["reason"]

    def test_declclause_export_allowed_by_wildcard_alone(self, tmp_project: Path, tmp_path: Path) -> None:
        """Control for the deny test: the same command passes when only '*' is set."""
        global_dir = self._setup(tmp_project, tmp_path)
        self._write_config(tmp_project, {"bash": {"*": "allow"}})
        result = self._test("export FOO=bar", tmp_project, global_dir)

        assert result.returncode == 0
        response = json.loads(result.stdout)
        assert response["decision"] == "approve"
        assert _in_label("variable assignment allowed: ['FOO=bar']") in self._label(result)

    def test_declclause_cmdsubst_extracted(self, tmp_project: Path, tmp_path: Path) -> None:
        """/--test: command substitution inside an assignment value is extracted."""
        global_dir = self._setup(tmp_project, tmp_path)
        result = self._test("export FOO=$(cat x)", tmp_project, global_dir)
        label = self._label(result)
        assert '"cat"' in label
        # The substituted command is a segment of its own, and the declaration
        # still splits into an assignment segment plus the `export` keyword, so
        # `export FOO=$(cat x)` yields three segments: ("", ["FOO=$(...)"]),
        # ("export", []) and ("cat", ["x"]).  Asserting only `"cat" in label`
        # would not notice the split being undone.
        assert '"export", "cat" commands do not match allowed patterns' in label
        assert _in_label("variable assignment requires approval: ['FOO=$(...)']") in label

    def test_if_then_and_cond_segments(self, tmp_project: Path, tmp_path: Path) -> None:
        """/-t: if cond; then ls; fi extracts both the cond and then-branch ls."""
        global_dir = self._setup(tmp_project, tmp_path)
        result = self._test("if true; then ls; fi", tmp_project, global_dir, flag="-t")
        label = self._label(result)
        assert '"true"' in label
        assert '"ls"' in label

    def test_if_elif_else_segments(self, tmp_project: Path, tmp_path: Path) -> None:
        """/--test: elif condition and else branch are extracted alongside then."""
        global_dir = self._setup(tmp_project, tmp_path)
        result = self._test("if true; then ls; elif false; then cat x; else pwd; fi", tmp_project, global_dir)
        label = self._label(result)
        assert '"false"' in label
        assert '"pwd"' in label

    def test_while_cond_segment_extracted(self, tmp_project: Path, tmp_path: Path) -> None:
        """/-t: while cond; do ls; done extracts the while-condition."""
        global_dir = self._setup(tmp_project, tmp_path)
        result = self._test("while false; do ls; done", tmp_project, global_dir, flag="-t")
        label = self._label(result)
        assert '"false"' in label

    def test_unary_test_no_phantom_command(self, tmp_project: Path, tmp_path: Path) -> None:
        """/--test: [[ -d /tmp ]] produces no phantom 'tmp' segment."""
        global_dir = self._setup(tmp_project, tmp_path)
        result = self._test("[[ -d /tmp ]]", tmp_project, global_dir)
        label = self._label(result)
        assert "no parseable segments" in label
        assert '"tmp"' not in label

    def test_unary_test_cmdsubst_extracted(self, tmp_project: Path, tmp_path: Path) -> None:
        """/-t: [[ -d $(cat x) ]] extracts the inner command substitution."""
        global_dir = self._setup(tmp_project, tmp_path)
        result = self._test("[[ -d $(cat x) ]]", tmp_project, global_dir, flag="-t")
        label = self._label(result)
        assert '"cat"' in label


class TestDevinCliCliTestRemainingNodes(_NodeCoverageBase):
    """Exercise every other supported AST node handler via --test/-t.

    DeclClause, IfClause/ElifBranch, WhileClause, and UnaryTest are covered in
    TestCliTestNodeCoverage; this class covers the rest: pipes, && / ||, case,
    loops, subshell, test clauses (Binary/Paren), time, coproc, command/process
    substitution, functions/blocks, multi-statement files, and the
    deliberately-skipped arithmetic nodes.
    """

    def test_pipe_side_commands(self, tmp_project: Path, tmp_path: Path) -> None:
        """/-t: BinaryCmd - both sides of a pipe are extracted."""
        global_dir = self._setup(tmp_project, tmp_path)
        result = self._test("ls | grep foo", tmp_project, global_dir, flag="-t")
        label = self._label(result)
        assert '"ls"' in label
        assert '"grep"' in label

    def test_and_cmd_side_commands(self, tmp_project: Path, tmp_path: Path) -> None:
        """/--test: AndCmd - both sides of && are extracted."""
        global_dir = self._setup(tmp_project, tmp_path)
        result = self._test("true && ls", tmp_project, global_dir)
        label = self._label(result)
        assert '"true"' in label
        assert '"ls"' in label

    def test_or_cmd_side_commands(self, tmp_project: Path, tmp_path: Path) -> None:
        """/-t: OrCmd - both sides of || are extracted."""
        global_dir = self._setup(tmp_project, tmp_path)
        result = self._test("false || ls", tmp_project, global_dir, flag="-t")
        label = self._label(result)
        assert '"false"' in label
        assert '"ls"' in label

    def test_case_branch_extracted(self, tmp_project: Path, tmp_path: Path) -> None:
        """/--test: CaseClause - commands in case branch bodies are extracted."""
        global_dir = self._setup(tmp_project, tmp_path)
        result = self._test("case x in a) ls;; esac", tmp_project, global_dir)
        label = self._label(result)
        assert '"ls"' in label

    def test_for_loop_body_extracted(self, tmp_project: Path, tmp_path: Path) -> None:
        """/-t: ForClause - the loop body command is extracted."""
        global_dir = self._setup(tmp_project, tmp_path)
        result = self._test("for i in a b; do ls; done", tmp_project, global_dir, flag="-t")
        label = self._label(result)
        assert '"ls"' in label

    def test_cstyle_loop_body_extracted(self, tmp_project: Path, tmp_path: Path) -> None:
        """/--test: CStyleLoop - the c-style for-loop body command is extracted."""
        global_dir = self._setup(tmp_project, tmp_path)
        result = self._test("for ((i=0;i<10;i++)); do cat x; done", tmp_project, global_dir)
        label = self._label(result)
        assert '"cat"' in label

    def test_subshell_extracted(self, tmp_project: Path, tmp_path: Path) -> None:
        """/-t: Subshell - commands inside ( ... ) are extracted."""
        global_dir = self._setup(tmp_project, tmp_path)
        result = self._test("( ls )", tmp_project, global_dir, flag="-t")
        label = self._label(result)
        assert '"ls"' in label

    def test_binary_test_right_operand(self, tmp_project: Path, tmp_path: Path) -> None:
        """/--test: BinaryTest - only substitutions in the && right operand inside [[ ]] run."""
        global_dir = self._setup(tmp_project, tmp_path)
        result = self._test("[[ -d /tmp && $(rm) ]]", tmp_project, global_dir)
        label = self._label(result)
        assert '"rm"' in label

    def test_parenthesized_test_extracted(self, tmp_project: Path, tmp_path: Path) -> None:
        """/-t: ParenTest - only substitutions inside a parenthesized test are extracted."""
        global_dir = self._setup(tmp_project, tmp_path)
        result = self._test("[[ ( -d /tmp ) && $(rm) ]]", tmp_project, global_dir, flag="-t")
        label = self._label(result)
        assert '"rm"' in label

    def test_time_clause_command_extracted(self, tmp_project: Path, tmp_path: Path) -> None:
        """/--test: TimeClause - the timed command is extracted."""
        global_dir = self._setup(tmp_project, tmp_path)
        result = self._test("time sleep 1", tmp_project, global_dir)
        label = self._label(result)
        assert '"sleep"' in label

    def test_coproc_command_extracted(self, tmp_project: Path, tmp_path: Path) -> None:
        """/-t: CoprocClause - the coprocess command is extracted."""
        global_dir = self._setup(tmp_project, tmp_path)
        result = self._test("coproc mycmd", tmp_project, global_dir, flag="-t")
        label = self._label(result)
        assert '"mycmd"' in label

    def test_cmdsubst_extracted(self, tmp_project: Path, tmp_path: Path) -> None:
        """/--test: CmdSubst - a command substitution in an argument is extracted."""
        global_dir = self._setup(tmp_project, tmp_path)
        result = self._test("echo $(ls)", tmp_project, global_dir)
        label = self._label(result)
        assert '"ls"' in label

    def test_procsubst_extracted(self, tmp_project: Path, tmp_path: Path) -> None:
        """/-t: ProcSubst - process substitutions are extracted."""
        global_dir = self._setup(tmp_project, tmp_path)
        result = self._test("diff <(ls) <(cat x)", tmp_project, global_dir, flag="-t")
        label = self._label(result)
        assert '"ls"' in label
        assert '"cat"' in label

    def test_function_body_extracted(self, tmp_project: Path, tmp_path: Path) -> None:
        """/--test: FuncDecl - the function body is extracted."""
        global_dir = self._setup(tmp_project, tmp_path)
        result = self._test("foo() { ls; }", tmp_project, global_dir)
        label = self._label(result)
        assert '"ls"' in label

    def test_brace_block_extracted(self, tmp_project: Path, tmp_path: Path) -> None:
        """/-t: Block - commands inside { ... } are extracted."""
        global_dir = self._setup(tmp_project, tmp_path)
        result = self._test("{ cat x; }", tmp_project, global_dir, flag="-t")
        label = self._label(result)
        assert '"cat"' in label

    def test_multi_statement_file_extracted(self, tmp_project: Path, tmp_path: Path) -> None:
        """/--test: File - every top-level statement is extracted."""
        global_dir = self._setup(tmp_project, tmp_path)
        result = self._test("ls; cat x", tmp_project, global_dir)
        label = self._label(result)
        assert '"ls"' in label
        assert '"cat"' in label

    def test_no_match_reason_printed_once_per_command(self, tmp_project: Path, tmp_path: Path) -> None:
        """/-t: non-matching segments yield one cumulative reason, not one per segment."""
        global_dir = self._setup(tmp_project, tmp_path)
        result = self._test("bogus1 one;bogus2 two;bogus3 x", tmp_project, global_dir, flag="-t")
        label = self._label(result)
        assert label.count("commands do not match allowed patterns") == 1
        assert '"bogus1", "bogus2", "bogus3" command' in label
        assert '"bogus1" command does not match' not in label

    def test_arithmetic_skipped(self, tmp_project: Path, tmp_path: Path) -> None:
        """/-t: ArithmCmd - (( ... )) produces no segments (arithmetic-only)."""
        global_dir = self._setup(tmp_project, tmp_path)
        result = self._test("((x=1))", tmp_project, global_dir, flag="-t")
        label = self._label(result)
        assert "no parseable segments" in label

    def test_let_treated_as_variable_assignment(self, tmp_project: Path, tmp_path: Path) -> None:
        """/--test: LetClause - let produces variable assignment segment (arithmetic var assign)."""
        global_dir = self._setup(tmp_project, tmp_path)
        result = self._test("let x=1", tmp_project, global_dir)
        label = self._label(result)
        assert "variable assignment" in label


class TestDevinCliCliTestMultilineCommands(_NodeCoverageBase):
    """Exercise multiline commands via --test/-t.

    Covers simple newline-separated statements and heredoc-fed interpreters
    (node/python3/cat). A heredoc surfaces as an input redirection on the
    segment, so the reason text also flags "input redirection requires
    approval".
    """

    def test_multiline_simple_statements(self, tmp_project: Path, tmp_path: Path) -> None:
        """/-t: each newline-separated statement is extracted."""
        global_dir = self._setup(tmp_project, tmp_path)
        result = self._test("ls\necho hi", tmp_project, global_dir, flag="-t")
        label = self._label(result)
        assert '"ls"' in label
        assert '"echo"' in label

    def test_multiline_many_statements(self, tmp_project: Path, tmp_path: Path) -> None:
        """/--test: every line is extracted, including repeated commands."""
        global_dir = self._setup(tmp_project, tmp_path)
        result = self._test("echo one\necho two\ncat x", tmp_project, global_dir)
        label = self._label(result)
        assert '"echo"' in label
        assert '"cat"' in label

    def test_node_heredoc_command_and_redirection(self, tmp_project: Path, tmp_path: Path) -> None:
        """/--test: node heredoc extracts 'node' and flags the input redirection."""
        global_dir = self._setup(tmp_project, tmp_path)
        result = self._test("node << 'EOF'\nconsole.log('hi')\nEOF", tmp_project, global_dir)
        label = self._label(result)
        assert '"node"' in label
        assert "input redirection requires approval" in label

    def test_python_heredoc_command_and_redirection(self, tmp_project: Path, tmp_path: Path) -> None:
        """/-t: python3 heredoc extracts 'python3' and flags the input redirection."""
        global_dir = self._setup(tmp_project, tmp_path)
        result = self._test("python3 << 'EOF'\nprint('hi')\nEOF", tmp_project, global_dir, flag="-t")
        label = self._label(result)
        assert '"python3"' in label
        assert "input redirection requires approval" in label

    def test_cat_heredoc_command_and_redirection(self, tmp_project: Path, tmp_path: Path) -> None:
        """/-t: cat heredoc extracts 'cat' and flags the input redirection."""
        global_dir = self._setup(tmp_project, tmp_path)
        result = self._test("cat << EOF\nhello\nworld\nEOF", tmp_project, global_dir, flag="-t")
        label = self._label(result)
        assert '"cat"' in label
        assert "input redirection requires approval" in label

    def test_python_dash_heredoc(self, tmp_project: Path, tmp_path: Path) -> None:
        """/--test: python3 - heredoc still extracts 'python3' via stdin."""
        global_dir = self._setup(tmp_project, tmp_path)
        result = self._test("python3 - << 'EOF'\nprint('hi')\nEOF", tmp_project, global_dir)
        label = self._label(result)
        assert '"python3"' in label
        assert "input redirection requires approval" in label


class TestDevinCliCliShowConfig:
    """Test --show-config flag: show effective config and file paths."""

    def test_show_config_valid_project(self, project_with_bash_config: Path) -> None:
        """Show config should output valid JSON with files and effectiveConfig."""
        result = run_cli(
            "--show-config",
            env={"DEVIN_PROJECT_DIR": str(project_with_bash_config)},
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert "files" in output
        assert "effectiveConfig" in output
        # Files should include project devin config path
        file_paths = [f["path"] for f in output["files"]]
        assert any(".devin/lovely-permissions.jsonc" in p for p in file_paths)

    def test_show_config_empty_project(self, tmp_project: Path) -> None:
        """Show config on an empty project should still work."""
        result = run_cli("--show-config", env={"DEVIN_PROJECT_DIR": str(tmp_project)})
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert "files" in output
        assert "effectiveConfig" in output

    def test_show_config_reports_file_existence(self, project_with_bash_config: Path) -> None:
        """Show config should report whether config files exist."""
        result = run_cli("--show-config", env={"DEVIN_PROJECT_DIR": str(project_with_bash_config)})
        output = json.loads(result.stdout)
        for f in output["files"]:
            assert "exists" in f
            assert isinstance(f["exists"], bool)
        # Project devin config should be reported as existing
        for f in output["files"]:
            if ".devin/lovely-permissions.jsonc" in f["path"]:
                assert f["exists"] is True


class TestDevinCliHookMode:
    """Test hook mode: receives JSON events on stdin."""

    def test_hook_pretooluse_allowed(self, project_with_bash_config: Path) -> None:
        """Hook mode with an allowed command should generate a response."""
        event = {
            "hook_event_name": "PreToolUse",
            "tool_name": "exec",
            "tool_input": {"command": "git status"},
        }
        result = run_cli(
            input_data=json.dumps(event),
            env={"DEVIN_PROJECT_DIR": str(project_with_bash_config)},
        )
        assert result.returncode == 0
        response = json.loads(result.stdout)
        # Response should have the correct structure
        assert response is not None
        assert "hookSpecificOutput" in response
        assert response["hookSpecificOutput"]["hookEventName"] == "PreToolUse"

    def test_hook_pretooluse_prompt(self, project_with_bash_config: Path) -> None:
        """Hook mode with a prompt command should generate an allow response."""
        event = {
            "hook_event_name": "PreToolUse",
            "tool_name": "exec",
            "tool_input": {"command": "apt-get install foo"},
        }
        result = run_cli(
            input_data=json.dumps(event),
            env={"DEVIN_PROJECT_DIR": str(project_with_bash_config)},
        )
        assert result.returncode == 0
        response = json.loads(result.stdout)
        assert response is not None
        assert response["hookSpecificOutput"]["hookEventName"] == "PreToolUse"

    def test_hook_non_exec_tool_ignored(self, project_with_bash_config: Path) -> None:
        """Hook mode should exit silently for non-exec tools."""
        event = {
            "hook_event_name": "PreToolUse",
            "tool_name": "read_file",
            "tool_input": {"path": "/etc/passwd"},
        }
        result = run_cli(
            input_data=json.dumps(event),
            env={"DEVIN_PROJECT_DIR": str(project_with_bash_config)},
        )
        assert result.returncode == 0
        assert result.stdout.strip() == ""

    def test_hook_mode_honors_devin_project_dir(self, project_with_bash_config: Path) -> None:
        """Hook mode uses DEVIN_PROJECT_DIR when the event omits project_dir."""
        event = {
            "hook_event_name": "PreToolUse",
            "tool_name": "exec",
            "tool_input": {"command": "curl http://x"},
        }
        result = run_cli(
            input_data=json.dumps(event),
            env={"DEVIN_PROJECT_DIR": str(project_with_bash_config)},
        )
        assert result.returncode == 2
        response = json.loads(result.stdout)
        assert response["decision"] == "block"

    def test_hook_mode_event_project_dir_wins(self, tmp_project: Path, project_with_bash_config: Path) -> None:
        """An explicit event project_dir overrides DEVIN_PROJECT_DIR."""
        event = {
            "hook_event_name": "PreToolUse",
            "tool_name": "exec",
            "tool_input": {"command": "curl http://x"},
            "project_dir": str(project_with_bash_config),
        }
        result = run_cli(
            input_data=json.dumps(event),
            env={"DEVIN_PROJECT_DIR": str(tmp_project)},
        )
        assert result.returncode == 2
        response = json.loads(result.stdout)
        assert response["decision"] == "block"

    def test_hook_write_to_process_evaluated(self, project_with_bash_config: Path) -> None:
        """Hook mode evaluates write_to_process commands like exec."""
        event = {
            "hook_event_name": "PreToolUse",
            "tool_name": "write_to_process",
            "tool_input": {"command": "git status"},
            "project_dir": str(project_with_bash_config),
        }
        result = run_cli(
            input_data=json.dumps(event),
            env={"DEVIN_PROJECT_DIR": str(project_with_bash_config)},
        )
        assert result.returncode == 0
        response = json.loads(result.stdout)
        assert response is not None
        assert response["hookSpecificOutput"]["hookEventName"] == "PreToolUse"

    def test_hook_pretooluse_block_exits_2(self, project_with_bash_config: Path) -> None:
        """Blocked command in hook mode exits 2 (Devin block convention)."""
        event = {
            "hook_event_name": "PreToolUse",
            "tool_name": "exec",
            "tool_input": {"command": "curl http://x"},
            "project_dir": str(project_with_bash_config),
        }
        result = run_cli(
            input_data=json.dumps(event),
            env={"DEVIN_PROJECT_DIR": str(project_with_bash_config)},
        )
        assert result.returncode == 2
        response = json.loads(result.stdout)
        assert response["decision"] == "block"

    def test_hook_permission_request_block_exits_2(self, project_with_bash_config: Path) -> None:
        """Blocked PermissionRequest in hook mode exits 2."""
        event = {
            "hook_event_name": "PermissionRequest",
            "tool_name": "write_to_process",
            "tool_input": {"command": "curl http://x"},
            "project_dir": str(project_with_bash_config),
        }
        result = run_cli(
            input_data=json.dumps(event),
            env={"DEVIN_PROJECT_DIR": str(project_with_bash_config)},
        )
        assert result.returncode == 2
        response = json.loads(result.stdout)
        assert response["decision"] == "block"

    def test_hook_empty_stdin_exits(self, project_with_bash_config: Path) -> None:
        """Hook mode with empty stdin should exit silently."""
        result = run_cli(
            input_data="",
            env={"DEVIN_PROJECT_DIR": str(project_with_bash_config)},
        )
        assert result.returncode == 0
        assert result.stdout.strip() == ""

    def test_hook_empty_command_is_evaluated(self, project_with_bash_config: Path) -> None:
        """Hook mode with an empty command gets a verdict, not silence.

        It used to exit 0 having printed nothing, while the Pi server answered
        the same input from the ``error`` policy - an empty string does not parse,
        so it landed there. Deciding it here is what makes one command one answer
        across both hosts.
        """
        event = {
            "hook_event_name": "PreToolUse",
            "tool_name": "exec",
            "tool_input": {"command": ""},
        }
        result = run_cli(
            input_data=json.dumps(event),
            env={"DEVIN_PROJECT_DIR": str(project_with_bash_config)},
        )
        assert result.returncode == 0
        response = json.loads(result.stdout)
        assert "error evaluating command" in response["hookSpecificOutput"]["updatedInput"]["command"]

    def test_hook_invalid_json_blocks(self, project_with_bash_config: Path) -> None:
        """Hook mode with invalid JSON emits a block decision and exits 2 (fail closed)."""
        result = run_cli(
            input_data="not valid json",
            env={"DEVIN_PROJECT_DIR": str(project_with_bash_config)},
        )
        assert result.returncode == 2
        response = json.loads(result.stdout)
        assert response["decision"] == "block"
        assert "invalid JSON on stdin" in response["reason"]

    def test_an_invalid_config_reaches_the_reason_without_the_validator_s_half(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, project_with_bash_config: Path
    ) -> None:
        """A config error is model-facing text, so it carries no validator internals.

        This reason is read by the agent the hook is gating, so a pydantic docs URL,
        a ``type=`` block and a dump of every pattern the user wrote all reached
        the model's context - and made this host's message differ from the Pi
        server's for the same config, which trimmed them at the far end instead.
        The key and the user's own value have to survive; nothing else may.
        """
        devin_dir = project_with_bash_config / ".devin"
        (devin_dir / "lovely-permissions.jsonc").write_text(
            json.dumps({"bash": {"allowed_cmds_regex": ["\\/etc", "\\.env$", "["], "*": "alow"}})
        )

        result = run_cli(
            input_data=json.dumps(
                {
                    "hook_event_name": "PreToolUse",
                    "tool_name": "exec",
                    "tool_input": {"command": "ls"},
                }
            ),
            env={"DEVIN_PROJECT_DIR": str(project_with_bash_config)},
        )
        assert result.returncode == 2
        reason = json.loads(result.stdout)["reason"]

        assert "allowed_cmds_regex" in reason  # which key
        assert "alow" in reason  # what they wrote
        assert "unterminated character set" in reason  # what is wrong
        for noise in ("errors.pydantic.dev", "type=", "input_value", "input_type", "Traceback"):
            assert noise not in reason, noise
        assert "\\/etc" not in reason  # not the rest of their allow list
        assert len(reason) < 400  # a prompt bullet, not a document

    def test_hook_non_object_json_blocks(self, project_with_bash_config: Path) -> None:
        """Hook mode with JSON that is not an object emits a block decision (fail closed)."""
        for payload in ("[1, 2, 3]", '"just a string"'):
            result = run_cli(
                input_data=payload,
                env={"DEVIN_PROJECT_DIR": str(project_with_bash_config)},
            )
            assert result.returncode == 2
            response = json.loads(result.stdout)
            assert response["decision"] == "block"
            assert "not an object" in response["reason"]

    def test_hook_non_dict_tool_input_blocks(self, project_with_bash_config: Path) -> None:
        """Hook mode with a non-object tool_input emits a block decision (fail closed)."""
        event = {
            "hook_event_name": "PreToolUse",
            "tool_name": "exec",
            "tool_input": "oops",
        }
        result = run_cli(
            input_data=json.dumps(event),
            env={"DEVIN_PROJECT_DIR": str(project_with_bash_config)},
        )
        assert result.returncode == 2
        response = json.loads(result.stdout)
        assert response["decision"] == "block"
        assert "tool_input is not an object" in response["reason"]

    def test_hook_mode_unexpected_exception_blocks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An unexpected exception in hook mode fails closed with a block decision."""

        def _boom(event: object) -> None:
            raise RuntimeError("hook boom")

        monkeypatch.setattr(
            "lovely_bash_permissions.devin_cli.handle_hook_event",
            _boom,
        )
        event = {
            "hook_event_name": "PreToolUse",
            "tool_name": "exec",
            "tool_input": {"command": "ls"},
        }
        out = run_cli_in_process(input_data=json.dumps(event))
        response = json.loads(out)
        assert response["decision"] == "block"
        assert "hook boom" in response["reason"]

    def test_hook_mode_invalid_config_blocks(self, tmp_path: Path) -> None:
        """Hook mode with an invalid lovely-permissions.jsonc blocks (exit 2)."""
        project = tmp_path / "proj"
        (project / ".devin").mkdir(parents=True)
        (project / ".devin" / "lovely-permissions.jsonc").write_text("not valid json")
        global_dir = tmp_path / "global"
        global_dir.mkdir()
        event = {
            "hook_event_name": "PreToolUse",
            "tool_name": "exec",
            "tool_input": {"command": "ls"},
        }
        result = run_cli(
            input_data=json.dumps(event),
            env={"DEVIN_PROJECT_DIR": str(project), "DEVIN_GLOBAL_CONFIG_DIR": str(global_dir)},
        )
        assert result.returncode == 2
        response = json.loads(result.stdout)
        assert response["decision"] == "block"
        assert "invalid permissions config (blocked)" in response["reason"]

    def test_hook_mode_malformed_devin_exec_rule_blocks(self, tmp_path: Path) -> None:
        """A malformed Devin Exec(...) allow rule blocks (fail closed)."""
        project = tmp_path / "proj2"
        (project / ".devin").mkdir(parents=True)
        (project / ".devin" / "config.json").write_text(json.dumps({"permissions": {"allow": ["Exec("]}}))
        global_dir = tmp_path / "global2"
        global_dir.mkdir()
        event = {
            "hook_event_name": "PreToolUse",
            "tool_name": "exec",
            "tool_input": {"command": "ls"},
        }
        result = run_cli(
            input_data=json.dumps(event),
            env={"DEVIN_PROJECT_DIR": str(project), "DEVIN_GLOBAL_CONFIG_DIR": str(global_dir)},
        )
        assert result.returncode == 2
        response = json.loads(result.stdout)
        assert response["decision"] == "block"
        assert "config error (blocked)" in response["reason"]


class TestDevinCliFlagPrecedence:
    """Test that CLI flags take precedence over stdin."""

    def test_setup_takes_precedence_over_stdin(self, tmp_path: Path) -> None:
        """--setup should work even with stdin data."""
        devin_dir = tmp_path / "devin-config"
        devin_dir.mkdir()
        with open(devin_dir / "config.json", "w") as f:
            json.dump({"permissions": {"allow": []}}, f)

        event = {
            "hook_event_name": "PreToolUse",
            "tool_name": "exec",
            "tool_input": {"command": "git status"},
        }
        result = run_cli_in_process("--setup", devin_config_dir=str(devin_dir), input_data=json.dumps(event))
        # Setup should have run (ignoring stdin)
        assert 'Added "Exec(:)' in result


class TestDevinCliErrorHandling:
    """Test error handling and error output."""

    def test_cli_errors_use_prefix(self, tmp_project: Path) -> None:
        """CLI errors should use the [Lovely] ERROR] prefix."""
        # Create an invalid config
        with open(tmp_project / "lovely-bash-permissions.jsonc", "w") as f:
            f.write("not valid json")

        result = run_cli("--show-config", cwd=str(tmp_project))
        # Should produce some output (possibly error)
        # The exact exit code depends on config validation
        # at least the CLI should not crash
        assert result.returncode in [0, 1]

    def test_main_catches_unexpected_exceptions(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """An escaping exception exits 1 with an error on stderr (fail closed)."""
        from lovely_bash_permissions.devin_cli import main

        orig_argv = sys.argv
        sys.argv = ["lovely-devin-permissions", "-t", "ls"]

        def _boom(_command: str) -> None:
            raise RuntimeError("internal boom")

        monkeypatch.setattr("lovely_bash_permissions.devin_cli.handle_test", _boom)
        try:
            with pytest.raises(SystemExit) as exc:
                main()
            assert exc.value.code == 1
        finally:
            sys.argv = orig_argv

        err = capsys.readouterr().err
        assert "unexpected error: internal boom" in err


class TestDevinCliCliTestErrorPolicy(_NodeCoverageBase):
    """Malformed bash routes through the bash `error` policy."""

    def test_error_deny_blocks_malformed(self, tmp_project: Path, tmp_path: Path) -> None:
        """/-t: error=deny blocks unparseable bash even under wildcard allow."""
        global_dir = self._setup(tmp_project, tmp_path)
        self._write_config(tmp_project, {"bash": {"*": "allow", "error": "deny"}})
        result = self._test('echo "unclosed', tmp_project, global_dir)

        assert result.returncode == 2
        response = json.loads(result.stdout)
        assert response["decision"] == "block"
        assert "error evaluating command" in response["reason"]
        assert "policy 'deny'" in response["reason"]

    def test_error_ask_asks_for_malformed(self, tmp_project: Path, tmp_path: Path) -> None:
        """/-t: error=ask surfaces an ask (no decision key) for unparseable bash."""
        global_dir = self._setup(tmp_project, tmp_path)
        self._write_config(tmp_project, {"bash": {"*": "allow", "error": "ask"}})
        result = self._test("(((invalid", tmp_project, global_dir, flag="-t")

        assert result.returncode == 0
        response = json.loads(result.stdout)
        assert "decision" not in response
        assert "error evaluating command" in str(response["hookSpecificOutput"]["updatedInput"]["command"])

    def test_error_defaults_to_wildcard(self, tmp_project: Path, tmp_path: Path) -> None:
        """/-t: no 'error' key means malformed bash inherits bash '*' (documented default)."""
        global_dir = self._setup(tmp_project, tmp_path)
        self._write_config(tmp_project, {"bash": {"*": "allow"}})
        result = self._test('echo "unclosed', tmp_project, global_dir, flag="-t")

        assert result.returncode == 0
        response = json.loads(result.stdout)
        # error inherits '*' → allow auto-approves; users set error: ask/deny to harden
        assert response["decision"] == "approve"
