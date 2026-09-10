"""Phase 12: Complex Nested Constructs

Tests for deeply nested and compound bash expressions with redirections.
Verifies the tool correctly handles complex nested structures including
process substitution, loops, conditionals, functions, and compound commands.
"""

import pytest
from lovely_bash_permissions.evaluate import evaluate_bash_command

# Config: empty (no rules)
EMPTY = {}

# Config: env2 (ls, true, echo, cat, grep, find allowed)
ENV2 = {
    "bash": {
        "allowed_cmds_regex": ["^ls$", "^true$", "^echo$", "^cat$", "^grep$", "^find$"]
    }
}

# Config: env3 (ls, true, echo allowed, /etc, /home blocked)
ENV3 = {
    "bash": {
        "allowed_cmds_regex": ["^ls .*", "^true$", "^echo$"],
        "blocked_paths_regex": ["/etc", "/home"]
    }
}


def test_if_with_cmdsub_and_pipe():
    """if with command substitution, here-doc, pipe, and redirection."""
    result = evaluate_bash_command("if [ $(echo hi) ]; then cat <<< \"x\" | grep x > file; fi", ENV2)
    assert result["status"] == "ask"


def test_for_loop_with_cmdsub():
    """for loop with command substitution and redirection."""
    result = evaluate_bash_command("for i in $(seq 1 3); do echo $i > file; done", ENV2)
    assert result["status"] == "ask"


def test_heredoc_with_pipe():
    """here-document piped to grep with output redirection."""
    result = evaluate_bash_command("cat << EOF | grep pattern > file\ncontent\nEOF", ENV2)
    assert result["status"] == "ask"


def test_if_with_procsub():
    """if with process substitution and nested command substitution."""
    result = evaluate_bash_command("if $(test -f <(echo hi)); then cat <<< $(echo ok) > file; fi", ENV2)
    assert result["status"] == "ask"


def test_nested_conditionals():
    """nested if statements with command substitution."""
    result = evaluate_bash_command("if [ $(echo x) ]; then if [ $(echo y) ]; then echo both > file; fi; fi", ENV2)
    assert result["status"] == "ask"


def test_while_loop():
    """while loop with command substitution and redirection."""
    result = evaluate_bash_command("while true; do if [ $(echo x) ]; then break; fi; done > file", ENV2)
    assert result["status"] == "ask"


def test_case_statement():
    """case statement with command substitution."""
    result = evaluate_bash_command("case $(echo x) in x) echo ok > file;; esac", ENV2)
    assert result["status"] == "ask"


def test_select_statement():
    """select statement with command substitution."""
    result = evaluate_bash_command("select opt in $(echo a b); do echo $opt > file; done", ENV2)
    assert result["status"] == "ask"


def test_compound_with_procsub():
    """compound command with process substitution."""
    result = evaluate_bash_command("{ cat <(echo hi); } > file", ENV2)
    assert result["status"] == "ask"


def test_subshell_with_procsub():
    """subshell with process substitution."""
    result = evaluate_bash_command("(cat <(echo hi)) > file", ENV2)
    assert result["status"] == "ask"


def test_function_definition():
    """function definition with output redirection."""
    result = evaluate_bash_command("fn() { echo hi > file; }; fn", ENV2)
    assert result["status"] == "ask"


def test_subshell_function():
    """subshell containing function definition."""
    result = evaluate_bash_command("(fn() { echo hi > file; }; fn)", ENV2)
    assert result["status"] == "ask"