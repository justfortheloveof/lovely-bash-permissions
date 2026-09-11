"""Phase 13: Advanced Bash Constructs (process substitution, coproc, trap, functions, builtins)"""

from typing import Any

from lovely_bash_permissions.evaluate import evaluate_bash_command

EMPTY: dict[str, Any] = {}
ENV2 = {
    "bash": {"allowed_cmds_regex": ["^ls", "^true", "^echo", "^cat", "^grep", "^find"], "variable_assignment": "allow"}
}
ENV3 = {"bash": {"allowed_cmds_regex": ["^ls", "^true", "^echo"], "variable_assignment": "allow"}}


def test_procsub_cat_echo_empty() -> None:
    """Process substitution with cat should require approval in empty env."""
    result = evaluate_bash_command("cat <(echo hi)", EMPTY)
    assert result["status"] == "ask"


def test_procsub_cat_echo_env2() -> None:
    """Process substitution with cat should require approval in env2."""
    result = evaluate_bash_command("cat <(echo hi)", ENV2)
    assert result["status"] == "ask"


def test_procsub_cat_echo_env3() -> None:
    """Process substitution with cat should require approval in env3."""
    result = evaluate_bash_command("cat <(echo hi)", ENV3)
    assert result["status"] == "ask"


def test_procsub_cat_echo_file2_env2() -> None:
    """Process substitution with cat to file should require approval in env2."""
    result = evaluate_bash_command("cat <(echo hi)", ENV2)
    assert result["status"] == "ask"


def test_diff_procsub_ls_empty() -> None:
    """Diff with process substitution should require approval in empty env."""
    result = evaluate_bash_command("diff <(ls file1) <(ls file2)", EMPTY)
    assert result["status"] == "ask"


def test_diff_procsub_ls_env2() -> None:
    """Diff with process substitution should require approval in env2."""
    result = evaluate_bash_command("diff <(ls file1) <(ls file2)", ENV2)
    assert result["status"] == "ask"


def test_diff_procsub_ls_env3() -> None:
    """Diff with process substitution should require approval in env3."""
    result = evaluate_bash_command("diff <(ls file1) <(ls file2)", ENV3)
    assert result["status"] == "ask"


def test_coproc_echo_empty() -> None:
    """Coproc with echo should require approval in empty env."""
    result = evaluate_bash_command("coproc myproc { echo hi; }", EMPTY)
    assert result["status"] == "ask"


def test_coproc_echo_env2() -> None:
    """Coproc with echo should require approval in env2 (coproc is not allowed)."""
    result = evaluate_bash_command("coproc myproc { echo hi; }", ENV2)
    assert result["status"] == "ask"


def test_coproc_echo_env3() -> None:
    """Coproc with echo should require approval in env3 (coproc is not allowed)."""
    result = evaluate_bash_command("coproc myproc { echo hi; }", ENV3)
    assert result["status"] == "ask"


def test_coproc_echo_file_env2() -> None:
    """Coproc with echo to file should require approval in env2."""
    result = evaluate_bash_command("coproc myproc { echo hi > file; }", ENV2)
    assert result["status"] == "ask"


def test_trap_echo_file_empty() -> None:
    """Trap with echo should require approval in empty env."""
    result = evaluate_bash_command('trap "echo trap > file" EXIT', EMPTY)
    assert result["status"] == "ask"


def test_trap_echo_file_env2() -> None:
    """Trap with echo should require approval in env2."""
    result = evaluate_bash_command('trap "echo trap > file" EXIT', ENV2)
    assert result["status"] == "ask"


def test_fn_def_echo_file_env2() -> None:
    """Function definition with echo should require approval in env2."""
    result = evaluate_bash_command("fn() { echo hi > file; }", ENV2)
    assert result["status"] == "ask"


def test_fn_def_echo_file_env3() -> None:
    """Function definition with echo should require approval in env3."""
    result = evaluate_bash_command("fn() { echo hi > file; }", ENV3)
    assert result["status"] == "ask"


def test_fn_call_redirect_env2() -> None:
    """Function call with redirect should require approval in env2."""
    result = evaluate_bash_command("fn > out", ENV2)
    assert result["status"] == "ask"


def test_fn_call_redirect_env3() -> None:
    """Function call with redirect should require approval in env3."""
    result = evaluate_bash_command("fn > out", ENV3)
    assert result["status"] == "ask"


def test_export_var_cmdsub_redirect_env2() -> None:
    """Export with command substitution should require approval in env2."""
    result = evaluate_bash_command("export VAR=$(echo hi) > file", ENV2)
    assert result["status"] == "ask"


def test_export_var_cmdsub_redirect_env3() -> None:
    """Export with command substitution should require approval in env3."""
    result = evaluate_bash_command("export VAR=$(echo hi) > file", ENV3)
    assert result["status"] == "ask"


def test_export_path_redirect_empty() -> None:
    """Export with path should require approval in empty env."""
    result = evaluate_bash_command('export PATH="$PATH:/usr/local/bin" > file', EMPTY)
    assert result["status"] == "ask"


def test_export_path_redirect_env2() -> None:
    """Export with path should require approval in env2."""
    result = evaluate_bash_command('export PATH="$PATH:/usr/local/bin" > file', ENV2)
    assert result["status"] == "ask"


def test_unset_array_redirect_empty() -> None:
    """Unset array should require approval in empty env."""
    result = evaluate_bash_command("unset arr[@] > file", EMPTY)
    assert result["status"] == "ask"


def test_unset_array_redirect_env2() -> None:
    """Unset array should require approval in env2."""
    result = evaluate_bash_command("unset arr[@] > file", ENV2)
    assert result["status"] == "ask"


def test_declare_assoc_redirect_env2() -> None:
    """Declare associative array should require approval in env2."""
    result = evaluate_bash_command("declare -A map > file", ENV2)
    assert result["status"] == "ask"


def test_declare_assoc_redirect_env3() -> None:
    """Declare associative array should require approval in env3."""
    result = evaluate_bash_command("declare -A map > file", ENV3)
    assert result["status"] == "ask"
