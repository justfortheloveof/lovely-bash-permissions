"""
Comprehensive tests for AST node types.

Verifies all node dataclasses exist, are registered in NODE_TYPES,
and parse correctly. Tests each type by parsing bash commands and
inspecting the resulting AST structure.
"""

from lovely_bash_permissions import (
    ArithmExp,
    Block,
    BraceExp,
    CmdSubst,
    DblQuoted,
    FuncDecl,
    Lit,
    ParamExp,
    ProcSubst,
    SglQuoted,
    parse_ast,
)


class TestLitNodes:
    """Tests for the Lit node type."""

    def test_simple_literal_value(self):
        tree = parse_ast("ls")
        cmd = tree.stmts[0].cmd
        assert cmd.type == "CallExpr"
        assert len(cmd.args) == 1
        assert cmd.args[0].type == "Word"
        assert len(cmd.args[0].parts) == 1
        assert cmd.args[0].parts[0].type == "Lit"
        assert cmd.args[0].parts[0].value == "ls"

    def test_literal_argument(self):
        tree = parse_ast("echo hello")
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == "Lit"
        assert cmd.args[1].parts[0].value == "hello"

    def test_literal_file_name(self):
        tree = parse_ast("cat file.txt")
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == "Lit"
        assert cmd.args[1].parts[0].value == "file.txt"

    def test_literal_flag(self):
        tree = parse_ast("ls -la")
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == "Lit"
        assert cmd.args[1].parts[0].value == "-la"

    def test_multiple_literal_arguments(self):
        tree = parse_ast("cp file1.txt file2.txt")
        cmd = tree.stmts[0].cmd
        assert len(cmd.args) == 3
        assert cmd.args[2].parts[0].type == "Lit"
        assert cmd.args[2].parts[0].value == "file2.txt"

    def test_literal_in_pipe(self):
        tree = parse_ast("cat file.txt | grep pattern")
        cmd = tree.stmts[0].cmd
        assert cmd.type == "BinaryCmd"
        assert cmd.right.args[1].parts[0].type == "Lit"
        assert cmd.right.args[1].parts[0].value == "pattern"

    def test_literal_with_special_chars(self):
        tree = parse_ast("echo hello-world_123")
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == "Lit"
        assert cmd.args[1].parts[0].value == "hello-world_123"

    def test_literal_with_slash(self):
        tree = parse_ast("cat /path/to/file.txt")
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == "Lit"
        assert cmd.args[1].parts[0].value == "/path/to/file.txt"

    def test_no_literal_with_variable(self):
        tree = parse_ast("echo $HOME")
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == "ParamExp"

    def test_no_literal_with_command_substitution(self):
        tree = parse_ast("echo $(date)")
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == "CmdSubst"

    def test_no_literal_with_quoted_string(self):
        tree = parse_ast("echo 'quoted'")
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == "SglQuoted"

    def test_literal_in_redirect(self):
        tree = parse_ast("echo hello > output.txt")
        assert tree.stmts[0].redirs[0].word.parts[0].type == "Lit"
        assert tree.stmts[0].redirs[0].word.parts[0].value == "output.txt"

    def test_literal_number(self):
        tree = parse_ast("sleep 5")
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == "Lit"
        assert cmd.args[1].parts[0].value == "5"

    def test_literal_multiline(self):
        tree = parse_ast("echo a\necho b")
        assert tree.stmts[1].cmd.args[1].parts[0].type == "Lit"
        assert tree.stmts[1].cmd.args[1].parts[0].value == "b"

    def test_literal_in_subshell(self):
        tree = parse_ast("(echo hello)")
        cmd = tree.stmts[0].cmd
        assert cmd.type == "Subshell"
        assert cmd.stmts[0].cmd.args[1].parts[0].type == "Lit"
        assert cmd.stmts[0].cmd.args[1].parts[0].value == "hello"

    def test_literal_position_info(self):
        tree = parse_ast("ls -la")
        cmd = tree.stmts[0].cmd
        for arg in cmd.args:
            for part in arg.parts:
                if part.type == "Lit":
                    assert part.pos is not None
                    assert part.end is not None

    def test_lit_imported_in_module(self):
        assert Lit is not None


class TestSglQuotedNodes:
    """Tests for the SglQuoted node type."""

    def test_simple_single_quoted(self):
        tree = parse_ast("echo 'hello world'")
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == "SglQuoted"
        assert cmd.args[1].parts[0].value == "hello world"

    def test_single_quoted_no_expansion(self):
        tree = parse_ast("echo '$HOME'")
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == "SglQuoted"
        assert cmd.args[1].parts[0].value == "$HOME"

    def test_multiple_single_quoted(self):
        tree = parse_ast("echo 'a' 'b'")
        cmd = tree.stmts[0].cmd
        assert len(cmd.args) == 3
        assert cmd.args[1].parts[0].type == "SglQuoted"
        assert cmd.args[2].parts[0].type == "SglQuoted"

    def test_single_quoted_asterisk(self):
        tree = parse_ast("echo 'foo*'")
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == "SglQuoted"

    def test_single_quoted_empty(self):
        tree = parse_ast("echo ''")
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == "SglQuoted"

    def test_single_quoted_backslashes(self):
        tree = parse_ast("echo 'hello\\\\nworld'")
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == "SglQuoted"

    def test_single_quoted_position_info(self):
        tree = parse_ast("echo 'hello'")
        part = tree.stmts[0].cmd.args[1].parts[0]
        assert part.type == "SglQuoted"
        assert part.pos is not None

    def test_sgquoted_imported(self):
        assert SglQuoted is not None


class TestParamExpNodes:
    """Tests for the ParamExp node type."""

    def test_short_param_expansion(self):
        tree = parse_ast("echo $HOME")
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == "ParamExp"
        assert cmd.args[1].parts[0].param == "HOME"
        assert cmd.args[1].parts[0].short is True

    def test_braced_param_expansion(self):
        tree = parse_ast("echo ${HOME}")
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == "ParamExp"
        assert cmd.args[1].parts[0].short is False

    def test_param_expansion_with_default(self):
        tree = parse_ast("echo ${HOME:-default}")
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].exp is not None

    def test_array_index_param_expansion(self):
        tree = parse_ast("echo ${arr[0]}")
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].index is not None

    def test_param_expansion_in_double_quotes(self):
        tree = parse_ast('echo "$HOME"')
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == "DblQuoted"
        assert cmd.args[1].parts[0].parts[0].type == "ParamExp"

    def test_multiple_param_expansions(self):
        tree = parse_ast('echo "$HOME is $USER"')
        cmd = tree.stmts[0].cmd
        parts = cmd.args[1].parts[0].parts
        assert len(parts) == 3

    def test_length_param_expansion(self):
        tree = parse_ast("echo ${#HOME}")
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].length is True

    def test_param_expansion_position_info(self):
        tree = parse_ast("echo $HOME")
        part = tree.stmts[0].cmd.args[1].parts[0]
        assert part.type == "ParamExp"
        assert part.pos is not None

    def test_param_exp_imported(self):
        assert ParamExp is not None


class TestDblQuotedNodes:
    """Tests for the DblQuoted node type."""

    def test_simple_double_quoted(self):
        tree = parse_ast('echo "hello"')
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == "DblQuoted"

    def test_double_quoted_with_variable(self):
        tree = parse_ast('echo "hello $world"')
        cmd = tree.stmts[0].cmd
        parts = cmd.args[1].parts[0].parts
        assert len(parts) == 2

    def test_empty_double_quoted(self):
        tree = parse_ast('echo ""')
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == "DblQuoted"

    def test_double_quoted_preserves_spaces(self):
        tree = parse_ast('echo "a b c"')
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].parts[0].value == "a b c"

    def test_dblquoted_position_info(self):
        tree = parse_ast('echo "hello"')
        part = tree.stmts[0].cmd.args[1].parts[0]
        assert part.type == "DblQuoted"
        assert part.pos is not None

    def test_dblquoted_imported(self):
        assert DblQuoted is not None


class TestCmdSubstNodes:
    """Tests for the CmdSubst node type."""

    def test_simple_cmdsubst(self):
        tree = parse_ast("echo $(date)")
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == "CmdSubst"

    def test_cmdsubst_backquotes(self):
        tree = parse_ast("echo `date`")
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].backquotes is True

    def test_cmdsubst_in_double_quotes(self):
        tree = parse_ast('echo "hello $(date)"')
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == "DblQuoted"

    def test_nested_cmdsubst(self):
        tree = parse_ast("echo $(echo $(date))")
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == "CmdSubst"

    def test_cmdsubst_position_info(self):
        tree = parse_ast("echo $(date)")
        part = tree.stmts[0].cmd.args[1].parts[0]
        assert part.pos is not None

    def test_cmdsubst_imported(self):
        assert CmdSubst is not None


class TestArithmExpNodes:
    """Tests for the ArithmExp node type."""

    def test_simple_arithmetic(self):
        tree = parse_ast("echo $((2 + 2))")
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == "ArithmExp"

    def test_arithmetic_with_variables(self):
        tree = parse_ast("echo $((x + y))")
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == "ArithmExp"

    def test_arithmetic_in_double_quotes(self):
        tree = parse_ast('echo "$((5))"')
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == "DblQuoted"

    def test_arithmetic_position_info(self):
        tree = parse_ast("echo $((2 + 2))")
        part = tree.stmts[0].cmd.args[1].parts[0]
        assert part.pos is not None

    def test_arithmexp_imported(self):
        assert ArithmExp is not None


class TestProcSubstNodes:
    """Tests for the ProcSubst node type."""

    def test_input_process_substitution(self):
        tree = parse_ast("cat <(echo 'hi')")
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == "ProcSubst"

    def test_output_process_substitution(self):
        tree = parse_ast("sort > >(cat)")
        assert tree.stmts[0].redirs[0].word.parts[0].type == "ProcSubst"

    def test_double_process_substitution(self):
        tree = parse_ast("diff <(echo 'hi') <(echo 'there')")
        cmd = tree.stmts[0].cmd
        assert cmd.args[1].parts[0].type == "ProcSubst"

    def test_procsubst_imported(self):
        assert ProcSubst is not None


class TestExtGlobNodes:
    """Tests for the ExtGlob node type."""

    def test_at_extended_glob(self):
        tree = parse_ast("ls *.@(txt|md)")
        cmd = tree.stmts[0].cmd
        extglob = cmd.args[1].parts[1]
        assert extglob.type == "ExtGlob"

    def test_bang_extended_glob(self):
        tree = parse_ast("ls *.!(txt|md)")
        cmd = tree.stmts[0].cmd
        extglob = cmd.args[1].parts[1]
        assert extglob.type == "ExtGlob"

    def test_extglob_imported(self):
        from lovely_bash_permissions import ExtGlob

        assert ExtGlob is not None


class TestBlockNodes:
    """Tests for the Block node type."""

    def test_simple_block(self):
        tree = parse_ast("{ echo 'a'; echo 'b'; }")
        cmd = tree.stmts[0].cmd
        assert cmd.type == "Block"

    def test_nested_blocks(self):
        tree = parse_ast("{ { echo 'inner'; }; }")
        outer = tree.stmts[0].cmd
        assert outer.type == "Block"

    def test_block_position_info(self):
        tree = parse_ast("{ echo 'a'; }")
        cmd = tree.stmts[0].cmd
        assert cmd.pos is not None

    def test_block_imported(self):
        assert Block is not None


class TestFuncDeclNodes:
    """Tests for the FuncDecl node type."""

    def test_func_decl_with_parens(self):
        tree = parse_ast("hello() { echo 'hi'; }")
        cmd = tree.stmts[0].cmd
        assert cmd.type == "FuncDecl"

    def test_func_decl_function_keyword(self):
        tree = parse_ast("function hello { echo 'hi'; }")
        cmd = tree.stmts[0].cmd
        assert cmd.type == "FuncDecl"

    def test_func_decl_position_info(self):
        tree = parse_ast("hello() { echo 'hi'; }")
        cmd = tree.stmts[0].cmd
        assert cmd.pos is not None

    def test_func_decl_imported(self):
        assert FuncDecl is not None


class TestBraceExpNode:
    """Tests for the BraceExp node type."""

    def test_brace_exp_dataclass_exists(self):
        from lovely_bash_permissions import BraceExp

        assert BraceExp is not None

    def test_brace_exp_type_string(self):
        node = BraceExp()
        assert node.type == "BraceExp"

    def test_brace_exp_sequence_default(self):
        node = BraceExp()
        assert node.sequence is False

    def test_brace_exp_elems_default(self):
        node = BraceExp()
        assert node.elems is None

    def test_brace_exp_registered_in_node_types(self):
        from lovely_bash_permissions.ast import NODE_TYPES

        assert "BraceExp" in NODE_TYPES

    def test_brace_exp_instantiation(self):
        from lovely_bash_permissions import BraceExp, Word

        node = BraceExp(sequence=True, elems=[Word(parts=[])])
        assert node.sequence is True
