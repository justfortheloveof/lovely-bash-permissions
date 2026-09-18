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


class TestDeclClause:
    """DeclClause (export/readonly/local/declare/typeset) segment extraction."""

    def test_export_is_a_command_segment(self) -> None:
        segs = parse_segments("export BOGUS=true bogus")
        assert [s["command"] for s in segs] == ["export"]
        assert segs[0]["arguments"] == ["BOGUS=true", "bogus"]

    def test_export_assignment_is_an_operand(self) -> None:
        segs = parse_segments("export FOO=bar")
        assert len(segs) == 1
        assert segs[0]["command"] == "export"
        assert segs[0]["arguments"] == ["FOO=bar"]

    def test_export_no_duplicate_segments(self) -> None:
        segs = parse_segments("export FOO=bar")
        assert len(segs) == 1
        segs = parse_segments("export BOGUS=true bogus")
        assert [s["command"] for s in segs] == ["export"]

    def test_export_multiple_naked_names(self) -> None:
        segs = parse_segments("export FOO bar")
        assert [s["command"] for s in segs] == ["export"]
        assert segs[0]["arguments"] == ["FOO", "bar"]

    def test_export_value_cmdsubst_extracted(self) -> None:
        # Command substitution in an assignment value is a real execution.
        segs = parse_segments("export FOO=$(rm x)")
        assert segs[0]["command"] == "export"
        assert any(s["command"] == "rm" for s in segs)

    def test_export_flag_operands(self) -> None:
        segs = parse_segments("export -f foo")
        assert segs[0]["command"] == "export"
        assert segs[0]["arguments"] == ["-f", "foo"]

    def test_declclause_variants_are_commands(self) -> None:
        for command, variant in [
            ("readonly FOO", "readonly"),
            ("local x=1 y=2", "local"),
            ("declare FOO=1", "declare"),
            ("typeset -x FOO", "typeset"),
        ]:
            segs = parse_segments(command)
            assert segs[0]["command"] == variant
            assert len(segs) == 1

    def test_declclause_array_operand(self) -> None:
        segs = parse_segments("declare -a arr=(a b)")
        assert segs[0]["command"] == "declare"
        assert segs[0]["arguments"] == ["-a", "arr=(...)"]

    def test_declclause_array_value_cmdsubst_extracted(self) -> None:
        # Command substitution inside an array element is a real execution.
        assert any(s["command"] == "ls" for s in parse_segments("declare -a arr=($(ls))"))


class TestConditionals:
    """if/elif/else and while segment extraction."""

    def test_if_then_extracted(self) -> None:
        assert any(s["command"] == "rm" for s in parse_segments("if true; then rm x; fi"))

    def test_if_cond_extracted(self) -> None:
        segs = parse_segments("if test -f x; then echo A; fi")
        assert [s["command"] for s in segs] == ["test", "echo"]

    def test_elif_branch_extracted(self) -> None:
        segs = parse_segments("if true; then echo A; elif true; then echo B; else echo C; fi")
        assert [s["command"] for s in segs] == ["true", "echo", "true", "echo", "echo"]

    def test_else_extracted(self) -> None:
        segs = parse_segments("if true; then echo A; else rm x; fi")
        assert [s["command"] for s in segs] == ["true", "echo", "rm"]


class TestTestClauses:
    """[[ ]] test-expression segment extraction."""

    def test_bare_unary_test_no_phantom_command(self) -> None:
        segs = parse_segments("[[ -d /tmp ]]")
        assert segs == []

    def test_unary_test_cmdsubst_extracted(self) -> None:
        assert any(s["command"] == "pwd" for s in parse_segments("[[ -d $(pwd) ]]"))

    def test_binary_test_right_operand_extracted(self) -> None:
        commands = [s["command"] for s in parse_segments("[[ -d /tmp && ls ]]")]
        assert "ls" in commands


class TestTestClauseRedirections:
    """[[ ]] statements with attached redirections."""

    def test_testclause_output_redirection_synthetic_segment(self) -> None:
        segs = parse_segments("[[ -f file ]] > /tmp/out")
        assert len(segs) == 1
        assert segs[0]["command"] == "[["
        assert segs[0]["redirections"][0]["Op"] == ">"
        assert segs[0]["redirections"][0]["Word"]["Parts"][0]["Value"] == "/tmp/out"

    def test_testclause_stderr_redirection_normalized(self) -> None:
        segs = parse_segments("[[ -f f ]] 2> /tmp/out")
        redir = segs[0]["redirections"][0]
        assert redir["Op"] == ">"
        assert redir["N"] == {"Value": "2"}

    def test_testclause_redir_with_command_body_keeps_single_redir(self) -> None:
        # The statement redirection must appear exactly once, on the synthetic
        # segment, and not be scattered onto the inner pseudo-command.
        segs = parse_segments("[[ -d /tmp && ls ]] > /tmp/out")
        carrying = [s for s in segs if s["redirections"]]
        assert len(carrying) == 1
        assert carrying[0]["command"] == "[["
        assert any(s["command"] == "ls" and s["redirections"] == [] for s in segs)

    def test_testclause_redir_with_nested_cmdsubst(self) -> None:
        segs = parse_segments("[[ -d $(pwd) ]] > /tmp/out")
        assert any(s["command"] == "pwd" for s in segs)
        assert any(s["command"] == "[[" and s["redirections"] for s in segs)

    def test_paren_test_redirection_synthetic_segment(self) -> None:
        segs = parse_segments("[[ ( -d /tmp ) ]] > /tmp/out")
        assert len(segs) == 1
        assert segs[0]["command"] == "[["
        assert segs[0]["redirections"]

    def test_bare_redirection_only_statement(self) -> None:
        segs = parse_segments("> /tmp/out")
        assert len(segs) == 1
        assert segs[0]["redirections"][0]["Op"] == ">"
        assert segs[0]["redirections"][0]["Word"]["Parts"][0]["Value"] == "/tmp/out"


class TestTestClauseRegexOperands:
    """[[ ]] =~ and comparison operands must not be treated as commands."""

    def test_regex_match_rhs_not_a_command(self) -> None:
        assert parse_segments("[[ $var =~ pat ]]") == []

    def test_regex_metachars_rhs_not_a_command(self) -> None:
        for cmd in ("[[ x =~ ^a.*$ ]]", "[[ x =~ (a|b) ]]", "[[ x =~ a.b$ ]]"):
            assert parse_segments(cmd) == [], cmd

    def test_glob_rhs_not_a_command(self) -> None:
        assert parse_segments("[[ $a == *.txt ]]") == []
        assert parse_segments("[[ $a != x ]]") == []

    def test_arithmetic_rhs_not_a_command(self) -> None:
        for cmd in ("[[ $n -eq 5 ]]", "[[ $n < 3 ]]", "[[ $n > 3 ]]", "[[ -f a -nt b ]]"):
            assert parse_segments(cmd) == [], cmd

    def test_cmdsubst_inside_regex_still_extracted(self) -> None:
        segs = parse_segments("[[ $var =~ $(cmd) ]]")
        assert [s["command"] for s in segs] == ["cmd"]

    def test_logical_rhs_still_extracted(self) -> None:
        commands = [s["command"] for s in parse_segments("[[ -d /tmp && ls ]]")]
        assert "ls" in commands

    def test_regex_rhs_with_redirection_no_phantom(self) -> None:
        segs = parse_segments("[[ $var =~ pat ]] > /tmp/out")
        commands = [s["command"] for s in segs]
        assert "pat" not in commands
        assert any(s["redirections"] for s in segs)


class TestNestedSubstitutionExtraction:
    """Nested command/process substitutions inside parts are extracted (issue #2)."""

    def test_cmdsubst_in_output_redirect_target(self) -> None:
        segs = parse_segments("echo hi > $(cat /etc/shells)")
        assert [s["command"] for s in segs] == ["echo", "cat"]

    def test_cmdsubst_in_input_redirect_target(self) -> None:
        segs = parse_segments("grep x < $(echo file.txt)")
        assert [s["command"] for s in segs] == ["grep", "echo"]

    def test_procsubst_in_output_redirect_target(self) -> None:
        segs = parse_segments("echo hi > >(grep foo)")
        assert [s["command"] for s in segs] == ["echo", "grep"]

    def test_cmdsubst_inside_double_quotes(self) -> None:
        segs = parse_segments('echo "$(whoami)"')
        assert [s["command"] for s in segs] == ["echo", "whoami"]

    def test_cmdsubst_in_param_exp_default(self) -> None:
        segs = parse_segments("echo ${x:-$(ls)}")
        assert [s["command"] for s in segs] == ["echo", "ls"]

    def test_cmdsubst_inside_arithmetic(self) -> None:
        segs = parse_segments("echo $(( $(ls) + 1 ))")
        assert [s["command"] for s in segs] == ["echo", "ls"]

    def test_cmdsubst_in_braced_index(self) -> None:
        segs = parse_segments("echo ${arr[$(cat idx)]}")
        assert [s["command"] for s in segs] == ["echo", "cat"]

    def test_cmdsubst_in_repl_replacement_extracted(self) -> None:
        # Bug 1: substitution in the replacement part of ${var/pat/rep}.
        segs = parse_segments("echo ${x//a/$(rm -rf x)}")
        assert [s["command"] for s in segs] == ["echo", "rm"]
        assert segs[1]["arguments"] == ["-rf", "x"]

    def test_cmdsubst_in_repl_pattern_extracted(self) -> None:
        # Bug 1: substitution in the *pattern* part of ${var/pat/rep}.
        segs = parse_segments("echo ${x//$(recon_cmd)/y}")
        assert [s["command"] for s in segs] == ["echo", "recon_cmd"]

    def test_cmdsubst_in_single_repl_extracted(self) -> None:
        # Bug 1: single-replacement form ${var/pat/rep} (Repl.All = false).
        segs = parse_segments("echo ${x/a/$(rm -rf x)}")
        assert [s["command"] for s in segs] == ["echo", "rm"]

    def test_cmdsubst_in_slice_extracted(self) -> None:
        # Bug 3: substitution in the offset/length of ${var:offset:length}.
        segs = parse_segments("echo ${x:0:$(cat N)}")
        assert [s["command"] for s in segs] == ["echo", "cat"]
        segs = parse_segments("echo ${x:$(seq 3)}")
        assert [s["command"] for s in segs] == ["echo", "seq"]

    def test_cmdsubst_in_standalone_assignment_extracted(self) -> None:
        segs = parse_segments("x=$(date)")
        assert [s["command"] for s in segs] == ["", "date"]

    def test_cmdsubst_assignment_redirection_carried(self) -> None:
        segs = parse_segments("x=$(echo hi > /etc/passwd)")
        assert [s["command"] for s in segs] == ["", "echo"]
        assert segs[1]["arguments"] == ["hi"]
        assert segs[1]["redirections"][0]["Op"] == ">"
        assert segs[1]["redirections"][0]["Word"]["Parts"][0]["Value"] == "/etc/passwd"

    def test_array_assignment_value_cmdsubst_extracted(self) -> None:
        segs = parse_segments("arr=($(ls > /tmp/out))")
        assert [s["command"] for s in segs] == ["", "ls"]
        assert segs[1]["redirections"][0]["Word"]["Parts"][0]["Value"] == "/tmp/out"

    def test_plain_parts_in_redirect_target_still_normal(self) -> None:
        segs = parse_segments("ls > /tmp/out")
        assert [s["command"] for s in segs] == ["ls"]


class TestCompoundCommandRedirections:
    """Redirections on time/funcdef/coproc compound commands are kept.

    Regression: the converter unwrapped the Stmt-shaped body/statement of
    TimeClause/CoprocClause/FuncDecl, silently dropping trailing redirections —
    so `time echo hi > /etc/passwd` was approved while the plain command was blocked.
    """

    def test_time_redirection_kept(self) -> None:
        segs = parse_segments("time echo hi > /etc/passwd")
        assert [s["command"] for s in segs] == ["echo"]
        assert segs[0]["redirections"][0]["Word"]["Parts"][0]["Value"] == "/etc/passwd"

    def test_time_posix_redirection_kept(self) -> None:
        segs = parse_segments("time -p echo hi > /etc/passwd")
        assert [s["command"] for s in segs] == ["echo"]
        assert segs[0]["redirections"][0]["Word"]["Parts"][0]["Value"] == "/etc/passwd"

    def test_funcdef_redirection_kept(self) -> None:
        segs = parse_segments("f() { echo hi; } > /etc/passwd")
        assert [s["command"] for s in segs] == ["echo"]
        assert segs[0]["redirections"][0]["Word"]["Parts"][0]["Value"] == "/etc/passwd"

    def test_coproc_redirection_kept(self) -> None:
        segs = parse_segments("coproc c { echo hi; } > /etc/passwd")
        assert [s["command"] for s in segs] == ["echo"]
        assert segs[0]["redirections"][0]["Word"]["Parts"][0]["Value"] == "/etc/passwd"


class TestErrorHandling:
    """Tests for error handling."""

    def test_parse_error_returns_empty(self) -> None:
        segs = parse_segments("(((((")
        assert segs == []
