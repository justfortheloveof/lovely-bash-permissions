"""Comprehensive tests for AST inspection and helper methods."""

from lovely_bash_permissions import (
    find_arguments,
    find_commands,
    get_arguments,
    get_commands,
    get_target_files,
    has_pipe,
    parse_ast,
)


class TestFindCommands:
    """Test find_commands() - find all CallExpr nodes."""

    def test_single_command(self):
        commands = find_commands(parse_ast("ls"))
        assert len(commands) == 1

    def test_multiple_commands_with_pipe(self):
        commands = find_commands(parse_ast("cat file.txt | grep pattern"))
        assert len(commands) == 2

    def test_complex_pipeline(self):
        commands = find_commands(
            parse_ast('cat data.csv | grep pattern | awk "{print $1}" | sort -u')
        )
        assert len(commands) == 4

    def test_no_commands(self):
        commands = find_commands(parse_ast('export PATH="/usr/bin"'))
        assert len(commands) == 0


class TestFindArguments:
    """Test find_arguments() - find all argument lists."""

    def test_no_arguments(self):
        args = find_arguments(parse_ast("ls"))
        assert len(args) == 1

    def test_single_command_with_args(self):
        args = find_arguments(parse_ast("cat file.txt"))
        assert len(args) == 1
        assert len(args[0]) == 1

    def test_multiple_commands(self):
        args = find_arguments(parse_ast("ls -la | grep -i txt"))
        assert len(args) == 2


class TestHasPipe:
    """Test has_pipe() - check for pipe operators."""

    def test_no_pipe(self):
        assert not has_pipe(parse_ast("ls -la"))

    def test_single_pipe(self):
        assert has_pipe(parse_ast("cat file.txt | grep pattern"))

    def test_multiple_pipes(self):
        assert has_pipe(parse_ast("cat file.txt | grep pattern | sort | uniq"))

    def test_nested_commands(self):
        assert not has_pipe(parse_ast("ls\\ngrep pattern"))

    def test_redirection_without_pipe(self):
        assert not has_pipe(parse_ast("cat file.txt > output.txt"))


class TestGetTargetFiles:
    """Test get_target_files() - extract file targets from redirections."""

    def test_no_redirections(self):
        assert get_target_files(parse_ast("ls -la")) == []

    def test_output_redirect(self):
        targets = get_target_files(parse_ast("cat file.txt > output.txt"))
        assert len(targets) == 1

    def test_input_redirect(self):
        targets = get_target_files(parse_ast("sort < input.txt"))
        assert len(targets) == 1

    def test_append_redirect(self):
        targets = get_target_files(parse_ast("cat file.txt >> output.txt"))
        assert len(targets) == 1

    def test_multiple_redirections(self):
        targets = get_target_files(parse_ast("cat file.txt > output.txt 2> errors.txt"))
        assert len(targets) == 2


class TestIntegration:
    """Integration tests combining multiple inspection methods."""

    def test_complex_command(self):
        command = (
            'cat data.csv | grep pattern | awk "{print $1}" | sort -u > results.txt'
        )
        tree = parse_ast(command)

        commands = get_commands(tree)
        assert "cat" in commands and "grep" in commands

        call_exprs = find_commands(tree)
        assert len(call_exprs) == 4

        assert has_pipe(tree)

        targets = get_target_files(tree)
        assert len(targets) == 1

        args = get_arguments(tree)
        assert len(args) == 4
