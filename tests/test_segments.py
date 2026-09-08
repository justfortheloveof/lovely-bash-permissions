"""
Comprehensive tests for the bash command segment parser.
"""

from lovely_bash_permissions.segments import parse_segments


class TestSimpleCommands:
    """Tests for simple commands."""

    def test_single_command(self) -> None:
        segs = parse_segments("ls")
        assert len(segs) == 1
        assert segs[0]["command"] == "ls"
        assert segs[0]["arguments"] == []
        assert segs[0]["redirections"] == []

    def test_command_with_arguments(self) -> None:
        segs = parse_segments("echo hello")
        assert len(segs) == 1
        assert segs[0]["command"] == "echo"
        assert segs[0]["arguments"] == ["hello"]
        assert segs[0]["redirections"] == []

    def test_command_with_multiple_arguments(self) -> None:
        segs = parse_segments("cp file1.txt file2.txt")
        assert len(segs) == 1
        assert segs[0]["command"] == "cp"
        assert segs[0]["arguments"] == ["file1.txt", "file2.txt"]
        assert segs[0]["redirections"] == []

    def test_command_with_flags(self) -> None:
        segs = parse_segments("ls -la")
        assert len(segs) == 1
        assert segs[0]["command"] == "ls"
        assert segs[0]["arguments"] == ["-la"]
        assert segs[0]["redirections"] == []

    def test_command_with_path_argument(self) -> None:
        segs = parse_segments("cd /tmp")
        assert len(segs) == 1
        assert segs[0]["command"] == "cd"
        assert segs[0]["arguments"] == ["/tmp"]
        assert segs[0]["redirections"] == []


class TestPipes:
    """Tests for pipe operations."""

    def test_simple_pipe(self) -> None:
        segs = parse_segments("ls | grep txt")
        assert len(segs) == 2
        assert segs[0]["command"] == "ls"
        assert segs[0]["arguments"] == []
        assert segs[1]["command"] == "grep"
        assert segs[1]["arguments"] == ["txt"]

    def test_pipe_with_arguments(self) -> None:
        segs = parse_segments("cat file.txt | head -5")
        assert len(segs) == 2
        assert segs[0]["command"] == "cat"
        assert segs[0]["arguments"] == ["file.txt"]
        assert segs[1]["command"] == "head"
        assert segs[1]["arguments"] == ["-5"]

    def test_multiple_pipes(self) -> None:
        segs = parse_segments("cat a.txt | grep x | head -5")
        assert len(segs) == 3
        assert segs[0]["command"] == "cat"
        assert segs[0]["arguments"] == ["a.txt"]
        assert segs[1]["command"] == "grep"
        assert segs[1]["arguments"] == ["x"]
        assert segs[2]["command"] == "head"
        assert segs[2]["arguments"] == ["-5"]


class TestLogicalAnd:
    """Tests for logical AND (&&) operations."""

    def test_simple_and(self) -> None:
        segs = parse_segments("cd /tmp && ls")
        assert len(segs) == 2
        assert segs[0]["command"] == "cd"
        assert segs[0]["arguments"] == ["/tmp"]
        assert segs[1]["command"] == "ls"
        assert segs[1]["arguments"] == []

    def test_and_with_arguments(self) -> None:
        segs = parse_segments("test -f file && cat file")
        assert len(segs) == 2
        assert segs[0]["command"] == "test"
        assert segs[0]["arguments"] == ["-f", "file"]
        assert segs[1]["command"] == "cat"
        assert segs[1]["arguments"] == ["file"]

    def test_multiple_and(self) -> None:
        segs = parse_segments("cd /tmp && ls && cat file")
        assert len(segs) == 3
        assert segs[0]["command"] == "cd"
        assert segs[0]["arguments"] == ["/tmp"]
        assert segs[1]["command"] == "ls"
        assert segs[1]["arguments"] == []
        assert segs[2]["command"] == "cat"
        assert segs[2]["arguments"] == ["file"]


class TestLogicalOr:
    """Tests for logical OR (||) operations."""

    def test_simple_or(self) -> None:
        segs = parse_segments("test -f file || echo missing")
        assert len(segs) == 2
        assert segs[0]["command"] == "test"
        assert segs[0]["arguments"] == ["-f", "file"]
        assert segs[1]["command"] == "echo"
        assert segs[1]["arguments"] == ["missing"]

    def test_multiple_or(self) -> None:
        segs = parse_segments("test -f a || test -f b || echo none")
        assert len(segs) == 3
        assert segs[0]["command"] == "test"
        assert segs[0]["arguments"] == ["-f", "a"]
        assert segs[1]["command"] == "test"
        assert segs[1]["arguments"] == ["-f", "b"]
        assert segs[2]["command"] == "echo"
        assert segs[2]["arguments"] == ["none"]


class TestBackground:
    """Tests for background execution."""

    def test_simple_background(self) -> None:
        segs = parse_segments("sleep 1 &")
        assert len(segs) == 1
        assert segs[0]["command"] == "sleep"
        assert segs[0]["arguments"] == ["1"]

    def test_background_with_command(self) -> None:
        segs = parse_segments("cd /tmp && ls &")
        assert len(segs) == 2
        assert segs[0]["command"] == "cd"
        assert segs[0]["arguments"] == ["/tmp"]
        assert segs[1]["command"] == "ls"
        assert segs[1]["arguments"] == []


class TestSequentialStatements:
    """Tests for sequential commands."""

    def test_sequential_commands(self) -> None:
        segs = parse_segments("cd /tmp; ls")
        assert len(segs) == 2
        assert segs[0]["command"] == "cd"
        assert segs[0]["arguments"] == ["/tmp"]
        assert segs[1]["command"] == "ls"
        assert segs[1]["arguments"] == []

    def test_multiple_sequential(self) -> None:
        segs = parse_segments("cd /tmp; ls; cat file")
        assert len(segs) == 3
        assert segs[0]["command"] == "cd"
        assert segs[0]["arguments"] == ["/tmp"]
        assert segs[1]["command"] == "ls"
        assert segs[1]["arguments"] == []
        assert segs[2]["command"] == "cat"
        assert segs[2]["arguments"] == ["file"]


class TestComplexExpressions:
    """Tests for complex command expressions."""

    def test_and_then_or(self) -> None:
        segs = parse_segments("cd /tmp && ls || echo empty")
        assert len(segs) == 3
        assert segs[0]["command"] == "cd"
        assert segs[0]["arguments"] == ["/tmp"]
        assert segs[1]["command"] == "ls"
        assert segs[1]["arguments"] == []
        assert segs[2]["command"] == "echo"
        assert segs[2]["arguments"] == ["empty"]

    def test_pipe_and_and(self) -> None:
        segs = parse_segments("ls | grep x && echo found")
        assert len(segs) == 3
        assert segs[0]["command"] == "ls"
        assert segs[0]["arguments"] == []
        assert segs[1]["command"] == "grep"
        assert segs[1]["arguments"] == ["x"]
        assert segs[2]["command"] == "echo"
        assert segs[2]["arguments"] == ["found"]

    def test_complex_piping(self) -> None:
        segs = parse_segments("cat a.txt | grep x | head -5 | tee b.txt | wc -l")
        assert len(segs) == 5
        assert segs[0]["command"] == "cat"
        assert segs[0]["arguments"] == ["a.txt"]
        assert segs[1]["command"] == "grep"
        assert segs[1]["arguments"] == ["x"]
        assert segs[2]["command"] == "head"
        assert segs[2]["arguments"] == ["-5"]
        assert segs[3]["command"] == "tee"
        assert segs[3]["arguments"] == ["b.txt"]
        assert segs[4]["command"] == "wc"
        assert segs[4]["arguments"] == ["-l"]

    def test_nested_and_or_pipes(self) -> None:
        segs = parse_segments("cd /tmp && ls | grep txt > output.txt")
        assert len(segs) == 3
        assert segs[0]["command"] == "cd"
        assert segs[0]["arguments"] == ["/tmp"]
        assert segs[1]["command"] == "ls"
        assert segs[1]["arguments"] == []
        assert segs[2]["command"] == "grep"
        assert segs[2]["arguments"] == ["txt"]


class TestEdgeCases:
    """Tests for edge cases."""

    def test_empty_command(self) -> None:
        segs = parse_segments("")
        assert segs == []

    def test_whitespace_only_command(self) -> None:
        segs = parse_segments("   ")
        assert segs == []

    def test_whitespace_surrounding_command(self) -> None:
        segs = parse_segments("  ls -la  ")
        assert len(segs) == 1
        assert segs[0]["command"] == "ls"
        assert segs[0]["arguments"] == ["-la"]

    def test_quoted_arguments(self) -> None:
        segs = parse_segments('echo "hello world"')
        assert len(segs) == 1
        assert segs[0]["command"] == "echo"
        assert len(segs[0]["arguments"]) == 1

    def test_variable_arguments(self) -> None:
        segs = parse_segments("echo $HOME")
        assert len(segs) == 1
        assert segs[0]["command"] == "echo"
        assert len(segs[0]["arguments"]) == 1

    def test_command_substitution(self) -> None:
        segs = parse_segments("echo $(date)")
        assert len(segs) == 2
        assert segs[0]["command"] == "echo"
        assert len(segs[0]["arguments"]) == 1
        assert segs[1]["command"] == "date"

    def test_invalid_bash_syntax(self) -> None:
        segs = parse_segments("((((")
        assert segs == []

    def test_semicolon_separator(self) -> None:
        segs = parse_segments("ls;cat")
        assert len(segs) == 2
        assert segs[0]["command"] == "ls"
        assert segs[1]["command"] == "cat"


class TestDialect:
    """Tests for shell dialect handling."""

    def test_default_dialect_is_bash(self) -> None:
        segs = parse_segments("ls")
        assert len(segs) == 1
        assert segs[0]["command"] == "ls"

    def test_posix_dialect(self) -> None:
        segs = parse_segments("ls", dialect="posix")
        assert len(segs) == 1
        assert segs[0]["command"] == "ls"


class TestErrorHandling:
    """Tests for error handling."""

    def test_parse_error_returns_empty(self) -> None:
        segs = parse_segments("(((((")
        assert segs == []
