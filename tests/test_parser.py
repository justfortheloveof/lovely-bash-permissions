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
