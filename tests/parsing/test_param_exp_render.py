"""
Tests for faithful rendering of bash parameter expansions (ParamExp).

A parameter expansion used to render as its bare parameter name, so the
whole operand was dropped before any pattern matching: ``echo ${BAR:-/etc/passwd}``
reached the matcher as ``echo $BAR`` and the literal path disappeared.  These
tests pin the operator/operand text back on - in the raw ``arguments`` form
and in the quote/backslash-normalized ``normalized_arguments`` form - while
keeping the two invariants intact: a ``$(...)`` operand stays the literal
opaque placeholder, and nested expansions terminate.
"""

from typing import Any, cast

from lovely_bash_permissions.ast import Lit, ParamExp, ParamExpExp, ParamExpSlice, Word
from lovely_bash_permissions.inspect import _word_value
from lovely_bash_permissions.segments import parse_segments


def _first(command: str) -> dict[str, Any]:
    """Return the first segment of *command* (the ``echo`` itself).

    A ``$(...)`` operand yields a *second* segment for the nested command -
    that is the whole point of the opaque-placeholder tests - so only the
    first segment is inspected here.
    """
    segs = parse_segments(command)
    assert segs, f"no segments parsed for {command!r}"
    assert segs[0]["command"] == "echo", f"unexpected first segment for {command!r}: {segs[0]}"
    return segs[0]


def _args(command: str) -> list[str]:
    """Return the raw (quote-preserving) arguments of the ``echo`` segment."""
    return cast(list[str], _first(command)["arguments"])


def _normalized(command: str) -> list[str]:
    """Return the executed (quote/backslash-normalized) arguments."""
    return cast(list[str], _first(command)["normalized_arguments"])


class TestDefaultOperators:
    """``${var:-word}`` and friends keep their operator and operand text."""

    def test_colon_dash_default(self) -> None:
        assert _args("echo ${BAR:-/etc/passwd}") == ["${BAR:-/etc/passwd}"]

    def test_dash_default(self) -> None:
        # The `-` form (no colon) behaves the same but only when unset.
        assert _args("echo ${BAR-/etc/passwd}") == ["${BAR-/etc/passwd}"]

    def test_assign_operator(self) -> None:
        assert _args("echo ${x:=/etc/passwd}") == ["${x:=/etc/passwd}"]

    def test_alternate_value_operator(self) -> None:
        assert _args("echo ${x:+set}") == ["${x:+set}"]

    def test_error_operator(self) -> None:
        assert _args("echo ${x:?unset}") == ["${x:?unset}"]

    def test_prefix_removal(self) -> None:
        assert _args("echo ${x%/etc/*}") == ["${x%/etc/*}"]
        assert _args("echo ${x%%/etc/*}") == ["${x%%/etc/*}"]

    def test_prefix_removal_hash(self) -> None:
        assert _args("echo ${x#*/etc/*}") == ["${x#*/etc/*}"]
        assert _args("echo ${x##*/etc/*}") == ["${x##*/etc/*}"]

    def test_operator_without_operand(self) -> None:
        # `${x:-}` has an operator but an empty (absent) operand.
        assert _args("echo ${x:-}") == ["${x:-}"]

    def test_case_modifier_without_operand(self) -> None:
        assert _args("echo ${x^}") == ["${x^}"]


class TestSubstitutionForms:
    """``${var/pat/rep}`` and the replace-all ``${var//pat/rep}``."""

    def test_single_slash_form(self) -> None:
        assert _args("echo ${x/a/b}") == ["${x/a/b}"]

    def test_double_slash_form(self) -> None:
        arg = _args("echo ${x//a/b}")[0]
        assert arg.startswith("${x//")
        assert arg != _args("echo ${x/a/b}")[0]

    def test_replace_all_is_double_slash(self) -> None:
        assert _args("echo ${x//a/b}") == ["${x//a/b}"]
        assert _args("echo ${x/a/b}") == ["${x/a/b}"]
        # The `all` flag is what turns the separator into a double slash.
        assert "//" in _args("echo ${x//a/b}")[0]
        assert "//" not in _args("echo ${x/a/b}")[0]

    def test_substitution_keeps_path_visible(self) -> None:
        # The whole point of the fix: a blocked-path pattern must still see
        # the literal path embedded in the expansion.
        assert "/etc/passwd" in _args("echo ${x/a/etc/passwd}")[0]


class TestIndexAndSlice:
    """Array subscripts and substrings keep their operand text."""

    def test_array_index(self) -> None:
        assert _args("echo ${arr[i]}") == ["${arr[i]}"]

    def test_slice_with_offset_and_length(self) -> None:
        assert _args("echo ${x:0:3}") == ["${x:0:3}"]

    def test_slice_offset_only(self) -> None:
        assert _args("echo ${x:1}") == ["${x:1}"]

    def test_slice_length_placeholder(self) -> None:
        # shfmt rejects `${x:0:}` (": must be followed by an expression"), so
        # the absent-length spelling is exercised through the renderer with a
        # hand-built node; `${x:1}` above covers the same offset-only path
        # end-to-end.
        node = ParamExp(
            param="x",
            slice=ParamExpSlice(offset=Word(parts=[Lit(value="0")]), length=None),
        )
        assert _word_value(Word(parts=[node])) == "${x:0}"

    def test_slice_nested_expansion(self) -> None:
        # A nested bare expansion keeps its simple `$y` spelling.
        assert _args("echo ${x:${y}}") == ["${x:$y}"]


class TestCombinedShapes:
    """Shapes shfmt never emits must still render without crashing."""

    def test_operator_and_index_together(self) -> None:
        node = ParamExp(
            param="arr",
            exp=ParamExpExp(op=":-", word=Word(parts=[Lit(value="def")])),
            index=Word(parts=[Lit(value="i")]),
        )
        assert _word_value(Word(parts=[node])) == "${arr:-def[i]}"

    def test_substitution_and_index_together(self) -> None:
        node = ParamExp(
            param="arr",
            orig=Word(parts=[Lit(value="a")]),
            replacement=Word(parts=[Lit(value="b")]),
            all=True,
            index=Word(parts=[Lit(value="i")]),
        )
        assert _word_value(Word(parts=[node])) == "${arr//a/b[i]}"

    def test_slice_with_empty_offset(self) -> None:
        # `${x::3}` - length given, offset absent.
        node = ParamExp(param="x", slice=ParamExpSlice(offset=None, length=Word(parts=[Lit(value="3")])))
        assert _word_value(Word(parts=[node])) == "${x::3}"


class TestUnchangedSimpleForms:
    """Bare expansions keep their historical short spelling."""

    def test_short_param(self) -> None:
        assert _args("echo $HOME") == ["$HOME"]

    def test_braced_param_without_operator(self) -> None:
        assert _args("echo ${x}") == ["$x"]

    def test_normalized_simple_form_unchanged(self) -> None:
        assert _normalized("echo $HOME") == ["$HOME"]

    def test_length_expansion_unchanged(self) -> None:
        # `${#x}` populates no operand field, so it keeps rendering as `$x`.
        assert _args("echo ${#x}") == ["$x"]


class TestNesting:
    """Nested parameter expansions render fully and terminate."""

    def test_nested_default(self) -> None:
        assert _args("echo ${A:-${B:-/etc/passwd}}") == ["${A:-${B:-/etc/passwd}}"]

    def test_nested_default_terminates(self) -> None:
        arg = _args("echo ${A:-${B:-${C:-/etc/passwd}}}")[0]
        assert arg == "${A:-${B:-${C:-/etc/passwd}}}"

    def test_nested_in_substitution_pattern(self) -> None:
        arg = _args("echo ${x/${y}/z}")[0]
        assert arg == "${x/$y/z}"


class TestOpaquePlaceholders:
    """A ``$(...)`` operand must stay the exact opaque placeholder.

    ``evaluate._command_string`` / ``_opaque_match_unreliable`` key off the
    literal string ``$(...)`` appearing in an argument; a bespoke operand
    renderer that emitted the substitution's raw text would silently break
    that safety net.
    """

    def test_cmd_subst_operand_keeps_placeholder(self) -> None:
        arg = _args("echo ${x:-$(cmd)}")[0]
        assert arg == "${x:-$(...)}"
        assert "$(...)" in arg

    def test_cmd_subst_operand_placeholder_in_normalized_form(self) -> None:
        assert "$(...)" in _normalized("echo ${x:-$(cmd)}")[0]

    def test_cmd_subst_inside_nested_default(self) -> None:
        arg = _args("echo ${A:-${B:-$(cmd)}}")[0]
        assert arg == "${A:-${B:-$(...)}}"

    def test_cmd_subst_in_slice_offset(self) -> None:
        assert _args("echo ${x:$(cmd):3}")[0] == "${x:$(...):3}"

    def test_cmd_subst_in_substitution(self) -> None:
        assert _args("echo ${x//a/$(cmd)}")[0] == "${x//a/$(...)}"


class TestQuotedVariants:
    """Quoting is preserved in the raw form; the exec form drops it."""

    def test_single_quoted_raw_form(self) -> None:
        assert _args("echo '${BAR:-/etc/passwd}'") == ["'${BAR:-/etc/passwd}'"]

    def test_single_quoted_normalized_form(self) -> None:
        assert _normalized("echo '${BAR:-/etc/passwd}'") == ["${BAR:-/etc/passwd}"]

    def test_double_quoted_raw_form_keeps_quotes(self) -> None:
        # A "..." region renders as one quoted region from DblQuoted's lossy
        # ``value`` field, so the expansion text is *not* in the raw form. That
        # is a DblQuoted-fidelity gap separate from this ParamExp fix; the
        # faithful expansion is available in the executed form (next test) and
        # is what the blocked/allowed matchers normalize to.
        assert _args('echo "${BAR:-/etc/passwd}"') == ['""']

    def test_double_quoted_expands_in_normalized_form(self) -> None:
        assert _normalized('echo "${BAR:-/etc/passwd}"') == ["${BAR:-/etc/passwd}"]

    def test_double_quoted_with_literal_prefix(self) -> None:
        assert _args('echo "pre${x:-/etc/passwd}"') == ['"pre"']
        assert _normalized('echo "pre${x:-/etc/passwd}"') == ["pre${x:-/etc/passwd}"]


class TestEscapedOperands:
    """Backslash-escaped operands unescape in the executed form only."""

    def test_escaped_replacement_raw_form(self) -> None:
        arg = _args(r"echo ${x/a/\/etc\/passwd}")[0]
        assert r"\/etc\/passwd" in arg

    def test_escaped_replacement_normalized_form(self) -> None:
        arg = _normalized(r"echo ${x/a/\/etc\/passwd}")[0]
        assert r"\/" not in arg
        assert "/etc" in arg
        assert "passwd" in arg
