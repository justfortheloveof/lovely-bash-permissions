"""
Comprehensive tests for the lovely-bash-permissions parser.
"""

import pytest

from lovely_bash_permissions import (
    ArithmExp,
    BinaryArithm,
    Block,
    CmdSubst,
    DblQuoted,
    FuncDecl,
    Lit,
    ParamExp,
    ProcSubst,
    SglQuoted,
    get_arguments,
    get_commands,
    get_redirections,
    has_variable,
    parse_ast,
)
from lovely_bash_permissions.parser import ParseError


class TestSimpleCommands:
    """Test simple command parsing."""

    def test_single_command(self):
        tree = parse_ast("ls")
        assert get_commands(tree) == ["ls"]
        assert get_arguments(tree) == [[]]

    def test_command_with_flags(self):
        tree = parse_ast("ls -la")
        assert get_commands(tree) == ["ls"]
        assert get_arguments(tree) == [["-la"]]

    def test_command_with_multiple_args(self):
        tree = parse_ast("cp file1.txt file2.txt")
        assert get_commands(tree) == ["cp"]
        assert get_arguments(tree) == [["file1.txt", "file2.txt"]]

    def test_echo_command(self):
        tree = parse_ast("echo hello")
        assert get_commands(tree) == ["echo"]
        assert get_arguments(tree) == [["hello"]]


class TestPipes:
    """Test pipe parsing."""

    def test_single_pipe(self):
        tree = parse_ast("cat file.txt | grep pattern")
        assert get_commands(tree) == ["cat", "grep"]
        assert get_arguments(tree) == [["file.txt"], ["pattern"]]

    def test_multiple_pipes(self):
        tree = parse_ast("cat file.txt | grep pattern | sort | uniq")
        assert get_commands(tree) == ["cat", "grep", "sort", "uniq"]
        assert get_arguments(tree) == [["file.txt"], ["pattern"], [], []]

    def test_pipe_with_flags(self):
        tree = parse_ast("ls -la | grep -i txt")
        assert get_commands(tree) == ["ls", "grep"]
        assert get_arguments(tree) == [["-la"], ["-i", "txt"]]


class TestRedirections:
    """Test redirection parsing."""

    def test_output_redirect(self):
        tree = parse_ast("cat file.txt > output.txt")
        assert get_commands(tree) == ["cat"]
        assert get_arguments(tree) == [["file.txt"]]
        redirs = get_redirections(tree)
        assert len(redirs) == 1
        assert redirs[0]["op"] == ">"
        assert redirs[0]["target"] == "output.txt"

    def test_append_redirect(self):
        tree = parse_ast("cat file.txt >> output.txt")
        redirs = get_redirections(tree)
        assert len(redirs) == 1
        assert redirs[0]["op"] == ">>"

    def test_input_redirect(self):
        tree = parse_ast("sort < input.txt")
        redirs = get_redirections(tree)
        assert len(redirs) == 1
        assert redirs[0]["op"] == "<"

    def test_pipe_with_redirect(self):
        tree = parse_ast("ls -la | grep txt > output.txt")
        assert get_commands(tree) == ["ls", "grep"]
        assert get_arguments(tree) == [["-la"], ["txt"]]
        redirs = get_redirections(tree)
        assert len(redirs) == 1
        assert redirs[0]["op"] == ">"
        assert redirs[0]["target"] == "output.txt"


class TestVariables:
    """Test variable detection."""

    def test_no_variables(self):
        tree = parse_ast("ls -la")
        assert not has_variable(tree)

    def test_simple_variable(self):
        tree = parse_ast("echo $HOME")
        assert has_variable(tree)

    def test_path_variable(self):
        tree = parse_ast("cat /path/to/file")
        assert not has_variable(tree)

    def test_multiple_variables(self):
        tree = parse_ast("echo $HOME $USER")
        assert has_variable(tree)

    def test_quoted_variable(self):
        tree = parse_ast('echo "$HOME"')
        assert has_variable(tree)

    def test_env_var(self):
        tree = parse_ast('export PATH="$HOME/bin:$PATH"')
        assert has_variable(tree)


class TestComplexCommands:
    """Test complex command parsing."""

    def test_complex_pipeline(self):
        tree = parse_ast(
            'cat data.csv | grep pattern | awk "{print $1}" | sort -u > results.txt'
        )
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

    def test_command_with_quoted_args(self):
        tree = parse_ast('find / -name "*.txt" -type f')
        assert get_commands(tree) == ["find"]
        args = get_arguments(tree)
        assert len(args) == 1
        assert args[0][0] == "/"
        assert args[0][1] == "-name"
        assert args[0][3] == "-type"
        assert args[0][4] == "f"

    def test_long_command(self):
        tree = parse_ast(
            'tar -czvf archive.tar.gz $(find . -name "*.py" -not -path "./.venv/*" -not -path "./tests/*")'
        )
        assert get_commands(tree) == ["tar"]
        assert has_variable(tree)


class TestEdgeCases:
    """Test edge cases."""

    def test_empty_command(self):
        with pytest.raises(ParseError):
            parse_ast("")

    def test_whitespace_only(self):
        with pytest.raises(ParseError):
            parse_ast("   ")

    def test_single_quote(self):
        tree = parse_ast("echo 'hello world'")
        assert get_commands(tree) == ["echo"]

    def test_double_quote(self):
        tree = parse_ast('echo "hello world"')
        assert get_commands(tree) == ["echo"]


class TestASTStructure:
    """Test AST structure and types."""

    def test_file_node_type(self):
        tree = parse_ast("ls")
        assert tree.type == "File"

    def test_stmt_count(self):
        tree = parse_ast("ls")
        assert len(tree.stmts) == 1

    def test_multiple_stmts(self):
        tree = parse_ast("ls\ngrep pattern file.txt")
        assert len(tree.stmts) == 2
        assert get_commands(tree) == ["ls", "grep"]

    def test_call_expr_node(self):
        tree = parse_ast("ls")
        cmd = tree.stmts[0].cmd
        assert cmd.type == "CallExpr"

    def test_binary_cmd_node(self):
        tree = parse_ast("ls | grep txt")
        cmd = tree.stmts[0].cmd
        assert cmd.type == "BinaryCmd"
        assert cmd.op == "|"


class TestLitNodes:
    """Tests for the Lit node type (Step 1 of node coverage)."""

    def test_simple_literal_value(self):
        """Parse a simple command and find the Lit node with its value."""
        tree = parse_ast("ls")
        cmd = tree.stmts[0].cmd
        assert cmd.type == "CallExpr"
        # First arg is the command name as a Word containing a Lit part
        assert len(cmd.args) == 1
        assert cmd.args[0].type == "Word"
        assert len(cmd.args[0].parts) == 1
        assert cmd.args[0].parts[0].type == "Lit"
        assert cmd.args[0].parts[0].value == "ls"

    def test_literal_argument(self):
        """Parse echo hello and verify the Lit argument value."""
        tree = parse_ast("echo hello")
        cmd = tree.stmts[0].cmd
        assert cmd.type == "CallExpr"
        # Second arg is the argument
        assert cmd.args[1].parts[0].type == "Lit"
        assert cmd.args[1].parts[0].value == "hello"

    def test_literal_file_name(self):
        """Parse cat file.txt and verify the Lit file argument."""
        tree = parse_ast("cat file.txt")
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == "Lit"
        assert cmd.args[1].parts[0].value == "file.txt"

    def test_literal_flag(self):
        """Parse ls -la and verify the Lit flag argument."""
        tree = parse_ast("ls -la")
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == "Lit"
        assert cmd.args[1].parts[0].value == "-la"

    def test_multiple_literal_arguments(self):
        """Parse cp with multiple literal arguments."""
        tree = parse_ast("cp file1.txt file2.txt")
        cmd = tree.stmts[0].cmd
        assert len(cmd.args) == 3
        assert cmd.args[0].parts[0].type == "Lit"
        assert cmd.args[0].parts[0].value == "cp"
        assert cmd.args[1].parts[0].type == "Lit"
        assert cmd.args[1].parts[0].value == "file1.txt"
        assert cmd.args[2].parts[0].type == "Lit"
        assert cmd.args[2].parts[0].value == "file2.txt"

    def test_literal_in_pipe(self):
        """Parse a piped command and verify both commands have Lit parts."""
        tree = parse_ast("cat file.txt | grep pattern")
        cmd = tree.stmts[0].cmd
        assert cmd.type == "BinaryCmd"
        # Left side: cat file.txt
        assert cmd.left.args[0].parts[0].type == "Lit"
        assert cmd.left.args[0].parts[0].value == "cat"
        assert cmd.left.args[1].parts[0].type == "Lit"
        assert cmd.left.args[1].parts[0].value == "file.txt"
        # Right side: grep pattern
        assert cmd.right.args[0].parts[0].type == "Lit"
        assert cmd.right.args[0].parts[0].value == "grep"
        assert cmd.right.args[1].parts[0].type == "Lit"
        assert cmd.right.args[1].parts[0].value == "pattern"

    def test_literal_with_special_chars(self):
        """Parse a command with special characters in a literal."""
        tree = parse_ast("echo hello-world_123")
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == "Lit"
        assert cmd.args[1].parts[0].value == "hello-world_123"

    def test_literal_with_slash(self):
        """Parse a command with a file path (slashes are allowed in literals)."""
        tree = parse_ast("cat /path/to/file.txt")
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == "Lit"
        assert cmd.args[1].parts[0].value == "/path/to/file.txt"

    def test_no_literal_with_variable(self):
        """Parse echo $HOME - variable is not a Lit node."""
        tree = parse_ast("echo $HOME")
        cmd = tree.stmts[0].cmd
        # The argument should be a ParamExp (short-form $var), not a Lit
        assert cmd.args[1].parts[0].type == "ParamExp"

    def test_no_literal_with_command_substitution(self):
        """Parse echo $(date) - command substitution is not a Lit node."""
        tree = parse_ast("echo $(date)")
        cmd = tree.stmts[0].cmd
        # The argument should be a CmdSubst, not a Lit
        assert cmd.args[1].parts[0].type == "CmdSubst"

    def test_no_literal_with_quoted_string(self):
        """Parse echo 'quoted' - quoted strings are SglQuoted, not Lit."""
        tree = parse_ast("echo 'quoted'")
        cmd = tree.stmts[0].cmd
        # The argument should be a SglQuoted, not a Lit
        assert cmd.args[1].parts[0].type == "SglQuoted"

    def test_literal_in_redirect(self):
        """Parse command with output redirect and verify Lit in redirect target."""
        tree = parse_ast("echo hello > output.txt")
        # The redirect target should contain a Lit with the filename
        assert tree.stmts[0].redirs[0].word.parts[0].type == "Lit"
        assert tree.stmts[0].redirs[0].word.parts[0].value == "output.txt"

    def test_literal_number(self):
        """Parse a command with a numeric literal."""
        tree = parse_ast("sleep 5")
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == "Lit"
        assert cmd.args[1].parts[0].value == "5"

    def test_literal_empty_word(self):
        """Parse a command and check that command name is a Lit node."""
        tree = parse_ast("true")
        cmd = tree.stmts[0].cmd
        assert cmd.args[0].parts[0].type == "Lit"
        assert cmd.args[0].parts[0].value == "true"

    def test_literal_multiline(self):
        """Parse multiple commands across lines and check Lit in both."""
        tree = parse_ast("echo a\necho b")
        # First command
        assert tree.stmts[0].cmd.args[1].parts[0].type == "Lit"
        assert tree.stmts[0].cmd.args[1].parts[0].value == "a"
        # Second command
        assert tree.stmts[1].cmd.args[1].parts[0].type == "Lit"
        assert tree.stmts[1].cmd.args[1].parts[0].value == "b"

    def test_literal_in_subshell(self):
        """Parse a subshell with a command and verify Lit inside."""
        tree = parse_ast("(echo hello)")
        cmd = tree.stmts[0].cmd
        assert cmd.type == "Subshell"
        assert cmd.stmts[0].cmd.args[1].parts[0].type == "Lit"
        assert cmd.stmts[0].cmd.args[1].parts[0].value == "hello"

    def test_literal_position_info(self):
        """Verify that Lit nodes have position information from shfmt."""
        tree = parse_ast("ls -la")
        cmd = tree.stmts[0].cmd
        # Verify that lit parts have proper pos/end values
        for arg in cmd.args:
            for part in arg.parts:
                if part.type == "Lit":
                    assert part.pos is not None
                    assert part.end is not None
                    assert isinstance(part.pos.offset, int)
                    assert isinstance(part.end.offset, int)

    def test_lit_imported_in_module(self):
        """Verify that Lit is imported in the lovely_bash_permissions module."""
        assert Lit is not None


class TestSglQuotedNodes:
    """Tests for the SglQuoted node type (Step 2 of node coverage)."""

    def test_simple_single_quoted(self):
        """Parse echo 'hello world' and verify it produces a SglQuoted node."""
        tree = parse_ast("echo 'hello world'")
        cmd = tree.stmts[0].cmd
        assert cmd.type == "CallExpr"
        assert len(cmd.args) == 2
        # The second argument is a SglQuoted part
        assert cmd.args[1].parts[0].type == "SglQuoted"
        assert cmd.args[1].parts[0].value == "hello world"

    def test_single_quoted_with_variable_no_expansion(self):
        """Parse echo '$HOME' and verify variable is not expanded (single quotes)."""
        tree = parse_ast("echo '$HOME'")
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == "SglQuoted"
        assert cmd.args[1].parts[0].value == "$HOME"

    def test_multiple_single_quoted_arguments(self):
        """Parse echo 'a' 'b' and verify both arguments are SglQuoted."""
        tree = parse_ast("echo 'a' 'b'")
        cmd = tree.stmts[0].cmd
        assert len(cmd.args) == 3
        assert cmd.args[1].parts[0].type == "SglQuoted"
        assert cmd.args[1].parts[0].value == "a"
        assert cmd.args[2].parts[0].type == "SglQuoted"
        assert cmd.args[2].parts[0].value == "b"

    def test_single_quoted_with_asterisk(self):
        """Parse echo 'foo*' and verify asterisk is literal in single quotes."""
        tree = parse_ast("echo 'foo*'")
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == "SglQuoted"
        assert cmd.args[1].parts[0].value == "foo*"

    def test_single_quoted_empty(self):
        """Parse echo '' and verify an empty SglQuoted is handled."""
        tree = parse_ast("echo ''")
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == "SglQuoted"
        assert cmd.args[1].parts[0].value == ""

    def test_single_quoted_backslashes(self):
        """Parse echo 'hello\nworld' and verify backslashes are literal."""
        tree = parse_ast("echo 'hello\nworld'")
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == "SglQuoted"
        assert cmd.args[1].parts[0].value == "hello\nworld"

    def test_single_quoted_with_dollar_sign(self):
        """Parse echo 'price $5' and verify the dollar sign is literal."""
        tree = parse_ast("echo 'price $5'")
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == "SglQuoted"
        assert cmd.args[1].parts[0].value == "price $5"

    def test_single_quoted_position_info(self):
        """Verify that SglQuoted nodes have position information from shfmt."""
        tree = parse_ast("echo 'hello'")
        cmd = tree.stmts[0].cmd
        part = cmd.args[1].parts[0]
        assert part.type == "SglQuoted"
        assert part.pos is not None
        assert part.end is not None
        assert isinstance(part.pos.offset, int)
        assert isinstance(part.end.offset, int)

    def test_sgquoted_imported_in_module(self):
        """Verify that SglQuoted is imported in the lovely_bash_permissions module."""
        assert SglQuoted is not None


class TestParamExpNodes:
    """Tests for the ParamExp node type (Step 4 of node coverage)."""

    def test_short_param_expansion(self):
        """Parse echo $HOME and verify it produces a ParamExp node with Short=True."""
        tree = parse_ast("echo $HOME")
        cmd = tree.stmts[0].cmd
        assert cmd.type == "CallExpr"
        assert len(cmd.args) == 2
        # The second argument is a ParamExp part
        assert cmd.args[1].parts[0].type == "ParamExp"
        assert cmd.args[1].parts[0].param == "HOME"
        assert cmd.args[1].parts[0].short is True

    def test_braced_param_expansion(self):
        """Parse echo ${HOME} and verify it produces a ParamExp node with Short=False."""
        tree = parse_ast("echo ${HOME}")
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == "ParamExp"
        assert cmd.args[1].parts[0].param == "HOME"
        assert cmd.args[1].parts[0].short is False

    def test_param_expansion_with_default(self):
        """Parse echo ${HOME:-default} and verify the Exp field."""
        tree = parse_ast("echo ${HOME:-default}")
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == "ParamExp"
        assert cmd.args[1].parts[0].param == "HOME"
        assert cmd.args[1].parts[0].exp is not None
        assert cmd.args[1].parts[0].exp["Op"] == ":-"

    def test_array_index_param_expansion(self):
        """Parse echo ${arr[0]} and verify the Index field."""
        tree = parse_ast("echo ${arr[0]}")
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == "ParamExp"
        assert cmd.args[1].parts[0].param == "arr"
        assert cmd.args[1].parts[0].index is not None
        assert cmd.args[1].parts[0].index.parts[0].value == "0"

    def test_param_expansion_in_double_quotes(self):
        """Parse echo "$HOME" and verify ParamExp inside DblQuoted."""
        tree = parse_ast('echo "$HOME"')
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == "DblQuoted"
        assert cmd.args[1].parts[0].parts[0].type == "ParamExp"
        assert cmd.args[1].parts[0].parts[0].param == "HOME"

    def test_multiple_param_expansions(self):
        """Parse echo "$HOME is $USER" and verify multiple ParamExp parts."""
        tree = parse_ast('echo "$HOME is $USER"')
        cmd = tree.stmts[0].cmd
        # Inside the DblQuoted, we should have: ParamExp, Lit, ParamExp
        assert cmd.args[1].parts[0].type == "DblQuoted"
        parts = cmd.args[1].parts[0].parts
        assert parts[0].type == "ParamExp"
        assert parts[0].param == "HOME"
        assert parts[1].type == "Lit"
        assert parts[1].value == " is "
        assert parts[2].type == "ParamExp"
        assert parts[2].param == "USER"

    def test_adjacent_param_expansions(self):
        """Parse echo "$HOME$USER" and verify two adjacent ParamExp parts."""
        tree = parse_ast('echo "$HOME$USER"')
        cmd = tree.stmts[0].cmd
        parts = cmd.args[1].parts[0].parts
        assert len(parts) == 2
        assert parts[0].type == "ParamExp"
        assert parts[0].param == "HOME"
        assert parts[1].type == "ParamExp"
        assert parts[1].param == "USER"

    def test_length_param_expansion(self):
        """Parse echo ${#HOME} and verify Length field."""
        tree = parse_ast("echo ${#HOME}")
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == "ParamExp"
        assert cmd.args[1].parts[0].param == "HOME"
        assert cmd.args[1].parts[0].length is True

    def test_special_param_expansion(self):
        """Parse echo "$@" and verify ParamExp with special parameter."""
        tree = parse_ast('echo "$@"')
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].parts[0].type == "ParamExp"
        assert cmd.args[1].parts[0].parts[0].param == "@"

    def test_position_param_expansion(self):
        """Parse echo "$0" and verify ParamExp with positional parameter."""
        tree = parse_ast('echo "$0"')
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].parts[0].type == "ParamExp"
        assert cmd.args[1].parts[0].parts[0].param == "0"

    def test_param_expansion_position_info(self):
        """Verify that ParamExp nodes have position information from shfmt."""
        tree = parse_ast("echo $HOME")
        cmd = tree.stmts[0].cmd
        part = cmd.args[1].parts[0]
        assert part.type == "ParamExp"
        assert part.pos is not None
        assert part.end is not None
        assert isinstance(part.pos.offset, int)
        assert isinstance(part.end.offset, int)

    def test_param_exp_imported_in_module(self):
        """Verify that ParamExp is imported in the lovely_bash_permissions module."""
        assert ParamExp is not None


class TestDblQuotedNodes:
    """Tests for the DblQuoted node type (Step 3 of node coverage)."""

    def test_simple_double_quoted(self):
        """Parse echo "hello" and verify it produces a DblQuoted node with Lit parts."""
        tree = parse_ast('echo "hello"')
        cmd = tree.stmts[0].cmd
        assert cmd.type == "CallExpr"
        assert len(cmd.args) == 2
        assert cmd.args[1].parts[0].type == "DblQuoted"
        assert len(cmd.args[1].parts[0].parts) == 1
        assert cmd.args[1].parts[0].parts[0].type == "Lit"
        assert cmd.args[1].parts[0].parts[0].value == "hello"

    def test_double_quoted_with_variable_expansion(self):
        """Parse echo "hello $world" and verify DblQuoted with Lit + ParamExp parts."""
        tree = parse_ast('echo "hello $world"')
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == "DblQuoted"
        parts = cmd.args[1].parts[0].parts
        assert len(parts) == 2
        assert parts[0].type == "Lit"
        assert parts[0].value == "hello "
        assert parts[1].type == "ParamExp"
        assert parts[1].param == "world"

    def test_double_quoted_multiple_variables(self):
        """Parse echo "$USER is here" and verify DblQuoted with multiple ParamExp parts."""
        tree = parse_ast('echo "$USER is here"')
        cmd = tree.stmts[0].cmd
        parts = cmd.args[1].parts[0].parts
        assert parts[0].type == "ParamExp"
        assert parts[0].param == "USER"
        assert parts[1].type == "Lit"
        assert parts[1].value == " is here"

    def test_empty_double_quoted(self):
        """Parse echo "" and verify an empty DblQuoted is handled."""
        tree = parse_ast('echo ""')
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == "DblQuoted"
        # shfmt-py: Empty DblQuoted has NO parts field at all (None in Python)
        assert cmd.args[1].parts[0].parts is None
        # shfmt Go: Would have an empty array: assert ...parts == []

    def test_empty_double_quoted_shfmt_go(self):
        """Test shfmt Go-style empty DblQuoted handling (for completeness)."""
        # In shfmt Go, empty double quotes would give a DblQuoted with an empty parts array.
        # Our parser should handle both: None parts (shfmt-py) and [] parts (shfmt Go).
        from lovely_bash_permissions.ast import DblQuoted

        dq_go = DblQuoted(type="DblQuoted", pos=None, end=None, parts=[])
        assert dq_go.parts == []

    def test_double_quoted_preserves_spaces(self):
        """Parse echo "a b c" and verify spaces are preserved in Lit parts."""
        tree = parse_ast('echo "a b c"')
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == "DblQuoted"
        assert len(cmd.args[1].parts[0].parts) == 1
        assert cmd.args[1].parts[0].parts[0].type == "Lit"
        assert cmd.args[1].parts[0].parts[0].value == "a b c"

    def test_nested_quotes(self):
        """Parse echo "$HOME is $USER" and verify multiple nested parts."""
        tree = parse_ast('echo "$HOME is $USER"')
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == "DblQuoted"
        parts = cmd.args[1].parts[0].parts
        assert len(parts) == 3
        assert parts[0].type == "ParamExp"
        assert parts[0].param == "HOME"
        assert parts[1].type == "Lit"
        assert parts[1].value == " is "
        assert parts[2].type == "ParamExp"
        assert parts[2].param == "USER"

    def test_escape_sequences_in_double_quotes(self):
        """Parse echo with escaped characters in double quotes."""
        tree = parse_ast('echo "\\n\\t\\r"')
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == "DblQuoted"
        # In shfmt-py, escaped sequences in double quotes become Lit parts with the literal escape sequences
        assert cmd.args[1].parts[0].parts[0].type == "Lit"
        assert cmd.args[1].parts[0].parts[0].value == "\\n\\t\\r"

    def test_mixed_literal_variable_escape(self):
        """Parse complex DblQuoted with lit, variable, and escapes mixed."""
        tree = parse_ast('echo "\\n$USER\\n"')
        cmd = tree.stmts[0].cmd
        parts = cmd.args[1].parts[0].parts
        assert len(parts) == 3
        assert parts[0].type == "Lit"
        assert parts[0].value == "\\n"
        assert parts[1].type == "ParamExp"
        assert parts[1].param == "USER"
        assert parts[2].type == "Lit"
        assert parts[2].value == "\\n"

    def test_dblquoted_position_info(self):
        """Verify that DblQuoted nodes have position information from shfmt."""
        tree = parse_ast('echo "hello"')
        cmd = tree.stmts[0].cmd
        part = cmd.args[1].parts[0]
        assert part.type == "DblQuoted"
        assert part.pos is not None
        assert part.end is not None
        assert isinstance(part.pos.offset, int)
        assert isinstance(part.end.offset, int)

    def test_dblquoted_imported_in_module(self):
        """Verify that DblQuoted is imported in the lovely_bash_permissions module."""
        assert DblQuoted is not None


class TestCmdSubstNodes:
    """Tests for the CmdSubst node type (Step 5 of node coverage)."""

    def test_simple_cmdsubst_syntax(self):
        """Parse echo $(date) and verify it produces a CmdSubst node."""
        tree = parse_ast("echo $(date)")
        cmd = tree.stmts[0].cmd
        assert cmd.type == "CallExpr"
        assert len(cmd.args) == 2
        assert cmd.args[1].parts[0].type == "CmdSubst"
        assert isinstance(cmd.args[1].parts[0], CmdSubst)
        assert len(cmd.args[1].parts[0].stmts) == 1
        inner_cmd = cmd.args[1].parts[0].stmts[0].cmd
        assert inner_cmd.type == "CallExpr"
        assert inner_cmd.args[0].parts[0].value == "date"

    def test_cmdsubst_with_backquotes(self):
        """Parse echo `date` and verify backquotes is True."""
        tree = parse_ast("echo `date`")
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == "CmdSubst"
        assert cmd.args[1].parts[0].backquotes is True
        assert cmd.args[1].parts[0].stmts[0].cmd.args[0].parts[0].value == "date"

    def test_cmdsubst_in_double_quotes(self):
        """Parse echo \"hello $(date)\" and verify CmdSubst inside DblQuoted."""
        tree = parse_ast('echo "hello $(date)"')
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == "DblQuoted"
        parts = cmd.args[1].parts[0].parts
        assert len(parts) == 2
        assert parts[0].type == "Lit"
        assert parts[0].value == "hello "
        assert parts[1].type == "CmdSubst"
        assert parts[1].stmts[0].cmd.args[0].parts[0].value == "date"

    def test_two_cmdsubst_parts(self):
        """Parse echo $(date) && $(date) and verify two CmdSubst parts."""
        tree = parse_ast("echo $(date) $(date)")
        cmd = tree.stmts[0].cmd
        assert len(cmd.args) == 3
        assert cmd.args[1].parts[0].type == "CmdSubst"
        assert cmd.args[2].parts[0].type == "CmdSubst"
        # Both have the same inner command
        assert cmd.args[1].parts[0].stmts[0].cmd.args[0].parts[0].value == "date"
        assert cmd.args[2].parts[0].stmts[0].cmd.args[0].parts[0].value == "date"

    def test_nested_cmdsubst(self):
        """Parse echo $(echo $(date)) and verify nested CmdSubst."""
        tree = parse_ast("echo $(echo $(date))")
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == "CmdSubst"
        outer_stmt = cmd.args[1].parts[0].stmts[0]
        assert outer_stmt.cmd.type == "CallExpr"
        assert outer_stmt.cmd.args[0].parts[0].value == "echo"
        inner_part = outer_stmt.cmd.args[1].parts[0]
        assert inner_part.type == "CmdSubst"
        assert inner_part.stmts[0].cmd.args[0].parts[0].value == "date"

    def test_cmdsubst_with_multiple_commands(self):
        """Parse echo $(ls | grep txt) and verify multiple inner statements."""
        tree = parse_ast("echo $(ls | grep txt)")
        cmd = tree.stmts[0].cmd
        cs = cmd.args[1].parts[0]
        assert cs.type == "CmdSubst"
        assert len(cs.stmts) == 1
        inner = cs.stmts[0].cmd
        assert inner.type == "BinaryCmd"
        assert inner.left.args[0].parts[0].value == "ls"
        assert inner.right.args[0].parts[0].value == "grep"
        assert inner.right.args[1].parts[0].value == "txt"

    def test_cmdsubst_position_info(self):
        """Verify that CmdSubst nodes have position information."""
        tree = parse_ast("echo $(date)")
        cmd = tree.stmts[0].cmd
        part = cmd.args[1].parts[0]
        assert part.pos is not None
        assert part.end is not None
        assert isinstance(part.pos.offset, int)
        assert isinstance(part.end.offset, int)

    def test_cmdsubst_backquotes_false(self):
        """Verify that $(...) has backquotes=False."""
        tree = parse_ast("echo $(date)")
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].backquotes is False

    def test_cmdsubst_imported_in_module(self):
        """Verify that CmdSubst is imported in the lovely_bash_permissions module."""
        from lovely_bash_permissions import CmdSubst

        assert CmdSubst is not None


class TestArithmExpNodes:
    """Tests for the ArithmExp node type (Step 6 of node coverage)."""

    def test_simple_arithmetic_expression(self):
        """Parse echo $((2 + 2)) and verify ArithmExp with BinaryArithm."""
        tree = parse_ast("echo $((2 + 2))")
        cmd = tree.stmts[0].cmd
        assert cmd.type == "CallExpr"
        assert len(cmd.args) == 2
        assert cmd.args[1].parts[0].type == "ArithmExp"
        assert isinstance(cmd.args[1].parts[0], ArithmExp)
        inner = cmd.args[1].parts[0].x
        assert inner.type == "BinaryArithm"
        assert inner.op == "+"
        assert inner.x.parts[0].type == "Lit"
        assert inner.x.parts[0].value == "2"
        assert inner.y.parts[0].type == "Lit"
        assert inner.y.parts[0].value == "2"

    def test_arithmetic_with_variables(self):
        """Parse echo $((x + y)) and verify ArithmExp with variables."""
        tree = parse_ast("echo $((x + y))")
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == "ArithmExp"
        inner = cmd.args[1].parts[0].x
        assert inner.type == "BinaryArithm"
        assert inner.op == "+"
        assert inner.x.parts[0].type == "Lit"
        assert inner.x.parts[0].value == "x"
        assert inner.y.parts[0].type == "Lit"
        assert inner.y.parts[0].value == "y"

    def test_single_value_arithmetic(self):
        """Parse echo $((50)) and verify ArithmExp with just a value."""
        tree = parse_ast("echo $((50))")
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == "ArithmExp"
        inner = cmd.args[1].parts[0].x
        assert inner.type == "Word"
        assert inner.parts[0].type == "Lit"
        assert inner.parts[0].value == "50"

    def test_arithmetic_in_double_quotes(self):
        """Parse echo \"$((5))\" and verify ArithmExp inside DblQuoted."""
        tree = parse_ast('echo "$((5))"')
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == "DblQuoted"
        dq = cmd.args[1].parts[0]
        assert dq.parts[0].type == "ArithmExp"
        inner = dq.parts[0].x
        assert inner.type == "Word"
        assert inner.parts[0].type == "Lit"
        assert inner.parts[0].value == "5"

    def test_complex_arithmetic_expression(self):
        """Parse echo $((2 * 3 + 4)) and verify nested BinaryArithm."""
        tree = parse_ast("echo $((2 * 3 + 4))")
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == "ArithmExp"
        inner = cmd.args[1].parts[0].x
        assert inner.type == "BinaryArithm"
        assert inner.op == "+"
        # Left side should be multiplication
        assert inner.x.type == "BinaryArithm"
        assert inner.x.op == "*"
        assert inner.x.x.parts[0].value == "2"
        assert inner.x.y.parts[0].value == "3"
        # Right side should be the number 4
        assert inner.y.parts[0].value == "4"

    def test_arithmetic_position_info(self):
        """Verify that ArithmExp nodes have position information."""
        tree = parse_ast("echo $((2 + 2))")
        cmd = tree.stmts[0].cmd
        part = cmd.args[1].parts[0]
        assert part.type == "ArithmExp"
        assert part.pos is not None
        assert part.end is not None
        assert isinstance(part.pos.offset, int)
        assert isinstance(part.end.offset, int)

    def test_binaryarithm_position_info(self):
        """Verify that BinaryArithm nodes have position information."""
        tree = parse_ast("echo $((2 + 2))")
        cmd = tree.stmts[0].cmd
        inner = cmd.args[1].parts[0].x
        assert inner.type == "BinaryArithm"
        assert inner.pos is not None
        assert inner.end is not None
        assert inner.op_pos is not None
        assert isinstance(inner.pos.offset, int)

    def test_arithmexp_imported_in_module(self):
        """Verify that ArithmExp is imported in the lovely_bash_permissions module."""
        from lovely_bash_permissions import ArithmExp

        assert ArithmExp is not None

    def test_binaryarithm_imported_in_module(self):
        """Verify that BinaryArithm is imported in the lovely_bash_permissions module."""
        assert BinaryArithm is not None


class TestProcSubstNodes:
    """Tests for the ProcSubst node type (Step 7 of node coverage)."""

    def test_input_process_substitution(self):
        """Parse cat <(echo 'hi') and verify ProcSubst with op='<('."""
        tree = parse_ast("cat <(echo 'hi')")
        cmd = tree.stmts[0].cmd
        assert cmd.type == "CallExpr"
        assert len(cmd.args) == 2
        assert cmd.args[1].parts[0].type == "ProcSubst"
        proc = cmd.args[1].parts[0]
        assert proc.op == "<("
        assert len(proc.stmts) == 1
        inner = proc.stmts[0].cmd
        assert inner.type == "CallExpr"
        assert inner.args[0].parts[0].value == "echo"
        assert inner.args[1].parts[0].type == "SglQuoted"
        assert inner.args[1].parts[0].value == "hi"

    def test_output_process_substitution(self):
        """Parse sort > >(cat) and verify ProcSubst with op='>('."""
        tree = parse_ast("sort > >(cat)")
        # The redirection target should be a ProcSubst
        assert tree.stmts[0].redirs[0].word.parts[0].type == "ProcSubst"
        proc = tree.stmts[0].redirs[0].word.parts[0]
        assert proc.op == ">("
        inner = proc.stmts[0].cmd
        assert inner.args[0].parts[0].value == "cat"

    def test_double_process_substitution(self):
        """Parse diff <(echo 'hi') <(echo 'there') with two ProcSubst nodes."""
        tree = parse_ast("diff <(echo 'hi') <(echo 'there')")
        cmd = tree.stmts[0].cmd
        assert len(cmd.args) == 3
        assert cmd.args[1].parts[0].type == "ProcSubst"
        assert cmd.args[2].parts[0].type == "ProcSubst"
        assert cmd.args[1].parts[0].op == "<("
        assert cmd.args[2].parts[0].op == "<("
        # Verify inner commands
        assert cmd.args[1].parts[0].stmts[0].cmd.args[0].parts[0].value == "echo"
        assert cmd.args[2].parts[0].stmts[0].cmd.args[0].parts[0].value == "echo"

    def test_process_substitution_in_double_quotes(self):
        """Parse echo \"<(cmd)\" - process substitution in double quotes is literal text."""
        # Note: bash does NOT expand <() inside double quotes
        tree = parse_ast('echo "<(echo hi)"')
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == "DblQuoted"
        # Inside double quotes, <() is literal, not a ProcSubst
        assert cmd.args[1].parts[0].parts[0].type == "Lit"
        assert cmd.args[1].parts[0].parts[0].value == "<(echo hi)"

    def test_process_substitution_position_info(self):
        """Verify ProcSubst nodes have position information from shfmt."""
        tree = parse_ast("cat <(echo 'hi')")
        cmd = tree.stmts[0].cmd
        part = cmd.args[1].parts[0]
        assert part.type == "ProcSubst"
        assert part.pos is not None
        assert part.end is not None
        assert part.op_pos is not None
        assert part.rparen is not None
        assert isinstance(part.pos.offset, int)
        assert isinstance(part.end.offset, int)

    def test_procsubst_imported_in_module(self):
        """Verify that ProcSubst is imported in the lovely_bash_permissions module."""
        assert ProcSubst is not None


class TestExtGlobNodes:
    """Tests for the ExtGlob node type (Step 8 of node coverage).

    Extended globs require `shopt -s extglob` in bash. shfmt parses
    them regardless. Syntax: @(pat|pat), +(pat|pat), *(pat|pat),
    ?(pat|pat), !(pat|pat). See https://www.gnu.org/software/bash/manual/bash.html#Pattern-Matching
    """

    def test_at_extended_glob(self):
        """Parse ls *.@(txt|md) and verify ExtGlob with op='@('."""
        tree = parse_ast("ls *.@(txt|md)")
        cmd = tree.stmts[0].cmd
        assert cmd.type == "CallExpr"
        assert len(cmd.args) == 2
        arg1 = cmd.args[1]
        assert arg1.parts[0].type == "Lit"
        assert arg1.parts[0].value == "*."
        assert arg1.parts[1].type == "ExtGlob"
        extglob = arg1.parts[1]
        assert extglob.op == "@("
        assert extglob.pattern.type == "Lit"
        assert extglob.pattern.value == "txt|md"

    def test_plus_extended_glob(self):
        """Parse ls *.+(txt|md) and verify ExtGlob with op='+('."""
        tree = parse_ast("ls *.+(txt|md)")
        cmd = tree.stmts[0].cmd
        extglob = cmd.args[1].parts[1]
        assert extglob.type == "ExtGlob"
        assert extglob.op == "+("
        assert extglob.pattern.value == "txt|md"

    def test_question_extended_glob(self):
        """Parse ls *.?(txt|md) and verify ExtGlob with op='?('."""
        tree = parse_ast("ls *.?(txt|md)")
        cmd = tree.stmts[0].cmd
        extglob = cmd.args[1].parts[1]
        assert extglob.type == "ExtGlob"
        assert extglob.op == "?("
        assert extglob.pattern.value == "txt|md"

    def test_bang_extended_glob(self):
        """Parse ls *.!(txt|md) and verify ExtGlob with op='!('."""
        tree = parse_ast("ls *.!(txt|md)")
        cmd = tree.stmts[0].cmd
        extglob = cmd.args[1].parts[1]
        assert extglob.type == "ExtGlob"
        assert extglob.op == "!("
        assert extglob.pattern.value == "txt|md"

    def test_star_extended_glob(self):
        """Parse ls *.*(txt|md) and verify ExtGlob with op='*(.'"""
        tree = parse_ast("ls *.*(txt|md)")
        cmd = tree.stmts[0].cmd
        extglob = cmd.args[1].parts[1]
        assert extglob.type == "ExtGlob"
        assert extglob.op == "*("
        assert extglob.pattern.value == "txt|md"

    def test_extglob_with_multiple_patterns(self):
        """Parse ls *.@(txt|md|json|yaml) with four patterns."""
        tree = parse_ast("ls *.@(txt|md|json|yaml)")
        cmd = tree.stmts[0].cmd
        extglob = cmd.args[1].parts[1]
        assert extglob.type == "ExtGlob"
        assert extglob.pattern.value == "txt|md|json|yaml"

    def test_extglob_position_info(self):
        """Verify ExtGlob nodes have position information from shfmt."""
        tree = parse_ast("ls *.@(txt|md)")
        cmd = tree.stmts[0].cmd
        extglob = cmd.args[1].parts[1]
        assert extglob.type == "ExtGlob"
        assert extglob.pos is not None
        assert extglob.end is not None
        assert extglob.op_pos is not None
        assert isinstance(extglob.pos.offset, int)
        assert isinstance(extglob.end.offset, int)

    def test_extglob_in_double_quotes(self):
        """Parse echo \"@(cmd)\" - extglob in double quotes is literal text."""
        # Note: bash does NOT expand @() inside double quotes without extglob
        tree = parse_ast('echo "@(txt|md)"')
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == "DblQuoted"
        assert cmd.args[1].parts[0].parts[0].type == "Lit"
        assert cmd.args[1].parts[0].parts[0].value == "@(txt|md)"

    def test_extglob_combined_with_procsubst(self):
        """Parse complex expression combining ExtGlob with other features."""
        tree = parse_ast("ls *.@(txt|md) | grep -i foo")
        assert tree.stmts[0].cmd.type == "BinaryCmd"
        assert tree.stmts[0].cmd.op == "|"
        # Left side should have ExtGlob
        left_arg = tree.stmts[0].cmd.left.args[1].parts[1]
        assert left_arg.type == "ExtGlob"
        assert left_arg.pattern.value == "txt|md"

    def test_extglob_imported_in_module(self):
        """Verify that ExtGlob is imported in the lovely_bash_permissions module."""
        from lovely_bash_permissions import ExtGlob

        assert ExtGlob is not None


class TestBlockNodes:
    """Tests for the Block node type (Step 10 of node coverage).

    Blocks are curly-brace groups: { cmd1; cmd2; }. They execute
    commands in the current shell environment (unlike subshells with
    parentheses which spawn a new shell).
    """

    def test_simple_block(self):
        """Parse { echo 'a'; echo 'b'; } and verify Block node."""
        tree = parse_ast("{ echo 'a'; echo 'b'; }")
        cmd = tree.stmts[0].cmd
        assert cmd.type == "Block"
        assert isinstance(cmd, Block)
        assert len(cmd.stmts) == 2
        # First statement: echo 'a'
        assert cmd.stmts[0].cmd.args[0].parts[0].value == "echo"
        assert cmd.stmts[0].cmd.args[1].parts[0].type == "SglQuoted"
        assert cmd.stmts[0].cmd.args[1].parts[0].value == "a"
        # Second statement: echo 'b'
        assert cmd.stmts[1].cmd.args[0].parts[0].value == "echo"
        assert cmd.stmts[1].cmd.args[1].parts[0].type == "SglQuoted"
        assert cmd.stmts[1].cmd.args[1].parts[0].value == "b"

    def test_block_with_true_false(self):
        """Parse { true; false; } and verify Block with boolean commands."""
        tree = parse_ast("{ true; false; }")
        cmd = tree.stmts[0].cmd
        assert cmd.type == "Block"
        assert len(cmd.stmts) == 2
        assert cmd.stmts[0].cmd.args[0].parts[0].value == "true"
        assert cmd.stmts[1].cmd.args[0].parts[0].value == "false"

    def test_nested_blocks(self):
        """Parse { { echo 'inner'; }; } and verify nested Block nodes."""
        tree = parse_ast("{ { echo 'inner'; }; }")
        outer = tree.stmts[0].cmd
        assert outer.type == "Block"
        assert len(outer.stmts) == 1
        inner = outer.stmts[0].cmd
        assert inner.type == "Block"
        assert len(inner.stmts) == 1
        assert inner.stmts[0].cmd.args[0].parts[0].value == "echo"
        assert inner.stmts[0].cmd.args[1].parts[0].value == "inner"

    def test_block_with_subshell(self):
        """Parse { (echo 'sub'); } and verify Block containing Subshell."""
        tree = parse_ast("{ (echo 'sub'); }")
        cmd = tree.stmts[0].cmd
        assert cmd.type == "Block"
        inner = cmd.stmts[0].cmd
        assert inner.type == "Subshell"
        assert inner.stmts[0].cmd.args[0].parts[0].value == "echo"

    def test_block_with_variables(self):
        """Parse { echo $HOME; } and verify Block with variable expansion."""
        tree = parse_ast("{ echo $HOME; }")
        cmd = tree.stmts[0].cmd
        assert cmd.type == "Block"
        assert cmd.stmts[0].cmd.args[1].parts[0].type == "ParamExp"
        assert cmd.stmts[0].cmd.args[1].parts[0].param == "HOME"

    def test_block_position_info(self):
        """Verify Block nodes have position information from shfmt."""
        tree = parse_ast("{ echo 'a'; }")
        cmd = tree.stmts[0].cmd
        assert cmd.type == "Block"
        assert cmd.pos is not None
        assert cmd.end is not None
        assert cmd.left_pos is not None
        assert cmd.right_pos is not None
        assert isinstance(cmd.pos.offset, int)
        assert isinstance(cmd.end.offset, int)
        # Lbrace should be before rbrace
        assert cmd.left_pos.offset < cmd.right_pos.offset

    def test_empty_block_with_commands(self):
        """Parse a block with multiple different command types."""
        tree = parse_ast("{ ls -la; cat file.txt; grep pattern file.txt; }")
        cmd = tree.stmts[0].cmd
        assert cmd.type == "Block"
        assert len(cmd.stmts) == 3
        assert cmd.stmts[0].cmd.args[0].parts[0].value == "ls"
        assert cmd.stmts[1].cmd.args[0].parts[0].value == "cat"
        assert cmd.stmts[2].cmd.args[0].parts[0].value == "grep"

    def test_block_pipe_inside(self):
        """Parse { ls | grep txt; } and verify pipe inside Block."""
        tree = parse_ast("{ ls | grep txt; }")
        cmd = tree.stmts[0].cmd
        assert cmd.type == "Block"
        inner = cmd.stmts[0].cmd
        assert inner.type == "BinaryCmd"
        assert inner.op == "|"
        assert inner.left.args[0].parts[0].value == "ls"
        assert inner.right.args[0].parts[0].value == "grep"
        assert inner.right.args[1].parts[0].value == "txt"

    def test_block_andcmd_inside(self):
        """Parse { test -f file && cat file; } with BinaryCmd(op='&&') inside Block.

        shfmt represents && as BinaryCmd with Op='&&', not AndCmd.
        AndCmd is used at statement level (across semicolons), not within blocks.
        """
        tree = parse_ast("{ test -f file && cat file; }")
        cmd = tree.stmts[0].cmd
        assert cmd.type == "Block"
        inner = cmd.stmts[0].cmd
        assert inner.type == "BinaryCmd"
        assert inner.op == "&&"
        assert inner.left.args[0].parts[0].value == "test"
        assert inner.right.args[0].parts[0].value == "cat"

    def test_block_with_redirect(self):
        """Parse { echo hello > output.txt; } with redirection inside Block."""
        tree = parse_ast("{ echo hello > output.txt; }")
        cmd = tree.stmts[0].cmd
        assert cmd.type == "Block"
        stmt = cmd.stmts[0]
        assert stmt.cmd.args[0].parts[0].value == "echo"
        assert len(stmt.redirs) == 1
        assert stmt.redirs[0].op == ">"
        assert stmt.redirs[0].word.parts[0].value == "output.txt"

    def test_block_cmdsubst_inside(self):
        """Parse { echo $(date); } with CmdSubst inside Block."""
        tree = parse_ast("{ echo $(date); }")
        cmd = tree.stmts[0].cmd
        assert cmd.type == "Block"
        inner_stmt = cmd.stmts[0]
        assert inner_stmt.cmd.args[1].parts[0].type == "CmdSubst"
        assert (
            inner_stmt.cmd.args[1].parts[0].stmts[0].cmd.args[0].parts[0].value
            == "date"
        )

    def test_block_if_inside(self):
        """Parse { if true; then echo 'yes'; fi; } with if statement inside Block."""
        tree = parse_ast("{ if true; then echo 'yes'; fi; }")
        cmd = tree.stmts[0].cmd
        assert cmd.type == "Block"
        inner = cmd.stmts[0].cmd
        assert inner.type == "IfClause"
        assert len(inner.then_stmts) == 1
        assert inner.then_stmts[0].cmd.args[0].parts[0].value == "echo"

    def test_block_with_arithmetic(self):
        """Parse { echo $((1 + 2)); } with ArithmExp inside Block."""
        tree = parse_ast("{ echo $((1 + 2)); }")
        cmd = tree.stmts[0].cmd
        assert cmd.type == "Block"
        inner = cmd.stmts[0].cmd
        assert inner.args[1].parts[0].type == "ArithmExp"
        inner_arith = inner.args[1].parts[0].x
        assert inner_arith.type == "BinaryArithm"
        assert inner_arith.op == "+"

    def test_deeply_nested_blocks(self):
        """Parse { { { echo 'deep'; }; }; } with three levels of nesting."""
        tree = parse_ast("{ { { echo 'deep'; }; }; }")
        outer = tree.stmts[0].cmd
        assert outer.type == "Block"
        mid = outer.stmts[0].cmd
        assert mid.type == "Block"
        inner = mid.stmts[0].cmd
        assert inner.type == "Block"
        assert inner.stmts[0].cmd.args[0].parts[0].value == "echo"
        assert inner.stmts[0].cmd.args[1].parts[0].value == "deep"

    def test_block_imported_in_module(self):
        """Verify that Block is imported in the lovely_bash_permissions module."""
        from lovely_bash_permissions import Block

        assert Block is not None


class TestFuncDeclNodes:
    """Tests for the FuncDecl node type (Step 11 of node coverage).

    Bash function declarations: name() { body }, function name { body },
    function name() { body }. The function body is always a Block node.
    """

    def test_func_decl_with_parens(self):
        """Parse hello() { echo 'hi'; } and verify FuncDecl node."""
        tree = parse_ast("hello() { echo 'hi'; }")
        cmd = tree.stmts[0].cmd
        assert cmd.type == "FuncDecl"
        assert isinstance(cmd, FuncDecl)
        # No 'function' keyword used
        assert cmd.rsrv_word is False
        # Parens used
        assert cmd.parens is True
        # Function name
        assert cmd.name is not None
        assert cmd.name.type == "Lit"
        assert cmd.name.value == "hello"
        # Body is a Block with one statement
        assert cmd.body is not None
        assert cmd.body.type == "Block"
        assert len(cmd.body.stmts) == 1
        body_stmt = cmd.body.stmts[0].cmd
        assert body_stmt.args[0].parts[0].value == "echo"
        assert body_stmt.args[1].parts[0].value == "hi"

    def test_func_decl_function_keyword_no_parens(self):
        """Parse function hello { echo 'hi'; } (POSIX style, no parens)."""
        tree = parse_ast("function hello { echo 'hi'; }")
        cmd = tree.stmts[0].cmd
        assert cmd.type == "FuncDecl"
        # Function keyword used
        assert cmd.rsrv_word is True
        # No parens used in this style
        assert cmd.parens is False
        # Function name
        assert cmd.name is not None
        assert cmd.name.type == "Lit"
        assert cmd.name.value == "hello"
        # Body is a Block with one statement
        assert cmd.body is not None
        assert cmd.body.type == "Block"
        assert len(cmd.body.stmts) == 1
        body_stmt = cmd.body.stmts[0].cmd
        assert body_stmt.args[0].parts[0].value == "echo"
        assert body_stmt.args[1].parts[0].value == "hi"

    def test_func_decl_function_keyword_with_parens(self):
        """Parse function hello() { echo 'hi'; } (function keyword + parens)."""
        tree = parse_ast("function hello() { echo 'hi'; }")
        cmd = tree.stmts[0].cmd
        assert cmd.type == "FuncDecl"
        # Function keyword used
        assert cmd.rsrv_word is True
        # Parens also used
        assert cmd.parens is True
        # Function name
        assert cmd.name is not None
        assert cmd.name.type == "Lit"
        assert cmd.name.value == "hello"
        # Body is a Block with one statement
        assert cmd.body is not None
        assert cmd.body.type == "Block"
        assert len(cmd.body.stmts) == 1
        body_stmt = cmd.body.stmts[0].cmd
        assert body_stmt.args[0].parts[0].value == "echo"
        assert body_stmt.args[1].parts[0].value == "hi"

    def test_func_decl_multiple_statements(self):
        """Parse a function with multiple statements in the body."""
        tree = parse_ast("greet() { echo 'hello'; echo 'world'; }")
        cmd = tree.stmts[0].cmd
        assert cmd.type == "FuncDecl"
        assert cmd.name.value == "greet"
        # Body should have two statements
        assert cmd.body.type == "Block"
        assert len(cmd.body.stmts) == 2
        first = cmd.body.stmts[0].cmd
        second = cmd.body.stmts[1].cmd
        assert first.args[0].parts[0].value == "echo"
        assert first.args[1].parts[0].value == "hello"
        assert second.args[0].parts[0].value == "echo"
        assert second.args[1].parts[0].value == "world"

    def test_func_decl_with_args(self):
        """Parse a function that uses parameters ($1, $2)."""
        tree = parse_ast("say() { echo $1 $2; }")
        cmd = tree.stmts[0].cmd
        assert cmd.type == "FuncDecl"
        assert cmd.name.value == "say"
        # Body should have one statement
        assert cmd.body.type == "Block"
        assert len(cmd.body.stmts) == 1
        body_stmt = cmd.body.stmts[0].cmd
        assert body_stmt.args[0].parts[0].value == "echo"
        # $1 is ParamExp
        assert body_stmt.args[1].parts[0].type == "ParamExp"
        assert body_stmt.args[1].parts[0].param == "1"
        # $2 is ParamExp
        assert body_stmt.args[2].parts[0].type == "ParamExp"
        assert body_stmt.args[2].parts[0].param == "2"

    def test_func_decl_with_variables(self):
        """Parse a function that references external variables."""
        tree = parse_ast("show() { echo $HOME; }")
        cmd = tree.stmts[0].cmd
        assert cmd.type == "FuncDecl"
        assert cmd.name.value == "show"
        # Body should have one statement
        assert cmd.body.type == "Block"
        assert len(cmd.body.stmts) == 1
        body_stmt = cmd.body.stmts[0].cmd
        assert body_stmt.args[0].parts[0].value == "echo"
        # $HOME is ParamExp
        assert body_stmt.args[1].parts[0].type == "ParamExp"
        assert body_stmt.args[1].parts[0].param == "HOME"

    def test_func_decl_cmdsubst_inside(self):
        """Parse a function with command substitution inside."""
        tree = parse_ast("now() { echo $(date); }")
        cmd = tree.stmts[0].cmd
        assert cmd.type == "FuncDecl"
        assert cmd.name.value == "now"
        # Body should have one statement
        assert cmd.body.type == "Block"
        assert len(cmd.body.stmts) == 1
        body_stmt = cmd.body.stmts[0].cmd
        assert body_stmt.args[0].parts[0].value == "echo"
        # Argument should be CmdSubst
        assert body_stmt.args[1].parts[0].type == "CmdSubst"
        # Nested statement in CmdSubst should be CallExpr with 'date'
        subst_stmt = body_stmt.args[1].parts[0].stmts[0].cmd
        assert subst_stmt.args[0].parts[0].value == "date"

    def test_func_decl_complex_body(self):
        """Parse a function with a complex body (pipe, redirect, if, etc.)."""
        tree = parse_ast("""process() {
    if [ -f "$1" ]; then
        cat "$1" | sort | uniq > "$2"
    fi
}""")
        cmd = tree.stmts[0].cmd
        assert cmd.type == "FuncDecl"
        assert cmd.name.value == "process"
        # Body should be a Block with one statement
        assert cmd.body.type == "Block"
        assert len(cmd.body.stmts) == 1
        # The inner statement should be IfClause
        inner = cmd.body.stmts[0].cmd
        assert inner.type == "IfClause"
        assert len(inner.cond_stmts) == 1
        assert len(inner.then_stmts) == 1
        # The body of the if should be a BinaryCmd (pipe chain)
        then_stmt = inner.then_stmts[0]
        assert then_stmt.cmd.type == "BinaryCmd"
        # The structure is: BinaryCmd(op="|", x=BinaryCmd(cat|sort), y=CallExpr(uniq > file))
        # Nested BinaryCmd: cat "$1" | sort
        left = then_stmt.cmd.left
        assert left.type == "BinaryCmd"
        assert left.op == "|"
        # left.left should be CallExpr for cat "$1"
        assert left.left.type == "CallExpr"
        assert left.left.args[0].parts[0].value == "cat"
        # "$1" is a DblQuoted containing a ParamExp for $1
        assert left.left.args[1].parts[0].type == "DblQuoted"
        inner_param = left.left.args[1].parts[0].parts[0]
        assert inner_param.type == "ParamExp"
        assert inner_param.param == "1"
        # left.right should be CallExpr for sort
        assert left.right.type == "CallExpr"
        assert left.right.args[0].parts[0].value == "sort"
        # The outer y should be CallExpr for uniq with redirection
        y = then_stmt.cmd.right
        assert y.type == "CallExpr"
        assert y.args[0].parts[0].value == "uniq"
        # Redirection on the y side: > "$2"
        assert len(then_stmt.redirs) == 1
        assert then_stmt.redirs[0].op == ">"
        redir_part = then_stmt.redirs[0].word.parts[0]
        # "$2" is a DblQuoted containing a ParamExp for $2
        assert redir_part.type == "DblQuoted"
        inner_redir_param = redir_part.parts[0]
        assert inner_redir_param.type == "ParamExp"
        assert inner_redir_param.param == "2"

    def test_func_decl_position_info(self):
        """Verify FuncDecl nodes have position information from shfmt."""
        tree = parse_ast("hello() { echo 'hi'; }")
        cmd = tree.stmts[0].cmd
        assert cmd.type == "FuncDecl"
        assert cmd.pos is not None
        assert cmd.end is not None
        assert isinstance(cmd.pos.offset, int)
        assert isinstance(cmd.end.offset, int)
        # Body should also have position info
        assert cmd.body is not None
        assert cmd.body.pos is not None
        assert cmd.body.end is not None
        # Body should start after function declaration
        assert cmd.body.pos.offset > cmd.pos.offset

    def test_func_decl_nested_calls(self):
        """Parse a function that calls other commands."""
        tree = parse_ast("setup() { mkdir -p out; cd out; }")
        cmd = tree.stmts[0].cmd
        assert cmd.type == "FuncDecl"
        assert cmd.name.value == "setup"
        # Body should have two statements
        assert cmd.body.type == "Block"
        assert len(cmd.body.stmts) == 2
        # First: mkdir -p out
        first = cmd.body.stmts[0].cmd
        assert first.args[0].parts[0].value == "mkdir"
        assert first.args[1].parts[0].value == "-p"
        assert first.args[2].parts[0].value == "out"
        # Second: cd out
        second = cmd.body.stmts[1].cmd
        assert second.args[0].parts[0].value == "cd"
        assert second.args[1].parts[0].value == "out"

    def test_func_decl_with_double_quotes(self):
        """Parse a function using double-quoted strings."""
        tree = parse_ast('hello() { echo "hello world"; }')
        cmd = tree.stmts[0].cmd
        assert cmd.type == "FuncDecl"
        assert cmd.name.value == "hello"
        # Body should have one statement
        assert cmd.body.type == "Block"
        assert len(cmd.body.stmts) == 1
        body_stmt = cmd.body.stmts[0].cmd
        assert body_stmt.args[0].parts[0].value == "echo"
        # Argument should be DblQuoted
        assert body_stmt.args[1].parts[0].type == "DblQuoted"
        assert body_stmt.args[1].parts[0].value == "hello world"

    def test_func_decl_empty_body(self):
        """Parse a function with empty body (noop using `:` builtin)."""
        # bash requires a statement in the function body
        # `:` is the no-op builtin, so noop() { :; } is an empty-function equivalent
        tree = parse_ast("noop() { :; }")
        cmd = tree.stmts[0].cmd
        assert cmd.type == "FuncDecl"
        assert cmd.name.value == "noop"
        # Body should be a Block with one statement (the `:` no-op)
        assert cmd.body.type == "Block"
        assert len(cmd.body.stmts) == 1
        assert cmd.body.stmts[0].cmd.args[0].parts[0].value == ":"

    def test_func_decl_imported_in_module(self):
        """Verify that FuncDecl is imported in the lovely_bash_permissions module."""
        from lovely_bash_permissions import FuncDecl

        assert FuncDecl is not None
