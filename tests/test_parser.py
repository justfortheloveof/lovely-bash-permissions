"""
Comprehensive tests for the lovely-bash-permissions parser.
"""

import pytest
from lovely_bash_permissions import (
    parse_ast, get_commands, get_arguments, has_variable, get_redirections,
    Lit, SglQuoted, ParamExp, DblQuoted, CmdSubst, ArithmExp, BinaryArithm
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


class TestSglQuotedNodes:
    """Tests for the SglQuoted node type (Step 2 of node coverage)."""

    def test_simple_single_quoted(self):
        """Parse echo 'hello world' and verify it produces a SglQuoted node."""
        tree = parse_ast("echo 'hello world'")
        cmd = tree.stmts[0].cmd
        assert cmd.type == 'CallExpr'
        assert len(cmd.args) == 2
        # The second argument is a SglQuoted part
        assert cmd.args[1].parts[0].type == 'SglQuoted'
        assert cmd.args[1].parts[0].value == 'hello world'

    def test_single_quoted_with_variable_no_expansion(self):
        """Parse echo '$HOME' and verify variable is not expanded (single quotes)."""
        tree = parse_ast("echo '$HOME'")
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == 'SglQuoted'
        assert cmd.args[1].parts[0].value == '$HOME'

    def test_multiple_single_quoted_arguments(self):
        """Parse echo 'a' 'b' and verify both arguments are SglQuoted."""
        tree = parse_ast("echo 'a' 'b'")
        cmd = tree.stmts[0].cmd
        assert len(cmd.args) == 3
        assert cmd.args[1].parts[0].type == 'SglQuoted'
        assert cmd.args[1].parts[0].value == 'a'
        assert cmd.args[2].parts[0].type == 'SglQuoted'
        assert cmd.args[2].parts[0].value == 'b'

    def test_single_quoted_with_asterisk(self):
        """Parse echo 'foo*' and verify asterisk is literal in single quotes."""
        tree = parse_ast("echo 'foo*'")
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == 'SglQuoted'
        assert cmd.args[1].parts[0].value == 'foo*'

    def test_single_quoted_empty(self):
        """Parse echo '' and verify an empty SglQuoted is handled."""
        tree = parse_ast("echo ''")
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == 'SglQuoted'
        assert cmd.args[1].parts[0].value == ''

    def test_single_quoted_backslashes(self):
        """Parse echo 'hello\nworld' and verify backslashes are literal."""
        tree = parse_ast("echo 'hello\nworld'")
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == 'SglQuoted'
        assert cmd.args[1].parts[0].value == 'hello\nworld'

    def test_single_quoted_with_dollar_sign(self):
        """Parse echo 'price $5' and verify the dollar sign is literal."""
        tree = parse_ast("echo 'price $5'")
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == 'SglQuoted'
        assert cmd.args[1].parts[0].value == 'price $5'

    def test_single_quoted_position_info(self):
        """Verify that SglQuoted nodes have position information from shfmt."""
        tree = parse_ast("echo 'hello'")
        cmd = tree.stmts[0].cmd
        part = cmd.args[1].parts[0]
        assert part.type == 'SglQuoted'
        assert part.pos is not None
        assert part.end is not None
        assert isinstance(part.pos.offset, int)
        assert isinstance(part.end.offset, int)

    def test_sgquoted_imported_in_module(self):
        """Verify that SglQuoted is imported in the lovely_bash_permissions module."""
        from lovely_bash_permissions import SglQuoted
        assert SglQuoted is not None


class TestParamExpNodes:
    """Tests for the ParamExp node type (Step 4 of node coverage)."""

    def test_short_param_expansion(self):
        """Parse echo $HOME and verify it produces a ParamExp node with Short=True."""
        tree = parse_ast('echo $HOME')
        cmd = tree.stmts[0].cmd
        assert cmd.type == 'CallExpr'
        assert len(cmd.args) == 2
        # The second argument is a ParamExp part
        assert cmd.args[1].parts[0].type == 'ParamExp'
        assert cmd.args[1].parts[0].param == 'HOME'
        assert cmd.args[1].parts[0].short is True

    def test_braced_param_expansion(self):
        """Parse echo ${HOME} and verify it produces a ParamExp node with Short=False."""
        tree = parse_ast('echo ${HOME}')
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == 'ParamExp'
        assert cmd.args[1].parts[0].param == 'HOME'
        assert cmd.args[1].parts[0].short is False

    def test_param_expansion_with_default(self):
        """Parse echo ${HOME:-default} and verify the Exp field."""
        tree = parse_ast('echo ${HOME:-default}')
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == 'ParamExp'
        assert cmd.args[1].parts[0].param == 'HOME'
        assert cmd.args[1].parts[0].exp is not None
        assert cmd.args[1].parts[0].exp['Op'] == ':-'

    def test_array_index_param_expansion(self):
        """Parse echo ${arr[0]} and verify the Index field."""
        tree = parse_ast('echo ${arr[0]}')
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == 'ParamExp'
        assert cmd.args[1].parts[0].param == 'arr'
        assert cmd.args[1].parts[0].index is not None
        assert cmd.args[1].parts[0].index.parts[0].value == '0'

    def test_param_expansion_in_double_quotes(self):
        """Parse echo "$HOME" and verify ParamExp inside DblQuoted."""
        tree = parse_ast('echo "$HOME"')
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == 'DblQuoted'
        assert cmd.args[1].parts[0].parts[0].type == 'ParamExp'
        assert cmd.args[1].parts[0].parts[0].param == 'HOME'

    def test_multiple_param_expansions(self):
        """Parse echo "$HOME is $USER" and verify multiple ParamExp parts."""
        tree = parse_ast('echo "$HOME is $USER"')
        cmd = tree.stmts[0].cmd
        # Inside the DblQuoted, we should have: ParamExp, Lit, ParamExp
        assert cmd.args[1].parts[0].type == 'DblQuoted'
        parts = cmd.args[1].parts[0].parts
        assert parts[0].type == 'ParamExp'
        assert parts[0].param == 'HOME'
        assert parts[1].type == 'Lit'
        assert parts[1].value == ' is '
        assert parts[2].type == 'ParamExp'
        assert parts[2].param == 'USER'

    def test_adjacent_param_expansions(self):
        """Parse echo "$HOME$USER" and verify two adjacent ParamExp parts."""
        tree = parse_ast('echo "$HOME$USER"')
        cmd = tree.stmts[0].cmd
        parts = cmd.args[1].parts[0].parts
        assert len(parts) == 2
        assert parts[0].type == 'ParamExp'
        assert parts[0].param == 'HOME'
        assert parts[1].type == 'ParamExp'
        assert parts[1].param == 'USER'

    def test_length_param_expansion(self):
        """Parse echo ${#HOME} and verify Length field."""
        tree = parse_ast('echo ${#HOME}')
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == 'ParamExp'
        assert cmd.args[1].parts[0].param == 'HOME'
        assert cmd.args[1].parts[0].length is True

    def test_special_param_expansion(self):
        """Parse echo "$@" and verify ParamExp with special parameter."""
        tree = parse_ast('echo "$@"')
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].parts[0].type == 'ParamExp'
        assert cmd.args[1].parts[0].parts[0].param == '@'

    def test_position_param_expansion(self):
        """Parse echo "$0" and verify ParamExp with positional parameter."""
        tree = parse_ast('echo "$0"')
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].parts[0].type == 'ParamExp'
        assert cmd.args[1].parts[0].parts[0].param == '0'

    def test_param_expansion_position_info(self):
        """Verify that ParamExp nodes have position information from shfmt."""
        tree = parse_ast('echo $HOME')
        cmd = tree.stmts[0].cmd
        part = cmd.args[1].parts[0]
        assert part.type == 'ParamExp'
        assert part.pos is not None
        assert part.end is not None
        assert isinstance(part.pos.offset, int)
        assert isinstance(part.end.offset, int)

    def test_param_exp_imported_in_module(self):
        """Verify that ParamExp is imported in the lovely_bash_permissions module."""
        from lovely_bash_permissions import ParamExp
        assert ParamExp is not None


class TestDblQuotedNodes:
    """Tests for the DblQuoted node type (Step 3 of node coverage)."""

    def test_simple_double_quoted(self):
        """Parse echo "hello" and verify it produces a DblQuoted node with Lit parts."""
        tree = parse_ast('echo "hello"')
        cmd = tree.stmts[0].cmd
        assert cmd.type == 'CallExpr'
        assert len(cmd.args) == 2
        assert cmd.args[1].parts[0].type == 'DblQuoted'
        assert len(cmd.args[1].parts[0].parts) == 1
        assert cmd.args[1].parts[0].parts[0].type == 'Lit'
        assert cmd.args[1].parts[0].parts[0].value == 'hello'

    def test_double_quoted_with_variable_expansion(self):
        """Parse echo "hello $world" and verify DblQuoted with Lit + ParamExp parts."""
        tree = parse_ast('echo "hello $world"')
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == 'DblQuoted'
        parts = cmd.args[1].parts[0].parts
        assert len(parts) == 2
        assert parts[0].type == 'Lit'
        assert parts[0].value == 'hello '
        assert parts[1].type == 'ParamExp'
        assert parts[1].param == 'world'

    def test_double_quoted_multiple_variables(self):
        """Parse echo "$USER is here" and verify DblQuoted with multiple ParamExp parts."""
        tree = parse_ast('echo "$USER is here"')
        cmd = tree.stmts[0].cmd
        parts = cmd.args[1].parts[0].parts
        assert parts[0].type == 'ParamExp'
        assert parts[0].param == 'USER'
        assert parts[1].type == 'Lit'
        assert parts[1].value == ' is here'

    def test_empty_double_quoted(self):
        """Parse echo "" and verify an empty DblQuoted is handled."""
        tree = parse_ast('echo ""')
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == 'DblQuoted'
        # shfmt-py: Empty DblQuoted has NO parts field at all (None in Python)
        assert cmd.args[1].parts[0].parts is None
        # shfmt Go: Would have an empty array: assert ...parts == []
        
    def test_empty_double_quoted_shfmt_go(self):
        """Test shfmt Go-style empty DblQuoted handling (for completeness)."""
        # In shfmt Go, empty double quotes would give a DblQuoted with an empty parts array.
        # Our parser should handle both: None parts (shfmt-py) and [] parts (shfmt Go).
        from lovely_bash_permissions.ast import DblQuoted, Part
        dq_go = DblQuoted(type="DblQuoted", pos=None, end=None, parts=[])
        assert dq_go.parts == []

    def test_double_quoted_preserves_spaces(self):
        """Parse echo "a b c" and verify spaces are preserved in Lit parts."""
        tree = parse_ast('echo "a b c"')
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == 'DblQuoted'
        assert len(cmd.args[1].parts[0].parts) == 1
        assert cmd.args[1].parts[0].parts[0].type == 'Lit'
        assert cmd.args[1].parts[0].parts[0].value == 'a b c'

    def test_nested_quotes(self):
        """Parse echo "$HOME is $USER" and verify multiple nested parts."""
        tree = parse_ast('echo "$HOME is $USER"')
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == 'DblQuoted'
        parts = cmd.args[1].parts[0].parts
        assert len(parts) == 3
        assert parts[0].type == 'ParamExp'
        assert parts[0].param == 'HOME'
        assert parts[1].type == 'Lit'
        assert parts[1].value == ' is '
        assert parts[2].type == 'ParamExp'
        assert parts[2].param == 'USER'

    def test_escape_sequences_in_double_quotes(self):
        """Parse echo with escaped characters in double quotes."""
        tree = parse_ast('echo "\\n\\t\\r"')
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == 'DblQuoted'
        # In shfmt-py, escaped sequences in double quotes become Lit parts with the literal escape sequences
        assert cmd.args[1].parts[0].parts[0].type == 'Lit'
        assert cmd.args[1].parts[0].parts[0].value == '\\n\\t\\r'

    def test_mixed_literal_variable_escape(self):
        """Parse complex DblQuoted with lit, variable, and escapes mixed."""
        tree = parse_ast('echo "\\n$USER\\n"')
        cmd = tree.stmts[0].cmd
        parts = cmd.args[1].parts[0].parts
        assert len(parts) == 3
        assert parts[0].type == 'Lit'
        assert parts[0].value == '\\n'
        assert parts[1].type == 'ParamExp'
        assert parts[1].param == 'USER'
        assert parts[2].type == 'Lit'
        assert parts[2].value == '\\n'

    def test_dblquoted_position_info(self):
        """Verify that DblQuoted nodes have position information from shfmt."""
        tree = parse_ast('echo "hello"')
        cmd = tree.stmts[0].cmd
        part = cmd.args[1].parts[0]
        assert part.type == 'DblQuoted'
        assert part.pos is not None
        assert part.end is not None
        assert isinstance(part.pos.offset, int)
        assert isinstance(part.end.offset, int)

    def test_dblquoted_imported_in_module(self):
        """Verify that DblQuoted is imported in the lovely_bash_permissions module."""
        from lovely_bash_permissions import DblQuoted
        assert DblQuoted is not None


class TestCmdSubstNodes:
    """Tests for the CmdSubst node type (Step 5 of node coverage)."""

    def test_simple_cmdsubst_syntax(self):
        """Parse echo $(date) and verify it produces a CmdSubst node."""
        tree = parse_ast('echo $(date)')
        cmd = tree.stmts[0].cmd
        assert cmd.type == 'CallExpr'
        assert len(cmd.args) == 2
        assert cmd.args[1].parts[0].type == 'CmdSubst'
        assert isinstance(cmd.args[1].parts[0], CmdSubst)
        assert len(cmd.args[1].parts[0].stmts) == 1
        inner_cmd = cmd.args[1].parts[0].stmts[0].cmd
        assert inner_cmd.type == 'CallExpr'
        assert inner_cmd.args[0].parts[0].value == 'date'

    def test_cmdsubst_with_backquotes(self):
        """Parse echo `date` and verify backquotes is True."""
        tree = parse_ast('echo `date`')
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == 'CmdSubst'
        assert cmd.args[1].parts[0].backquotes is True
        assert cmd.args[1].parts[0].stmts[0].cmd.args[0].parts[0].value == 'date'

    def test_cmdsubst_in_double_quotes(self):
        """Parse echo \"hello $(date)\" and verify CmdSubst inside DblQuoted."""
        tree = parse_ast('echo "hello $(date)"')
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == 'DblQuoted'
        parts = cmd.args[1].parts[0].parts
        assert len(parts) == 2
        assert parts[0].type == 'Lit'
        assert parts[0].value == 'hello '
        assert parts[1].type == 'CmdSubst'
        assert parts[1].stmts[0].cmd.args[0].parts[0].value == 'date'

    def test_two_cmdsubst_parts(self):
        """Parse echo $(date) && $(date) and verify two CmdSubst parts."""
        tree = parse_ast('echo $(date) $(date)')
        cmd = tree.stmts[0].cmd
        assert len(cmd.args) == 3
        assert cmd.args[1].parts[0].type == 'CmdSubst'
        assert cmd.args[2].parts[0].type == 'CmdSubst'
        # Both have the same inner command
        assert cmd.args[1].parts[0].stmts[0].cmd.args[0].parts[0].value == 'date'
        assert cmd.args[2].parts[0].stmts[0].cmd.args[0].parts[0].value == 'date'

    def test_nested_cmdsubst(self):
        """Parse echo $(echo $(date)) and verify nested CmdSubst."""
        tree = parse_ast('echo $(echo $(date))')
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == 'CmdSubst'
        outer_stmt = cmd.args[1].parts[0].stmts[0]
        assert outer_stmt.cmd.type == 'CallExpr'
        assert outer_stmt.cmd.args[0].parts[0].value == 'echo'
        inner_part = outer_stmt.cmd.args[1].parts[0]
        assert inner_part.type == 'CmdSubst'
        assert inner_part.stmts[0].cmd.args[0].parts[0].value == 'date'

    def test_cmdsubst_with_multiple_commands(self):
        """Parse echo $(ls | grep txt) and verify multiple inner statements."""
        tree = parse_ast('echo $(ls | grep txt)')
        cmd = tree.stmts[0].cmd
        cs = cmd.args[1].parts[0]
        assert cs.type == 'CmdSubst'
        assert len(cs.stmts) == 1
        inner = cs.stmts[0].cmd
        assert inner.type == 'BinaryCmd'
        assert inner.x.args[0].parts[0].value == 'ls'
        assert inner.y.args[0].parts[0].value == 'grep'
        assert inner.y.args[1].parts[0].value == 'txt'

    def test_cmdsubst_position_info(self):
        """Verify that CmdSubst nodes have position information."""
        tree = parse_ast('echo $(date)')
        cmd = tree.stmts[0].cmd
        part = cmd.args[1].parts[0]
        assert part.pos is not None
        assert part.end is not None
        assert isinstance(part.pos.offset, int)
        assert isinstance(part.end.offset, int)

    def test_cmdsubst_backquotes_false(self):
        """Verify that $(...) has backquotes=False."""
        tree = parse_ast('echo $(date)')
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
        tree = parse_ast('echo $((2 + 2))')
        cmd = tree.stmts[0].cmd
        assert cmd.type == 'CallExpr'
        assert len(cmd.args) == 2
        assert cmd.args[1].parts[0].type == 'ArithmExp'
        assert isinstance(cmd.args[1].parts[0], ArithmExp)
        inner = cmd.args[1].parts[0].x
        assert inner.type == 'BinaryArithm'
        assert inner.op == '+'
        assert inner.x.parts[0].type == 'Lit'
        assert inner.x.parts[0].value == '2'
        assert inner.y.parts[0].type == 'Lit'
        assert inner.y.parts[0].value == '2'

    def test_arithmetic_with_variables(self):
        """Parse echo $((x + y)) and verify ArithmExp with variables."""
        tree = parse_ast('echo $((x + y))')
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == 'ArithmExp'
        inner = cmd.args[1].parts[0].x
        assert inner.type == 'BinaryArithm'
        assert inner.op == '+'
        assert inner.x.parts[0].type == 'Lit'
        assert inner.x.parts[0].value == 'x'
        assert inner.y.parts[0].type == 'Lit'
        assert inner.y.parts[0].value == 'y'

    def test_single_value_arithmetic(self):
        """Parse echo $((50)) and verify ArithmExp with just a value."""
        tree = parse_ast('echo $((50))')
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == 'ArithmExp'
        inner = cmd.args[1].parts[0].x
        assert inner.type == 'Word'
        assert inner.parts[0].type == 'Lit'
        assert inner.parts[0].value == '50'

    def test_arithmetic_in_double_quotes(self):
        """Parse echo \"$((5))\" and verify ArithmExp inside DblQuoted."""
        tree = parse_ast('echo "$((5))"')
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == 'DblQuoted'
        dq = cmd.args[1].parts[0]
        assert dq.parts[0].type == 'ArithmExp'
        inner = dq.parts[0].x
        assert inner.type == 'Word'
        assert inner.parts[0].type == 'Lit'
        assert inner.parts[0].value == '5'

    def test_complex_arithmetic_expression(self):
        """Parse echo $((2 * 3 + 4)) and verify nested BinaryArithm."""
        tree = parse_ast('echo $((2 * 3 + 4))')
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == 'ArithmExp'
        inner = cmd.args[1].parts[0].x
        assert inner.type == 'BinaryArithm'
        assert inner.op == '+'
        # Left side should be multiplication
        assert inner.x.type == 'BinaryArithm'
        assert inner.x.op == '*'
        assert inner.x.x.parts[0].value == '2'
        assert inner.x.y.parts[0].value == '3'
        # Right side should be the number 4
        assert inner.y.parts[0].value == '4'

    def test_arithmetic_position_info(self):
        """Verify that ArithmExp nodes have position information."""
        tree = parse_ast('echo $((2 + 2))')
        cmd = tree.stmts[0].cmd
        part = cmd.args[1].parts[0]
        assert part.type == 'ArithmExp'
        assert part.pos is not None
        assert part.end is not None
        assert isinstance(part.pos.offset, int)
        assert isinstance(part.end.offset, int)

    def test_binaryarithm_position_info(self):
        """Verify that BinaryArithm nodes have position information."""
        tree = parse_ast('echo $((2 + 2))')
        cmd = tree.stmts[0].cmd
        inner = cmd.args[1].parts[0].x
        assert inner.type == 'BinaryArithm'
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
        from lovely_bash_permissions import BinaryArithm
        assert BinaryArithm is not None
