"""Phase 10: Tricky Patterns

Tests for uncommon or ambiguous bash syntax with redirections.
These patterns often trip up parsers with no spaces, mixed direction
redirections, fd manipulation, and background job combinations.
"""

from typing import Any

from lovely_bash_permissions.evaluate import evaluate_bash_command

# Config: empty (no rules, wildcard: allow)
EMPTY: dict[str, Any] = {}

# Config: env2 (true, echo allowed)
ENV2 = {"bash": {"allowed_cmds_regex": ["^true$", "^echo$"]}}

# Config: env3 (true, echo allowed, /etc blocked)
ENV3 = {"bash": {"allowed_cmds_regex": ["^true$", "^echo$"], "blocked_paths_regex": ["/etc"]}}


def test_phase10_no_space_redirect_empty() -> None:
    """true>file (no space) should require approval in empty config."""
    result = evaluate_bash_command("true>file", EMPTY)
    assert result["status"] == "ask"


def test_phase10_no_space_redirect_env2() -> None:
    """true>file (no space) should require approval in env2 (redirection requires approval)."""
    result = evaluate_bash_command("true>file", ENV2)
    assert result["status"] == "ask"


def test_phase10_partial_space_redirect_env2() -> None:
    """true> file (partial space) should require approval in env2."""
    result = evaluate_bash_command("true> file", ENV2)
    assert result["status"] == "ask"


def test_phase10_no_space_after_redirect_env2() -> None:
    """true >file (no space after) should require approval in env2."""
    result = evaluate_bash_command("true >file", ENV2)
    assert result["status"] == "ask"


def test_phase10_chained_redirect_empty() -> None:
    """true > file > file2 should require approval in empty config."""
    result = evaluate_bash_command("true > file > file2", EMPTY)
    assert result["status"] == "ask"


def test_phase10_chained_redirect_env2() -> None:
    """true > file > file2 should require approval in env2."""
    result = evaluate_bash_command("true > file > file2", ENV2)
    assert result["status"] == "ask"


def test_phase10_mixed_direction_redirect_empty() -> None:
    """true > file < file2 should require approval in empty config."""
    result = evaluate_bash_command("true > file < file2", EMPTY)
    assert result["status"] == "ask"


def test_phase10_mixed_direction_redirect_env2() -> None:
    """true > file < file2 should require approval in env2."""
    result = evaluate_bash_command("true > file < file2", ENV2)
    assert result["status"] == "ask"


def test_phase10_stderr_to_stdout_empty() -> None:
    """true > file 2>&1 should require approval in empty config."""
    result = evaluate_bash_command("true > file 2>&1", EMPTY)
    assert result["status"] == "ask"


def test_phase10_stderr_to_stdout_env2() -> None:
    """true > file 2>&1 should require approval in env2."""
    result = evaluate_bash_command("true > file 2>&1", ENV2)
    assert result["status"] == "ask"


def test_phase10_background_empty() -> None:
    """true > file & should require approval in empty config."""
    result = evaluate_bash_command("true > file &", EMPTY)
    assert result["status"] == "ask"


def test_phase10_background_env2() -> None:
    """true > file & should require approval in env2."""
    result = evaluate_bash_command("true > file &", ENV2)
    assert result["status"] == "ask"


def test_phase10_devnull_empty() -> None:
    """cmd > /dev/null should require approval in empty config."""
    result = evaluate_bash_command("cmd > /dev/null", EMPTY)
    assert result["status"] == "ask"


def test_phase10_devnull_env2() -> None:
    """cmd > /dev/null should require approval in env2 (cmd not allowed)."""
    result = evaluate_bash_command("cmd > /dev/null", ENV2)
    assert result["status"] == "ask"


def test_phase10_devnull_env3() -> None:
    """cmd > /dev/null should require approval in env3 (cmd not allowed)."""
    result = evaluate_bash_command("cmd > /dev/null", ENV3)
    assert result["status"] == "ask"


def test_phase10_devnull_input_empty() -> None:
    """cmd < /dev/null should require approval in empty config."""
    result = evaluate_bash_command("cmd < /dev/null", EMPTY)
    assert result["status"] == "ask"


def test_phase10_devnull_chain_empty() -> None:
    """true > /dev/null 2>&1 > /dev/null should require approval in empty config."""
    result = evaluate_bash_command("true > /dev/null 2>&1 > /dev/null", EMPTY)
    assert result["status"] == "ask"


def test_phase10_devnull_chain_env2() -> None:
    """true > /dev/null 2>&1 > /dev/null should require approval in env2."""
    result = evaluate_bash_command("true > /dev/null 2>&1 > /dev/null", ENV2)
    assert result["status"] == "ask"


def test_phase10_save_fd_empty() -> None:
    """true 3>&1 > /dev/null should require approval in empty config."""
    result = evaluate_bash_command("true 3>&1 > /dev/null", EMPTY)
    assert result["status"] == "ask"


def test_phase10_save_fd_env2() -> None:
    """true 3>&1 > /dev/null should require approval in env2."""
    result = evaluate_bash_command("true 3>&1 > /dev/null", ENV2)
    assert result["status"] == "ask"


def test_phase10_save_fd_after_empty() -> None:
    """true > /dev/null 3>&1 should require approval in empty config."""
    result = evaluate_bash_command("true > /dev/null 3>&1", EMPTY)
    assert result["status"] == "ask"


def test_phase10_save_fd_after_env2() -> None:
    """true > /dev/null 3>&1 should require approval in env2."""
    result = evaluate_bash_command("true > /dev/null 3>&1", ENV2)
    assert result["status"] == "ask"


def test_phase10_redirect_order_empty() -> None:
    """true > file </dev/null should require approval in empty config."""
    result = evaluate_bash_command("true > file </dev/null", EMPTY)
    assert result["status"] == "ask"


def test_phase10_redirect_order_env2() -> None:
    """true > file </dev/null should require approval in env2."""
    result = evaluate_bash_command("true > file </dev/null", ENV2)
    assert result["status"] == "ask"


def test_phase10_other_redirect_order_empty() -> None:
    """true </dev/null > file should require approval in empty config."""
    result = evaluate_bash_command("true </dev/null > file", EMPTY)
    assert result["status"] == "ask"


def test_phase10_other_redirect_order_env2() -> None:
    """true </dev/null > file should require approval in env2."""
    result = evaluate_bash_command("true </dev/null > file", ENV2)
    assert result["status"] == "ask"


def test_phase10_complex_bg_empty() -> None:
    """true > file1 2>&1 & true > file2 should require approval in empty config."""
    result = evaluate_bash_command("true > file1 2>&1 & true > file2", EMPTY)
    assert result["status"] == "ask"


def test_phase10_complex_bg_env2() -> None:
    """true > file1 2>&1 & true > file2 should require approval in env2."""
    result = evaluate_bash_command("true > file1 2>&1 & true > file2", ENV2)
    assert result["status"] == "ask"
