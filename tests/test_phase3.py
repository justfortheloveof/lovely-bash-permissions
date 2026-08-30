"""
Comprehensive Phase 3 tests: edge cases, error handling, shell features,
multi-line commands, and robust parsing.
"""

import pytest
from lovely_bash_permissions import (
    parse_ast, get_commands, get_arguments, has_variable, get_redirections,
    has_pipe, get_target_files, find_commands
)


class TestSubshells:
    """Test subshell parsing."""

    def test_basic_subshell(self):
        tree = parse_ast('(cd /tmp && ls)')
        assert get_commands(tree) == ['cd', 'ls']

    def test_nested_subshells(self):
        tree = parse_ast('( (cd /tmp && ls) | grep txt )')
        assert get_commands(tree) == ['cd', 'ls', 'grep']
        assert get_arguments(tree) == [['/tmp'], [], ['txt']]

    def test_subshell_with_redirection(self):
        tree = parse_ast('(cat file.txt) > output.txt')
        assert get_commands(tree) == ['cat']
        assert get_arguments(tree) == [['file.txt']]
        redirs = get_redirections(tree)
        assert len(redirs) == 1
        assert redirs[0]['target'] == 'output.txt'


class TestIfStatements:
    """Test if/else statement parsing."""

    def test_simple_if(self):
        tree = parse_ast('if [ -f file.txt ]; then cat file.txt; fi')
        # [ is parsed as a command (alias for test), ] is its final arg
        assert get_commands(tree) == ['[', 'cat']
        assert get_arguments(tree) == [['-f', 'file.txt', ']'], ['file.txt']]

    def test_if_else(self):
        tree = parse_ast('if [ -f file.txt ]; then cat file.txt; else echo missing; fi')
        assert get_commands(tree) == ['[', 'cat', 'echo']
        assert get_arguments(tree) == [['-f', 'file.txt', ']'], ['file.txt'], ['missing']]

    def test_if_with_variable(self):
        tree = parse_ast('if [ "$x" = "y" ]; then echo yes; fi')
        assert has_variable(tree)
        assert get_commands(tree) == ['[', 'echo']

    def test_nested_if(self):
        tree = parse_ast('if [ -f file.txt ]; then if [ -r file.txt ]; then cat file.txt; fi; fi')
        assert get_commands(tree) == ['[', '[', 'cat']

    def test_if_with_pipe(self):
        tree = parse_ast('if [ -f file.txt ]; then cat file.txt | grep pattern; fi')
        assert get_commands(tree) == ['[', 'cat', 'grep']
        assert has_pipe(tree)

    def test_if_else_elif(self):
        tree = parse_ast('if [ "$x" = "a" ]; then echo A; elif [ "$x" = "b" ]; then echo B; else echo C; fi')
        assert get_commands(tree) == ['[', 'echo', '[', 'echo', 'echo']
        assert get_arguments(tree) == [['', '=', 'a', ']'], ['A'], ['', '=', 'b', ']'], ['B'], ['C']]
        assert has_variable(tree)


class TestForLoops:
    """Test for loop parsing."""

    def test_basic_for_loop(self):
        tree = parse_ast('for file in *.txt; do cat "$file"; done')
        assert get_commands(tree) == ['cat']
        assert has_variable(tree)

    def test_for_with_variable(self):
        tree = parse_ast('for i in $numbers; do echo $i; done')
        assert has_variable(tree)
        assert get_commands(tree) == ['echo']

    def test_nested_for_loops(self):
        tree = parse_ast('for i in 1 2 3; do for j in a b; do echo "$i-$j"; done; done')
        assert get_commands(tree) == ['echo']
        assert has_variable(tree)


class TestWhileLoops:
    """Test while loop parsing."""

    def test_basic_while(self):
        tree = parse_ast('while [ "$i" -lt 10 ]; do echo "$i"; done')
        assert get_commands(tree) == ['[', 'echo']
        assert has_variable(tree)

    def test_while_with_variable(self):
        tree = parse_ast('while read line; do echo "$line"; done < file.txt')
        assert get_commands(tree) == ['read', 'echo']
        assert get_arguments(tree) == [['line'], ['']]
        redirs = get_redirections(tree)
        assert len(redirs) == 1
        assert redirs[0]['target'] == 'file.txt'


class TestAndOrOperators:
    """Test && and || operators."""

    def test_and_operator(self):
        tree = parse_ast('cd /tmp && ls')
        assert get_commands(tree) == ['cd', 'ls']
        assert get_arguments(tree) == [['/tmp'], []]

    def test_or_operator(self):
        tree = parse_ast('ls dir || echo empty')
        assert get_commands(tree) == ['ls', 'echo']
        assert get_arguments(tree) == [['dir'], ['empty']]

    def test_chained_and(self):
        tree = parse_ast('mkdir -p dir && cd dir && ls')
        assert get_commands(tree) == ['mkdir', 'cd', 'ls']
        assert get_arguments(tree) == [['-p', 'dir'], ['dir'], []]

    def test_mixed_and_or(self):
        tree = parse_ast('test -f file || (cd /tmp && ls)')
        assert get_commands(tree) == ['test', 'cd', 'ls']


class TestMultiLineCommands:
    """Test multi-line command parsing."""

    def test_multiline_if(self):
        cmd = "if [ -f file.txt ]; then\n    cat file.txt\nelse\n    echo \"file not found\"\nfi"
        tree = parse_ast(cmd)
        assert get_commands(tree) == ['[', 'cat', 'echo']
        assert get_arguments(tree) == [['-f', 'file.txt', ']'], ['file.txt'], ['file not found']]

    def test_multiline_for(self):
        cmd = "for file in *.txt; do\n    cat \"$file\"\ndone"
        tree = parse_ast(cmd)
        assert get_commands(tree) == ['cat']
        assert has_variable(tree)

    def test_multiline_while(self):
        cmd = "while read line; do\n    echo \"$line\"\ndone < file.txt"
        tree = parse_ast(cmd)
        assert get_commands(tree) == ['read', 'echo']

    def test_multiline_pipe_chain(self):
        cmd = "cat data.csv |\n    grep pattern |\n    awk '{print $1}' |\n    sort -u > results.txt"
        tree = parse_ast(cmd)
        assert get_commands(tree) == ['cat', 'grep', 'awk', 'sort']
        redirs = get_redirections(tree)
        assert len(redirs) == 1
        assert redirs[0]['target'] == 'results.txt'

    def test_multiline_with_command_substitution(self):
        cmd = 'files=$(find . -name "*.txt" | grep -v ".git")\necho "$files"'
        tree = parse_ast(cmd)
        assert get_commands(tree) == ['find', 'grep', 'echo']
        assert has_variable(tree)


class TestComplexNestedStructures:
    """Test deeply nested and complex commands."""

    def test_nested_subshell_with_pipe(self):
        tree = parse_ast('( (cat file1.txt) | (cat file2.txt) ) | sort | uniq')
        assert get_commands(tree) == ['cat', 'cat', 'sort', 'uniq']
        assert get_arguments(tree) == [['file1.txt'], ['file2.txt'], [], []]

    def test_complex_pipeline(self):
        tree = parse_ast('find . -name "*.py" | grep -v ".venv" | sort | head -n 10')
        assert get_commands(tree) == ['find', 'grep', 'sort', 'head']
        assert get_arguments(tree) == [['.', '-name', '*.py'], ['-v', '.venv'], [], ['-n', '10']]

    def test_mixed_operators(self):
        tree = parse_ast('[ -f file.txt ] && cat file.txt | grep pattern || echo "no match"')
        assert get_commands(tree) == ['[', 'cat', 'grep', 'echo']
        assert has_pipe(tree)


class TestEdgeCases:
    """Test various edge cases."""

    def test_empty_command_error(self):
        with pytest.raises(Exception) as exc_info:
            parse_ast('')
        assert "Empty" in str(exc_info.value)

    def test_whitespace_only_error(self):
        with pytest.raises(Exception):
            parse_ast('   ')

    def test_single_quote(self):
        tree = parse_ast("echo 'hello world'")
        assert get_commands(tree) == ['echo']

    def test_double_quote(self):
        tree = parse_ast('echo "hello world"')
        assert get_commands(tree) == ['echo']

    def test_mixed_quotes(self):
        tree = parse_ast("echo 'hello' \"world\"")
        assert get_commands(tree) == ['echo']

    def test_command_with_equals(self):
        tree = parse_ast('export FOO=bar')
        # export is parsed as DeclClause, not CallExpr
        assert get_commands(tree) == []

    def test_multiple_command_separator(self):
        tree = parse_ast('ls; grep txt file.txt')
        assert get_commands(tree) == ['ls', 'grep']
        assert get_arguments(tree) == [[], ['txt', 'file.txt']]

    def test_semicolon_and_pipe(self):
        tree = parse_ast('ls; echo hello | grep l')
        assert get_commands(tree) == ['ls', 'echo', 'grep']
        assert has_pipe(tree)

    def test_complex_argument_with_equals(self):
        tree = parse_ast('git log --since="2024-01-01"')
        assert get_commands(tree) == ['git']
        # Quotes are stripped by shfmt
        assert get_arguments(tree) == [['log', '--since=2024-01-01']]


class TestCommandSubstitution:
    """Test command substitution."""

    def test_backtick_substitution(self):
        tree = parse_ast('echo `date`')
        assert get_commands(tree) == ['echo']
        # The inner command is in a different structure, not detected by get_commands
        # but shfmt parses it

    def test_dollar_paren_substitution(self):
        tree = parse_ast('echo $(date)')
        assert get_commands(tree) == ['echo']
        assert has_variable(tree)

    def test_nested_command_substitution(self):
        tree = parse_ast('echo "$(ls -la)"')
        assert get_commands(tree) == ['echo']
        assert has_variable(tree)


class TestRedirectionComplex:
    """Test complex redirections."""

    def test_multiple_redirections(self):
        tree = parse_ast('cat input.txt > output.txt 2> error.txt')
        assert get_commands(tree) == ['cat']
        assert get_arguments(tree) == [['input.txt']]
        redirs = get_redirections(tree)
        assert len(redirs) == 2
        assert redirs[0]['target'] == 'output.txt'
        assert redirs[1]['target'] == 'error.txt'

    def test_redirect_in_subshell(self):
        tree = parse_ast('(cat file.txt > /tmp/out)')
        assert get_commands(tree) == ['cat']
        assert get_arguments(tree) == [['file.txt']]
        redirs = get_redirections(tree)
        assert len(redirs) == 1
        assert redirs[0]['target'] == '/tmp/out'


class TestVariablesComplex:
    """Test complex variable detection."""

    def test_nested_variable(self):
        tree = parse_ast('echo "${HOME:-default}"')
        assert has_variable(tree)

    def test_variable_in_condition(self):
        tree = parse_ast('if [ "$x" -gt "$y" ]; then echo yes; fi')
        assert has_variable(tree)
        assert get_commands(tree) == ['[', 'echo']

    def test_variable_in_loop(self):
        tree = parse_ast('for item in "$@"; do echo "$item"; done')
        assert has_variable(tree)
        assert get_commands(tree) == ['echo']


class TestErrorMessages:
    """Test error message quality."""

    def test_shfmt_failure_message(self):
        with pytest.raises(Exception) as exc_info:
            parse_ast('')
        assert "Empty" in str(exc_info.value)

    def test_unbalanced_quotes(self):
        # shfmt fails on unclosed quotes
        with pytest.raises(Exception):
            parse_ast("echo 'unclosed")


class TestParseErrorAttributes:
    """Test ParseError has useful attributes."""

    def test_parse_error_command_attribute(self):
        with pytest.raises(Exception) as exc_info:
            parse_ast('')
        # Check the exception message contains useful info
        assert "Empty" in str(exc_info.value)