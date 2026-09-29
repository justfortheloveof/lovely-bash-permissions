"""
Comprehensive tests for the lovely-bash-permissions parser
"""

import pytest

from lovely_bash_permissions import (
    ArithmExp,
    BinaryArithm,
    BinaryCmd,
    Block,
    CallExpr,
    CmdSubst,
    DblQuoted,
    ExtGlob,
    FuncDecl,
    IfClause,
    Lit,
    ParamExp,
    ParamExpExp,
    ParamExpSlice,
    ProcSubst,
    SglQuoted,
    Subshell,
    Word,
    get_arguments,
    get_commands,
    get_redirections,
    has_variable,
    parse_ast,
)
from lovely_bash_permissions.errors import ShfmtError
from lovely_bash_permissions.parser import ParseError, parse
from lovely_bash_permissions.segments import parse_segments


class TestSimpleCommands:
    """Test simple command parsing."""

    def test_single_command(self) -> None:
        tree = parse_ast("ls")
        assert get_commands(tree) == ["ls"]
        assert get_arguments(tree) == [[]]

    def test_command_with_flags(self) -> None:
        tree = parse_ast("ls -la")
        assert get_commands(tree) == ["ls"]
        assert get_arguments(tree) == [["-la"]]

    def test_command_with_multiple_args(self) -> None:
        tree = parse_ast("cp file1.txt file2.txt")
        assert get_commands(tree) == ["cp"]
        assert get_arguments(tree) == [["file1.txt", "file2.txt"]]

    def test_echo_command(self) -> None:
        tree = parse_ast("echo hello")
        assert get_commands(tree) == ["echo"]
        assert get_arguments(tree) == [["hello"]]


class TestPipes:
    """Test pipe parsing."""

    def test_single_pipe(self) -> None:
        tree = parse_ast("cat file.txt | grep pattern")
        assert get_commands(tree) == ["cat", "grep"]
        assert get_arguments(tree) == [["file.txt"], ["pattern"]]

    def test_multiple_pipes(self) -> None:
        tree = parse_ast("cat file.txt | grep pattern | sort | uniq")
        assert get_commands(tree) == ["cat", "grep", "sort", "uniq"]
        assert get_arguments(tree) == [["file.txt"], ["pattern"], [], []]

    def test_pipe_with_flags(self) -> None:
        tree = parse_ast("ls -la | grep -i txt")
        assert get_commands(tree) == ["ls", "grep"]
        assert get_arguments(tree) == [["-la"], ["-i", "txt"]]


class TestRedirections:
    """Test redirection parsing."""

    def test_output_redirect(self) -> None:
        tree = parse_ast("cat file.txt > output.txt")
        assert get_commands(tree) == ["cat"]
        assert get_arguments(tree) == [["file.txt"]]
        redirs = get_redirections(tree)
        assert len(redirs) == 1
        assert redirs[0]["op"] == ">"
        assert redirs[0]["target"] == "output.txt"

    def test_append_redirect(self) -> None:
        tree = parse_ast("cat file.txt >> output.txt")
        redirs = get_redirections(tree)
        assert len(redirs) == 1
        assert redirs[0]["op"] == ">>"

    def test_input_redirect(self) -> None:
        tree = parse_ast("sort < input.txt")
        redirs = get_redirections(tree)
        assert len(redirs) == 1
        assert redirs[0]["op"] == "<"

    def test_pipe_with_redirect(self) -> None:
        tree = parse_ast("ls -la | grep txt > output.txt")
        assert get_commands(tree) == ["ls", "grep"]
        assert get_arguments(tree) == [["-la"], ["txt"]]
        redirs = get_redirections(tree)
        assert len(redirs) == 1
        assert redirs[0]["op"] == ">"
        assert redirs[0]["target"] == "output.txt"

    def test_redirect_on_left_of_and(self) -> None:
        """Redirection on the X side of && must not be dropped."""
        tree = parse_ast("cmd4 > out4 && ls")
        redirs = get_redirections(tree)
        assert len(redirs) == 1
        assert redirs[0]["op"] == ">"
        assert redirs[0]["target"] == "out4"

    def test_redirect_on_middle_of_pipeline(self) -> None:
        """Redirection on a non-final pipeline segment must not be dropped."""
        tree = parse_ast("cmd1 | cmd2 > f | cmd3")
        redirs = get_redirections(tree)
        assert len(redirs) == 1
        assert redirs[0]["op"] == ">"
        assert redirs[0]["target"] == "f"

    def test_redirect_on_right_of_and(self) -> None:
        """Redirection on the Y side of && must not be dropped."""
        tree = parse_ast("cmd > out && ls")
        redirs = get_redirections(tree)
        assert len(redirs) == 1
        assert redirs[0]["op"] == ">"
        assert redirs[0]["target"] == "out"

    def test_trailing_redirect_on_pipe_lives_on_binary_cmd(self) -> None:
        """A pipe's trailing redirection is stored on the BinaryCmd node."""
        tree = parse_ast("echo hi | cat > out")
        stmt = tree.stmts[0]
        assert isinstance(stmt.cmd, BinaryCmd)
        assert stmt.cmd.redirs
        assert stmt.cmd.redirs[0].op == ">"
        redir_word = stmt.cmd.redirs[0].word
        assert isinstance(redir_word, Word)
        rw_part = redir_word.parts[0]
        assert isinstance(rw_part, Lit)
        assert rw_part.value == "out"


class TestVariables:
    """Test variable detection."""

    def test_no_variables(self) -> None:
        tree = parse_ast("ls -la")
        assert not has_variable(tree)

    def test_simple_variable(self) -> None:
        tree = parse_ast("echo $HOME")
        assert has_variable(tree)

    def test_path_variable(self) -> None:
        tree = parse_ast("cat /path/to/file")
        assert not has_variable(tree)

    def test_multiple_variables(self) -> None:
        tree = parse_ast("echo $HOME $USER")
        assert has_variable(tree)

    def test_quoted_variable(self) -> None:
        tree = parse_ast('echo "$HOME"')
        assert has_variable(tree)

    def test_env_var(self) -> None:
        tree = parse_ast('export PATH="$HOME/bin:$PATH"')
        assert has_variable(tree)


class TestComplexCommands:
    """Test complex command parsing."""

    def test_complex_pipeline(self) -> None:
        tree = parse_ast('cat data.csv | grep pattern | awk "{print $1}" | sort -u > results.txt')
        commands = get_commands(tree)
        assert "cat" in commands
        assert "grep" in commands
        assert "awk" in commands
        assert "sort" in commands
        # awk's argument has inner structure (DblQuoted with parts)
        # shfmt evaluates variables within double-quoted strings
        args = get_arguments(tree)
        assert len(args) == 4
        assert args[0] == ["data.csv"]
        assert args[1] == ["pattern"]
        # args[2] is the awk program - has inner structure, not a simple value
        assert args[3] == ["-u"]
        redirs = get_redirections(tree)
        assert len(redirs) == 1
        assert redirs[0]["target"] == "results.txt"

    def test_command_with_quoted_args(self) -> None:
        tree = parse_ast('find / -name "*.txt" -type f')
        assert get_commands(tree) == ["find"]
        args = get_arguments(tree)
        assert len(args) == 1
        assert args[0][0] == "/"
        assert args[0][1] == "-name"
        assert args[0][3] == "-type"
        assert args[0][4] == "f"

    def test_long_command(self) -> None:
        tree = parse_ast(
            'tar -czvf archive.tar.gz $(find . -name "*.py" -not -path "./.venv/*" -not -path "./tests/*")'
        )
        assert get_commands(tree) == ["tar", "find"]
        assert has_variable(tree)


class TestEdgeCases:
    """Test edge cases."""

    def test_empty_command(self) -> None:
        with pytest.raises(ParseError):
            parse_ast("")

    def test_whitespace_only(self) -> None:
        with pytest.raises(ParseError):
            parse_ast("   ")

    def test_single_quote(self) -> None:
        tree = parse_ast("echo 'hello world'")
        assert get_commands(tree) == ["echo"]

    def test_double_quote(self) -> None:
        tree = parse_ast('echo "hello world"')
        assert get_commands(tree) == ["echo"]


class TestErrorTypes:
    """ShfmtError hierarchy and infra-failure wrapping."""

    def test_parse_error_is_shfmt_error(self) -> None:
        assert issubclass(ParseError, ShfmtError)

    def test_missing_shfmt_wrapped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _raise_missing() -> str:
            raise FileNotFoundError("shfmt binary not found")

        monkeypatch.setattr("lovely_bash_permissions.parser.find_shfmt", _raise_missing)
        with pytest.raises(ShfmtError, match="shfmt binary not found"):
            parse("ls")

    def test_timeout_wrapped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import subprocess

        def _fake_run(*args: object, **kwargs: object) -> None:
            raise subprocess.TimeoutExpired(cmd="shfmt", timeout=30)

        monkeypatch.setattr("lovely_bash_permissions.parser.find_shfmt", lambda: "/usr/bin/shfmt")
        monkeypatch.setattr("lovely_bash_permissions.parser.subprocess.run", _fake_run)
        with pytest.raises(ShfmtError, match="timed out"):
            parse("ls")

    def test_os_error_wrapped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _fake_run(*args: object, **kwargs: object) -> None:
            raise OSError("exec format error")

        monkeypatch.setattr("lovely_bash_permissions.parser.find_shfmt", lambda: "/usr/bin/shfmt")
        monkeypatch.setattr("lovely_bash_permissions.parser.subprocess.run", _fake_run)
        with pytest.raises(ShfmtError, match="failed to run shfmt"):
            parse("ls")


class TestASTStructure:
    """Test AST structure and types."""

    def test_file_node_type(self) -> None:
        tree = parse_ast("ls")
        assert tree.type == "File"

    def test_stmt_count(self) -> None:
        tree = parse_ast("ls")
        assert len(tree.stmts) == 1

    def test_multiple_stmts(self) -> None:
        tree = parse_ast("ls\ngrep pattern file.txt")
        assert len(tree.stmts) == 2
        assert get_commands(tree) == ["ls", "grep"]

    def test_call_expr_node(self) -> None:
        tree = parse_ast("ls")
        cmd = tree.stmts[0].cmd
        assert cmd is not None
        assert isinstance(cmd, CallExpr)
        assert cmd.type == "CallExpr"

    def test_binary_cmd_node(self) -> None:
        tree = parse_ast("ls | grep txt")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, BinaryCmd)
        assert cmd.op == "|"


class TestLitNodes:
    """Tests for the Lit node type."""

    def test_simple_literal_value(self) -> None:
        """Parse a simple command and find the Lit node with its value."""
        tree = parse_ast("ls")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, CallExpr)
        # First arg is the command name as a Word containing a Lit part
        assert len(cmd.args) == 1
        cmd_arg = cmd.args[0]
        assert isinstance(cmd_arg, Word)
        assert len(cmd_arg.parts) == 1
        part = cmd_arg.parts[0]
        assert isinstance(part, Lit)
        assert part.type == "Lit"
        assert part.value == "ls"

    def test_literal_argument(self) -> None:
        """Parse echo hello and verify the Lit argument value."""
        tree = parse_ast("echo hello")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, CallExpr)
        # Second arg is the argument
        cmd_arg = cmd.args[1]
        assert isinstance(cmd_arg, Word)
        part = cmd_arg.parts[0]
        assert isinstance(part, Lit)
        assert part.type == "Lit"
        assert part.value == "hello"

    def test_literal_file_name(self) -> None:
        """Parse cat file.txt and verify the Lit file argument."""
        tree = parse_ast("cat file.txt")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, CallExpr)
        cmd_arg = cmd.args[1]
        assert isinstance(cmd_arg, Word)
        part = cmd_arg.parts[0]
        assert isinstance(part, Lit)
        assert part.type == "Lit"
        assert part.value == "file.txt"

    def test_literal_flag(self) -> None:
        """Parse ls -la and verify the Lit flag argument."""
        tree = parse_ast("ls -la")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, CallExpr)
        cmd_arg = cmd.args[1]
        assert isinstance(cmd_arg, Word)
        part = cmd_arg.parts[0]
        assert isinstance(part, Lit)
        assert part.type == "Lit"
        assert part.value == "-la"

    def test_multiple_literal_arguments(self) -> None:
        """Parse cp with multiple literal arguments."""
        tree = parse_ast("cp file1.txt file2.txt")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, CallExpr)
        assert len(cmd.args) == 3
        cmd_arg0 = cmd.args[0]
        assert isinstance(cmd_arg0, Word)
        part0 = cmd_arg0.parts[0]
        assert isinstance(part0, Lit)
        assert part0.type == "Lit"
        assert part0.value == "cp"
        cmd_arg1 = cmd.args[1]
        assert isinstance(cmd_arg1, Word)
        part1 = cmd_arg1.parts[0]
        assert isinstance(part1, Lit)
        assert part1.type == "Lit"
        assert part1.value == "file1.txt"
        cmd_arg2 = cmd.args[2]
        assert isinstance(cmd_arg2, Word)
        part2 = cmd_arg2.parts[0]
        assert isinstance(part2, Lit)
        assert part2.type == "Lit"
        assert part2.value == "file2.txt"

    def test_literal_in_pipe(self) -> None:
        """Parse a piped command and verify both commands have Lit parts."""
        tree = parse_ast("cat file.txt | grep pattern")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, BinaryCmd)
        # Left side: cat file.txt
        cmd_left = cmd.left
        assert isinstance(cmd_left, CallExpr)
        left_arg0 = cmd_left.args[0]
        assert isinstance(left_arg0, Word)
        left_part0 = left_arg0.parts[0]
        assert isinstance(left_part0, Lit)
        assert left_part0.type == "Lit"
        assert left_part0.value == "cat"
        left_arg1 = cmd_left.args[1]
        assert isinstance(left_arg1, Word)
        left_part1 = left_arg1.parts[0]
        assert isinstance(left_part1, Lit)
        assert left_part1.type == "Lit"
        assert left_part1.value == "file.txt"
        # Right side: grep pattern
        cmd_right = cmd.right
        assert isinstance(cmd_right, CallExpr)
        right_arg0 = cmd_right.args[0]
        assert isinstance(right_arg0, Word)
        right_part0 = right_arg0.parts[0]
        assert isinstance(right_part0, Lit)
        assert right_part0.type == "Lit"
        assert right_part0.value == "grep"
        right_arg1 = cmd_right.args[1]
        assert isinstance(right_arg1, Word)
        right_part1 = right_arg1.parts[0]
        assert isinstance(right_part1, Lit)
        assert right_part1.type == "Lit"
        assert right_part1.value == "pattern"

    def test_literal_with_special_chars(self) -> None:
        """Parse a command with special characters in a literal."""
        tree = parse_ast("echo hello-world_123")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, CallExpr)
        cmd_arg = cmd.args[1]
        assert isinstance(cmd_arg, Word)
        part = cmd_arg.parts[0]
        assert isinstance(part, Lit)
        assert part.type == "Lit"
        assert part.value == "hello-world_123"

    def test_literal_with_slash(self) -> None:
        """Parse a command with a file path (slashes are allowed in literals)."""
        tree = parse_ast("cat /path/to/file.txt")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, CallExpr)
        cmd_arg = cmd.args[1]
        assert isinstance(cmd_arg, Word)
        part = cmd_arg.parts[0]
        assert isinstance(part, Lit)
        assert part.type == "Lit"
        assert part.value == "/path/to/file.txt"

    def test_no_literal_with_variable(self) -> None:
        """Parse echo $HOME - variable is not a Lit node."""
        tree = parse_ast("echo $HOME")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, CallExpr)
        # The argument should be a ParamExp (short-form $var), not a Lit
        cmd_arg = cmd.args[1]
        assert isinstance(cmd_arg, Word)
        part = cmd_arg.parts[0]
        assert part.type == "ParamExp"

    def test_no_literal_with_command_substitution(self) -> None:
        """Parse echo $(date) - command substitution is not a Lit node."""
        tree = parse_ast("echo $(date)")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, CallExpr)
        # The argument should be a CmdSubst, not a Lit
        cmd_arg = cmd.args[1]
        assert isinstance(cmd_arg, Word)
        part = cmd_arg.parts[0]
        assert part.type == "CmdSubst"

    def test_no_literal_with_quoted_string(self) -> None:
        """Parse echo 'quoted' - quoted strings are SglQuoted, not Lit."""
        tree = parse_ast("echo 'quoted'")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, CallExpr)
        # The argument should be a SglQuoted, not a Lit
        cmd_arg = cmd.args[1]
        assert isinstance(cmd_arg, Word)
        part = cmd_arg.parts[0]
        assert part.type == "SglQuoted"

    def test_literal_in_redirect(self) -> None:
        """Parse command with output redirect and verify Lit in redirect target."""
        tree = parse_ast("echo hello > output.txt")
        # The redirect target should contain a Lit with the filename
        word = tree.stmts[0].redirs[0].word
        assert isinstance(word, Word)
        part = word.parts[0]
        assert isinstance(part, Lit)
        assert part.type == "Lit"
        assert part.value == "output.txt"

    def test_literal_number(self) -> None:
        """Parse a command with a numeric literal."""
        tree = parse_ast("sleep 5")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, CallExpr)
        cmd_arg = cmd.args[1]
        assert isinstance(cmd_arg, Word)
        part = cmd_arg.parts[0]
        assert isinstance(part, Lit)
        assert part.type == "Lit"
        assert part.value == "5"

    def test_literal_empty_word(self) -> None:
        """Parse a command and check that command name is a Lit node."""
        tree = parse_ast("true")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, CallExpr)
        cmd_arg = cmd.args[0]
        assert isinstance(cmd_arg, Word)
        part = cmd_arg.parts[0]
        assert isinstance(part, Lit)
        assert part.type == "Lit"
        assert part.value == "true"

    def test_literal_multiline(self) -> None:
        """Parse multiple commands across lines and check Lit in both."""
        tree = parse_ast("echo a\necho b")
        # First command
        cmd0 = tree.stmts[0].cmd
        assert isinstance(cmd0, CallExpr)
        arg0 = cmd0.args[1]
        assert isinstance(arg0, Word)
        part0 = arg0.parts[0]
        assert isinstance(part0, Lit)
        assert part0.type == "Lit"
        assert part0.value == "a"
        # Second command
        cmd1 = tree.stmts[1].cmd
        assert isinstance(cmd1, CallExpr)
        arg1 = cmd1.args[1]
        assert isinstance(arg1, Word)
        part1 = arg1.parts[0]
        assert isinstance(part1, Lit)
        assert part1.type == "Lit"
        assert part1.value == "b"

    def test_literal_in_subshell(self) -> None:
        """Parse a subshell with a command and verify Lit inside."""
        tree = parse_ast("(echo hello)")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, Subshell)
        inner_cmd = cmd.stmts[0].cmd
        assert isinstance(inner_cmd, CallExpr)
        inner_arg = inner_cmd.args[1]
        assert isinstance(inner_arg, Word)
        part = inner_arg.parts[0]
        assert isinstance(part, Lit)
        assert part.type == "Lit"
        assert part.value == "hello"

    def test_literal_position_info(self) -> None:
        """Verify that Lit nodes have position information from shfmt."""
        tree = parse_ast("ls -la")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, CallExpr)
        # Verify that lit parts have proper pos/end values
        for arg in cmd.args:
            assert isinstance(arg, Word)
            for part in arg.parts:
                if part.type == "Lit":
                    assert isinstance(part, Lit)
                    assert part.pos is not None
                    assert part.end is not None
                    assert isinstance(part.pos.offset, int)
                    assert isinstance(part.end.offset, int)

    def test_lit_imported_in_module(self) -> None:
        """Verify that Lit is imported in the lovely_bash_permissions module."""
        assert Lit is not None


class TestSglQuotedNodes:
    """Tests for the SglQuoted node type."""

    def test_simple_single_quoted(self) -> None:
        """Parse echo 'hello world' and verify it produces a SglQuoted node."""
        tree = parse_ast("echo 'hello world'")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, CallExpr)
        assert len(cmd.args) == 2
        # The second argument is a SglQuoted part
        cmd_arg = cmd.args[1]
        assert isinstance(cmd_arg, Word)
        part = cmd_arg.parts[0]
        assert part.type == "SglQuoted"
        assert isinstance(part, SglQuoted)
        assert part.value == "hello world"

    def test_single_quoted_with_variable_no_expansion(self) -> None:
        """Parse echo '$HOME' and verify variable is not expanded (single quotes)."""
        tree = parse_ast("echo '$HOME'")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, CallExpr)
        cmd_arg = cmd.args[1]
        assert isinstance(cmd_arg, Word)
        part = cmd_arg.parts[0]
        assert part.type == "SglQuoted"
        assert isinstance(part, SglQuoted)
        assert part.value == "$HOME"

    def test_multiple_single_quoted_arguments(self) -> None:
        """Parse echo 'a' 'b' and verify both arguments are SglQuoted."""
        tree = parse_ast("echo 'a' 'b'")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, CallExpr)
        assert len(cmd.args) == 3
        arg1 = cmd.args[1]
        assert isinstance(arg1, Word)
        part1 = arg1.parts[0]
        assert part1.type == "SglQuoted"
        assert isinstance(part1, SglQuoted)
        assert part1.value == "a"
        arg2 = cmd.args[2]
        assert isinstance(arg2, Word)
        part2 = arg2.parts[0]
        assert part2.type == "SglQuoted"
        assert isinstance(part2, SglQuoted)
        assert isinstance(part2, SglQuoted)
        assert isinstance(part2, SglQuoted)
        assert isinstance(part2, SglQuoted)
        assert isinstance(part2, SglQuoted)
        assert part2.value == "b"

    def test_single_quoted_with_asterisk(self) -> None:
        """Parse echo 'foo*' and verify asterisk is literal in single quotes."""
        tree = parse_ast("echo 'foo*'")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, CallExpr)
        arg1 = cmd.args[1]
        assert isinstance(arg1, Word)
        part1 = arg1.parts[0]
        assert part1.type == "SglQuoted"
        assert isinstance(part1, SglQuoted)
        assert isinstance(part1, SglQuoted)
        assert isinstance(part1, SglQuoted)
        assert isinstance(part1, SglQuoted)
        assert isinstance(part1, SglQuoted)
        assert part1.value == "foo*"

    def test_single_quoted_empty(self) -> None:
        """Parse echo '' and verify an empty SglQuoted is handled."""
        tree = parse_ast("echo ''")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, CallExpr)
        arg1 = cmd.args[1]
        assert isinstance(arg1, Word)
        part1 = arg1.parts[0]
        assert part1.type == "SglQuoted"
        assert isinstance(part1, SglQuoted)
        assert isinstance(part1, SglQuoted)
        assert isinstance(part1, SglQuoted)
        assert isinstance(part1, SglQuoted)
        assert isinstance(part1, SglQuoted)
        assert part1.value == ""

    def test_single_quoted_backslashes_are_literal(self) -> None:
        """Single quotes preserve a literal backslash: 'hello\\nworld' stays backslash+n."""
        tree = parse_ast(r"echo 'hello\nworld'")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, CallExpr)
        arg1 = cmd.args[1]
        assert isinstance(arg1, Word)
        part1 = arg1.parts[0]
        assert isinstance(part1, SglQuoted)
        assert part1.value == r"hello\nworld"

    def test_single_quoted_multiline(self) -> None:
        """Single quotes may span a real newline (existing behavior documented)."""
        tree = parse_ast("echo 'hello\nworld'")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, CallExpr)
        arg1 = cmd.args[1]
        assert isinstance(arg1, Word)
        part1 = arg1.parts[0]
        assert isinstance(part1, SglQuoted)
        assert part1.value == "hello\nworld"

    def test_single_quoted_with_dollar_sign(self) -> None:
        """Parse echo 'price $5' and verify the dollar sign is literal."""
        tree = parse_ast("echo 'price $5'")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, CallExpr)
        arg1 = cmd.args[1]
        assert isinstance(arg1, Word)
        part1 = arg1.parts[0]
        assert isinstance(part1, SglQuoted)
        assert part1.value == "price $5"

    def test_single_quoted_position_info(self) -> None:
        """Verify that SglQuoted nodes have position information from shfmt."""
        tree = parse_ast("echo 'hello'")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, CallExpr)
        arg1 = cmd.args[1]
        assert isinstance(arg1, Word)
        part = arg1.parts[0]
        assert part.type == "SglQuoted"
        assert part.pos is not None
        assert part.end is not None
        assert isinstance(part.pos.offset, int)
        assert isinstance(part.end.offset, int)

    def test_sgquoted_imported_in_module(self) -> None:
        """Verify that SglQuoted is imported in the lovely_bash_permissions module."""
        assert SglQuoted is not None


class TestParamExpNodes:
    """Tests for the ParamExp node type."""

    def test_short_param_expansion(self) -> None:
        """Parse echo $HOME and verify it produces a ParamExp node with Short=True."""
        tree = parse_ast("echo $HOME")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, CallExpr)
        assert len(cmd.args) == 2
        # The second argument is a ParamExp part
        arg1 = cmd.args[1]
        assert isinstance(arg1, Word)
        part1 = arg1.parts[0]
        assert part1.type == "ParamExp"
        assert isinstance(part1, ParamExp)
        assert part1.param == "HOME"
        assert part1.short is True

    def test_braced_param_expansion(self) -> None:
        """Parse echo ${HOME} and verify it produces a ParamExp
        node with Short=False."""
        tree = parse_ast("echo ${HOME}")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, CallExpr)
        arg1 = cmd.args[1]
        assert isinstance(arg1, Word)
        part1 = arg1.parts[0]
        assert part1.type == "ParamExp"
        assert isinstance(part1, ParamExp)
        assert part1.param == "HOME"
        assert part1.short is False

    def test_param_expansion_with_default(self) -> None:
        """Parse echo ${HOME:-default} and verify the Exp field."""
        tree = parse_ast("echo ${HOME:-default}")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, CallExpr)
        arg1 = cmd.args[1]
        assert isinstance(arg1, Word)
        part1 = arg1.parts[0]
        assert isinstance(part1, ParamExp)
        assert part1.type == "ParamExp"
        assert isinstance(part1, ParamExp)
        assert isinstance(part1, ParamExp)
        assert part1.param == "HOME"
        inner = arg1.parts[0]
        assert isinstance(inner, ParamExp)
        exp = inner.exp
        assert exp is not None
        assert exp.op == ":-"

    def test_array_index_param_expansion(self) -> None:
        """Parse echo ${arr[0]} and verify the Index field."""
        tree = parse_ast("echo ${arr[0]}")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, CallExpr)
        arg1 = cmd.args[1]
        assert isinstance(arg1, Word)
        part1 = arg1.parts[0]
        assert part1.type == "ParamExp"
        assert isinstance(part1, ParamExp)
        assert isinstance(part1, ParamExp)
        assert isinstance(part1, ParamExp)
        assert isinstance(part1, ParamExp)
        assert isinstance(part1, ParamExp)
        assert part1.param == "arr"
        idx = part1.index
        assert isinstance(idx, Word)
        idx_part = idx.parts[0]
        assert idx_part.type == "Lit"
        assert isinstance(idx_part, Lit)
        assert isinstance(idx_part, Lit)
        assert isinstance(idx_part, Lit)
        assert isinstance(idx_part, Lit)
        assert isinstance(idx_part, Lit)
        assert idx_part.value == "0"

    def test_param_expansion_in_double_quotes(self) -> None:
        """Parse echo "$HOME" and verify ParamExp inside DblQuoted."""
        tree = parse_ast('echo "$HOME"')
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, CallExpr)
        arg1 = cmd.args[1]
        assert isinstance(arg1, Word)
        part1 = arg1.parts[0]
        assert isinstance(part1, DblQuoted)
        inner_parts = part1.parts
        ip0 = inner_parts[0]
        assert isinstance(ip0, ParamExp)
        assert ip0.param == "HOME"

    def test_multiple_param_expansions(self) -> None:
        """Parse echo "$HOME is $USER" and verify multiple ParamExp parts."""
        tree = parse_ast('echo "$HOME is $USER"')
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, CallExpr)
        # Inside the DblQuoted, we should have: ParamExp, Lit, ParamExp
        arg1 = cmd.args[1]
        assert isinstance(arg1, Word)
        inner = arg1.parts[0]
        assert isinstance(inner, DblQuoted)
        dq_parts = inner.parts
        assert dq_parts[0].type == "ParamExp"
        assert isinstance(dq_parts[0], ParamExp)
        assert isinstance(dq_parts[0], ParamExp)
        assert isinstance(dq_parts[0], ParamExp)
        assert isinstance(dq_parts[2], ParamExp)
        assert isinstance(dq_parts[0], ParamExp)
        assert dq_parts[0].param == "HOME"
        lit_part = dq_parts[1]
        assert isinstance(lit_part, Lit)
        assert lit_part.value == " is "
        assert dq_parts[2].type == "ParamExp"
        assert isinstance(dq_parts[0], ParamExp)
        assert isinstance(dq_parts[0], ParamExp)
        assert isinstance(dq_parts[0], ParamExp)
        assert isinstance(dq_parts[0], ParamExp)
        assert isinstance(dq_parts[0], ParamExp)
        assert dq_parts[2].param == "USER"

    def test_adjacent_param_expansions(self) -> None:
        """Parse echo "$HOME$USER" and verify two adjacent ParamExp parts."""
        tree = parse_ast('echo "$HOME$USER"')
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, CallExpr)
        inner = cmd.args[1].parts[0]
        assert isinstance(inner, DblQuoted)
        dq_parts = inner.parts
        assert len(dq_parts) == 2
        pq0 = dq_parts[0]
        assert isinstance(pq0, ParamExp)
        assert isinstance(dq_parts[0], ParamExp)
        assert dq_parts[0].param == "HOME"
        assert dq_parts[1].type == "ParamExp"
        assert isinstance(dq_parts[0], ParamExp)
        pq1 = dq_parts[1]
        assert isinstance(pq1, ParamExp)
        assert pq1.param == "USER"

    def test_length_param_expansion(self) -> None:
        """Parse echo ${#HOME} and verify Length field."""
        tree = parse_ast("echo ${#HOME}")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, CallExpr)
        arg1 = cmd.args[1]
        assert isinstance(arg1, Word)
        part1 = arg1.parts[0]
        assert part1.type == "ParamExp"
        assert isinstance(part1, ParamExp)
        assert part1.param == "HOME"
        assert part1.length is True

    def test_special_param_expansion(self) -> None:
        """Parse echo "$@" and verify ParamExp with special parameter."""
        tree = parse_ast('echo "$@"')
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, CallExpr)
        inner = cmd.args[1].parts[0]
        assert isinstance(inner, DblQuoted)
        dq_parts = inner.parts
        pq0 = dq_parts[0]
        assert isinstance(pq0, ParamExp)
        assert pq0.param == "@"

    def test_position_param_expansion(self) -> None:
        """Parse echo "$0" and verify ParamExp with positional parameter."""
        tree = parse_ast('echo "$0"')
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, CallExpr)
        inner = cmd.args[1].parts[0]
        assert isinstance(inner, DblQuoted)
        dq_parts = inner.parts
        pq0 = dq_parts[0]
        assert isinstance(pq0, ParamExp)
        assert pq0.param == "0"

    def test_param_expansion_position_info(self) -> None:
        """Verify that ParamExp nodes have position information from shfmt."""
        tree = parse_ast("echo $HOME")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, CallExpr)
        arg1 = cmd.args[1]
        assert isinstance(arg1, Word)
        part = arg1.parts[0]
        assert part.type == "ParamExp"
        assert part.pos is not None
        assert part.end is not None
        assert isinstance(part.pos.offset, int)
        assert isinstance(part.end.offset, int)

    def test_param_exp_imported_in_module(self) -> None:
        """Verify that ParamExp is imported in the lovely_bash_permissions module."""
        assert ParamExp is not None

    def test_repl_expansion_typed(self) -> None:
        """Parse ${x//a/b} and verify Repl fields are kept as typed Word nodes."""
        tree = parse_ast("echo ${x//a/b}")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, CallExpr)
        part = cmd.args[1].parts[0]
        assert isinstance(part, ParamExp)
        assert part.all is True
        assert isinstance(part.orig, Word)
        assert isinstance(part.orig.parts[0], Lit)
        assert part.orig.parts[0].value == "a"
        assert isinstance(part.replacement, Word)
        assert isinstance(part.replacement.parts[0], Lit)
        assert part.replacement.parts[0].value == "b"

    def test_single_repl_expansion_all_false(self) -> None:
        """Parse ${x/a/b} and verify Repl.All is False."""
        tree = parse_ast("echo ${x/a/b}")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, CallExpr)
        part = cmd.args[1].parts[0]
        assert isinstance(part, ParamExp)
        assert part.all is False
        assert part.orig is not None
        assert part.replacement is not None

    def test_repl_expansion_with_cmdsubst_preserved(self) -> None:
        """Parse ${x//a/$(h)} and verify the internal CmdSubst is retained."""
        tree = parse_ast("echo ${x//a/$(h)}")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, CallExpr)
        part = cmd.args[1].parts[0]
        assert isinstance(part, ParamExp)
        assert isinstance(part.replacement, Word)
        assert isinstance(part.replacement.parts[0], CmdSubst)

    def test_param_exp_exp_typed(self) -> None:
        """Parse ${x:-word} and verify exp is a typed ParamExpExp node."""
        tree = parse_ast("echo ${x:-foo}")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, CallExpr)
        part = cmd.args[1].parts[0]
        assert isinstance(part, ParamExp)
        assert isinstance(part.exp, ParamExpExp)
        assert part.exp.op == ":-"
        assert isinstance(part.exp.word, Word)
        assert isinstance(part.exp.word.parts[0], Lit)
        assert part.exp.word.parts[0].value == "foo"

    def test_param_exp_slice_typed(self) -> None:
        """Parse ${x:0:3} and verify slice is a typed ParamExpSlice node."""
        tree = parse_ast("echo ${x:0:3}")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, CallExpr)
        part = cmd.args[1].parts[0]
        assert isinstance(part, ParamExp)
        assert isinstance(part.slice, ParamExpSlice)
        assert isinstance(part.slice.offset, Word)
        assert isinstance(part.slice.length, Word)
        assert isinstance(part.slice.offset.parts[0], Lit)
        assert isinstance(part.slice.length.parts[0], Lit)
        assert part.slice.offset.parts[0].value == "0"
        assert part.slice.length.parts[0].value == "3"

    def test_param_exp_slice_no_length(self) -> None:
        """Parse ${x:0} and verify slice length is None."""
        tree = parse_ast("echo ${x:0}")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, CallExpr)
        part = cmd.args[1].parts[0]
        assert isinstance(part, ParamExp)
        assert isinstance(part.slice, ParamExpSlice)
        assert part.slice.offset is not None
        assert part.slice.length is None


class TestDblQuotedNodes:
    """Tests for the DblQuoted node type."""

    def test_simple_double_quoted(self) -> None:
        """Parse echo "hello" and verify it produces a DblQuoted node with Lit parts."""
        tree = parse_ast('echo "hello"')
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, CallExpr)
        assert len(cmd.args) == 2
        arg1 = cmd.args[1]
        assert isinstance(arg1, Word)
        part1 = arg1.parts[0]
        assert part1.type == "DblQuoted"
        assert isinstance(part1, DblQuoted)
        assert isinstance(part1, DblQuoted)
        assert isinstance(part1, DblQuoted)
        assert isinstance(part1, DblQuoted)
        assert len(part1.parts) == 1
        ip1 = part1.parts[0]
        assert isinstance(ip1, Lit)
        assert ip1.type == "Lit"
        assert ip1.value == "hello"

    def test_double_quoted_with_variable_expansion(self) -> None:
        """Parse echo "hello $world" and verify DblQuoted with Lit + ParamExp parts."""
        tree = parse_ast('echo "hello $world"')
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, CallExpr)
        arg1 = cmd.args[1]
        assert isinstance(arg1, Word)
        inner = arg1.parts[0]
        assert isinstance(inner, DblQuoted)
        dq_parts = inner.parts
        assert len(dq_parts) == 2
        lit0 = dq_parts[0]
        assert isinstance(lit0, Lit)
        assert lit0.value == "hello "
        param1 = dq_parts[1]
        assert isinstance(param1, ParamExp)

    def test_double_quoted_multiple_variables(self) -> None:
        """Parse echo "$USER is here" and verify DblQuoted
        with multiple ParamExp parts."""
        tree = parse_ast('echo "$USER is here"')
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, CallExpr)
        inner2 = cmd.args[1].parts[0]
        assert isinstance(inner2, DblQuoted)
        dq_parts = inner2.parts
        p0 = dq_parts[0]
        assert isinstance(p0, ParamExp)
        assert p0.type == "ParamExp"
        assert p0.param == "USER"
        assert dq_parts[1].type == "Lit"
        assert isinstance(dq_parts[1], Lit)
        assert dq_parts[1].value == " is here"

    def test_empty_double_quoted(self) -> None:
        """Parse echo "" and verify an empty DblQuoted is handled."""
        tree = parse_ast('echo ""')
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, CallExpr)
        arg1 = cmd.args[1]
        assert isinstance(arg1, Word)
        part1 = arg1.parts[0]
        assert part1.type == "DblQuoted"
        assert isinstance(part1, DblQuoted)
        # Empty DblQuoted has an empty parts list
        assert part1.parts == []

    def test_empty_double_quoted_shfmt_go(self) -> None:
        """Test shfmt Go-style empty DblQuoted handling (for completeness)."""
        # In shfmt Go, empty double quotes would give a DblQuoted
        # with an empty parts array
        # Our parser should handle both: None parts (shfmt-py) and [] parts (shfmt Go)
        from lovely_bash_permissions.ast import DblQuoted

        dq_go = DblQuoted(type="DblQuoted", pos=None, end=None, parts=[])
        assert dq_go.parts == []

    def test_double_quoted_preserves_spaces(self) -> None:
        """Parse echo "a b c" and verify spaces are preserved in Lit parts."""
        tree = parse_ast('echo "a b c"')
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, CallExpr)
        arg1 = cmd.args[1]
        assert isinstance(arg1, Word)
        part1 = arg1.parts[0]
        assert part1.type == "DblQuoted"
        assert isinstance(part1, DblQuoted)
        assert isinstance(part1, DblQuoted)
        assert isinstance(part1, DblQuoted)
        assert isinstance(part1, DblQuoted)
        assert len(part1.parts) == 1
        ip1 = part1.parts[0]
        assert isinstance(ip1, Lit)
        assert ip1.value == "a b c"

    def test_nested_quotes(self) -> None:
        """Parse echo "$HOME is $USER" and verify multiple nested parts."""
        tree = parse_ast('echo "$HOME is $USER"')
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, CallExpr)
        arg1 = cmd.args[1]
        assert isinstance(arg1, Word)
        inner = arg1.parts[0]
        assert isinstance(inner, DblQuoted)
        dq_parts = inner.parts
        assert len(dq_parts) == 3
        p0 = dq_parts[0]
        assert isinstance(p0, ParamExp)
        assert p0.type == "ParamExp"
        assert p0.param == "HOME"
        lit1 = dq_parts[1]
        assert isinstance(lit1, Lit)
        assert lit1.value == " is "
        p2 = dq_parts[2]
        assert isinstance(p2, ParamExp)
        assert p2.type == "ParamExp"

    def test_escape_sequences_in_double_quotes(self) -> None:
        """Parse echo with escaped characters in double quotes."""
        tree = parse_ast('echo "\\n\\t\\r"')
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, CallExpr)
        arg1 = cmd.args[1]
        assert isinstance(arg1, Word)
        part1 = arg1.parts[0]
        assert part1.type == "DblQuoted"
        assert isinstance(part1, DblQuoted)
        assert isinstance(part1, DblQuoted)
        assert isinstance(part1, DblQuoted)
        # In shfmt-py, escaped sequences in double quotes become
        # Lit parts with the literal escape sequences
        ip1 = part1.parts[0]
        assert isinstance(ip1, Lit)
        assert ip1.value == "\\n\\t\\r"

    def test_mixed_literal_variable_escape(self) -> None:
        """Parse complex DblQuoted with lit, variable, and escapes mixed."""
        tree = parse_ast('echo "\\n$USER\\n"')
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, CallExpr)
        inner2 = cmd.args[1].parts[0]
        assert isinstance(inner2, DblQuoted)
        dq_parts = inner2.parts
        assert len(dq_parts) == 3
        l0 = dq_parts[0]
        assert isinstance(l0, Lit)
        assert l0.type == "Lit"
        assert l0.value == "\\n"
        p1 = dq_parts[1]
        assert isinstance(p1, ParamExp)
        assert p1.type == "ParamExp"
        assert p1.param == "USER"
        assert dq_parts[2].type == "Lit"
        assert isinstance(dq_parts[2], Lit)
        assert dq_parts[2].value == "\\n"

    def test_dblquoted_position_info(self) -> None:
        """Verify that DblQuoted nodes have position information from shfmt."""
        tree = parse_ast('echo "hello"')
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, CallExpr)
        arg1 = cmd.args[1]
        assert isinstance(arg1, Word)
        part = arg1.parts[0]
        assert isinstance(part, DblQuoted)
        assert part.pos is not None
        assert part.end is not None
        assert isinstance(part.pos.offset, int)
        assert isinstance(part.end.offset, int)

    def test_dblquoted_imported_in_module(self) -> None:
        """Verify that DblQuoted is imported in the lovely_bash_permissions module."""
        assert DblQuoted is not None


class TestCmdSubstNodes:
    """Tests for the CmdSubst node type."""

    def test_simple_cmdsubst_syntax(self) -> None:
        """Parse echo $(date) and verify it produces a CmdSubst node."""
        tree = parse_ast("echo $(date)")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, CallExpr)
        assert len(cmd.args) == 2
        arg1 = cmd.args[1]
        assert isinstance(arg1, Word)
        cs_part = arg1.parts[0]
        assert isinstance(cs_part, CmdSubst)
        assert cs_part.type == "CmdSubst"
        assert len(cs_part.stmts) == 1
        inner_cmd = cs_part.stmts[0].cmd
        assert isinstance(inner_cmd, CallExpr)
        inner_arg = inner_cmd.args[0]
        assert isinstance(inner_arg, Word)
        part = inner_arg.parts[0]
        assert isinstance(part, Lit)
        assert part.value == "date"

    def test_cmdsubst_with_backquotes(self) -> None:
        """Parse echo `date` and verify backquotes is True."""
        tree = parse_ast("echo `date`")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, CallExpr)
        arg1 = cmd.args[1]
        assert isinstance(arg1, Word)
        cs_part = arg1.parts[0]
        assert isinstance(cs_part, CmdSubst)
        assert cs_part.backquotes is True
        inner_cmd = cs_part.stmts[0].cmd
        assert isinstance(inner_cmd, CallExpr)
        inner_arg = inner_cmd.args[0]
        assert isinstance(inner_arg, Word)
        part = inner_arg.parts[0]
        assert isinstance(part, Lit)
        assert part.value == "date"

    def test_cmdsubst_in_double_quotes(self) -> None:
        """Parse echo \"hello $(date)\" and verify CmdSubst inside DblQuoted."""
        tree = parse_ast('echo "hello $(date)"')
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, CallExpr)
        arg1 = cmd.args[1]
        assert isinstance(arg1, Word)
        inner = arg1.parts[0]
        assert isinstance(inner, DblQuoted)
        dq_parts = inner.parts
        assert len(dq_parts) == 2
        lit0 = dq_parts[0]
        assert isinstance(lit0, Lit)
        assert lit0.value == "hello "
        cs_part = dq_parts[1]
        assert isinstance(cs_part, CmdSubst)
        inner_cmd = cs_part.stmts[0].cmd
        assert isinstance(inner_cmd, CallExpr)
        inner_arg = inner_cmd.args[0]
        assert isinstance(inner_arg, Word)
        part = inner_arg.parts[0]
        assert isinstance(part, Lit)
        assert part.value == "date"

    def test_two_cmdsubst_parts(self) -> None:
        """Parse echo $(date) && $(date) and verify two CmdSubst parts."""
        tree = parse_ast("echo $(date) $(date)")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, CallExpr)
        assert len(cmd.args) == 3
        arg1 = cmd.args[1]
        assert isinstance(arg1, Word)
        cs1 = arg1.parts[0]
        assert isinstance(cs1, CmdSubst)
        arg2 = cmd.args[2]
        assert isinstance(arg2, Word)
        cs2 = arg2.parts[0]
        assert isinstance(cs2, CmdSubst)
        # Both have the same inner command
        inner1 = cs1.stmts[0].cmd
        assert isinstance(inner1, CallExpr)
        a1 = inner1.args[0]
        assert isinstance(a1, Word)
        p1 = a1.parts[0]
        assert isinstance(p1, Lit)
        assert p1.value == "date"
        inner2 = cs2.stmts[0].cmd
        assert isinstance(inner2, CallExpr)
        a2 = inner2.args[0]
        assert isinstance(a2, Word)
        p2 = a2.parts[0]
        assert isinstance(p2, Lit)
        assert p2.value == "date"

    def test_nested_cmdsubst(self) -> None:
        """Parse echo $(echo $(date)) and verify nested CmdSubst."""
        tree = parse_ast("echo $(echo $(date))")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, CallExpr)
        arg1 = cmd.args[1]
        assert isinstance(arg1, Word)
        cs1 = arg1.parts[0]
        assert isinstance(cs1, CmdSubst)
        outer_stmt = cs1.stmts[0]
        assert isinstance(outer_stmt.cmd, CallExpr)
        outer_arg = outer_stmt.cmd.args[0]
        assert isinstance(outer_arg, Word)
        p1 = outer_arg.parts[0]
        assert isinstance(p1, Lit)
        assert p1.value == "echo"
        inner_cs = outer_stmt.cmd.args[1].parts[0]
        assert isinstance(inner_cs, CmdSubst)
        inner_cmd = inner_cs.stmts[0].cmd
        assert isinstance(inner_cmd, CallExpr)
        inner_arg = inner_cmd.args[0]
        assert isinstance(inner_arg, Word)
        p2 = inner_arg.parts[0]
        assert isinstance(p2, Lit)
        assert p2.value == "date"

    def test_cmdsubst_with_multiple_commands(self) -> None:
        """Parse echo $(ls | grep txt) and verify multiple inner statements."""
        tree = parse_ast("echo $(ls | grep txt)")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, CallExpr)
        arg1 = cmd.args[1]
        assert isinstance(arg1, Word)
        cs = arg1.parts[0]
        assert isinstance(cs, CmdSubst)
        assert len(cs.stmts) == 1
        inner = cs.stmts[0].cmd
        assert isinstance(inner, BinaryCmd)
        left = inner.left
        assert isinstance(left, CallExpr)
        la0 = left.args[0]
        assert isinstance(la0, Word)
        lp0 = la0.parts[0]
        assert isinstance(lp0, Lit)
        assert lp0.value == "ls"
        right = inner.right
        assert isinstance(right, CallExpr)
        ra0 = right.args[0]
        assert isinstance(ra0, Word)
        rp0 = ra0.parts[0]
        assert isinstance(rp0, Lit)
        assert rp0.value == "grep"
        ra1 = right.args[1]
        assert isinstance(ra1, Word)
        rp1 = ra1.parts[0]
        assert isinstance(rp1, Lit)
        assert rp1.value == "txt"

    def test_cmdsubst_position_info(self) -> None:
        """Verify that CmdSubst nodes have position information."""
        tree = parse_ast("echo $(date)")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, CallExpr)
        arg1 = cmd.args[1]
        assert isinstance(arg1, Word)
        part = arg1.parts[0]
        assert isinstance(part, CmdSubst)
        assert part.pos is not None
        assert part.end is not None
        assert isinstance(part.pos.offset, int)
        assert isinstance(part.end.offset, int)

    def test_cmdsubst_backquotes_false(self) -> None:
        """Verify that $(...) has backquotes=False."""
        tree = parse_ast("echo $(date)")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, CallExpr)
        arg1 = cmd.args[1]
        assert isinstance(arg1, Word)
        cs_part = arg1.parts[0]
        assert isinstance(cs_part, CmdSubst)
        assert cs_part.backquotes is False

    def test_cmdsubst_imported_in_module(self) -> None:
        """Verify that CmdSubst is imported in the lovely_bash_permissions module."""
        from lovely_bash_permissions import CmdSubst

        assert CmdSubst is not None


class TestArithmExpNodes:
    """Tests for the ArithmExp node type."""

    def test_simple_arithmetic_expression(self) -> None:
        """Parse echo $((2 + 2)) and verify ArithmExp with BinaryArithm."""
        tree = parse_ast("echo $((2 + 2))")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, CallExpr)
        assert len(cmd.args) == 2
        arg1 = cmd.args[1]
        assert isinstance(arg1, Word)
        ae_part = arg1.parts[0]
        assert isinstance(ae_part, ArithmExp)
        inner = ae_part.x
        assert isinstance(inner, BinaryArithm)
        assert inner.op == "+"
        left = inner.left
        assert isinstance(left, Word)
        lit_left = left.parts[0]
        assert isinstance(lit_left, Lit)
        assert lit_left.value == "2"
        right = inner.right
        assert isinstance(right, Word)
        lit_right = right.parts[0]
        assert isinstance(lit_right, Lit)
        assert lit_right.value == "2"

    def test_arithmetic_with_variables(self) -> None:
        """Parse echo $((x + y)) and verify ArithmExp with variables."""
        tree = parse_ast("echo $((x + y))")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, CallExpr)
        arg1 = cmd.args[1]
        assert isinstance(arg1, Word)
        ae_part = arg1.parts[0]
        assert isinstance(ae_part, ArithmExp)
        inner = ae_part.x
        assert isinstance(inner, BinaryArithm)
        assert inner.op == "+"
        left = inner.left
        assert isinstance(left, Word)
        lit_left = left.parts[0]
        assert isinstance(lit_left, Lit)
        assert lit_left.value == "x"
        right = inner.right
        assert isinstance(right, Word)
        lit_right = right.parts[0]
        assert isinstance(lit_right, Lit)
        assert lit_right.value == "y"

    def test_single_value_arithmetic(self) -> None:
        """Parse echo $((50)) and verify ArithmExp with just a value."""
        tree = parse_ast("echo $((50))")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, CallExpr)
        arg1 = cmd.args[1]
        assert isinstance(arg1, Word)
        ae_part = arg1.parts[0]
        assert isinstance(ae_part, ArithmExp)
        inner = ae_part.x
        assert isinstance(inner, Word)
        w_parts = inner.parts
        lit_part = w_parts[0]
        assert isinstance(lit_part, Lit)
        assert lit_part.value == "50"

    def test_arithmetic_in_double_quotes(self) -> None:
        """Parse echo \"$((5))\" and verify ArithmExp inside DblQuoted."""
        tree = parse_ast('echo "$((5))"')
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, CallExpr)
        arg1 = cmd.args[1]
        assert isinstance(arg1, Word)
        dq_part = arg1.parts[0]
        assert isinstance(dq_part, DblQuoted)
        ae_inner = dq_part.parts[0]
        assert isinstance(ae_inner, ArithmExp)
        inner = ae_inner.x
        assert isinstance(inner, Word)
        w_parts = inner.parts
        lit_part = w_parts[0]
        assert isinstance(lit_part, Lit)
        assert lit_part.value == "5"

    def test_complex_arithmetic_expression(self) -> None:
        """Parse echo $((2 * 3 + 4)) and verify nested BinaryArithm."""
        tree = parse_ast("echo $((2 * 3 + 4))")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, CallExpr)
        arg1 = cmd.args[1]
        assert isinstance(arg1, Word)
        ae_part = arg1.parts[0]
        assert isinstance(ae_part, ArithmExp)
        inner = ae_part.x
        assert isinstance(inner, BinaryArithm)
        assert inner.op == "+"
        # Left side should be multiplication
        left = inner.left
        assert isinstance(left, BinaryArithm)
        lit_left = left.left
        assert isinstance(lit_left, Word)
        ll_part = lit_left.parts[0]
        assert isinstance(ll_part, Lit)
        assert ll_part.value == "2"
        lit_mid = left.right
        assert isinstance(lit_mid, Word)
        lm_part = lit_mid.parts[0]
        assert isinstance(lm_part, Lit)
        assert lm_part.value == "3"
        # Right side should be the number 4
        right = inner.right
        assert isinstance(right, Word)
        lit_right = right.parts[0]
        assert isinstance(lit_right, Lit)
        assert lit_right.value == "4"

    def test_arithmetic_position_info(self) -> None:
        """Verify that ArithmExp nodes have position information."""
        tree = parse_ast("echo $((2 + 2))")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, CallExpr)
        arg1 = cmd.args[1]
        assert isinstance(arg1, Word)
        part = arg1.parts[0]
        assert isinstance(part, ArithmExp)
        assert part.pos is not None
        assert part.end is not None
        assert isinstance(part.pos.offset, int)
        assert isinstance(part.end.offset, int)

    def test_binaryarithm_position_info(self) -> None:
        """Verify that BinaryArithm nodes have position information."""
        tree = parse_ast("echo $((2 + 2))")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, CallExpr)
        arg1 = cmd.args[1]
        assert isinstance(arg1, Word)
        ae_part = arg1.parts[0]
        assert isinstance(ae_part, ArithmExp)
        inner = ae_part.x
        assert isinstance(inner, BinaryArithm)
        assert inner.pos is not None
        assert inner.end is not None
        assert inner.op_pos is not None
        assert isinstance(inner.pos.offset, int)

    def test_arithmexp_imported_in_module(self) -> None:
        """Verify that ArithmExp is imported in the lovely_bash_permissions module."""
        from lovely_bash_permissions import ArithmExp

        assert ArithmExp is not None

    def test_binaryarithm_imported_in_module(self) -> None:
        """Verify that BinaryArithm is imported in the module."""
        assert BinaryArithm is not None


class TestProcSubstNodes:
    """Tests for the ProcSubst node type."""

    def test_input_process_substitution(self) -> None:
        """Parse cat <(echo 'hi') and verify ProcSubst with op='<('."""
        tree = parse_ast("cat <(echo 'hi')")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, CallExpr)
        assert len(cmd.args) == 2
        arg1 = cmd.args[1]
        assert isinstance(arg1, Word)
        ps_part = arg1.parts[0]
        assert isinstance(ps_part, ProcSubst)
        assert ps_part.op == "<("
        assert len(ps_part.stmts) == 1
        inner = ps_part.stmts[0].cmd
        assert isinstance(inner, CallExpr)
        inner_arg0 = inner.args[0]
        assert isinstance(inner_arg0, Word)
        p0 = inner_arg0.parts[0]
        assert isinstance(p0, Lit)
        assert p0.value == "echo"
        inner_arg1 = inner.args[1]
        assert isinstance(inner_arg1, Word)
        p1 = inner_arg1.parts[0]
        assert isinstance(p1, SglQuoted)
        assert p1.value == "hi"

    def test_output_process_substitution(self) -> None:
        """Parse sort > >(cat) and verify ProcSubst with op='>('."""
        tree = parse_ast("sort > >(cat)")
        # The redirection target should be a ProcSubst
        word = tree.stmts[0].redirs[0].word
        assert isinstance(word, Word)
        ps_part = word.parts[0]
        assert isinstance(ps_part, ProcSubst)
        assert ps_part.op == ">("
        inner = ps_part.stmts[0].cmd
        assert isinstance(inner, CallExpr)
        inner_arg = inner.args[0]
        assert isinstance(inner_arg, Word)
        p0 = inner_arg.parts[0]
        assert isinstance(p0, Lit)
        assert p0.value == "cat"

    def test_double_process_substitution(self) -> None:
        """Parse diff <(echo 'hi') <(echo 'there') with two ProcSubst nodes."""
        tree = parse_ast("diff <(echo 'hi') <(echo 'there')")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, CallExpr)
        assert len(cmd.args) == 3
        arg1 = cmd.args[1]
        assert isinstance(arg1, Word)
        ps1a = arg1.parts[0]
        assert isinstance(ps1a, ProcSubst)
        ps1b = arg1.parts[0]
        assert isinstance(ps1b, ProcSubst)
        assert ps1b.op == "<("
        arg2 = cmd.args[2]
        assert isinstance(arg2, Word)
        ps2a = arg2.parts[0]
        assert isinstance(ps2a, ProcSubst)
        ps2b = arg2.parts[0]
        assert isinstance(ps2b, ProcSubst)
        assert ps2b.op == "<("
        # Verify inner commands
        inn1 = ps1a.stmts[0].cmd
        assert isinstance(inn1, CallExpr)
        a1 = inn1.args[0]
        assert isinstance(a1, Word)
        p1 = a1.parts[0]
        assert isinstance(p1, Lit)
        assert p1.value == "echo"
        inn2 = ps2a.stmts[0].cmd
        assert isinstance(inn2, CallExpr)
        a2 = inn2.args[0]
        assert isinstance(a2, Word)
        p2 = a2.parts[0]
        assert isinstance(p2, Lit)
        assert p2.value == "echo"

    def test_process_substitution_in_double_quotes(self) -> None:
        """Parse echo \"<(cmd)\" - process substitution
        in double quotes is literal text."""
        # Note: bash does NOT expand <() inside double quotes
        tree = parse_ast('echo "<(echo hi)"')
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, CallExpr)
        arg1 = cmd.args[1]
        assert isinstance(arg1, Word)
        dq_part = arg1.parts[0]
        assert isinstance(dq_part, DblQuoted)
        # Inside double quotes, <() is literal, not a ProcSubst
        inner = dq_part.parts[0]
        assert isinstance(inner, Lit)
        assert inner.value == "<(echo hi)"

    def test_process_substitution_position_info(self) -> None:
        """Verify ProcSubst nodes have position information from shfmt."""
        tree = parse_ast("cat <(echo 'hi')")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, CallExpr)
        arg1 = cmd.args[1]
        assert isinstance(arg1, Word)
        part = arg1.parts[0]
        assert isinstance(part, ProcSubst)
        assert part.type == "ProcSubst"
        assert part.pos is not None
        assert part.end is not None
        assert part.op_pos is not None
        assert part.rparen is not None
        assert isinstance(part.pos.offset, int)
        assert isinstance(part.end.offset, int)

    def test_procsubst_imported_in_module(self) -> None:
        """Verify that ProcSubst is imported in the lovely_bash_permissions module."""
        assert ProcSubst is not None


class TestExtGlobNodes:
    """Tests for the ExtGlob node type.

    Extended globs require `shopt -s extglob` in bash. shfmt parses
    them regardless. Syntax: @(pat|pat), +(pat|pat), *(pat|pat),
    ?(pat|pat), !(pat|pat). See https://www.gnu.org/software/bash/manual/bash.html#Pattern-Matching

    NOTE: In real bash these patterns are only valid with
    `shopt -s extglob` enabled. shfmt parses them regardless of the
    shell option, so these tests assert the AST shape without the
    option needing to be set - see test_extglob_invalid_without_shopt
    """

    @pytest.mark.parametrize(
        "cmd,op,pat",
        [
            ("ls *.@(txt|md)", "@(", "txt|md"),
            ("ls *.+(txt|md)", "+(", "txt|md"),
            ("ls *.?(txt|md)", "?(", "txt|md"),
            ("ls *.!(txt|md)", "!(", "txt|md"),
            ("ls *.*(txt|md)", "*(", "txt|md"),
            ("ls *.@(txt|md|json|yaml)", "@(", "txt|md|json|yaml"),
        ],
    )
    def test_extglob_op_pattern(self, cmd: str, op: str, pat: str) -> None:
        """Parse `cmd` and verify the ExtGlob op and pattern."""
        tree = parse_ast(cmd)
        cmd_node = tree.stmts[0].cmd
        assert isinstance(cmd_node, CallExpr)
        arg1 = cmd_node.args[1]
        assert isinstance(arg1, Word)
        eg = arg1.parts[1]
        assert isinstance(eg, ExtGlob)
        assert eg.type == "ExtGlob"
        assert eg.op == op
        assert isinstance(eg.pattern, Lit)
        assert eg.pattern.value == pat

    def test_extglob_invalid_without_shopt(self) -> None:
        """Real bash rejects @(...) unless `shopt -s extglob` is enabled

        Documents the prerequisite stated in the class docstring: shfmt
        parses extglob syntax regardless of the shell option, but plain
        bash refuses it at parse time
        """
        import subprocess

        proc = subprocess.run(
            ["bash", "-c", "echo *.@(txt|md)"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode != 0

    def test_extglob_no_unhandled_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """ExtGlob patterns are handled explicitly and never emit a segment

        Guards the fix for the extraction gap: `_extract_segments` has a
        branch for ExtGlob nodes now (extended glob patterns are literal and
        contain no substitutions), so no 'Unhandled AST node type' warning is
        logged and no phantom command segment is produced
        """
        segs = parse_segments("ls *.@(txt|md)")
        assert [s["command"] for s in segs] == ["ls"]
        assert not any("Unhandled AST node type" in message for _logger, _level, message in caplog.record_tuples)

    def test_extglob_position_info(self) -> None:
        """Verify ExtGlob nodes have position information from shfmt."""
        tree = parse_ast("ls *.@(txt|md)")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, CallExpr)
        arg1 = cmd.args[1]
        assert isinstance(arg1, Word)
        eg_part = arg1.parts[1]
        assert isinstance(eg_part, ExtGlob)
        extglob = eg_part
        assert extglob.type == "ExtGlob"
        assert extglob.pos is not None
        assert extglob.end is not None
        assert extglob.op_pos is not None
        assert isinstance(extglob.pos.offset, int)
        assert isinstance(extglob.end.offset, int)

    def test_extglob_in_double_quotes(self) -> None:
        """Parse echo \"@(cmd)\" - extglob in double quotes is literal text."""
        # Note: bash does NOT expand @() inside double quotes without extglob
        tree = parse_ast('echo "@(txt|md)"')
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, CallExpr)
        arg1 = cmd.args[1]
        assert isinstance(arg1, Word)
        dq_part = arg1.parts[0]
        assert isinstance(dq_part, DblQuoted)
        inner = dq_part.parts[0]
        assert isinstance(inner, Lit)
        iv = inner
        assert iv.value == "@(txt|md)"

    def test_extglob_combined_with_procsubst(self) -> None:
        """Parse complex expression combining ExtGlob with other features."""
        tree = parse_ast("ls *.@(txt|md) | grep -i foo")
        bc = tree.stmts[0].cmd
        assert isinstance(bc, BinaryCmd)
        assert bc.op == "|"
        # Left side should have ExtGlob
        left_cmd = bc.left
        assert isinstance(left_cmd, CallExpr)
        arg1 = left_cmd.args[1]
        assert isinstance(arg1, Word)
        eg_part2 = arg1.parts[1]
        assert isinstance(eg_part2, ExtGlob)
        pat_eg = eg_part2.pattern
        assert isinstance(pat_eg, Lit)
        assert pat_eg.value == "txt|md"

    def test_extglob_imported_in_module(self) -> None:
        """Verify that ExtGlob is imported in the lovely_bash_permissions module."""
        from lovely_bash_permissions import ExtGlob

        assert isinstance(ExtGlob, type)


class TestBlockNodes:
    """Tests for the Block node type.

    Blocks are curly-brace groups: { cmd1; cmd2; }. They execute
    commands in the current shell environment (unlike subshells with
    parentheses which spawn a new shell)
    """

    def test_simple_block(self) -> None:
        """Parse { echo 'a'; echo 'b'; } and verify Block node."""
        tree = parse_ast("{ echo 'a'; echo 'b'; }")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, Block)
        assert len(cmd.stmts) == 2
        # First statement: echo 'a'
        stmt1_cmd = cmd.stmts[0].cmd
        assert isinstance(stmt1_cmd, CallExpr)
        s1a = stmt1_cmd.args[0]
        assert isinstance(s1a, Word)
        p1 = s1a.parts[0]
        assert isinstance(p1, Lit)
        v1 = p1
        assert v1.value == "echo"
        s1b = stmt1_cmd.args[1]
        assert isinstance(s1b, Word)
        q1 = s1b.parts[0]
        assert isinstance(q1, SglQuoted)
        q1v = q1
        assert q1v.value == "a"
        # Second statement: echo 'b'
        stmt2_cmd = cmd.stmts[1].cmd
        assert isinstance(stmt2_cmd, CallExpr)
        s2a = stmt2_cmd.args[0]
        assert isinstance(s2a, Word)
        p2 = s2a.parts[0]
        assert isinstance(p2, Lit)
        v2 = p2
        assert v2.value == "echo"
        s2b = stmt2_cmd.args[1]
        assert isinstance(s2b, Word)
        q2 = s2b.parts[0]
        assert isinstance(q2, SglQuoted)
        q2v = q2
        assert q2v.value == "b"

    def test_block_with_true_false(self) -> None:
        """Parse { true; false; } and verify Block with boolean commands."""
        tree = parse_ast("{ true; false; }")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, Block)
        assert len(cmd.stmts) == 2
        stmt1_cmd = cmd.stmts[0].cmd
        assert isinstance(stmt1_cmd, CallExpr)
        s1a = stmt1_cmd.args[0]
        assert isinstance(s1a, Word)
        p1 = s1a.parts[0]
        assert isinstance(p1, Lit)
        assert p1.value == "true"
        stmt2_cmd = cmd.stmts[1].cmd
        assert isinstance(stmt2_cmd, CallExpr)
        s2a = stmt2_cmd.args[0]
        assert isinstance(s2a, Word)
        p2 = s2a.parts[0]
        assert isinstance(p2, Lit)
        assert p2.value == "false"

    def test_nested_blocks(self) -> None:
        """Parse { { echo 'inner'; }; } and verify nested Block nodes."""
        tree = parse_ast("{ { echo 'inner'; }; }")
        outer = tree.stmts[0].cmd
        assert isinstance(outer, Block)
        assert len(outer.stmts) == 1
        inner_block = outer.stmts[0].cmd
        assert isinstance(inner_block, Block)
        assert len(inner_block.stmts) == 1
        inner_cmd = inner_block.stmts[0].cmd
        assert isinstance(inner_cmd, CallExpr)
        i1a = inner_cmd.args[0]
        assert isinstance(i1a, Word)
        p1 = i1a.parts[0]
        assert isinstance(p1, Lit)
        assert p1.value == "echo"
        i1b = inner_cmd.args[1]
        assert isinstance(i1b, Word)
        q1 = i1b.parts[0]
        assert isinstance(q1, SglQuoted)
        assert q1.value == "inner"

    def test_block_with_subshell(self) -> None:
        """Parse { (echo 'sub'); } and verify Block containing Subshell."""
        tree = parse_ast("{ (echo 'sub'); }")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, Block)
        inner_cmd = cmd.stmts[0].cmd
        assert isinstance(inner_cmd, Subshell)
        inner_st = inner_cmd.stmts[0].cmd
        assert isinstance(inner_st, CallExpr)
        i1a = inner_st.args[0]
        assert isinstance(i1a, Word)
        p1 = i1a.parts[0]
        assert isinstance(p1, Lit)
        assert p1.value == "echo"

    def test_block_with_variables(self) -> None:
        """Parse { echo $HOME; } and verify Block with variable expansion."""
        tree = parse_ast("{ echo $HOME; }")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, Block)
        stmt1_cmd = cmd.stmts[0].cmd
        assert isinstance(stmt1_cmd, CallExpr)
        arg1 = stmt1_cmd.args[1]
        assert isinstance(arg1, Word)
        pe_part = arg1.parts[0]
        assert isinstance(pe_part, ParamExp)
        assert pe_part.type == "ParamExp"
        assert pe_part.param == "HOME"

    def test_block_position_info(self) -> None:
        """Verify Block nodes have position information from shfmt."""
        tree = parse_ast("{ echo 'a'; }")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, Block)
        assert cmd.pos is not None
        assert cmd.end is not None
        assert cmd.left_pos is not None
        assert cmd.right_pos is not None
        assert isinstance(cmd.pos.offset, int)
        assert isinstance(cmd.end.offset, int)
        # Lbrace should be before rbrace
        assert cmd.left_pos.offset < cmd.right_pos.offset

    def test_empty_block_with_commands(self) -> None:
        """Parse a block with multiple different command types."""
        tree = parse_ast("{ ls -la; cat file.txt; grep pattern file.txt; }")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, Block)
        assert len(cmd.stmts) == 3
        for i in range(3):
            sc = cmd.stmts[i].cmd
            assert isinstance(sc, CallExpr)
            sc_args = sc.args
            sa = sc_args[0]
            assert isinstance(sa, Word)
            p = sa.parts[0]
            assert isinstance(p, Lit)
        values = ["ls", "cat", "grep"]
        for i in range(3):
            stmt_cmd = cmd.stmts[i].cmd
            assert isinstance(stmt_cmd, CallExpr)
            sc2_args = stmt_cmd.args
            sa = sc2_args[0]
            assert isinstance(sa, Word)
            p = sa.parts[0]
            assert isinstance(p, Lit)
            assert p.value == values[i]

    def test_block_pipe_inside(self) -> None:
        """Parse { ls | grep txt; } and verify pipe inside Block."""
        tree = parse_ast("{ ls | grep txt; }")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, Block)
        inner_cmd = cmd.stmts[0].cmd
        assert isinstance(inner_cmd, BinaryCmd)
        bc = inner_cmd
        assert bc.op == "|"
        left = bc.left
        assert isinstance(left, CallExpr)
        la0 = left.args[0]
        assert isinstance(la0, Word)
        lp0 = la0.parts[0]
        assert isinstance(lp0, Lit)
        assert lp0.value == "ls"
        right = bc.right
        assert isinstance(right, CallExpr)
        ra0 = right.args[0]
        assert isinstance(ra0, Word)
        rp0 = ra0.parts[0]
        assert isinstance(rp0, Lit)
        assert rp0.value == "grep"
        ra1 = right.args[1]
        assert isinstance(ra1, Word)
        rp1 = ra1.parts[0]
        assert isinstance(rp1, Lit)
        assert rp1.value == "txt"

    def test_block_andcmd_inside(self) -> None:
        """Parse { test -f file && cat file; } with BinaryCmd(op='&&') inside Block

        shfmt represents && as BinaryCmd with Op='&&'; there is no separate
        AndCmd node type, inside a block or at statement level.
        """
        tree = parse_ast("{ test -f file && cat file; }")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, Block)
        inner_cmd = cmd.stmts[0].cmd
        assert isinstance(inner_cmd, BinaryCmd)
        bc = inner_cmd
        assert bc.op == "&&"
        left = bc.left
        assert isinstance(left, CallExpr)
        la0 = left.args[0]
        assert isinstance(la0, Word)
        lp0 = la0.parts[0]
        assert isinstance(lp0, Lit)
        assert lp0.value == "test"
        right = bc.right
        assert isinstance(right, CallExpr)
        ra0 = right.args[0]
        assert isinstance(ra0, Word)
        rp0 = ra0.parts[0]
        assert isinstance(rp0, Lit)
        assert rp0.value == "cat"

    def test_block_with_redirect(self) -> None:
        """Parse { echo hello > output.txt; } with redirection inside Block."""
        tree = parse_ast("{ echo hello > output.txt; }")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, Block)
        stmt = cmd.stmts[0]
        scmd = stmt.cmd
        assert isinstance(scmd, CallExpr)
        sa0 = scmd.args[0]
        assert isinstance(sa0, Word)
        p0 = sa0.parts[0]
        assert isinstance(p0, Lit)
        assert p0.value == "echo"
        assert len(stmt.redirs) == 1
        assert stmt.redirs[0].op == ">"
        word = stmt.redirs[0].word
        assert isinstance(word, Word)
        w0 = word.parts[0]
        assert isinstance(w0, Lit)
        assert w0.value == "output.txt"

    def test_block_cmdsubst_inside(self) -> None:
        """Parse { echo $(date); } with CmdSubst inside Block."""
        tree = parse_ast("{ echo $(date); }")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, Block)
        inner_stmt = cmd.stmts[0]
        scmd = inner_stmt.cmd
        assert isinstance(scmd, CallExpr)
        arg1 = scmd.args[1]
        assert isinstance(arg1, Word)
        cs_part = arg1.parts[0]
        assert isinstance(cs_part, CmdSubst)
        cs_st = cs_part.stmts[0].cmd
        assert isinstance(cs_st, CallExpr)
        csa = cs_st.args[0]
        assert isinstance(csa, Word)
        cp = csa.parts[0]
        assert isinstance(cp, Lit)
        assert cp.value == "date"

    def test_block_if_inside(self) -> None:
        """Parse { if true; then echo 'yes'; fi; } with if statement inside Block."""
        tree = parse_ast("{ if true; then echo 'yes'; fi; }")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, Block)
        inner_cmd = cmd.stmts[0].cmd
        assert isinstance(inner_cmd, IfClause)
        ic = inner_cmd
        assert len(ic.then_stmts) == 1
        then_cmd = ic.then_stmts[0].cmd
        assert isinstance(then_cmd, CallExpr)
        tc0 = then_cmd.args[0]
        assert isinstance(tc0, Word)
        tp0 = tc0.parts[0]
        assert isinstance(tp0, Lit)
        assert tp0.value == "echo"

    def test_block_with_arithmetic(self) -> None:
        """Parse { echo $((1 + 2)); } with ArithmExp inside Block."""
        tree = parse_ast("{ echo $((1 + 2)); }")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, Block)
        inner_cmd = cmd.stmts[0].cmd
        assert isinstance(inner_cmd, CallExpr)
        ia1 = inner_cmd.args[1]
        assert isinstance(ia1, Word)
        ae_part = ia1.parts[0]
        assert isinstance(ae_part, ArithmExp)
        ae = ae_part.x
        assert isinstance(ae, BinaryArithm)
        assert ae.op == "+"

    def test_deeply_nested_blocks(self) -> None:
        """Parse { { { echo 'deep'; }; }; } with three levels of nesting."""
        tree = parse_ast("{ { { echo 'deep'; }; }; }")
        outer = tree.stmts[0].cmd
        assert isinstance(outer, Block)
        mid_block = outer.stmts[0].cmd
        assert isinstance(mid_block, Block)
        inner_block = mid_block.stmts[0].cmd
        assert isinstance(inner_block, Block)
        inner_cmd = inner_block.stmts[0].cmd
        assert isinstance(inner_cmd, CallExpr)
        i1a = inner_cmd.args[0]
        assert isinstance(i1a, Word)
        p1 = i1a.parts[0]
        assert isinstance(p1, Lit)
        assert p1.value == "echo"
        i1b = inner_cmd.args[1]
        assert isinstance(i1b, Word)
        q1 = i1b.parts[0]
        assert isinstance(q1, SglQuoted)
        assert q1.value == "deep"

    def test_block_imported_in_module(self) -> None:
        """Verify that Block is imported in the lovely_bash_permissions module."""
        from lovely_bash_permissions import Block

        assert isinstance(Block, type)


class TestFuncDeclNodes:
    """Tests for the FuncDecl node type.

    Bash function declarations: name() { body }, function name { body },
    function name() { body }. The function body is always a Block node
    """

    def test_func_decl_with_parens(self) -> None:
        """Parse hello() { echo 'hi'; } and verify FuncDecl node."""
        tree = parse_ast("hello() { echo 'hi'; }")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, FuncDecl)
        # No 'function' keyword used
        assert cmd.rsrv_word is False
        # Parens used
        assert cmd.parens is True
        # Function name
        assert cmd.name is not None
        assert isinstance(cmd.name, Lit)
        assert cmd.name.type == "Lit"
        assert cmd.name.value == "hello"
        # Body is a Block with one statement
        assert cmd.body is not None
        assert isinstance(cmd.body, Block)
        assert len(cmd.body.stmts) == 1
        body_stmt = cmd.body.stmts[0].cmd
        assert isinstance(body_stmt, CallExpr)
        bsa = body_stmt.args[0]
        assert isinstance(bsa, Word)
        bp0 = bsa.parts[0]
        assert isinstance(bp0, Lit)
        v_bp0 = bp0
        assert v_bp0.value == "echo"
        bsa2 = body_stmt.args[1]
        assert isinstance(bsa2, Word)
        bq0 = bsa2.parts[0]
        assert isinstance(bq0, SglQuoted)
        assert bq0 is not None
        v_bq0 = bq0
        assert v_bq0.value == "hi"

    def test_func_decl_function_keyword_no_parens(self) -> None:
        """Parse function hello { echo 'hi'; } (POSIX style, no parens)."""
        tree = parse_ast("function hello { echo 'hi'; }")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, FuncDecl)
        # Function keyword used
        assert cmd.rsrv_word is True
        # No parens used in this style
        assert cmd.parens is False
        # Function name
        assert cmd.name is not None
        assert isinstance(cmd.name, Lit)
        assert cmd.name.type == "Lit"
        assert cmd.name.value == "hello"
        # Body is a Block with one statement
        assert cmd.body is not None
        assert isinstance(cmd.body, Block)
        assert len(cmd.body.stmts) == 1
        body_stmt = cmd.body.stmts[0].cmd
        assert isinstance(body_stmt, CallExpr)
        bsa = body_stmt.args[0]
        assert isinstance(bsa, Word)
        bp0 = bsa.parts[0]
        assert isinstance(bp0, Lit)
        v_bp0 = bp0
        assert v_bp0.value == "echo"
        bsa2 = body_stmt.args[1]
        assert isinstance(bsa2, Word)
        bq0 = bsa2.parts[0]
        assert isinstance(bq0, SglQuoted)
        assert bq0 is not None
        v_bq0 = bq0
        assert v_bq0.value == "hi"

    def test_func_decl_function_keyword_with_parens(self) -> None:
        """Parse function hello() { echo 'hi'; } (function keyword + parens)."""
        tree = parse_ast("function hello() { echo 'hi'; }")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, FuncDecl)
        # Function keyword used
        assert cmd.rsrv_word is True
        # Parens also used
        assert cmd.parens is True
        # Function name
        assert cmd.name is not None
        assert isinstance(cmd.name, Lit)
        assert cmd.name.type == "Lit"
        assert cmd.name.value == "hello"
        # Body is a Block with one statement
        assert cmd.body is not None
        assert isinstance(cmd.body, Block)
        assert len(cmd.body.stmts) == 1
        body_stmt = cmd.body.stmts[0].cmd
        assert isinstance(body_stmt, CallExpr)
        bsa = body_stmt.args[0]
        assert isinstance(bsa, Word)
        bp0 = bsa.parts[0]
        assert isinstance(bp0, Lit)
        v_bp0 = bp0
        assert v_bp0.value == "echo"
        bsa2 = body_stmt.args[1]
        assert isinstance(bsa2, Word)
        bq0 = bsa2.parts[0]
        assert isinstance(bq0, SglQuoted)
        assert bq0 is not None
        v_bq0 = bq0
        assert v_bq0.value == "hi"

    def test_func_decl_multiple_statements(self) -> None:
        """Parse a function with multiple statements in the body."""
        tree = parse_ast("greet() { echo 'hello'; echo 'world'; }")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, FuncDecl)
        assert cmd.name is not None
        assert cmd.name.value == "greet"
        # Body should have two statements
        body = cmd.body
        assert isinstance(body, Block)
        assert len(body.stmts) == 2
        first = body.stmts[0].cmd
        assert isinstance(first, CallExpr)
        fa1 = first.args[0]
        assert isinstance(fa1, Word)
        fp1 = fa1.parts[0]
        assert isinstance(fp1, Lit)
        assert fp1 is not None
        v_fp1 = fp1
        assert v_fp1 is not None
        assert v_fp1.value == "echo"
        fa2 = first.args[1]
        assert isinstance(fa2, Word)
        fq2 = fa2.parts[0]
        assert isinstance(fq2, SglQuoted)
        v_fq2 = fq2
        assert v_fq2.value == "hello"
        second = body.stmts[1].cmd
        assert isinstance(second, CallExpr)
        sa1 = second.args[0]
        assert isinstance(sa1, Word)
        sp1 = sa1.parts[0]
        assert isinstance(sp1, Lit)
        v_sp1 = sp1
        assert v_sp1.value == "echo"
        sa2 = second.args[1]
        assert isinstance(sa2, Word)
        sq2 = sa2.parts[0]
        assert isinstance(sq2, SglQuoted)
        v_sq2 = sq2
        assert v_sq2.value == "world"

    def test_func_decl_with_args(self) -> None:
        """Parse a function that uses parameters ($1, $2)."""
        tree = parse_ast("say() { echo $1 $2; }")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, FuncDecl)
        assert cmd.name is not None
        assert cmd.name.value == "say"
        # Body should have one statement
        body = cmd.body
        assert isinstance(body, Block)
        assert len(body.stmts) == 1
        body_stmt = body.stmts[0].cmd
        assert isinstance(body_stmt, CallExpr)
        bsa = body_stmt.args[0]
        assert isinstance(bsa, Word)
        bp1 = bsa.parts[0]
        assert isinstance(bp1, Lit)
        assert bp1 is not None
        v_bp1 = bp1
        assert v_bp1 is not None
        assert v_bp1.value == "echo"
        # $1 is ParamExp
        bsa2 = body_stmt.args[1]
        assert isinstance(bsa2, Word)
        pe1 = bsa2.parts[0]
        assert isinstance(pe1, ParamExp)
        assert pe1.type == "ParamExp"
        assert pe1.param == "1"
        # $2 is ParamExp
        bsa3 = body_stmt.args[2]
        assert isinstance(bsa3, Word)
        pe2 = bsa3.parts[0]
        assert isinstance(pe2, ParamExp)
        assert pe2.type == "ParamExp"
        assert pe2.param == "2"

    def test_func_decl_with_variables(self) -> None:
        """Parse a function that references external variables."""
        tree = parse_ast("show() { echo $HOME; }")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, FuncDecl)
        assert cmd.name is not None
        assert cmd.name.value == "show"
        # Body should have one statement
        body = cmd.body
        assert isinstance(body, Block)
        assert len(body.stmts) == 1
        body_stmt = body.stmts[0].cmd
        assert isinstance(body_stmt, CallExpr)
        bsa = body_stmt.args[0]
        assert isinstance(bsa, Word)
        bp1 = bsa.parts[0]
        assert isinstance(bp1, Lit)
        assert bp1 is not None
        v_bp1h = bp1
        assert v_bp1h is not None
        assert v_bp1h.value == "echo"
        # $HOME is ParamExp
        bsa2 = body_stmt.args[1]
        assert isinstance(bsa2, Word)
        pe = bsa2.parts[0]
        assert isinstance(pe, ParamExp)
        assert pe.type == "ParamExp"
        param_home = pe
        assert param_home.param == "HOME"

    def test_func_decl_cmdsubst_inside(self) -> None:
        """Parse a function with command substitution inside."""
        tree = parse_ast("now() { echo $(date); }")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, FuncDecl)
        assert cmd.name is not None
        assert cmd.name.value == "now"
        # Body should have one statement
        body = cmd.body
        assert isinstance(body, Block)
        assert len(body.stmts) == 1
        body_stmt = body.stmts[0].cmd
        assert isinstance(body_stmt, CallExpr)
        bsa = body_stmt.args[0]
        assert isinstance(bsa, Word)
        bp1 = bsa.parts[0]
        assert isinstance(bp1, Lit)
        assert bp1 is not None
        v_bp1 = bp1
        assert v_bp1 is not None
        assert v_bp1.value == "echo"
        # Argument should be CmdSubst
        bsa2 = body_stmt.args[1]
        assert isinstance(bsa2, Word)
        cs_part = bsa2.parts[0]
        assert isinstance(cs_part, CmdSubst)
        # Nested statement in CmdSubst should be CallExpr with 'date'
        subst_cmd = cs_part.stmts[0].cmd
        assert isinstance(subst_cmd, CallExpr)
        sc = subst_cmd.args[0]
        assert isinstance(sc, Word)
        sp = sc.parts[0]
        assert isinstance(sp, Lit)
        v_sp = sp
        assert v_sp.value == "date"

    def test_func_decl_complex_body(self) -> None:
        """Parse a function with a complex body (pipe, redirect, if, etc.)."""
        tree = parse_ast("""process() {
    if [ -f "$1" ]; then
        cat "$1" | sort | uniq > "$2"
    fi
}""")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, FuncDecl)
        assert cmd.name is not None
        assert cmd.name.value == "process"
        # Body should be a Block with one statement
        body = cmd.body
        assert isinstance(body, Block)
        assert len(body.stmts) == 1
        # The inner statement should be IfClause
        inner = body.stmts[0].cmd
        assert isinstance(inner, IfClause)
        assert len(inner.cond_stmts) == 1
        assert len(inner.then_stmts) == 1
        # The body of the if should be a BinaryCmd (pipe chain)
        then_stmt = inner.then_stmts[0]
        bc = then_stmt.cmd
        assert isinstance(bc, BinaryCmd)
        # Nested BinaryCmd: cat "$1" | sort
        left = bc.left
        assert isinstance(left, BinaryCmd)
        assert left.op == "|"
        # left.left should be CallExpr for cat "$1"
        ll = left.left
        assert isinstance(ll, CallExpr)
        la0 = ll.args[0]
        assert isinstance(la0, Word)
        assert la0 is not None
        lp0 = la0.parts[0]
        assert isinstance(lp0, Lit)
        assert lp0 is not None
        assert lp0.value == "cat"
        # "$1" is a DblQuoted containing a ParamExp for $1
        la1 = ll.args[1]
        assert isinstance(la1, Word)
        dq1 = la1.parts[0]
        assert isinstance(dq1, DblQuoted)
        ip = dq1.parts[0]
        assert isinstance(ip, ParamExp)
        assert ip.param == "1"
        # left.right should be CallExpr for sort
        lr = left.right
        assert isinstance(lr, CallExpr)
        ra0 = lr.args[0]
        assert isinstance(ra0, Word)
        rp0 = ra0.parts[0]
        assert isinstance(rp0, Lit)
        v_rp0 = rp0
        assert v_rp0 is not None
        assert v_rp0.value == "sort"
        # The outer y should be CallExpr for uniq with redirection
        y = bc.right
        assert isinstance(y, CallExpr)
        ya0 = y.args[0]
        assert isinstance(ya0, Word)
        fp3 = ya0.parts[0]
        assert isinstance(fp3, Lit)
        v_fp3 = fp3
        assert v_fp3 is not None
        assert v_fp3.value == "uniq"
        # Redirection on the y side: > "$2" is attached to the outer
        pipe = bc
        assert len(pipe.redirs) == 1
        assert pipe.redirs[0].op == ">"
        redir_word = pipe.redirs[0].word
        assert isinstance(redir_word, Word)
        redir_part = redir_word.parts[0]
        # "$2" is a DblQuoted containing a ParamExp for $2
        assert isinstance(redir_part, DblQuoted)
        irp = redir_part.parts[0]
        assert isinstance(irp, ParamExp)
        assert irp.param == "2"

    def test_func_decl_position_info(self) -> None:
        """Verify FuncDecl nodes have position information from shfmt."""
        tree = parse_ast("hello() { echo 'hi'; }")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, FuncDecl)
        assert cmd.pos is not None
        assert cmd.end is not None
        assert isinstance(cmd.pos.offset, int)
        assert isinstance(cmd.end.offset, int)
        # Body should also have position info
        body = cmd.body
        assert isinstance(body, Block)
        assert body.pos is not None
        assert body.end is not None
        # Body should start after function declaration
        assert body.pos.offset > cmd.pos.offset

    def test_func_decl_nested_calls(self) -> None:
        """Parse a function that calls other commands."""
        tree = parse_ast("setup() { mkdir -p out; cd out; }")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, FuncDecl)
        assert cmd.name is not None
        assert cmd.name.value == "setup"
        # Body should have two statements
        body = cmd.body
        assert isinstance(body, Block)
        assert len(body.stmts) == 2
        # First: mkdir -p out
        first = body.stmts[0].cmd
        assert isinstance(first, CallExpr)
        fa1 = first.args[0]
        assert isinstance(fa1, Word)
        fp1 = fa1.parts[0]
        assert isinstance(fp1, Lit)
        assert fp1.value == "mkdir"
        fa2 = first.args[1]
        assert isinstance(fa2, Word)
        fp2 = fa2.parts[0]
        assert isinstance(fp2, Lit)
        assert fp2.value == "-p"
        fa3 = first.args[2]
        assert isinstance(fa3, Word)
        fp3 = fa3.parts[0]
        assert isinstance(fp3, Lit)
        fp3v = fp3
        assert fp3v.value == "out"
        # Second: cd out
        second = body.stmts[1].cmd
        assert isinstance(second, CallExpr)
        sa1 = second.args[0]
        assert isinstance(sa1, Word)
        sp1 = sa1.parts[0]
        assert isinstance(sp1, Lit)
        v_sp1 = sp1
        assert v_sp1 is not None
        assert v_sp1.value == "cd"
        sa2 = second.args[1]
        assert isinstance(sa2, Word)
        sq2 = sa2.parts[0]
        assert isinstance(sq2, Lit)
        v_sq2 = sq2
        assert v_sq2.value == "out"

    def test_func_decl_with_double_quotes(self) -> None:
        """Parse a function using double-quoted strings."""
        tree = parse_ast('hello() { echo "hello world"; }')
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, FuncDecl)
        assert cmd.name is not None
        assert cmd.name.value == "hello"
        # Body should have one statement
        body = cmd.body
        assert isinstance(body, Block)
        assert len(body.stmts) == 1
        body_stmt = body.stmts[0].cmd
        assert isinstance(body_stmt, CallExpr)
        bsa = body_stmt.args[0]
        assert isinstance(bsa, Word)
        bp1 = bsa.parts[0]
        assert isinstance(bp1, Lit)
        assert bp1.value == "echo"
        # Argument should be DblQuoted
        bsa2 = body_stmt.args[1]
        assert isinstance(bsa2, Word)
        dq = bsa2.parts[0]
        assert isinstance(dq, DblQuoted)
        dq_val = dq.parts[0]
        assert isinstance(dq_val, Lit)
        v_dqv = dq_val
        assert v_dqv is not None
        assert v_dqv.value == "hello world"

    def test_func_decl_empty_body(self) -> None:
        """Parse a function with empty body (noop using `:` builtin)."""
        # bash requires a statement in the function body
        # `:` is the no-op builtin, so noop() { :; } is an empty-function equivalent
        tree = parse_ast("noop() { :; }")
        cmd = tree.stmts[0].cmd
        assert isinstance(cmd, FuncDecl)
        assert cmd.name is not None
        assert cmd.name.value == "noop"
        # Body should be a Block with one statement (the `:` no-op)
        body = cmd.body
        assert isinstance(body, Block)
        assert len(body.stmts) == 1
        inner_cmd = body.stmts[0].cmd
        assert isinstance(inner_cmd, CallExpr)
        parts0 = inner_cmd.args[0].parts[0]
        assert isinstance(parts0, Lit)
        assert parts0.value == ":"

    def test_func_decl_imported_in_module(self) -> None:
        """Verify that FuncDecl is imported in the lovely_bash_permissions module."""
        from lovely_bash_permissions import FuncDecl

        assert FuncDecl is not None


class TestDeepNestingRecursion:
    """deep nesting must convert instead of raising RecursionError."""

    def test_deep_cmdsubst_does_not_crash(self) -> None:
        deep = "echo " + "$(" * 200 + "true" + ")" * 200
        parse_ast(deep)

    def test_deep_compound_does_not_crash(self) -> None:
        parse_ast("if :; then " * 300 + "true" + "; fi" * 300)
        chain = " && ".join(["a"] * 400)
        assert len(parse_segments(chain)) == 400
        parse_ast("while :; do " * 400 + "true" + "; done" * 400)
