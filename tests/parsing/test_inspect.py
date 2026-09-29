"""Comprehensive tests for AST inspection and helper methods."""

from lovely_bash_permissions import (
    CmdSubst,
    DblQuoted,
    Lit,
    ParamExp,
    SglQuoted,
    Word,
    find_arguments,
    find_commands,
    get_arguments,
    get_commands,
    get_target_files,
    has_pipe,
    iter_children,
    parse_ast,
)
from lovely_bash_permissions.inspect import _word_exec


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
        node1 = commands[1].args[0].parts[0]
        assert node1 is not None
        assert isinstance(node1, Lit)
        assert node1.value == "ls"
        node2 = commands[2].args[0].parts[0]
        assert node2 is not None
        assert isinstance(node2, Lit)
        assert node2.value == "grep"


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

    def test_statements_on_separate_lines_without_pipe(self) -> None:
        tree = parse_ast("ls\ngrep pattern")
        # Two separate statements across a newline, no pipe operator.
        assert len(tree.stmts) == 2
        assert not has_pipe(tree)

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


class TestGetCommandsParamExp:
    """Commands inside parameter expansions are reported."""

    def test_repl_replacement(self) -> None:
        commands = get_commands(parse_ast("echo ${x//a/$(rm -rf x)}"))
        assert "rm" in commands

    def test_repl_pattern(self) -> None:
        commands = get_commands(parse_ast("echo ${x//$(recon_cmd)/y}"))
        assert "recon_cmd" in commands

    def test_exp_default(self) -> None:
        commands = get_commands(parse_ast('echo "${y:-$(rm -rf x)}"'))
        assert "rm" in commands

    def test_exp_trim(self) -> None:
        commands = get_commands(parse_ast('echo "${z%$(cat /etc/passwd)}"'))
        assert "cat" in commands

    def test_slice_offset(self) -> None:
        commands = get_commands(parse_ast("echo ${x:$(seq 3)}"))
        assert "seq" in commands


class TestWordExec:
    """Test _word_exec() - the executed-form renderer (quotes removed,
    backslashes unescaped bash-style, expansion placeholders kept)."""

    def test_quote_split_path(self) -> None:
        word = Word(parts=[Lit(value="/e"), DblQuoted(parts=[Lit(value="tc")], value=None), Lit(value="/passwd")])
        assert _word_exec(word) == "/etc/passwd"

    def test_backslash_escaped_flag(self) -> None:
        # shfmt parses `find /tmp -ex\ec` as a single Lit with a backslash
        # literal; unquoted backslash drops the next character.
        word = Word(parts=[Lit(value=r"-ex\ec")])
        assert _word_exec(word) == "-exec"

    def test_double_quoted_backslash_t_stays(self) -> None:
        # Inside "..." bash only unescapes $ ` " \ and newline, so a
        # backslash-t keeps its backslash.
        word = Word(parts=[DblQuoted(parts=[Lit(value="/e\tc/passwd")], value=None)])
        assert _word_exec(word) == "/e\tc/passwd"

    def test_single_quoted_verbatim(self) -> None:
        # Single quotes: content is verbatim, no unescaping.
        word = Word(parts=[SglQuoted(value='"a\b"')])
        assert _word_exec(word) == '"a\b"'

    def test_param_exp_placeholder(self) -> None:
        word = Word(parts=[ParamExp(param="DIR"), Lit(value="/out.txt")])
        assert _word_exec(word) == "$DIR/out.txt"

    def test_cmd_subst_placeholder(self) -> None:
        word = Word(parts=[CmdSubst(), Lit(value="/x")])
        assert _word_exec(word) == "$(...)/x"

    def test_plain_literal(self) -> None:
        word = Word(parts=[Lit(value="hello")])
        assert _word_exec(word) == "hello"

    def test_nested_double_quotes(self) -> None:
        # Adjacent double-quoted regions ("/dev""/null") render as the
        # concatenated content.
        word = Word(
            parts=[DblQuoted(parts=[Lit(value="/dev"), DblQuoted(parts=[Lit(value="/null")], value=None)], value=None)]
        )
        assert _word_exec(word) == "/dev/null"

    def test_double_quoted_with_expansion(self) -> None:
        # "..." with a nested ParamExp: placeholder kept, backslash rules
        # applied to the nested Lit in double-quote context.
        word = Word(parts=[DblQuoted(parts=[ParamExp(param="DIR"), Lit(value="/out.txt")], value=None)])
        assert _word_exec(word) == "$DIR/out.txt"
