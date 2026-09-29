"""Comprehensive tests: edge cases, error handling,
shell features, multi-line commands."""

import pytest

from lovely_bash_permissions import (
    get_commands,
    get_redirections,
    has_pipe,
    has_variable,
    parse_ast,
)
from lovely_bash_permissions.parser import ParseError


class TestParsingFeaturesSubshells:
    def test_basic_subshell(self) -> None:
        tree = parse_ast("(cd /tmp && ls)")
        assert get_commands(tree) == ["cd", "ls"]

    def test_nested_subshells(self) -> None:
        tree = parse_ast("( (cd /tmp && ls) | grep txt )")
        assert get_commands(tree) == ["cd", "ls", "grep"]

    def test_subshell_with_redirection(self) -> None:
        tree = parse_ast("(cat file.txt) > output.txt")
        assert get_commands(tree) == ["cat"]


class TestParsingFeaturesIfStatements:
    def test_simple_if(self) -> None:
        tree = parse_ast("if [ -f file.txt ]; then cat file.txt; fi")
        assert get_commands(tree) == ["[", "cat"]

    def test_if_else(self) -> None:
        tree = parse_ast("if [ -f file.txt ]; then cat file.txt; else echo missing; fi")
        assert get_commands(tree) == ["[", "cat", "echo"]

    def test_if_with_variable(self) -> None:
        tree = parse_ast('if [ "$x" = "y" ]; then echo yes; fi')
        assert has_variable(tree)

    def test_nested_if(self) -> None:
        tree = parse_ast("if [ -f file.txt ]; then if [ -r file.txt ]; then cat file.txt; fi; fi")
        assert get_commands(tree) == ["[", "[", "cat"]

    def test_if_with_pipe(self) -> None:
        tree = parse_ast("if [ -f file.txt ]; then cat file.txt | grep pattern; fi")
        assert has_pipe(tree)


class TestParsingFeaturesForLoops:
    def test_basic_for_loop(self) -> None:
        tree = parse_ast('for file in *.txt; do cat "$file"; done')
        assert get_commands(tree) == ["cat"]

    def test_for_with_variable(self) -> None:
        tree = parse_ast("for i in $numbers; do echo $i; done")
        assert has_variable(tree)

    def test_nested_for_loops(self) -> None:
        tree = parse_ast('for i in 1 2 3; do for j in a b; do echo "$i-$j"; done; done')
        assert get_commands(tree) == ["echo"]


class TestParsingFeaturesWhileLoops:
    def test_basic_while(self) -> None:
        tree = parse_ast('while [ "$i" -lt 10 ]; do echo "$i"; done')
        assert get_commands(tree) == ["[", "echo"]

    def test_while_with_variable(self) -> None:
        tree = parse_ast('while read line; do echo "$line"; done < file.txt')
        assert get_commands(tree) == ["read", "echo"]


class TestParsingFeaturesAndOrOperators:
    def test_and_operator(self) -> None:
        tree = parse_ast("cd /tmp && ls")
        assert get_commands(tree) == ["cd", "ls"]

    def test_or_operator(self) -> None:
        tree = parse_ast("ls dir || echo empty")
        assert get_commands(tree) == ["ls", "echo"]

    def test_chained_and(self) -> None:
        tree = parse_ast("mkdir -p dir && cd dir && ls")
        assert get_commands(tree) == ["mkdir", "cd", "ls"]

    def test_mixed_and_or(self) -> None:
        tree = parse_ast("[ -f file.txt ] && cat file.txt | grep pattern || echo no match")
        assert get_commands(tree) == ["[", "cat", "grep", "echo"]


class TestParsingFeaturesMultiLineCommands:
    def test_multiline_if(self) -> None:
        cmd = 'if [ -f file.txt ]; then\n    cat file.txt\nelse\n    echo "file not found"\nfi'
        tree = parse_ast(cmd)
        assert get_commands(tree) == ["[", "cat", "echo"]

    def test_multiline_for(self) -> None:
        cmd = 'for file in *.txt; do\n    cat "$file"\ndone'
        tree = parse_ast(cmd)
        assert get_commands(tree) == ["cat"]

    def test_multiline_with_command_substitution(self) -> None:
        cmd = 'files=$(find . -name "*.txt" | grep -v ".git")\necho "$files"'
        tree = parse_ast(cmd)
        assert get_commands(tree) == ["find", "grep", "echo"]


class TestParsingFeaturesComplexNestedStructures:
    def test_nested_subshell_with_pipe(self) -> None:
        tree = parse_ast("( (cat file1.txt) | (cat file2.txt) ) | sort | uniq")
        assert get_commands(tree) == ["cat", "cat", "sort", "uniq"]

    def test_complex_pipeline(self) -> None:
        tree = parse_ast('find . -name "*.py" | grep -v ".venv" | sort | head -n 10')
        assert get_commands(tree) == ["find", "grep", "sort", "head"]


class TestParsingFeaturesEdgeCases:
    def test_command_with_equals(self) -> None:
        tree = parse_ast("export FOO=bar")
        assert get_commands(tree) == []

    def test_multiple_command_separator(self) -> None:
        tree = parse_ast("ls; grep txt file.txt")
        assert get_commands(tree) == ["ls", "grep"]


class TestParsingFeaturesCommandSubstitution:
    def test_backtick_substitution(self) -> None:
        tree = parse_ast("echo `date`")
        assert get_commands(tree) == ["echo", "date"]

    def test_dollar_paren_substitution(self) -> None:
        tree = parse_ast("echo $(date)")
        assert get_commands(tree) == ["echo", "date"]

    def test_nested_command_substitution(self) -> None:
        tree = parse_ast('echo "$(ls -la)"')
        assert get_commands(tree) == ["echo", "ls"]


class TestParsingFeaturesRedirectionComplex:
    def test_multiple_redirections(self) -> None:
        tree = parse_ast("cat input.txt > output.txt 2> error.txt")
        redirs = get_redirections(tree)
        assert len(redirs) == 2


class TestParsingFeaturesVariablesComplex:
    def test_nested_variable(self) -> None:
        tree = parse_ast('echo "${HOME:-default}"')
        assert has_variable(tree)

    def test_variable_in_condition(self) -> None:
        tree = parse_ast('if [ "$x" -gt "$y" ]; then echo yes; fi')
        assert has_variable(tree)


class TestParsingFeaturesErrorMessages:
    def test_unbalanced_quotes(self) -> None:
        with pytest.raises(ParseError):
            parse_ast("echo 'unclosed")


class TestParsingFeaturesParseErrorAttributes:
    def test_parse_error_has_command(self) -> None:
        with pytest.raises(ParseError) as exc_info:
            parse_ast("")
        assert exc_info.value.command == ""
