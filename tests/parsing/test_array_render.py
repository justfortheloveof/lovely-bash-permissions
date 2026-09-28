"""
Tests for faithful rendering of bash array assignment literals.

Bash array assignments used to be collapsed to a ``(...)`` placeholder, so
the element text never reached any pattern matcher::

    A=(/etc/passwd foo)   ->  {"command": "", "arguments": ["A=(...)"]}

That hid the elements from allowed-pattern / blocked-path checks entirely.
These tests pin the rendered element list, keep the placeholder only for the
genuinely empty array, and confirm command substitutions inside elements are
still extracted as the real commands they run.
"""

from lovely_bash_permissions.segments import parse_segments


def _commands(command: str) -> list[str]:
    """Return the command names extracted from *command*."""
    return [s["command"] for s in parse_segments(command)]


class TestStandaloneArrayAssignment:
    """A bare array assignment statement renders its elements."""

    def test_single_element_array(self) -> None:
        segs = parse_segments("A=(/etc/passwd)")
        assert [(s["command"], s["arguments"]) for s in segs] == [("", ["A=(/etc/passwd)"])]

    def test_multiple_element_array(self) -> None:
        segs = parse_segments("A=(/etc/passwd foo)")
        assert [(s["command"], s["arguments"]) for s in segs] == [("", ["A=(/etc/passwd foo)"])]

    def test_elements_keep_their_order(self) -> None:
        segs = parse_segments("A=(c b a)")
        assert segs[0]["arguments"] == ["A=(c b a)"]

    def test_empty_array_falls_back_to_placeholder(self) -> None:
        segs = parse_segments("A=()")
        assert [(s["command"], s["arguments"]) for s in segs] == [("", ["A=(...)"])]

    def test_inline_array_before_command_does_not_parse(self) -> None:
        # bash/shfmt reject `A=(...) cmd`; parsing yields no segments rather
        # than a half-rendered one.
        assert parse_segments("A=(/etc/passwd foo) ls") == []

    def test_array_in_a_for_loop_body(self) -> None:
        segs = parse_segments("for i in a; do A=(/etc/passwd); done")
        assert [(s["command"], s["arguments"]) for s in segs] == [("", ["A=(/etc/passwd)"])]


class TestSparseArrayElements:
    """Indexed elements (``A=([0]=x)``) keep their subscript visible."""

    def test_indexed_elements_render_with_subscript(self) -> None:
        segs = parse_segments("A=([0]=x [2]=y)")
        assert segs[0]["arguments"] == ["A=([0]=x [2]=y)"]


class TestDeclClauseArrayOperands:
    """Declaration builtins render array operands like CallExpr does."""

    def test_export_array(self) -> None:
        segs = parse_segments("export A=(/etc/passwd foo)")
        assert [(s["command"], s["arguments"]) for s in segs] == [("export", ["A=(/etc/passwd foo)"])]

    def test_declare_array_with_flag(self) -> None:
        segs = parse_segments("declare -a arr=(a b)")
        assert segs[0]["command"] == "declare"
        assert segs[0]["arguments"] == ["-a", "arr=(a b)"]

    def test_readonly_local_typeset_arrays(self) -> None:
        for variant in ("readonly", "local", "typeset"):
            segs = parse_segments(f"{variant} A=(a b)")
            assert segs[0]["command"] == variant, variant
            assert segs[0]["arguments"] == ["A=(a b)"], variant

    def test_empty_decl_array_falls_back_to_placeholder(self) -> None:
        segs = parse_segments("declare -a arr=()")
        assert segs[0]["arguments"] == ["-a", "arr=(...)"]


class TestArrayElementSubstitutions:
    """Substitutions inside array elements are still extracted as commands."""

    def test_nested_substitution_element_surfaces_command(self) -> None:
        segs = parse_segments("A=($(cmd))")
        assert _commands("A=($(cmd))") == ["", "cmd"]
        # The element text itself is preserved (raw form renders $(...)).
        assert segs[0]["arguments"] == ["A=($(...))"]

    def test_substitution_among_plain_elements(self) -> None:
        assert _commands("A=(one $(cmd) three)") == ["", "cmd"]

    def test_nested_substitution_in_decl_array(self) -> None:
        assert _commands("declare -a arr=($(ls))") == ["declare", "ls"]

    def test_capture_assignment_still_surfaces_the_substitution(self) -> None:
        """A standalone capture assignment yields its value plus the inner command."""
        segs = parse_segments("x=$(cat file)")
        assert [(s["command"], s["arguments"]) for s in segs] == [("", ["x=$(...)"]), ("cat", ["file"])]


class TestNonArrayAssignmentShapes:
    """Scalar assignment rendering is unchanged by the array helper."""

    def test_plain_export(self) -> None:
        segs = parse_segments("export FOO=bar")
        assert [(s["command"], s["arguments"]) for s in segs] == [("export", ["FOO=bar"])]

    def test_plain_callexpr_assign(self) -> None:
        segs = parse_segments("FOO=bar ls")
        assert segs[0]["arguments"] == ["FOO=bar"]
        assert segs[1]["command"] == "ls"

    def test_naked_declaration_name(self) -> None:
        segs = parse_segments("export FOO")
        assert segs[0]["arguments"] == ["FOO"]

    def test_naked_declaration_multiple_names(self) -> None:
        segs = parse_segments("local x=1 y=2")
        assert segs[0]["command"] == "local"
        assert segs[0]["arguments"] == ["x=1", "y=2"]

    def test_append_assignment(self) -> None:
        segs = parse_segments("FOO+=bar")
        assert segs[0]["arguments"] == ["FOO+=bar"]

    def test_indexed_scalar_assignment_keeps_name_and_value(self) -> None:
        # Pre-existing shape: the subscript of a *scalar* assignment is not
        # rendered (only the array-element case carries an index).
        segs = parse_segments("A[i]=value")
        assert segs[0]["arguments"] == ["A=value"]
