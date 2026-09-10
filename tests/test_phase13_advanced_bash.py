"""Phase 13: Advanced Bash Constructs

Tests process substitution, coproc, traps, functions, export, unset,
and declare with redirections across multiple environments.
"""

from lovely_bash_permissions.evaluate import evaluate_bash_command

EMPTY = {}
ENV2 = {"bash": {"allowed_cmds_regex": ["^ls$", "^true$", "^echo$", "^cat$", "^grep$", "^find$"]}}
ENV3 = {"bash": {"allowed_cmds_regex": ["^ls .*", "^true$", "^echo$"], "blocked_paths_regex": ["/etc", "/home"]}}


def test_procsub_cat_echo_empty():
    """Process substitution with cat/echo in empty config should ask."""
    result = evaluate_bash_command("cat <(echo hi) > file", EMPTY)
    assert result["status"] == "ask"


def test_procsub_cat_echo_env2():
    """Process substitution with cat/echo in env2 should ask."""
    result = evaluate_bash_command("cat <(echo hi) > file", ENV2)
    assert result["status"] == "ask"


def test_procsub_cat_echo_env3():
    """Process substitution with cat/echo in env3 should ask."""
    result = evaluate_bash_command("cat <(echo hi) > file", ENV3)
    assert result["status"] == "ask"


def test_diff_procsub_ls_empty():
    """Diff with process substitution and ls in empty config should ask."""
    result = evaluate_bash_command("diff <(ls file1) <(ls file2)", EMPTY)
    assert result["status"] == "ask"


def test_diff_procsub_ls_env2():
    """Diff with process substitution and ls in env2 should ask."""
    result = evaluate_bash_command("diff <(ls file1) <(ls file2)", ENV2)
    assert result["status"] == "ask"


def test_diff_procsub_ls_env3():
    """Diff with process substitution and ls in env3 should ask."""
    result = evaluate_bash_command("diff <(ls file1) <(ls file2)", ENV3)
    assert result["status"] == "ask"


def test_procsub_cat_echo_file2_env2():
    """Process substitution writing to file2 in env2 should ask."""
    result = evaluate_bash_command("cat <(echo hi) > file2", ENV2)
    assert result["status"] == "ask"


def test_coproc_echo_env2():
    """Coproc with echo in env2 should ask (coproc itself not allowed)."""
    result = evaluate_bash_command("coproc myproc { echo hi; }", ENV2)
    assert result["status"] == "ask"


def test_coproc_echo_file_env2():
    """Coproc with echo and redirection in env2 should ask."""
    result = evaluate_bash_command("coproc myproc { echo hi > file; }", ENV2)
    assert result["status"] == "ask"


def test_trap_echo_file_empty():
    """Trap with echo and redirection in empty config should ask."""
    result = evaluate_bash_command('trap "echo trap > file" EXIT', EMPTY)
    assert result["status"] == "ask"


def test_fn_def_echo_file_env2():
    """Function definition with echo and redirection in env2 should ask."""
    result = evaluate_bash_command("fn() { echo hi > file; }", ENV2)
    assert result["status"] == "ask"


def test_fn_call_redirect_env2():
    """Function call with redirection in env2 should ask."""
    result = evaluate_bash_command("fn > out", ENV2)
    assert result["status"] == "ask"


def test_export_path_redirect_empty():
    """Export PATH with redirection in empty config should ask."""
    result = evaluate_bash_command('export PATH="$PATH:/usr/local/bin" > file', EMPTY)
    assert result["status"] == "ask"


def test_export_var_cmdsub_redirect_env2():
    """Export with command substitution and redirection in env2 should ask."""
    result = evaluate_bash_command("export VAR=$(echo hi) > file", ENV2)
    assert result["status"] == "ask"


def test_unset_array_redirect_empty():
    """Unset array with redirection in empty config should ask."""
    result = evaluate_bash_command("unset arr[@] > file", EMPTY)
    assert result["status"] == "ask"


def test_declare_assoc_redirect_env2():
    """Declare associative array with redirection in env2 should ask."""
    result = evaluate_bash_command("declare -A map > file", ENV2)
    assert result["status"] == "ask"