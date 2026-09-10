"""Phase 11: Nested Constructs and Compound Expressions

Tests for deeply nested and compound bash expressions with redirections.
Verifies the tool correctly handles complex nested structures.
"""

from typing import Any

from lovely_bash_permissions.evaluate import evaluate_bash_command

EMPTY: dict[str, Any] = {}
ENV2 = {"bash": {"allowed_cmds_regex": ["^ls$", "^true$", "^echo$", "^cat$", "^grep$", "^find$"]}}
ENV3 = {"bash": {"allowed_cmds_regex": ["^ls .*", "^true$", "^echo$"], "blocked_paths_regex": ["/etc", "/home"]}}


def test_nested_command_substitution_empty() -> None:
    """Nested command substitution with output redirection should ask in empty config."""
    result = evaluate_bash_command("echo $(echo $(echo $(echo hi))) > file", EMPTY)
    assert result["status"] == "ask"


def test_nested_command_substitution_env2() -> None:
    """Nested command substitution with output redirection should ask in env2."""
    result = evaluate_bash_command("echo $(echo $(echo $(echo hi))) > file", ENV2)
    assert result["status"] == "ask"


def test_nested_command_substitution_env3() -> None:
    """Nested command substitution with output redirection should ask in env3."""
    result = evaluate_bash_command("echo $(echo $(echo $(echo hi))) > file", ENV3)
    assert result["status"] == "ask"


def test_pipe_chain_empty() -> None:
    """Pipe chain with output redirection should ask in empty config."""
    result = evaluate_bash_command("echo hi | grep hi | grep h | cat > file", EMPTY)
    assert result["status"] == "ask"


def test_pipe_chain_env2() -> None:
    """Pipe chain with output redirection should ask in env2."""
    result = evaluate_bash_command("echo hi | grep hi | grep h | cat > file", ENV2)
    assert result["status"] == "ask"


def test_pipe_chain_env3() -> None:
    """Pipe chain with output redirection should ask in env3."""
    result = evaluate_bash_command("echo hi | grep hi | grep h | cat > file", ENV3)
    assert result["status"] == "ask"


def test_complex_pipeline_empty() -> None:
    """Complex pipeline with output redirection should ask in empty config."""
    result = evaluate_bash_command("ls | grep text | xargs cat > file", EMPTY)
    assert result["status"] == "ask"


def test_complex_pipeline_env2() -> None:
    """Complex pipeline with output redirection should ask in env2."""
    result = evaluate_bash_command("ls | grep text | xargs cat > file", ENV2)
    assert result["status"] == "ask"


def test_complex_pipeline_env3() -> None:
    """Complex pipeline with output redirection should ask in env3."""
    result = evaluate_bash_command("ls | grep text | xargs cat > file", ENV3)
    assert result["status"] == "ask"


def test_nested_conditionals_empty() -> None:
    """Nested conditionals with output redirection should ask in empty config."""
    result = evaluate_bash_command("if [ x ]; then if [ y ]; then echo hi > file; fi; fi", EMPTY)
    assert result["status"] == "ask"


def test_nested_conditionals_env2() -> None:
    """Nested conditionals with output redirection should ask in env2."""
    result = evaluate_bash_command("if [ x ]; then if [ y ]; then echo hi > file; fi; fi", ENV2)
    assert result["status"] == "ask"


def test_nested_conditionals_env3() -> None:
    """Nested conditionals with output redirection should ask in env3."""
    result = evaluate_bash_command("if [ x ]; then if [ y ]; then echo hi > file; fi; fi", ENV3)
    assert result["status"] == "ask"


def test_compound_logical_empty() -> None:
    """Compound logical expressions with output redirection should ask in empty config."""
    result = evaluate_bash_command("[ x ] && ([ y ] || [ z ]) > file", EMPTY)
    assert result["status"] == "ask"


def test_compound_logical_env2() -> None:
    """Compound logical expressions with output redirection should ask in env2."""
    result = evaluate_bash_command("[ x ] && ([ y ] || [ z ]) > file", ENV2)
    assert result["status"] == "ask"


def test_compound_logical_env3() -> None:
    """Compound logical expressions with output redirection should ask in env3."""
    result = evaluate_bash_command("[ x ] && ([ y ] || [ z ]) > file", ENV3)
    assert result["status"] == "ask"


def test_brace_expansion_empty() -> None:
    """Brace expansion with output redirection should ask in empty config."""
    result = evaluate_bash_command("echo {a,b,c} > file", EMPTY)
    assert result["status"] == "ask"


def test_brace_expansion_env2() -> None:
    """Brace expansion with output redirection should ask in env2."""
    result = evaluate_bash_command("echo {a,b,c} > file", ENV2)
    assert result["status"] == "ask"


def test_brace_expansion_env3() -> None:
    """Brace expansion with output redirection should ask in env3."""
    result = evaluate_bash_command("echo {a,b,c} > file", ENV3)
    assert result["status"] == "ask"


def test_nested_brace_expansion_env2() -> None:
    """Nested brace expansion with output redirection should ask in env2."""
    result = evaluate_bash_command("echo {a,b}{c,d} > file", ENV2)
    assert result["status"] == "ask"


def test_heredoc_with_substitution_empty() -> None:
    """Here-document with substitution and output redirection should ask in empty config."""
    result = evaluate_bash_command("cat <<< $(echo hi) > file", EMPTY)
    assert result["status"] == "ask"


def test_heredoc_with_substitution_env2() -> None:
    """Here-document with substitution and output redirection should ask in env2."""
    result = evaluate_bash_command("cat <<< $(echo hi) > file", ENV2)
    assert result["status"] == "ask"


def test_heredoc_with_substitution_env3() -> None:
    """Here-document with substitution and output redirection should ask in env3."""
    result = evaluate_bash_command("cat <<< $(echo hi) > file", ENV3)
    assert result["status"] == "ask"
