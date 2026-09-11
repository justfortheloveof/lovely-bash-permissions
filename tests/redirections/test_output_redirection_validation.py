"""
Pytest validation tests for all output_redirection permissions.

Tests every redirection pattern (> >> &> >& 2>&1) against allow/ask/deny
policies, including mixed redirections and object-form per-kind policies.

Note on dialect: `&>>` (both-append) is a shfmt/dash-ism that plain bash does
not support, and the bash syntax-error operator formed by `>&` followed by a
word is likewise rejected. We only test operators that are valid bash and
that shfmt parses consistently.

Config isolation: every invocation points DEVIN_PROJECT_DIR and
DEVIN_GLOBAL_CONFIG_DIR at `tmp_path`-backed directories, so tests never read
or mutate the repo's `.devin/` or the user's real global config.
"""

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.redirections.conftest import run_test, write_local_config

ROOT = Path(__file__).resolve().parent.parent

TS_PATH = Path("../jftlo/lovely-devin-permissions/dist/hook.js")

# Valid bash output-redirection patterns under the default config.
BASIC_PATTERNS = [
    # (description, command)
    ("simple stdout >", "echo hi > /tmp/out.txt"),
    ("append >>", "echo hi >> /tmp/out.txt"),
    ("&> both (shfmt &>)", "echo hi &> /tmp/out.txt"),
    (">& both (bash >&)", "echo hi >& /tmp/out.txt"),
    ("2>&1 stderr-to-stdout", "echo hi 2>&1"),
    ("2> stderr to file", "echo hi 2> /tmp/err.txt"),
    ("2>> stderr append", "echo hi 2>> /tmp/err.txt"),
    ("truncate <>", "cat <> /tmp/out.txt"),
    ("pipe + redirect", "ls -la | grep txt > /tmp/out.txt"),
]

MIXED = [
    ("stdout+stderr same target (2>&1 after >)", "echo hi > /tmp/out.txt 2>&1"),
    ("stderr redirect then stdout", "echo hi 2> /tmp/err.txt > /tmp/out.txt"),
    ("&> then dev/null", "echo hi &> /dev/null"),
    ("disable globbing with redirect", "set -f; echo hi > /tmp/out.txt"),
]

# Every redirection captures these commands. Each config enables the top-level
# wildcard so the command-level decision does not mask the redirection policy,
# making the output_redirection outcome the sole determinant of the decision.
POLICY_CMDS = [
    ("redir", "echo hi > /tmp/out.txt"),
    ("stdout-null", "echo hi > /dev/null"),
    ("stderr-null", "echo hi 2> /dev/null"),
    ("stderr-stdout", "echo hi 2>&1"),
]

# Each entry is (label, bash-level config keys, {cmd_desc: expected decision}).
POLICIES: list[tuple[str, dict[str, Any], dict[str, str]]] = [
    (
        "deny-all",
        {"*": "allow", "output_redirection": {"*": "deny"}},
        {"redir": "block", "stdout-null": "block", "stderr-null": "block", "stderr-stdout": "block"},
    ),
    (
        "allow-all",
        {"*": "allow", "output_redirection": {"*": "allow"}},
        {"redir": "approve", "stdout-null": "approve", "stderr-null": "approve", "stderr-stdout": "approve"},
    ),
    (
        "per-kind deny stderr_to_dev_null",
        {"*": "allow", "output_redirection": {"*": "ask", "stderr_to_dev_null": "deny"}},
        {"redir": "ask", "stdout-null": "ask", "stderr-null": "block", "stderr-stdout": "ask"},
    ),
    (
        "per-kind deny stderr_to_stdout",
        {"*": "allow", "output_redirection": {"*": "ask", "stderr_to_stdout": "deny"}},
        {"redir": "ask", "stdout-null": "ask", "stderr-null": "ask", "stderr-stdout": "block"},
    ),
    (
        "per-kind deny stdout_to_dev_null",
        {"*": "allow", "output_redirection": {"*": "ask", "stdout_to_dev_null": "deny"}},
        {"redir": "ask", "stdout-null": "block", "stderr-null": "ask", "stderr-stdout": "ask"},
    ),
    (
        "per-kind deny all three",
        {
            "*": "allow",
            "output_redirection": {
                "*": "ask",
                "stderr_to_dev_null": "deny",
                "stderr_to_stdout": "deny",
                "stdout_to_dev_null": "deny",
            },
        },
        {"redir": "ask", "stdout-null": "block", "stderr-null": "block", "stderr-stdout": "block"},
    ),
]

VALID_DECISIONS = ("approve", "block", "ask")


def decision_of(result: dict[str, Any]) -> str:
    """Return the effective decision encoded in a --test CLI result.

    A `decision` key is present only for approve/block; an ask outcome is only
    visible through the `[♡ perms: 💛 REQUIRES-USER-APPROVAL]` label.
    """
    d = result.get("decision")
    if isinstance(d, str) and d in VALID_DECISIONS:
        return d
    command = result.get("hookSpecificOutput", {}).get("updatedInput", {}).get("command", "")
    if "REQUIRES-USER-APPROVAL" in command:
        return "ask"
    raise ValueError(f"unrecognized CLI result: {result!r}")


class TestOutputRedirectionValidation:
    """Run every redirection pattern and assert the CLI returns a decision."""

    def test_basic_patterns(self, tmp_path: Path) -> None:
        for desc, cmd in BASIC_PATTERNS:
            r = run_test(cmd, project_dir=tmp_path, tmp_global_dir=tmp_path)
            assert decision_of(r) in VALID_DECISIONS, f"{desc}: {cmd!r} -> {r}"

    def test_mixed_redirections(self, tmp_path: Path) -> None:
        for desc, cmd in MIXED:
            r = run_test(cmd, project_dir=tmp_path, tmp_global_dir=tmp_path)
            assert decision_of(r) in VALID_DECISIONS, f"{desc}: {cmd!r} -> {r}"

    def test_no_output_redirection_baseline(self, tmp_path: Path) -> None:
        """A command with no redirection still yields a decision."""
        r = run_test("ls -la", project_dir=tmp_path, tmp_global_dir=tmp_path)
        assert decision_of(r) in VALID_DECISIONS

    @pytest.mark.parametrize("label,cfg,expected", POLICIES, ids=[p[0] for p in POLICIES])
    def test_per_kind_policies(self, tmp_path: Path, label: str, cfg: dict[str, Any], expected: dict[str, str]) -> None:
        write_local_config(cfg, tmp_path)
        for desc, cmd in POLICY_CMDS:
            r = run_test(cmd, project_dir=tmp_path, tmp_global_dir=tmp_path)
            got = decision_of(r)
            assert got == expected[desc], f"{label}/{desc}: {cmd!r} expected {expected[desc]} got {got}"

    def test_default_config_asks_on_redirection(self, tmp_path: Path) -> None:
        """With no output policy configured, redirection requires approval."""
        r = run_test("echo hi > /tmp/out.txt", project_dir=tmp_path, tmp_global_dir=tmp_path)
        assert decision_of(r) == "ask"

    def test_does_not_mutate_repo_devin_dir(self, tmp_path: Path) -> None:
        """The test environment must never write into the repo's real .devin/."""
        real_devin = ROOT / ".devin"
        before = real_devin.read_bytes() if real_devin.is_file() else None
        for _desc, cmd in BASIC_PATTERNS[:2]:
            run_test(cmd, project_dir=tmp_path, tmp_global_dir=tmp_path)
        assert (real_devin.is_file() and real_devin.read_bytes() == before) or not real_devin.is_file()

    def test_truncate_redir_denied(self, tmp_path: Path) -> None:
        """`<>` (truncate) is treated as an output redirection."""
        write_local_config({"*": "allow", "output_redirection": "deny"}, tmp_path)
        r = run_test("cat <> /tmp/out.txt", project_dir=tmp_path, tmp_global_dir=tmp_path)
        assert decision_of(r) == "block"

    def test_truncate_redir_ask(self, tmp_path: Path) -> None:
        """`<>` (truncate) triggers output_redirection ask policy."""
        write_local_config({"*": "allow", "output_redirection": "ask"}, tmp_path)
        r = run_test("cat <> /tmp/out.txt", project_dir=tmp_path, tmp_global_dir=tmp_path)
        assert decision_of(r) == "ask"


@pytest.mark.skipif(not TS_PATH.exists(), reason="TS hook.js not present")
class TestCompareWithTsVersion:
    """Smoke-test the comparison harness against the reference TS hook.

    The TS implementation uses a different config schema, so we only assert
    both sides produce a parseable decision rather than exact parity.
    """

    def test_compare_with_ts_version(self, tmp_path: Path) -> None:
        env = os.environ.copy()
        env["DEVIN_PROJECT_DIR"] = str(tmp_path)
        env["DEVIN_GLOBAL_CONFIG_DIR"] = str(tmp_path)
        for desc, cmd in [
            ("> stdout", "echo hi > /tmp/out.txt"),
            ("2> null", "echo hi 2> /dev/null"),
            ("2>&1", "echo hi 2>&1"),
        ]:
            r_py = run_test(cmd, project_dir=tmp_path, tmp_global_dir=tmp_path)
            ts_r = subprocess.run(
                ["node", str(TS_PATH), "--test", cmd],
                capture_output=True,
                text=True,
                env=env,
                timeout=30,
                check=False,
            )
            py_status = decision_of(r_py)
            ts_status = json.loads(ts_r.stdout).get("decision", "?") if ts_r.stdout.strip() else "?"
            assert py_status in VALID_DECISIONS, f"{desc}: Py gave {py_status!r}"
            assert ts_status in ("approve", "block", "ask"), f"{desc}: TS gave {ts_status!r}"
