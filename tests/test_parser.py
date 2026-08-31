"""
Comprehensive tests for the lovely-bash-permissions parser.
"""

import pytest
from lovely_bash_permissions import (
    parse_ast, get_commands, get_arguments, has_variable, get_redirections
)


class TestSimpleCommands:
    """Test simple command parsing."""

    def test_single_command(self):
        tree = parse_ast('ls')
        assert get_commands(tree) == ['ls']
        assert get_arguments(tree) == [[]]

    def test_command_with_flags(self):
        tree = parse_ast('ls -la')
        assert get_commands(tree) == ['ls']
        assert get_arguments(tree) == [['-la']]

    def test_command_with_multiple_args(self):
        tree = parse_ast('cp file1.txt file2.txt')
        assert get_commands(tree) == ['cp']
        assert get_arguments(tree) == [['file1.txt', 'file2.txt']]

    def test_echo_command(self):
        tree = parse_ast('echo hello')
        assert get_commands(tree) == ['echo']
        assert get_arguments(tree) == [['hello']]


class TestPipes:
    """Test pipe parsing."""

    def test_single_pipe(self):
        tree = parse_ast('cat file.txt | grep pattern')
        assert get_commands(tree) == ['cat', 'grep']
        assert get_arguments(tree) == [['file.txt'], ['pattern']]

    def test_multiple_pipes(self):
        tree = parse_ast('cat file.txt | grep pattern | sort | uniq')
        assert get_commands(tree) == ['cat', 'grep', 'sort', 'uniq']
        assert get_arguments(tree) == [['file.txt'], ['pattern'], [], []]

    def test_pipe_with_flags(self):
        tree = parse_ast('ls -la | grep -i txt')
        assert get_commands(tree) == ['ls', 'grep']
        assert get_arguments(tree) == [['-la'], ['-i', 'txt']]


class TestRedirections:
    """Test redirection parsing."""

    def test_output_redirect(self):
        tree = parse_ast('cat file.txt > output.txt')
        assert get_commands(tree) == ['cat']
        assert get_arguments(tree) == [['file.txt']]
        redirs = get_redirections(tree)
        assert len(redirs) == 1
        assert redirs[0]['op'] == '>'
        assert redirs[0]['target'] == 'output.txt'

    def test_append_redirect(self):
        tree = parse_ast('cat file.txt >> output.txt')
        redirs = get_redirections(tree)
        assert len(redirs) == 1
        assert redirs[0]['op'] == '>>'

    def test_input_redirect(self):
        tree = parse_ast('sort < input.txt')
        redirs = get_redirections(tree)
        assert len(redirs) == 1
        assert redirs[0]['op'] == '<'

    def test_pipe_with_redirect(self):
        tree = parse_ast('ls -la | grep txt > output.txt')
        assert get_commands(tree) == ['ls', 'grep']
        assert get_arguments(tree) == [['-la'], ['txt']]
        redirs = get_redirections(tree)
        assert len(redirs) == 1
        assert redirs[0]['op'] == '>'
        assert redirs[0]['target'] == 'output.txt'


class TestVariables:
    """Test variable detection."""

    def test_no_variables(self):
        tree = parse_ast('ls -la')
        assert not has_variable(tree)

    def test_simple_variable(self):
        tree = parse_ast('echo $HOME')
        assert has_variable(tree)

    def test_path_variable(self):
        tree = parse_ast('cat /path/to/file')
        assert not has_variable(tree)

    def test_multiple_variables(self):
        tree = parse_ast('echo $HOME $USER')
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
        tree = parse_ast('cat data.csv | grep pattern | awk \"{print $1}\" | sort -u > results.txt')
        commands = get_commands(tree)
        assert 'cat' in commands
        assert 'grep' in commands
        assert 'awk' in commands
        assert 'sort' in commands
        # awk's argument has inner structure (DblQuoted with parts)
        # shfmt evaluates variables within double-quoted strings
        args = get_arguments(tree)
        assert len(args) == 4
        assert args[0] == ['data.csv']
        assert args[1] == ['pattern']
        # args[2] is the awk program - has inner structure, not a simple value
        assert args[3] == ['-u']
        redirs = get_redirections(tree)
        assert len(redirs) == 1
        assert redirs[0]['target'] == 'results.txt'

    def test_command_with_quoted_args(self):
        tree = parse_ast('find / -name "*.txt" -type f')
        assert get_commands(tree) == ['find']
        args = get_arguments(tree)
        assert len(args) == 1
        assert args[0][0] == '/'
        assert args[0][1] == '-name'
        assert args[0][3] == '-type'
        assert args[0][4] == 'f'

    def test_long_command(self):
        tree = parse_ast('tar -czvf archive.tar.gz $(find . -name "*.py" -not -path "./.venv/*" -not -path "./tests/*")')
        assert get_commands(tree) == ['tar']
        assert has_variable(tree)


class TestEdgeCases:
    """Test edge cases."""

    def test_empty_command(self):
        with pytest.raises(Exception):
            parse_ast('')

    def test_whitespace_only(self):
        with pytest.raises(Exception):
            parse_ast('   ')

    def test_single_quote(self):
        tree = parse_ast("echo 'hello world'")
        assert get_commands(tree) == ['echo']

    def test_double_quote(self):
        tree = parse_ast('echo "hello world"')
        assert get_commands(tree) == ['echo']


class TestASTStructure:
    """Test AST structure and types."""

    def test_file_node_type(self):
        tree = parse_ast('ls')
        assert tree.type == 'File'

    def test_stmt_count(self):
        tree = parse_ast('ls')
        assert len(tree.stmts) == 1

    def test_multiple_stmts(self):
        tree = parse_ast('ls\ngrep pattern file.txt')
        assert len(tree.stmts) == 2
        assert get_commands(tree) == ['ls', 'grep']

    def test_call_expr_node(self):
        tree = parse_ast('ls')
        cmd = tree.stmts[0].cmd
        assert cmd.type == 'CallExpr'

    def test_binary_cmd_node(self):
        tree = parse_ast('ls | grep txt')
        cmd = tree.stmts[0].cmd
        assert cmd.type == 'BinaryCmd'
        assert cmd.op == '|'


class TestLitNodes:
    """Tests for the Lit node type (Step 1 of node coverage)."""

    def test_simple_literal_value(self):
        """Parse a simple command and find the Lit node with its value."""
        tree = parse_ast('ls')
        cmd = tree.stmts[0].cmd
        assert cmd.type == 'CallExpr'
        # First arg is the command name as a Word containing a Lit part
        assert len(cmd.args) == 1
        assert cmd.args[0].type == 'Word'
        assert len(cmd.args[0].parts) == 1
        assert cmd.args[0].parts[0].type == 'Lit'
        assert cmd.args[0].parts[0].value == 'ls'

    def test_literal_argument(self):
        """Parse echo hello and verify the Lit argument value."""
        tree = parse_ast('echo hello')
        cmd = tree.stmts[0].cmd
        assert cmd.type == 'CallExpr'
        # Second arg is the argument
        assert cmd.args[1].parts[0].type == 'Lit'
        assert cmd.args[1].parts[0].value == 'hello'

    def test_literal_file_name(self):
        """Parse cat file.txt and verify the Lit file argument."""
        tree = parse_ast('cat file.txt')
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == 'Lit'
        assert cmd.args[1].parts[0].value == 'file.txt'

    def test_literal_flag(self):
        """Parse ls -la and verify the Lit flag argument."""
        tree = parse_ast('ls -la')
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == 'Lit'
        assert cmd.args[1].parts[0].value == '-la'

    def test_multiple_literal_arguments(self):
        """Parse cp with multiple literal arguments."""
        tree = parse_ast('cp file1.txt file2.txt')
        cmd = tree.stmts[0].cmd
        assert len(cmd.args) == 3
        assert cmd.args[0].parts[0].type == 'Lit'
        assert cmd.args[0].parts[0].value == 'cp'
        assert cmd.args[1].parts[0].type == 'Lit'
        assert cmd.args[1].parts[0].value == 'file1.txt'
        assert cmd.args[2].parts[0].type == 'Lit'
        assert cmd.args[2].parts[0].value == 'file2.txt'

    def test_literal_in_pipe(self):
        """Parse a piped command and verify both commands have Lit parts."""
        tree = parse_ast('cat file.txt | grep pattern')
        cmd = tree.stmts[0].cmd
        assert cmd.type == 'BinaryCmd'
        # Left side: cat file.txt
        assert cmd.x.args[0].parts[0].type == 'Lit'
        assert cmd.x.args[0].parts[0].value == 'cat'
        assert cmd.x.args[1].parts[0].type == 'Lit'
        assert cmd.x.args[1].parts[0].value == 'file.txt'
        # Right side: grep pattern
        assert cmd.y.args[0].parts[0].type == 'Lit'
        assert cmd.y.args[0].parts[0].value == 'grep'
        assert cmd.y.args[1].parts[0].type == 'Lit'
        assert cmd.y.args[1].parts[0].value == 'pattern'

    def test_literal_with_special_chars(self):
        """Parse a command with special characters in a literal."""
        tree = parse_ast('echo hello-world_123')
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == 'Lit'
        assert cmd.args[1].parts[0].value == 'hello-world_123'

    def test_literal_with_slash(self):
        """Parse a command with a file path (slashes are allowed in literals)."""
        tree = parse_ast('cat /path/to/file.txt')
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == 'Lit'
        assert cmd.args[1].parts[0].value == '/path/to/file.txt'

    def test_no_literal_with_variable(self):
        """Parse echo $HOME - variable is not a Lit node."""
        tree = parse_ast('echo $HOME')
        cmd = tree.stmts[0].cmd
        # The argument should be a ParamExp (short-form $var), not a Lit
        assert cmd.args[1].parts[0].type == 'ParamExp'

    def test_no_literal_with_command_substitution(self):
        """Parse echo $(date) - command substitution is not a Lit node."""
        tree = parse_ast('echo $(date)')
        cmd = tree.stmts[0].cmd
        # The argument should be a CmdSubst, not a Lit
        assert cmd.args[1].parts[0].type == 'CmdSubst'

    def test_no_literal_with_quoted_string(self):
        """Parse echo 'quoted' - quoted strings are SglQuoted, not Lit."""
        tree = parse_ast("echo 'quoted'")
        cmd = tree.stmts[0].cmd
        # The argument should be a SglQuoted, not a Lit
        assert cmd.args[1].parts[0].type == 'SglQuoted'

    def test_literal_in_redirect(self):
        """Parse command with output redirect and verify Lit in redirect target."""
        tree = parse_ast('echo hello > output.txt')
        cmd = tree.stmts[0].cmd
        # The redirect target should contain a Lit with the filename
        assert tree.stmts[0].redirs[0].word.parts[0].type == 'Lit'
        assert tree.stmts[0].redirs[0].word.parts[0].value == 'output.txt'

    def test_literal_number(self):
        """Parse a command with a numeric literal."""
        tree = parse_ast('sleep 5')
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == 'Lit'
        assert cmd.args[1].parts[0].value == '5'

    def test_literal_empty_word(self):
        """Parse a command and check that command name is a Lit node."""
        tree = parse_ast('true')
        cmd = tree.stmts[0].cmd
        assert cmd.args[0].parts[0].type == 'Lit'
        assert cmd.args[0].parts[0].value == 'true'

    def test_literal_multiline(self):
        """Parse multiple commands across lines and check Lit in both."""
        tree = parse_ast('echo a\necho b')
        # First command
        assert tree.stmts[0].cmd.args[1].parts[0].type == 'Lit'
        assert tree.stmts[0].cmd.args[1].parts[0].value == 'a'
        # Second command
        assert tree.stmts[1].cmd.args[1].parts[0].type == 'Lit'
        assert tree.stmts[1].cmd.args[1].parts[0].value == 'b'

    def test_literal_in_subshell(self):
        """Parse a subshell with a command and verify Lit inside."""
        tree = parse_ast('(echo hello)')
        cmd = tree.stmts[0].cmd
        assert cmd.type == 'Subshell'
        assert cmd.stmts[0].cmd.args[1].parts[0].type == 'Lit'
        assert cmd.stmts[0].cmd.args[1].parts[0].value == 'hello'

    def test_literal_position_info(self):
        """Verify that Lit nodes have position information from shfmt."""
        tree = parse_ast('ls -la')
        cmd = tree.stmts[0].cmd
        # Verify that lit parts have proper pos/end values
        for arg in cmd.args:
            for part in arg.parts:
                if part.type == 'Lit':
                    assert part.pos is not None
                    assert part.end is not None
                    assert isinstance(part.pos.offset, int)
                    assert isinstance(part.end.offset, int)

    def test_lit_imported_in_module(self):
        """Verify that Lit is imported in the lovely_bash_permissions module."""
        from lovely_bash_permissions import Lit
        assert Lit is not None
