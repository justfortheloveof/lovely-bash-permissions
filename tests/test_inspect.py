"""Comprehensive tests for AST inspection and helper methods."""

from lovely_bash_permissions import (
    find_arguments,
    find_commands,
    get_arguments,
    get_commands,
    get_target_files,
    has_pipe,
    iter_children,
    parse_ast,
)


class TestFindCommands:
    """Test find_commands() - find all CallExpr nodes."""

    def test_single_command(self) -> None:
        commands = find_commands(parse_ast("ls"))
        assert len(commands) == 1

    def test_multiple_commands_with_pipe(self) -> None:
        commands = find_commands(parse_ast("cat file.txt | grep pattern"))
        assert len(commands) == 2

    def test_complex_pipeline(self) -> None:
        commands = find_commands(parse_ast('cat data.csv | grep pattern | awk "{print $1}" | sort -u'))
        assert len(commands) == 4

    def test_no_commands(self) -> None:
        commands = find_commands(parse_ast('export PATH="/usr/bin"'))
        assert len(commands) == 0

    def test_command_name_substitution(self) -> None:
        """Commands in the command-name position are discovered."""
        commands = find_commands(parse_ast("$(ls | grep x) arg"))
        assert len(commands) == 3
        assert commands[0].args[0].parts[0].type == "CmdSubst"
        assert commands[1].args[0].parts[0].value == "ls"
        assert commands[2].args[0].parts[0].value == "grep"


class TestIterChildren:
    """Test the shared traversal helper exported for the CLI."""

    def test_exposed(self) -> None:
        from lovely_bash_permissions import CallExpr

        tree = parse_ast("ls -la")
        children = list(iter_children(tree.stmts[0]))
        assert len(children) == 1
        assert isinstance(children[0], CallExpr)


class TestFindArguments:
    """Test find_arguments() - find all argument lists."""

    def test_no_arguments(self) -> None:
        args = find_arguments(parse_ast("ls"))
        assert len(args) == 1

    def test_single_command_with_args(self) -> None:
        args = find_arguments(parse_ast("cat file.txt"))
        assert len(args) == 1
        assert len(args[0]) == 1

    def test_multiple_commands(self) -> None:
        args = find_arguments(parse_ast("ls -la | grep -i txt"))
        assert len(args) == 2


class TestHasPipe:
    """Test has_pipe() - check for pipe operators."""

    def test_no_pipe(self) -> None:
        assert not has_pipe(parse_ast("ls -la"))

    def test_single_pipe(self) -> None:
        assert has_pipe(parse_ast("cat file.txt | grep pattern"))

    def test_multiple_pipes(self) -> None:
        assert has_pipe(parse_ast("cat file.txt | grep pattern | sort | uniq"))

    def test_nested_commands(self) -> None:
        assert not has_pipe(parse_ast("ls\\ngrep pattern"))

    def test_redirection_without_pipe(self) -> None:
        assert not has_pipe(parse_ast("cat file.txt > output.txt"))


class TestGetTargetFiles:
    """Test get_target_files() - extract file targets from redirections."""

    def test_no_redirections(self) -> None:
        assert get_target_files(parse_ast("ls -la")) == []

    def test_output_redirect(self) -> None:
        targets = get_target_files(parse_ast("cat file.txt > output.txt"))
        assert len(targets) == 1

    def test_input_redirect(self) -> None:
        targets = get_target_files(parse_ast("sort < input.txt"))
        assert len(targets) == 1

    def test_append_redirect(self) -> None:
        targets = get_target_files(parse_ast("cat file.txt >> output.txt"))
        assert len(targets) == 1

    def test_multiple_redirections(self) -> None:
        targets = get_target_files(parse_ast("cat file.txt > output.txt 2> errors.txt"))
        assert len(targets) == 2


class TestIntegration:
    """Integration tests combining multiple inspection methods."""

    def test_complex_command(self) -> None:
        command = 'cat data.csv | grep pattern | awk "{print $1}" | sort -u > results.txt'
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
