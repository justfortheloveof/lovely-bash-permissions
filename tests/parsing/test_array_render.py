"""
Tests for faithful rendering of bash variable-assignment operands.

Array elements must reach the pattern matchers verbatim, so the rendered
operand is the operand as bash itself reads it::

    A=(/etc/passwd foo)   ->  {"command": "", "arguments": ["A=(/etc/passwd foo)"]}

Collapsing the elements into a ``(...)`` placeholder would hide them from
allowed-pattern / blocked-path checks entirely.  Every other assignment shape is
lossless for the same reason: ``+=`` is tested after the plain array form so
``A+=(a b)`` renders with its elements intact, and a subscript is rendered so
that ``A[i]=value`` reports ``A[i]=value`` rather than ``A=value``.

These tests pin the rendered operand for every shape - scalar, subscripted,
array, and append combined with either - keep the ``(...)`` placeholder only for
the genuinely empty array, and confirm command substitutions inside elements
are still extracted as the real commands they run.

A declaration builtin's operands are variable assignments, so they render on
the same ``command == ""`` segment a bare assignment uses
(``export A=(a b)`` -> ``{"command": "", "arguments": ["A=(a b)"]}`` plus a
separate ``{"command": "export", "arguments": []}`` segment).  That split is
what makes the ``variable_assignment`` policy reach them at all - it is only
consulted for an empty-command segment, so an array rendered onto the ``export``
command segment instead would slip past ``"variable_assignment": "deny"``.  The
rendering is shared, so the bare form and the declaration form cannot drift
apart.
"""

from typing import ClassVar

import pytest

from lovely_bash_permissions.errors import ShfmtError
from lovely_bash_permissions.evaluate import evaluate_bash_command
from lovely_bash_permissions.segments import parse_segments


def _commands(command: str) -> list[str]:
    """Return the command names extracted from *command*."""
    return [s["command"] for s in parse_segments(command)]


def _args(command: str) -> list[str]:
    """Return the arguments of the variable-assignment segment *command* produces.

    The operand is looked up by its empty command name rather than by position,
    because a declaration builtin reports its operands on their own ``""``
    segment while the variant keyword keeps a separate command segment.  So the
    same helper reads ``A=(a b)`` and ``export A=(a b)`` alike.
    """
    segs = parse_segments(command)
    assigns = [s for s in segs if s["command"] == ""]
    assert len(assigns) == 1, f"{command!r} -> {[(s['command'], s['arguments']) for s in segs]}"
    return assigns[0]["arguments"]


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
    """Declaration builtins render array operands like CallExpr does.

    The rendering is shared, but the operand lands on its own variable-assignment
    segment (``command == ""``) with the variant keyword left as a bare command
    segment - the split that lets ``variable_assignment`` reach it.
    """

    def test_export_array(self) -> None:
        segs = parse_segments("export A=(/etc/passwd foo)")
        assert [(s["command"], s["arguments"]) for s in segs] == [("", ["A=(/etc/passwd foo)"]), ("export", [])]

    def test_declare_array_with_flag(self) -> None:
        segs = parse_segments("declare -a arr=(a b)")
        assert [(s["command"], s["arguments"]) for s in segs] == [("", ["-a", "arr=(a b)"]), ("declare", [])]

    def test_readonly_local_typeset_arrays(self) -> None:
        for variant in ("readonly", "local", "typeset"):
            segs = parse_segments(f"{variant} A=(a b)")
            assert [(s["command"], s["arguments"]) for s in segs] == [("", ["A=(a b)"]), (variant, [])], variant

    def test_empty_decl_array_falls_back_to_placeholder(self) -> None:
        assert _args("declare -a arr=()") == ["-a", "arr=(...)"]


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
        # An element substitution is a real execution, so `ls` is surfaced; the
        # operand itself is not a capture-output assignment (the carve-out only
        # looks at `value`), so the variable-assignment segment is still there.
        assert _commands("declare -a arr=($(ls))") == ["", "declare", "ls"]
        assert _args("declare -a arr=($(ls))") == ["-a", "arr=($(...))"]

    def test_capture_assignment_still_surfaces_the_substitution(self) -> None:
        """A standalone capture assignment yields its value plus the inner command."""
        segs = parse_segments("x=$(cat file)")
        assert [(s["command"], s["arguments"]) for s in segs] == [("", ["x=$(...)"]), ("cat", ["file"])]


class TestNonArrayAssignmentShapes:
    """Scalar and naked assignment rendering is unchanged by the helper."""

    def test_plain_export(self) -> None:
        segs = parse_segments("export FOO=bar")
        assert [(s["command"], s["arguments"]) for s in segs] == [("", ["FOO=bar"]), ("export", [])]

    def test_plain_callexpr_assign(self) -> None:
        segs = parse_segments("FOO=bar ls")
        assert segs[0]["arguments"] == ["FOO=bar"]
        assert segs[1]["command"] == "ls"

    def test_naked_declaration_name(self) -> None:
        assert _args("export FOO") == ["FOO"]

    def test_naked_declaration_multiple_names(self) -> None:
        segs = parse_segments("local x=1 y=2")
        assert [(s["command"], s["arguments"]) for s in segs] == [("", ["x=1", "y=2"]), ("local", [])]

    def test_append_assignment(self) -> None:
        segs = parse_segments("FOO+=bar")
        assert segs[0]["arguments"] == ["FOO+=bar"]

    def test_indexed_scalar_assignment_keeps_the_subscript(self) -> None:
        # The subscript belongs to the assignment, not just the value; dropping
        # it would turn `A[i]=value` into `A=value`.
        assert _args("A[i]=value") == ["A[i]=value"]

    def test_indexed_append_scalar_keeps_the_subscript(self) -> None:
        assert _args("A[i]+=v") == ["A[i]+=v"]

    def test_append_with_no_value_renders_the_operator(self) -> None:
        # `A+=` is all bash records; the segment must still name the variable.
        assert _args("A+=") == ["A+="]

    def test_indexed_arithmetic_value(self) -> None:
        assert _args("A[i]=$((1))") == ["A[i]=$(( ... ))"]


class TestAssignmentShapesBare:
    """Every assign shape renders, in the bare (non-declaration) form.

    The five shapes below - scalar, subscripted scalar, array, append-array and
    subscripted append-array - each lose meaning if any part is dropped, so all
    of them go through one shared helper and a bare form and its
    declaration-builtin form cannot drift apart.
    """

    def test_scalar(self) -> None:
        assert _args("FOO=bar") == ["FOO=bar"]

    def test_subscripted_scalar(self) -> None:
        assert _args("A[i]=value") == ["A[i]=value"]

    def test_array(self) -> None:
        assert _args("A=(a b)") == ["A=(a b)"]

    def test_append_array(self) -> None:
        # shfmt puts an append's value in `array`, and `append` is tested after
        # `array` so that the elements cannot be dropped entirely.
        assert _args("A+=(a b)") == ["A+=(a b)"]

    def test_subscripted_append_array(self) -> None:
        assert _args("A[i]+=(x y)") == ["A[i]+=(x y)"]

    def test_append_array_with_one_element(self) -> None:
        assert _args("A+=(x)") == ["A+=(x)"]


class TestAssignmentShapesInDeclarations:
    """The same five shapes render identically under a declaration builtin.

    The declaration form puts the operand on its own variable-assignment
    segment (``command == ""``) and leaves the variant as a bare command
    segment, so a bare form and its declaration-builtin form cannot drift apart.
    """

    _VARIANTS = ("export", "declare", "local", "readonly", "typeset")

    def test_all_shapes_match_the_bare_rendering(self) -> None:
        for variant in self._VARIANTS:
            for shape, expected in (
                ("FOO=bar", "FOO=bar"),
                ("A[i]=value", "A[i]=value"),
                ("A=(a b)", "A=(a b)"),
                ("A+=(a b)", "A+=(a b)"),
                ("A[i]+=(x y)", "A[i]+=(x y)"),
            ):
                # The bare form pins the expected text...
                assert _args(shape) == [expected], shape
                # ...and the declaration form must render it identically, on a
                # segment of its own, with the keyword segment left empty.
                segs = parse_segments(f"{variant} {shape}")
                assert [(s["command"], s["arguments"]) for s in segs] == [("", [expected]), (variant, [])], (
                    f"{variant} {shape} -> {segs}"
                )

    def test_declaration_flag_precedes_the_operand(self) -> None:
        # shfmt reports a leading flag as a name-less naked assign; it must
        # still render ahead of the assignment operand.
        assert _commands("declare -a A+=(a b)") == ["", "declare"]
        assert _args("declare -a A+=(a b)") == ["-a", "A+=(a b)"]

    def test_empty_array_under_declaration_still_placeholder(self) -> None:
        for variant in self._VARIANTS:
            assert _args(f"{variant} A=()") == ["A=(...)"], variant


class TestSubscriptPlusArrayIsAParseError:
    """``A[i]=(x y)`` is not valid bash - shfmt rejects it outright.

    It cannot be a rendering gap: the syntax never reaches the assign
    renderer.  shfmt reports "arrays cannot be nested", bash itself says
    "cannot assign list to array member", so the only subscripted-array shape
    that can be parsed is the append form (``A[i]+=(x y)``) pinned above.
    ``parse_segments`` reports the failure as "no segments" and
    ``evaluate_bash_command`` raises, which the hook maps to the ``error``
    policy - never a silent approval.
    """

    def test_parse_segments_yields_no_segments(self) -> None:
        assert parse_segments("A[i]=(x y)") == []

    def test_evaluation_raises_rather_than_approving(self) -> None:
        with pytest.raises(ShfmtError):
            evaluate_bash_command("A[i]=(x y)", {"*": "allow", "variable_assignment": "deny"})


class TestVariableAssignmentPolicyApplies:
    """Rendered operands reach the variable_assignment policy.

    The policy is consulted for the empty-command segment, which is where a
    declaration builtin's operands live too - so a declared array is gated
    exactly like a bare one.  With every element dropped (``A+=``) a blocked
    assignment would still trip the policy, but an allowed-pattern rule could
    not match the array contents, and a zero-segment assignment would skip the
    policy entirely.
    """

    _CONFIG: ClassVar[dict[str, str]] = {"*": "allow", "variable_assignment": "deny"}

    def test_append_array_is_denied(self) -> None:
        assert evaluate_bash_command("A+=(a b)", self._CONFIG)["status"] == "deny"

    def test_subscripted_append_array_is_denied(self) -> None:
        assert evaluate_bash_command("A[i]+=(x y)", self._CONFIG)["status"] == "deny"

    def test_array_is_denied(self) -> None:
        assert evaluate_bash_command("A=(a b)", self._CONFIG)["status"] == "deny"

    def test_declared_array_is_denied(self) -> None:
        # `export A=(a b)` assigns exactly as `A=(a b)` does, so denying the
        # bare form must deny the declared one - the operand belongs to its own
        # variable-assignment segment, which is the one the policy sees, not an
        # argument of the `export` segment.
        for source in ("export A=(a b)", "declare -a A=(a b)", "export A+=(a b)", "declare A=()"):
            assert evaluate_bash_command(source, self._CONFIG)["status"] == "deny", source

    def test_denied_reason_carries_the_rendered_operand(self) -> None:
        # The point of rendering: the operand the policy reports is the whole
        # assignment, not a bare `A+=`.
        reason = evaluate_bash_command("A+=(a b)", self._CONFIG)["reason"]
        assert "A+=(a b)" in reason
