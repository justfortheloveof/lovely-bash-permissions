"""
Comprehensive tests for Phase 2: AST inspection, visitor pattern, and new helper methods.
"""

import pytest
from lovely_bash_permissions import (
    parse_ast, get_commands, get_arguments, has_variable, get_redirections,
    find_commands, find_arguments, has_pipe, get_target_files, Visitor,
    Node, CallExpr, BinaryCmd, Word, Part, Stmt, File, Redir
)


class TestVisitorPattern:
    """Test the AST visitor pattern."""

    def test_basic_visitor(self):
        """Test that Visitor.walk visits all nodes."""
        tree = parse_ast('ls -la | grep txt > output.txt')
        
        visited = {'File': 0, 'Stmt': 0, 'CallExpr': 0, 'BinaryCmd': 0}
        
        class CountVisitor(Visitor):
            def visit_file(self, node):
                visited['File'] += 1
            def visit_stmt(self, node):
                visited['Stmt'] += 1
            def visit_call_expr(self, node):
                visited['CallExpr'] += 1
            def visit_binary_cmd(self, node):
                visited['BinaryCmd'] += 1
        
        visitor = CountVisitor()
        visitor.walk(tree)
        
        assert visited['File'] == 1
        assert visited['Stmt'] == 1
        assert visited['CallExpr'] == 2
        assert visited['BinaryCmd'] == 1

    def test_word_visitor(self):
        """Test visiting Word nodes."""
        tree = parse_ast('cat file.txt')
        
        word_count = 0
        
        class WordCountVisitor(Visitor):
            def visit_word(self, node):
                nonlocal word_count
                word_count += 1
        
        WordCountVisitor().walk(tree)
        # "cat" and "file.txt" are both words
        assert word_count == 2

    def test_part_visitor(self):
        """Test visiting Part nodes."""
        tree = parse_ast('ls -la')
        
        part_count = 0
        
        class PartCountVisitor(Visitor):
            def visit_part(self, node):
                nonlocal part_count
                part_count += 1
        
        PartCountVisitor().walk(tree)
        # "ls" has 1 part, "-la" has 1 part
        assert part_count == 2

    def test_recursive_visit(self):
        """Test that visitor properly recurses into nested structures."""
        tree = parse_ast('cat file1.txt | grep pattern')
        
        call_expr_names = []
        
        class CollectVisitor(Visitor):
            def visit_call_expr(self, node):
                nonlocal call_expr_names
                if node.args:
                    call_expr_names.append(node.args[0])
        
        CollectVisitor().walk(tree)
        # Should have visited both cat and grep call expressions
        assert len(call_expr_names) == 2

    def test_visit_dispatch(self):
        """Test that visit() dispatches to correct method."""
        tree = parse_ast('echo hello')
        
        method_calls = []
        
        class DispatchVisitor(Visitor):
            def visit_file(self, node):
                method_calls.append('file')
            def visit_stmt(self, node):
                method_calls.append('stmt')
            def visit_call_expr(self, node):
                method_calls.append('call')
        
        visitor = DispatchVisitor()
        visitor.walk(tree)
        assert method_calls == ['file', 'stmt', 'call']


class TestFindCommands:
    """Test find_commands() - find all CallExpr nodes."""

    def test_single_command(self):
        tree = parse_ast('ls')
        commands = find_commands(tree)
        assert len(commands) == 1
        assert isinstance(commands[0], CallExpr)

    def test_multiple_commands_with_pipe(self):
        tree = parse_ast('cat file.txt | grep pattern')
        commands = find_commands(tree)
        assert len(commands) == 2
        assert isinstance(commands[0], CallExpr)
        assert isinstance(commands[1], CallExpr)

    def test_complex_pipeline(self):
        tree = parse_ast('cat data.csv | grep pattern | awk "{print $1}" | sort -u')
        commands = find_commands(tree)
        assert len(commands) == 4

    def test_no_commands(self):
        tree = parse_ast('export PATH="/usr/bin"')
        commands = find_commands(tree)
        assert len(commands) == 0

    def test_command_names_match(self):
        tree = parse_ast('ls -la | grep txt')
        commands = find_commands(tree)
        names = []
        for cmd in commands:
            if cmd.args:
                names.append(cmd.args[0])
        assert len(names) == 2


class TestFindArguments:
    """Test find_arguments() - find all argument lists."""

    def test_no_arguments(self):
        tree = parse_ast('ls')
        args = find_arguments(tree)
        assert len(args) == 1
        assert args[0] == []

    def test_single_command_with_args(self):
        tree = parse_ast('cat file.txt')
        args = find_arguments(tree)
        assert len(args) == 1
        assert len(args[0]) == 1
        assert isinstance(args[0][0], Word)

    def test_multiple_commands(self):
        tree = parse_ast('ls -la | grep -i txt')
        args = find_arguments(tree)
        assert len(args) == 2
        assert len(args[0]) == 1
        assert len(args[1]) == 2

    def test_command_names_excluded(self):
        tree = parse_ast('echo hello')
        args = find_arguments(tree)
        assert len(args) == 1
        assert len(args[0]) == 1
        # Should be "hello", not "echo"


class TestHasPipe:
    """Test has_pipe() - check for pipe operators."""

    def test_no_pipe(self):
        tree = parse_ast('ls -la')
        assert not has_pipe(tree)

    def test_single_pipe(self):
        tree = parse_ast('cat file.txt | grep pattern')
        assert has_pipe(tree)

    def test_multiple_pipes(self):
        tree = parse_ast('cat file.txt | grep pattern | sort | uniq')
        assert has_pipe(tree)

    def test_nested_commands(self):
        tree = parse_ast('ls\ngrep pattern')
        assert not has_pipe(tree)

    def test_redirection_without_pipe(self):
        tree = parse_ast('cat file.txt > output.txt')
        assert not has_pipe(tree)


class TestGetTargetFiles:
    """Test get_target_files() - extract file targets from redirections."""

    def test_no_redirections(self):
        tree = parse_ast('ls -la')
        targets = get_target_files(tree)
        assert targets == []

    def test_output_redirect(self):
        tree = parse_ast('cat file.txt > output.txt')
        targets = get_target_files(tree)
        assert len(targets) == 1
        assert targets[0] == 'output.txt'

    def test_input_redirect(self):
        tree = parse_ast('sort < input.txt')
        targets = get_target_files(tree)
        assert len(targets) == 1
        assert targets[0] == 'input.txt'

    def test_append_redirect(self):
        tree = parse_ast('cat file.txt >> output.txt')
        targets = get_target_files(tree)
        assert len(targets) == 1
        assert targets[0] == 'output.txt'

    def test_multiple_redirections(self):
        tree = parse_ast('cat file.txt > output.txt 2> errors.txt')
        targets = get_target_files(tree)
        assert len(targets) == 2
        assert targets[0] == 'output.txt'
        assert targets[1] == 'errors.txt'

    def test_pipe_with_redirect(self):
        tree = parse_ast('ls -la | grep txt > output.txt')
        targets = get_target_files(tree)
        assert len(targets) == 1
        assert targets[0] == 'output.txt'


class TestIntegration:
    """Integration tests combining multiple inspection methods."""

    def test_complex_command(self):
        command = 'cat data.csv | grep pattern | awk "{print $1}" | sort -u > results.txt'
        tree = parse_ast(command)
        
        # Test get_commands
        commands = get_commands(tree)
        assert 'cat' in commands
        assert 'grep' in commands
        assert 'awk' in commands
        assert 'sort' in commands
        
        # Test find_commands
        call_exprs = find_commands(tree)
        assert len(call_exprs) == 4
        
        # Test has_pipe
        assert has_pipe(tree)
        
        # Test get_target_files
        targets = get_target_files(tree)
        assert len(targets) == 1
        assert targets[0] == 'results.txt'
        
        # Test get_arguments
        args = get_arguments(tree)
        assert len(args) == 4

    def test_variable_detection_with_visitor(self):
        tree = parse_ast('echo $HOME')
        
        variables = []
        
        class VariableVisitor(Visitor):
            def visit_part(self, node):
                if node.type in ("Var", "ParamExp"):
                    variables.append(node)
        
        VariableVisitor().walk(tree)
        assert len(variables) == 1

    def test_visitor_command_collection(self):
        """Test using visitor to collect commands (alternative to find_commands)."""
        tree = parse_ast('cat file.txt | grep pattern')
        
        collected = []
        
        class CommandCollector(Visitor):
            def visit_call_expr(self, node):
                if node.args:
                    collected.append(node)
        
        CommandCollector().walk(tree)
        assert len(collected) == 2