"""Comprehensive tests for Phase 2: AST inspection, visitor pattern, and new helper methods."""

from lovely_bash_permissions import (
    Visitor,
    find_arguments,
    find_commands,
    get_arguments,
    get_commands,
    get_target_files,
    has_pipe,
    parse_ast,
)


class TestVisitorPattern:
    """Test the AST visitor pattern."""

    def test_basic_visitor(self):
        tree = parse_ast("ls -la | grep txt > output.txt")

        visited = {"File": 0, "Stmt": 0, "CallExpr": 0, "BinaryCmd": 0}

        class CountVisitor(Visitor):
            def visit_file(self, node):
                visited["File"] += 1

            def visit_stmt(self, node):
                visited["Stmt"] += 1

            def visit_call_expr(self, node):
                visited["CallExpr"] += 1

            def visit_binary_cmd(self, node):
                visited["BinaryCmd"] += 1

        visitor = CountVisitor()
        visitor.walk(tree)

        assert visited["File"] == 1
        assert visited["Stmt"] == 1
        assert visited["CallExpr"] == 2
        assert visited["BinaryCmd"] == 1

    def test_word_visitor(self):
        tree = parse_ast("cat file.txt")
        word_count = 0

        class WordCountVisitor(Visitor):
            def visit_word(self, node):
                nonlocal word_count
                word_count += 1

        WordCountVisitor().walk(tree)
        assert word_count == 2

    def test_part_visitor(self):
        tree = parse_ast("ls -la")
        part_count = 0

        class PartCountVisitor(Visitor):
            def visit_part(self, node):
                nonlocal part_count
                part_count += 1

            def visit_lit(self, node):
                nonlocal part_count
                part_count += 1

        PartCountVisitor().walk(tree)
        assert part_count == 2

    def test_recursive_visit(self):
        tree = parse_ast("cat file1.txt | grep pattern")

        call_expr_names = []

        class CollectVisitor(Visitor):
            def visit_call_expr(self, node):
                nonlocal call_expr_names
                if node.args:
                    call_expr_names.append(node)

        CollectVisitor().walk(tree)
        assert len(call_expr_names) == 2

    def test_visit_dispatch(self):
        tree = parse_ast("echo hello")
        method_calls = []

        class DispatchVisitor(Visitor):
            def visit_file(self, node):
                method_calls.append("file")

            def visit_stmt(self, node):
                method_calls.append("stmt")

            def visit_call_expr(self, node):
                method_calls.append("call")

        visitor = DispatchVisitor()
        visitor.walk(tree)
        assert method_calls == ["file", "stmt", "call"]


class TestFindCommands:
    """Test find_commands() - find all CallExpr nodes."""

    def test_single_command(self):
        commands = find_commands(parse_ast("ls"))
        assert len(commands) == 1

    def test_multiple_commands_with_pipe(self):
        commands = find_commands(parse_ast("cat file.txt | grep pattern"))
        assert len(commands) == 2

    def test_complex_pipeline(self):
        commands = find_commands(
            parse_ast('cat data.csv | grep pattern | awk "{print $1}" | sort -u')
        )
        assert len(commands) == 4

    def test_no_commands(self):
        commands = find_commands(parse_ast('export PATH="/usr/bin"'))
        assert len(commands) == 0


class TestFindArguments:
    """Test find_arguments() - find all argument lists."""

    def test_no_arguments(self):
        args = find_arguments(parse_ast("ls"))
        assert len(args) == 1

    def test_single_command_with_args(self):
        args = find_arguments(parse_ast("cat file.txt"))
        assert len(args) == 1
        assert len(args[0]) == 1

    def test_multiple_commands(self):
        args = find_arguments(parse_ast("ls -la | grep -i txt"))
        assert len(args) == 2


class TestHasPipe:
    """Test has_pipe() - check for pipe operators."""

    def test_no_pipe(self):
        assert not has_pipe(parse_ast("ls -la"))

    def test_single_pipe(self):
        assert has_pipe(parse_ast("cat file.txt | grep pattern"))

    def test_multiple_pipes(self):
        assert has_pipe(parse_ast("cat file.txt | grep pattern | sort | uniq"))

    def test_nested_commands(self):
        assert not has_pipe(parse_ast("ls\\ngrep pattern"))

    def test_redirection_without_pipe(self):
        assert not has_pipe(parse_ast("cat file.txt > output.txt"))


class TestGetTargetFiles:
    """Test get_target_files() - extract file targets from redirections."""

    def test_no_redirections(self):
        assert get_target_files(parse_ast("ls -la")) == []

    def test_output_redirect(self):
        targets = get_target_files(parse_ast("cat file.txt > output.txt"))
        assert len(targets) == 1

    def test_input_redirect(self):
        targets = get_target_files(parse_ast("sort < input.txt"))
        assert len(targets) == 1

    def test_append_redirect(self):
        targets = get_target_files(parse_ast("cat file.txt >> output.txt"))
        assert len(targets) == 1

    def test_multiple_redirections(self):
        targets = get_target_files(parse_ast("cat file.txt > output.txt 2> errors.txt"))
        assert len(targets) == 2


class TestIntegration:
    """Integration tests combining multiple inspection methods."""

    def test_complex_command(self):
        command = (
            'cat data.csv | grep pattern | awk "{print $1}" | sort -u > results.txt'
        )
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

    def test_variable_detection_with_visitor(self):
        tree = parse_ast("echo $HOME")
        variables = []

        class VariableVisitor(Visitor):
            def visit_part(self, node):
                if node.type in ("Var", "ParamExp"):
                    variables.append(node)

        VariableVisitor().walk(tree)
        assert len(variables) == 1

    def test_visitor_command_collection(self):
        tree = parse_ast("cat file.txt | grep pattern")

        collected = []

        class CommandCollector(Visitor):
            def visit_call_expr(self, node):
                if node.args:
                    collected.append(node)

        CommandCollector().walk(tree)
        assert len(collected) == 2
