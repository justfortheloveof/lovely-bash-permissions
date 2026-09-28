"""
Comprehensive tests for the bash command segment parser.
"""

from typing import Any, ClassVar

from lovely_bash_permissions.evaluate import evaluate_bash_command
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
    """DeclClause (export/readonly/local/declare/typeset) segment extraction.

    A declaration builtin's operands *are* variable assignments - `export
    FOO=bar` assigns exactly as `FOO=bar` does, and `local x=1` likewise - so
    they are split into their own variable-assignment segment (the one whose
    ``command`` is ``""``), the same way the CallExpr handler splits
    `FOO=bar ls`.  The variant keyword stays a command segment in its own
    right, because it really does run.

    Why the split matters: ``variable_assignment`` is only consulted for
    segments with an empty command, so hanging the operands off the variant
    segment meant the policy never reached them.  With
    ``{"*": "allow", "variable_assignment": "deny"}`` the bare ``FOO=bar``
    denied while ``export FOO=bar`` was approved - the policy was bypassed by
    typing one extra word.
    """

    def test_export_is_a_command_segment(self) -> None:
        # `export` still runs, so it is still a command segment - but its
        # operands now live on the variable-assignment segment ahead of it.
        segs = parse_segments("export BOGUS=true bogus")
        assert [s["command"] for s in segs] == ["", "export"]
        assert segs[0]["arguments"] == ["BOGUS=true", "bogus"]
        assert segs[1]["arguments"] == []

    def test_export_operand_is_its_own_variable_assignment_segment(self) -> None:
        segs = parse_segments("export FOO=bar")
        assert [(s["command"], s["arguments"]) for s in segs] == [("", ["FOO=bar"]), ("export", [])]

    def test_export_no_duplicate_segments(self) -> None:
        # Exactly one variable-assignment segment plus one keyword segment: the
        # operand is reported once, not once as an assignment and again as an
        # argument of `export`.
        segs = parse_segments("export FOO=bar")
        assert [(s["command"], s["arguments"]) for s in segs] == [("", ["FOO=bar"]), ("export", [])]
        segs = parse_segments("export BOGUS=true bogus")
        assert [(s["command"], s["arguments"]) for s in segs] == [("", ["BOGUS=true", "bogus"]), ("export", [])]

    def test_export_multiple_naked_names(self) -> None:
        segs = parse_segments("export FOO bar")
        assert [(s["command"], s["arguments"]) for s in segs] == [("", ["FOO", "bar"]), ("export", [])]

    def test_export_value_cmdsubst_extracted(self) -> None:
        # `export FOO=$(rm x)` is a real execution *and* a real assignment, so
        # it yields both: the variable-assignment segment (which the
        # `variable_assignment` policy gates) and the substituted command
        # itself (which the substitution policies gate).
        segs = parse_segments("export FOO=$(rm x)")
        assert [(s["command"], s["arguments"]) for s in segs] == [
            ("", ["FOO=$(...)"]),
            ("export", []),
            ("rm", ["x"]),
        ]

    def test_export_bare_substitution_operand(self) -> None:
        # `export $(cmd)` - the whole operand is a substitution, and it is still
        # reported as an assignment alongside the command it runs.
        segs = parse_segments("export $(cmd)")
        assert [(s["command"], s["arguments"]) for s in segs] == [
            ("", ["$(...)"]),
            ("export", []),
            ("cmd", []),
        ]

    def test_export_flag_operands(self) -> None:
        segs = parse_segments("export -f foo")
        assert [(s["command"], s["arguments"]) for s in segs] == [("", ["-f", "foo"]), ("export", [])]

    def test_declclause_variants_are_commands(self) -> None:
        for source, variant, operands in [
            ("readonly FOO", "readonly", ["FOO"]),
            ("local x=1 y=2", "local", ["x=1", "y=2"]),
            ("declare FOO=1", "declare", ["FOO=1"]),
            ("typeset -x FOO", "typeset", ["-x", "FOO"]),
        ]:
            segs = parse_segments(source)
            assert [(s["command"], s["arguments"]) for s in segs] == [("", operands), (variant, [])], source

    def test_declclause_array_operand(self) -> None:
        segs = parse_segments("declare -a arr=(a b)")
        assert [(s["command"], s["arguments"]) for s in segs] == [("", ["-a", "arr=(a b)"]), ("declare", [])]

    def test_declclause_array_value_cmdsubst_extracted(self) -> None:
        # The substitution carve-out only inspects the assignment's `value`, not
        # its array *elements*, so `arr=($(ls))` keeps its variable-assignment
        # segment - matching the pre-existing CallExpr behaviour for
        # `A=($(ls))` - while still surfacing the command that really runs.
        segs = parse_segments("declare -a arr=($(ls))")
        assert [(s["command"], s["arguments"]) for s in segs] == [
            ("", ["-a", "arr=($(...))"]),
            ("declare", []),
            ("ls", []),
        ]

    def test_bare_variant_without_operands_yields_no_segments(self) -> None:
        # `export` on its own assigns nothing, and a keyword segment is only
        # emitted alongside an operand - so the operand-less form produces no
        # segments at all, as it did before the split.
        assert parse_segments("export") == []
        assert parse_segments("readonly") == []


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

    def test_binary_test_operands_are_values_not_commands(self) -> None:
        # `[[ ]]` never executes its operands, so neither the left nor the
        # `&&` right operand is a command - only substitutions inside them run.
        assert parse_segments("[[ -d /tmp && ls ]]") == []


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
        # segment. The test body itself yields no segments any more (its
        # operands are values), so nothing else could carry it.
        segs = parse_segments("[[ -d /tmp && ls ]] > /tmp/out")
        carrying = [s for s in segs if s["redirections"]]
        assert len(carrying) == 1
        assert carrying[0]["command"] == "[["
        assert carrying[0]["redirections"][0]["Op"] == ">"

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

    def test_logical_rhs_operand_not_extracted(self) -> None:
        # The `&&` right operand is a value, not a command.
        assert [s["command"] for s in parse_segments("[[ -d /tmp && ls ]]")] == []

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
    TimeClause/CoprocClause/FuncDecl, silently dropping trailing redirections -
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


class TestRedirectionOnlyOperands:
    """Redirection-only operands of && / || / | (NEW_BUGS #3).

    shfmt emits these as operand dicts with Redirs but no Type and no Cmd,
    e.g. `> /etc/x && cat file`. The converter turns them into Stmt(cmd=None)
    and the segment parser emits a synthetic redir-only segment - otherwise
    the redirection is silently dropped and bypasses all redir/blocked-path
    checks. (The redir can be duplicated cosmetically inside the segment; do
    not assert on the exact redirection count.)
    """

    def test_and_left_redirection_only(self) -> None:
        segs = parse_segments("> /etc/x && cat file")
        assert len(segs) == 2
        assert segs[0]["command"] == ""
        assert segs[0]["arguments"] == []
        redir = segs[0]["redirections"][0]
        assert redir["Op"] == ">"
        assert redir["Target"] == "/etc/x"

    def test_pipe_right_redirection_only(self) -> None:
        segs = parse_segments("true | > /etc/x")
        assert len(segs) == 2
        assert segs[1]["command"] == ""
        assert segs[1]["arguments"] == []
        redir = segs[1]["redirections"][0]
        assert redir["Op"] == ">"
        assert redir["Target"] == "/etc/x"

    def test_or_right_redirection_only(self) -> None:
        segs = parse_segments("cat file || > /etc/x")
        assert len(segs) == 2
        assert segs[1]["command"] == ""
        assert segs[1]["arguments"] == []
        redir = segs[1]["redirections"][0]
        assert redir["Op"] == ">"
        assert redir["Target"] == "/etc/x"


class TestErrorHandling:
    """Tests for error handling."""

    def test_parse_error_returns_empty(self) -> None:
        segs = parse_segments("(((((")
        assert segs == []


class TestForLoopListSegments:
    """for-loop list words are evaluated before the body (bug #5)."""

    def test_cmdsubst_in_loop_list_extracted(self) -> None:
        assert [s["command"] for s in parse_segments("for i in $(seq 3); do echo $i; done")] == ["seq", "echo"]

    def test_cmdsubst_among_literal_words(self) -> None:
        assert [s["command"] for s in parse_segments("for f in a $(ls) b; do echo $f; done")] == ["ls", "echo"]

    def test_literal_loop_list_unchanged(self) -> None:
        assert [s["command"] for s in parse_segments("for i in 1 2 3; do echo hi; done")] == ["echo"]


class TestArithmeticCommandSubstitutions:
    """``(( expr ))`` runs no command, but still evaluates substitutions.

    The ``ArithmCmd`` handler used to ``pass``, so a command substitution
    inside ``(( ... ))`` produced no segment at all.  Zero segments fall
    through the empty-segment path to the wildcard, so under
    ``{"*": "allow", "command_substitution": "allow"}``
    ``(( x=$(rm -rf /) ))`` was auto-approved with nothing having inspected the
    ``rm``.  Every sibling spelling already recursed; this brings ``(( ... ))``
    in line.  The arithmetic itself must still produce no segment.
    """

    CONFIG: ClassVar[dict[str, Any]] = {
        "*": "ask",
        "command_substitution": "allow",
        "allowed_cmds_regex": [r"^ls$"],
    }

    def test_cmdsubst_in_arithmetic_command_extracted(self) -> None:
        assert [s["command"] for s in parse_segments("(( x=$(rm -rf /) ))")] == ["rm"]

    def test_arithmetic_only_produces_no_segments(self) -> None:
        # Nothing here is a command; the walk must not invent one.
        for source in ("(( y=1 ))", "(( x=1+2 ))", "(( arr[i]=0 ))", "(( i<n ))", "(( x=0x10 ))"):
            assert parse_segments(source) == [], source

    def test_nested_substitutions_in_arithmetic_extracted(self) -> None:
        assert [s["command"] for s in parse_segments("(( x=$(( $(n) + 1 )) ))")] == ["n"]
        assert [s["command"] for s in parse_segments("(( y=${a:-$(cmd)} ))")] == ["cmd"]

    def test_hidden_command_is_gated_by_the_allowlist(self) -> None:
        # The regression that mattered: this used to report "produced no
        # parseable segments" and fall to the wildcard instead of naming rm.
        result = evaluate_bash_command("(( x=$(rm -rf /) ))", self.CONFIG)
        assert result["status"] == "ask"
        assert '"rm" command does not match allowed patterns' in result["reason"]
        assert "produced no parseable segments" not in result["reason"]

    def test_agrees_with_sibling_spellings(self) -> None:
        # All five spellings of the same substitution must now be gated alike.
        for source in (
            "(( x=$(rm -rf /) ))",
            "x=$(rm -rf /)",
            "let x=$(rm -rf /)",
            "[[ -n $(rm -rf /) ]]",
            "$(( $(rm -rf /) ))",
        ):
            assert evaluate_bash_command(source, self.CONFIG)["status"] == "ask", source

    def test_arithmetic_only_still_falls_to_the_wildcard(self) -> None:
        # No command means nothing to allow-list, so the wildcard still decides.
        result = evaluate_bash_command("(( y=1 ))", self.CONFIG)
        assert result["segments"] == []
        assert result["status"] == "ask"

    def test_blocked_scan_reaches_the_hidden_command(self) -> None:
        result = evaluate_bash_command("(( x=$(cat /etc/passwd) ))", {"*": "ask", "blocked_cmds_regex": [r"\/etc"]})
        assert result["status"] == "deny"


class TestAssignOperandSubstitutions:
    """Command substitutions inside assignment operands are always walked.

    An assignment's value, subscript or array elements can contain command
    substitutions and bash runs them.  The walk used to exist only on the
    *standalone* assignment path, so an assignment **prefix** hid the whole
    substitution: `x=$(cmd) ls` reported no segment for `cmd`, and a
    redirection inside it escaped `output_redirection` / `input_redirection`
    entirely while the identical standalone form was denied.
    """

    def test_assign_prefix_surfaces_the_inner_command(self) -> None:
        assert [s["command"] for s in parse_segments("x=$(rm -rf /) ls")] == ["", "ls", "rm"]

    def test_array_assign_prefix_surfaces_the_inner_command(self) -> None:
        assert [s["command"] for s in parse_segments("A=$(rm -rf /) ls")] == ["", "ls", "rm"]

    def test_all_spellings_agree(self) -> None:
        # Prefix, standalone and declaration forms must extract identically.
        for source in ("x=$(rm -rf /) ls", "x=$(rm -rf /)", "export x=$(rm -rf /)"):
            assert "rm" in [s["command"] for s in parse_segments(source)], source

    def test_redirection_inside_a_prefix_substitution_is_visible(self) -> None:
        # The redirection must land on a segment, which is what the
        # redirection policies read.
        segs = parse_segments("x=$(echo hi > /tmp/f) ls")
        assert [(s["command"], [r["Op"] for r in s["redirections"]]) for s in segs] == [
            ("", []),
            ("ls", []),
            ("echo", [">"]),
        ]

    def test_standalone_form_is_not_double_counted(self) -> None:
        segs = parse_segments("x=$(echo hi > /tmp/f)")
        assert [(s["command"], [r["Op"] for r in s["redirections"]]) for s in segs] == [("", []), ("echo", [">"])]

    def test_literal_assignments_produce_no_extra_segments(self) -> None:
        # No substitution, so nothing extra may appear.
        assert [s["command"] for s in parse_segments("FOO=bar ls")] == ["", "ls"]
        assert [s["command"] for s in parse_segments("FOO=bar")] == [""]

    def test_output_redirection_deny_fires_for_the_prefix_form(self) -> None:
        cfg: dict[str, Any] = {"*": "allow", "output_redirection": "deny"}
        for source in (
            "x=$(echo hi > /tmp/f) ls",
            "x=$(echo hi > /tmp/f)",
            "export x=$(echo hi > /tmp/f)",
            "A=$(echo hi > /tmp/f) ls",
            "ls; x=$(echo hi > /tmp/f)",
        ):
            assert evaluate_bash_command(source, cfg)["status"] == "deny", source

    def test_input_redirection_deny_fires_for_the_prefix_form(self) -> None:
        cfg: dict[str, Any] = {"*": "allow", "input_redirection": "deny"}
        for source in ("x=$(cat < /tmp/f) ls", "x=$(cat < /tmp/f)"):
            assert evaluate_bash_command(source, cfg)["status"] == "deny", source


class TestCommandNameSubstitutions:
    """A command name that is an expansion still runs what it expands to.

    `CallExpr` recursed into `args[1:]` but not `args[0]`, so a substitution in
    *command-name* position was never walked. The inner command was still gated
    for allow-matching (the evaluator's nested-CallExpr walk finds it) and
    blocked patterns still saw the raw text, but a redirection inside it escaped
    `output_redirection` / `input_redirection` entirely:

        {"*": "allow", "output_redirection": "deny"}
        $(echo hi > /tmp/f)   ->  allow   (the write slipped through)
    """

    def test_substitution_in_command_name_is_extracted(self) -> None:
        assert [s["command"] for s in parse_segments("$(rm -rf /)")] == ["$(...)", "rm"]
        assert [s["command"] for s in parse_segments("`rm -rf /`")] == ["$(...)", "rm"]

    def test_param_default_in_command_name_is_extracted(self) -> None:
        assert [s["command"] for s in parse_segments("${x:-$(rm -rf /)}")] == ["${x:-$(...)}", "rm"]

    def test_command_name_substitution_keeps_the_command_position(self) -> None:
        segs = parse_segments("$(which rm) -rf /")
        assert segs[0]["command"] == "$(...)"
        assert segs[0]["arguments"] == ["-rf", "/"]
        assert segs[1]["command"] == "which"

    def test_plain_command_names_are_not_duplicated(self) -> None:
        for source, expected in (("ls", ["ls"]), ("echo hi", ["echo"]), ("grep -i x f", ["grep"])):
            assert [s["command"] for s in parse_segments(source)] == expected, source

    def test_output_redirection_deny_fires_in_command_name_position(self) -> None:
        cfg: dict[str, Any] = {"*": "allow", "output_redirection": "deny"}
        for source in ("$(echo hi > /tmp/f)", "$(echo hi > /tmp/f); ls", "${x:-$(echo hi > /tmp/f)}"):
            assert evaluate_bash_command(source, cfg)["status"] == "deny", source

    def test_input_redirection_deny_fires_in_command_name_position(self) -> None:
        cfg: dict[str, Any] = {"*": "allow", "input_redirection": "deny"}
        assert evaluate_bash_command("$(cat < /tmp/f)", cfg)["status"] == "deny"

    def test_each_policy_only_fires_for_its_own_direction(self) -> None:
        # Guard against the two policies cross-triggering.
        assert (
            evaluate_bash_command("$(echo hi > /tmp/f)", {"*": "allow", "input_redirection": "deny"})["status"]
            == "allow"
        )
        assert (
            evaluate_bash_command("$(cat < /tmp/f)", {"*": "allow", "output_redirection": "deny"})["status"] == "allow"
        )


class TestCStyleLoopSegments:
    """C-style for ((init; cond; post)) preludes are extracted (security-critical)."""

    def test_prelude_cmdsubst_extracted(self) -> None:
        segs = parse_segments("for ((i=$(seq 3); i < $n; i++)); do echo $i; done")
        assert [s["command"] for s in segs] == ["seq", "echo"]

    def test_literal_prelude_unchanged(self) -> None:
        assert [s["command"] for s in parse_segments("for ((i=0; i<10; i++)); do echo x; done")] == ["echo"]

    def test_degenerate_prelude(self) -> None:
        assert [s["command"] for s in parse_segments("for ((;;)); do :; done")] == [":"]


class TestBinaryTestLeftOperand:
    """Left operands of [[ ]] binary tests hold nested substitutions (bug #5)."""

    def test_left_operand_cmdsubst_extracted(self) -> None:
        assert [s["command"] for s in parse_segments("[[ $(pwd) == /root* ]]")] == ["pwd"]

    def test_both_sides_cmdsubst(self) -> None:
        assert [s["command"] for s in parse_segments("[[ $(a) == $(b) ]]")] == ["a", "b"]

    def test_literal_left_operand_still_no_phantom(self) -> None:
        # Neither side of a `&&` inside `[[ ]]` is a command.
        assert [s["command"] for s in parse_segments("[[ -d /tmp && ls ]]")] == []


class TestNoPhantomTestCommands:
    """$(...)/$var inside [[ ]] are not emitted as literal command names (bug #6)."""

    def test_cmdsubst_operand_is_real_command(self) -> None:
        assert [s["command"] for s in parse_segments("[[ $(cmd) ]]")] == ["cmd"]

    def test_cmdsubst_after_logical_and(self) -> None:
        assert [s["command"] for s in parse_segments("[[ -f x && $(c2) ]] && echo and")] == ["c2", "echo"]

    def test_quoted_cmdsubst(self) -> None:
        assert [s["command"] for s in parse_segments('[[ cond && "$(cmd)" ]]')] == ["cmd"]

    def test_bare_param_exp_not_a_command(self) -> None:
        assert parse_segments("[[ $var ]]") == []

    def test_quoted_param_exp_not_a_command(self) -> None:
        assert parse_segments('[[ "$var" ]]') == []

    def test_logical_and_literal_operand_not_extracted(self) -> None:
        # A literal in any test operand position is a value, not a command.
        assert [s["command"] for s in parse_segments("[[ -d /tmp && ls ]]")] == []

    def test_bare_literal_operand_not_a_command(self) -> None:
        # A bare literal in a test body is the value under test, not a
        # command - `[[ /etc/passwd ]]` must not report a `/etc/passwd`
        # command (its blocked-path text is covered by the whole-command
        # scan instead).
        assert [s["command"] for s in parse_segments("[[ foo ]]")] == []


class TestCaseCommandSubstitution:
    """case subject word and branch patterns are segments."""

    def test_case_word_command_substitution_extracted(self) -> None:
        """bug #8: the case subject word is a segment."""
        result = parse_segments("case $(evil) in a) echo 1;; esac")
        assert [s["command"] for s in result] == ["evil", "echo"]

    def test_case_branch_pattern_command_substitution_extracted(self) -> None:
        """bug #8: branch patterns are segments too."""
        result = parse_segments("case $x in $(evil)) echo hit;; esac")
        assert [s["command"] for s in result] == ["evil", "echo"]


class TestNormalizedArguments:
    """normalized_arguments: quote/backslash-normalized (executed) form of args."""

    def test_quote_split_argument_normalized(self) -> None:
        segs = parse_segments('cat /e"tc"/passwd')
        assert len(segs) == 1
        assert segs[0]["arguments"] == ['/e"tc"/passwd']
        assert segs[0]["normalized_arguments"] == ["/etc/passwd"]

    def test_backslash_escaped_flag_normalized(self) -> None:
        segs = parse_segments("find /tmp -ex\\ec rm")
        assert len(segs) == 1
        assert segs[0]["arguments"][1] == "-ex\\ec"
        assert segs[0]["normalized_arguments"][1] == "-exec"


class TestRedirTarget:
    """redirections carry the full executed-form target (all word parts)."""

    def test_quoted_param_exp_target(self) -> None:
        segs = parse_segments('echo hi > "$DIR/out.txt"')
        assert segs[0]["redirections"][0]["Target"] == "$DIR/out.txt"

    def test_concatenated_quoted_target(self) -> None:
        segs = parse_segments('echo hi 2>"/dev""/null"')
        assert segs[0]["redirections"][0]["Target"] == "/dev/null"
