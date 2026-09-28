"""
Tests for faithful rendering of bash parameter expansions (ParamExp).

A parameter expansion used to render as its bare parameter name, so the
whole operand was dropped before any pattern matching: ``echo ${BAR:-/etc/passwd}``
reached the matcher as ``echo $BAR`` and the literal path disappeared.  These
tests pin the operator/operand text back on - in the raw ``arguments`` form
and in the quote/backslash-normalized ``normalized_arguments`` form - while
keeping the two invariants intact: a ``$(...)`` operand stays the literal
opaque placeholder, and nested expansions terminate.

Two further fidelity gaps are pinned here because they share the same
rendering code and the same matcher:

* A ``DblQuoted`` used to render from its lossy ``value`` field, which splices
  every expansion out (``"pre${x}y"`` became the string ``"prey"`` - text the
  user never wrote).  ``"..."`` regions now render from their parts.
* ``ParamExp.length`` (``${#x}``) was never rendered, so ``${#x}`` reached the
  matcher as ``$x`` - a *different* expression with a different meaning.

The third sigil gap is ``ParamExp.excl``: ``${!x}`` (indirect expansion - read
the variable *named* by ``$x``) and the prefix form ``${!prefix*}`` also
rendered as ``$x`` / ``$prefix``.  Every other operator was already faithful, so
:class:`TestUnchangedOperatorForms` pins the rest byte-for-byte: a sigil fix must
not disturb the spellings that were already right.
"""

from typing import Any, ClassVar, cast

from lovely_bash_permissions.ast import DblQuoted, Lit, ParamExp, ParamExpExp, ParamExpSlice, Word
from lovely_bash_permissions.converter import parse_ast
from lovely_bash_permissions.evaluate import evaluate_bash_command
from lovely_bash_permissions.inspect import _word_exec, _word_raw, _word_value, find_arguments
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


def _value(command: str) -> list[str]:
    """Return the arguments of the first call expression in *value* form.

    The third renderer: ``_word_value`` strips quotes and backslashes but keeps
    expansion text, so it is the last of the three shapes an argument can reach
    the matcher in.  Unlike the hand-built node tests below this walks the real
    shfmt parse, so it also proves ``converter._convert_param_exp`` carried the
    flag across the boundary.
    """
    calls = find_arguments(parse_ast(command))
    assert calls, f"no call arguments parsed for {command!r}"
    return [_word_value(arg) for arg in calls[0]]


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


class TestLengthExpansion:
    """``${#x}`` keeps its ``#``: it is a *different* expression from ``${x}``.

    ``ParamExp.length`` is populated by shfmt (``"Length": true``) but used to
    go unrendered, so ``echo ${#x}`` reached the matcher as ``echo $x`` - the
    string length being talked about as if it were the variable's value.
    """

    def test_simple_length_expansion(self) -> None:
        assert _args("echo ${#x}") == ["${#x}"]

    def test_length_expansion_is_not_the_bare_param(self) -> None:
        arg = _args("echo ${#x}")[0]
        assert arg != "$x"
        assert arg.startswith("${#")

    def test_length_expansion_normalized_form(self) -> None:
        assert _normalized("echo ${#x}") == ["${#x}"]

    def test_array_length_expansion(self) -> None:
        assert _args("echo ${#arr[@]}") == ["${#arr[@]}"]

    def test_length_expansion_hand_built_node(self) -> None:
        # The bare `${#x}` spelling has no operator, so it exercises the
        # simple-form branch rather than the operator/suffix branch.
        node = ParamExp(param="x", length=True)
        assert _word_value(Word(parts=[node])) == "${#x}"

    def test_non_length_expansion_has_no_sigil(self) -> None:
        node = ParamExp(param="x")
        assert _word_value(Word(parts=[node])) == "$x"

    def test_length_expansion_keeps_operator_text(self) -> None:
        # `${#x}` and `${x}` differ only in the sigil; with an operator present
        # both the sigil and the operator must survive.
        node = ParamExp(param="x", length=True, exp=ParamExpExp(op=":-", word=Word(parts=[Lit(value="d")])))
        assert _word_value(Word(parts=[node])) == "${#x:-d}"


class TestIndirectExpansion:
    """``${!x}`` keeps its ``!``: it reads the variable *named* by ``$x``.

    ``ParamExp.excl`` is populated by shfmt (``"Excl": true``) but used to go
    unrendered, so ``echo ${!x}`` reached the matcher as ``echo $x`` - the
    indirection silently dropped, which is a different expansion entirely.
    """

    def test_simple_indirect_expansion(self) -> None:
        assert _args("echo ${!x}") == ["${!x}"]

    def test_indirect_expansion_is_not_the_bare_param(self) -> None:
        arg = _args("echo ${!x}")[0]
        assert arg != "$x"
        assert arg.startswith("${!")

    def test_indirect_expansion_normalized_form(self) -> None:
        assert _normalized("echo ${!x}") == ["${!x}"]

    def test_indirect_expansion_value_form(self) -> None:
        # Walks the real shfmt parse, so this also pins converter behaviour.
        assert _value("echo ${!x}") == ["${!x}"]

    def test_indirect_array_expansion(self) -> None:
        assert _args("echo ${!x[@]}") == ["${!x[@]}"]

    def test_indirect_array_expansion_normalized_form(self) -> None:
        assert _normalized("echo ${!x[@]}") == ["${!x[@]}"]

    def test_indirect_array_expansion_value_form(self) -> None:
        assert _value("echo ${!x[@]}") == ["${!x[@]}"]

    def test_indirect_star_subscript_is_preserved(self) -> None:
        # `${!arr[*]}` is not the prefix form: here the `*` really is an array
        # subscript and reaches the renderer through `Index`, so it survives
        # whole.  Contrast with ${!prefix*}, which shfmt does not preserve.
        assert _args("echo ${!arr[*]}") == ["${!arr[*]}"]

    def test_indirect_expansion_keeps_operator_text(self) -> None:
        assert _args("echo ${!x:-cmd}") == ["${!x:-cmd}"]

    def test_indirect_expansion_keeps_case_modifier(self) -> None:
        assert _args("echo ${!x@Q}") == ["${!x@Q}"]
        assert _args("echo ${!x^^}") == ["${!x^^}"]

    def test_indirect_expansion_keeps_slice_and_substitution(self) -> None:
        assert _args("echo ${!x:1:2}") == ["${!x:1:2}"]
        assert _args("echo ${!x/a/b}") == ["${!x/a/b}"]

    def test_indirect_expansion_hand_built_node(self) -> None:
        node = ParamExp(param="x", excl=True)
        assert _word_value(Word(parts=[node])) == "${!x}"

    def test_indirect_expansion_keeps_operator_text_hand_built_node(self) -> None:
        node = ParamExp(param="x", excl=True, exp=ParamExpExp(op=":-", word=Word(parts=[Lit(value="d")])))
        assert _word_value(Word(parts=[node])) == "${!x:-d}"

    def test_non_indirect_expansion_has_no_sigil(self) -> None:
        # `${!x}` and `${x}` differ only in the sigil; the `excl` default of
        # False must keep the historical short spelling.
        node = ParamExp(param="x")
        assert _word_value(Word(parts=[node])) == "$x"

    def test_length_and_excl_are_mutually_exclusive(self) -> None:
        # bash rejects `${#!x}` as a bad substitution, so shfmt never emits
        # both; if it somehow did, `length` wins (the pre-existing sigil).
        node = ParamExp(param="x", length=True, excl=True)
        assert _word_value(Word(parts=[node])) == "${#x}"

    def test_indirect_expansion_keeps_literal_affixes(self) -> None:
        assert _args("echo a${!x}b") == ["a${!x}b"]
        assert _args('echo "pre${!x}post"') == ['"pre${!x}post"']

    def test_indirect_expansion_in_quotes(self) -> None:
        assert _args('echo "${!x}"') == ['"${!x}"']
        assert _normalized('echo "${!x}"') == ["${!x}"]


class TestIndirectPrefixExpansionLimitation:
    """``${!prefix*}`` renders as ``${!prefix}`` - a known truncation.

    The prefix/indirect *name-list* form is the one shape shfmt does not hand
    back whole.  Its JSON keeps ``Param.Value == "prefix"`` and parks the ``*``
    in a sibling ``Names`` key on the same ParamExp node; ``_convert_param_exp``
    reads neither ``Names`` nor the original source text, so the ``*`` is
    already lost by the time the renderer sees the node.  Only ``Excl``
    survives the converter boundary, so the rendered argument is
    ``${!prefix}`` - still a distinct expansion from ``$prefix``, but not the
    one the user wrote.

    This test pins the *current* behaviour so the truncation stays visible.  It
    is a fidelity gap in the safe direction only in the sense that the argument
    is still opaque to the matcher; it is NOT reconstructed, and if shfmt ever
    stops dropping the information this test is the one that should change.
    """

    def test_prefix_expansion_renders_without_the_star(self) -> None:
        assert _args("echo ${!prefix*}") == ["${!prefix}"]

    def test_prefix_expansion_normalized_form(self) -> None:
        assert _normalized("echo ${!prefix*}") == ["${!prefix}"]

    def test_prefix_expansion_value_form(self) -> None:
        assert _value("echo ${!prefix*}") == ["${!prefix}"]

    def test_prefix_expansion_is_distinguishable_from_the_plain_param(self) -> None:
        # Even truncated, `${!prefix}` is not `$prefix`: the indirection is
        # still visible, so the expansion is not silently collapsed.
        arg = _args("echo ${!prefix*}")[0]
        assert arg != "$prefix"
        assert arg == _args("echo ${!prefix}")[0]

    def test_star_is_not_reconstructed_from_the_surrounding_word(self) -> None:
        # A `*` written as a *separate* word part is untouched, which shows the
        # loss above is specific to the `${!...*}` subscript spelling rather
        # than a general dropping of `*`.
        assert _args("echo ${!prefix*} *") == ["${!prefix}", "*"]


class TestUnchangedOperatorForms:
    """Byte-for-byte regression pins for the operators that were already right.

    Every expectation here is the rendering from *before* the ``excl`` work.
    ``_param_exp_text`` is shared by all three renderers, so a change to the
    sigil handling could plausibly have disturbed the branches below it; these
    cases are the canary.
    """

    CASES: ClassVar[dict[str, list[str]]] = {
        "echo ${x@Q}": ["${x@Q}"],
        "echo ${x^^}": ["${x^^}"],
        "echo ${x,,}": ["${x,,}"],
        "echo ${#x}": ["${#x}"],
        "echo ${#arr[@]}": ["${#arr[@]}"],
        "echo ${x:1:2}": ["${x:1:2}"],
        "echo ${x:1}": ["${x:1}"],
        "echo ${x/a/b}": ["${x/a/b}"],
        "echo ${x//a/b}": ["${x//a/b}"],
        "echo ${x:-def}": ["${x:-def}"],
        "echo ${x%/p}": ["${x%/p}"],
        "echo ${x%%/p}": ["${x%%/p}"],
        "echo ${x#p}": ["${x#p}"],
        "echo ${x:+set}": ["${x:+set}"],
        "echo ${x:?msg}": ["${x:?msg}"],
        "echo ${arr[i]}": ["${arr[i]}"],
        "echo ${x^}": ["${x^}"],
        "echo ${x:-}": ["${x:-}"],
        "echo $HOME": ["$HOME"],
        "echo ${x}": ["$x"],
    }

    def test_raw_forms_unchanged(self) -> None:
        for command, expected in self.CASES.items():
            assert _args(command) == expected, command

    def test_executed_forms_unchanged(self) -> None:
        for command, expected in self.CASES.items():
            assert _normalized(command) == expected, command

    def test_value_forms_unchanged(self) -> None:
        for command, expected in self.CASES.items():
            assert _value(command) == expected, command


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

    def test_cmd_subst_operand_of_indirect_expansion_keeps_placeholder(self) -> None:
        # The `excl` sigil must not disturb the operand renderer: the `!` is
        # added around the expansion, the `$(...)` inside it stays the exact
        # opaque placeholder `evaluate` keys off.
        arg = _args("echo ${!x:-$(cmd)}")[0]
        assert arg == "${!x:-$(...)}"
        assert "$(...)" in arg

    def test_cmd_subst_operand_of_indirect_expansion_normalized_form(self) -> None:
        assert "$(...)" in _normalized("echo ${!x:-$(cmd)}")[0]

    def test_cmd_subst_operand_of_indirect_expansion_value_form(self) -> None:
        assert _value("echo ${!x:-$(cmd)}") == ["${!x:-$(...)}"]


class TestQuotedVariants:
    """Quoting is preserved in the raw form; the exec form drops it."""

    def test_single_quoted_raw_form(self) -> None:
        assert _args("echo '${BAR:-/etc/passwd}'") == ["'${BAR:-/etc/passwd}'"]

    def test_single_quoted_normalized_form(self) -> None:
        assert _normalized("echo '${BAR:-/etc/passwd}'") == ["${BAR:-/etc/passwd}"]

    def test_double_quoted_expands_in_normalized_form(self) -> None:
        assert _normalized('echo "${BAR:-/etc/passwd}"') == ["${BAR:-/etc/passwd}"]


class TestDoubleQuotedFidelity:
    """A ``"..."`` region renders from its parts, not from its lossy ``value``.

    ``DblQuoted.value`` is built by ``converter._convert_dbl_quoted`` from only
    the ``Lit``/``SglQuoted`` children, substituting ``""`` for everything
    else - so ``"pre${x:-/etc/passwd}post"`` used to render as ``"prepost"``,
    a literal string the user never wrote.  A restrictive allowed pattern can
    be satisfied by text that was dropped, so the raw form must keep the
    expansion visible.
    """

    def test_bare_expansion_in_quotes_is_kept(self) -> None:
        assert _args('echo "$HOME"') == ['"$HOME"']
        assert _args('echo "${x}"') == ['"$x"']

    def test_expansion_with_literal_prefix_and_suffix(self) -> None:
        # The exact string that used to come out as "prepost".
        assert _args('echo "pre${x:-/etc/passwd}post"') == ['"pre${x:-/etc/passwd}post"']

    def test_plain_quoted_literal_unchanged(self) -> None:
        # A "..." region with no expansion never touched the lossy path.
        assert _args('echo "plain"') == ['"plain"']

    def test_empty_quoted_region_unchanged(self) -> None:
        # shfmt emits no parts at all for `""`, so the stored-value fallback
        # applies and the word contributes nothing.
        assert _args('echo ""') == [""]

    def test_quoted_path_operator_stays_visible(self) -> None:
        assert _args('echo "${BAR:-/etc/passwd}"') == ['"${BAR:-/etc/passwd}"']

    def test_single_quoted_expansion_unchanged(self) -> None:
        # Single quotes are verbatim, so the expansion text is already there.
        assert _args("echo '${x}'") == ["'${x}'"]

    def test_mixed_literal_and_expansion(self) -> None:
        assert _args('echo "a${x}b$c"') == ['"a$xb$c"']

    def test_adjacent_quoted_and_bare_regions(self) -> None:
        # The "a"b"c" shape: a bare Lit, then two "..." regions in one word.
        assert _args('echo a"b"c') == ['a"b"c']

    def test_backslash_kept_in_raw_form(self) -> None:
        # The raw form is the text as written; unescaping is the exec form's
        # job, so the backslash must survive here.
        assert _args('echo "\\$x"') == ['"\\$x"']

    def test_nested_dbl_quoted_renders_recursively(self) -> None:
        # True nesting (a DblQuoted inside a DblQuoted) is not reachable from
        # bash source - adjacent regions are separate parts - so it is built by
        # hand.  Both renderers recurse and terminate.
        inner = DblQuoted(parts=[Lit(value="in")])
        region = DblQuoted(parts=[Lit(value="a"), inner, ParamExp(param="x")], value=None)
        word = Word(parts=[Lit(value="pre"), region])
        assert _word_raw(word) == 'pre"a"in"$x"'
        assert _word_value(word) == "preain$x"

    def test_nested_dbl_quoted_exec_form_unchanged(self) -> None:
        inner = DblQuoted(parts=[Lit(value="in")])
        region = DblQuoted(parts=[Lit(value="a"), inner, ParamExp(param="x")], value=None)
        word = Word(parts=[Lit(value="pre"), region])
        assert _word_exec(word) == "preain$x"


class TestDoubleQuotedOpaquePlaceholder:
    """``$(...)`` inside ``"..."`` must still render as the opaque placeholder.

    ``evaluate._command_string`` and ``_opaque_match_unreliable`` key off the
    literal string ``$(...)`` to decide that a pattern match is unreliable, so
    recursing into a ``DblQuoted`` must not replace it with the substitution's
    own text.  The lossy ``value`` field dropped it outright (``"a$(cmd)b"``
    became ``"ab"``), which is exactly the signal the guard needs.
    """

    def test_cmd_subst_inside_quotes_keeps_placeholder(self) -> None:
        arg = _args('echo "a$(cmd)b"')[0]
        assert arg == '"a$(...)b"'
        assert "$(...)" in arg

    def test_cmd_subst_inside_quotes_normalized_form(self) -> None:
        assert _normalized('echo "a$(cmd)b"') == ["a$(...)b"]

    def test_cmd_subst_inside_quotes_with_expansion(self) -> None:
        arg = _args('echo "nested $(cmd ${x})"')[0]
        assert arg == '"nested $(...)"'
        assert "$(...)" in arg
        assert "${x}" not in arg


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


class TestExecFormUnchanged:
    """The executed form is a byte-for-byte regression pin.

    The raw renderers changed; ``normalized_arguments`` (the executed form
    ``evaluate`` matches on first) must not have.  Every expectation here is
    the value that renderer produced *before* the ``DblQuoted`` fix.  The one
    deliberate exception is ``${#x}``, whose ``#`` is the second finding and is
    shared by both renderers through ``_param_exp_text``.
    """

    def test_exec_form_unchanged_for_every_quoted_case(self) -> None:
        cases = {
            'echo "$HOME"': ["$HOME"],
            'echo "pre${x:-/etc/passwd}post"': ["pre${x:-/etc/passwd}post"],
            'echo "plain"': ["plain"],
            'echo "pre${x:-/etc/passwd}"': ["pre${x:-/etc/passwd}"],
            'echo "${BAR:-/etc/passwd}"': ["${BAR:-/etc/passwd}"],
            "echo '${x}'": ["${x}"],
            'echo "a$(cmd)b"': ["a$(...)b"],
            'echo "a${x}b$c"': ["a$xb$c"],
            'echo a"b"c': ["abc"],
            'echo ""': [""],
            'echo "\\$x"': ["$x"],
            'echo "${x}"': ["$x"],
            'echo "${A:-${B:-/x}}"': ["${A:-${B:-/x}}"],
            'echo "${x//a/b}"': ["${x//a/b}"],
            "echo '${BAR:-/etc/passwd}'": ["${BAR:-/etc/passwd}"],
        }
        for command, expected in cases.items():
            assert _normalized(command) == expected, command


class TestAllowSideQuotedFidelity:
    """Allow-side regressions for the raw ``arguments`` text.

    ``allowed_cmds_regex`` matches the joined segment text, and
    ``evaluate._texts_for`` tries the executed form first with the raw form as a
    fallback.  While a ``"..."`` region rendered from its lossy ``value``, that
    fallback text was text the user never wrote, so a restrictive guard could be
    satisfied by dropped content.  ``evaluate._command_string`` also applies
    ``_strip_quotes`` to every argument, so a pattern written with explicit
    quote characters never matches either form - these tests use the
    quote-stripped spelling, which is the one a pattern must be written in.
    """

    def test_expansion_text_is_visible_to_an_allowed_pattern(self) -> None:
        result = evaluate_bash_command(
            'echo "${BAR:-/etc/passwd}"', {"*": "ask", "allowed_cmds_regex": [r"^echo\s+\S+$"]}
        )
        assert result["status"] == "allow"

    def test_opaque_expansion_does_not_satisfy_a_slash_free_guard(self) -> None:
        # `[^/]*` means "no slash in the argument".  The expansion carries a
        # literal path, so the guard must not approve it - previously the raw
        # fallback was the empty string `""` and matched.
        result = evaluate_bash_command(
            'echo "${BAR:-/etc/passwd}"', {"*": "ask", "allowed_cmds_regex": [r"^echo\s+[^/]*$"]}
        )
        assert result["status"] == "ask"

    def test_opaque_expansion_does_not_satisfy_a_quoted_slash_free_guard(self) -> None:
        result = evaluate_bash_command('echo "$X"', {"*": "ask", "allowed_cmds_regex": [r'^echo\s+"[^/]*"$']})
        assert result["status"] == "ask"

    def test_quoted_literal_still_satisfies_a_slash_free_guard(self) -> None:
        result = evaluate_bash_command('echo "plain"', {"*": "ask", "allowed_cmds_regex": [r"^echo\s+[^/]*$"]})
        assert result["status"] == "allow"

    def test_bare_expansion_pattern_matches(self) -> None:
        # `${x}` renders in its historical short `$x` spelling, so the matching
        # pattern is written that way.
        result = evaluate_bash_command('echo "${x}"', {"*": "ask", "allowed_cmds_regex": [r"^echo\s+\$x$"]})
        assert result["status"] == "allow"

    def test_pattern_with_literal_quotes_never_matches(self) -> None:
        # Documented consequence of `_command_string` stripping outer quotes
        # from every argument: a quote-preserving pattern cannot match, so
        # this stays `ask` (it also stayed `ask` before the fix).
        result = evaluate_bash_command('echo "${x}"', {"*": "ask", "allowed_cmds_regex": [r'^echo\s+"\$\{x\}\"$']})
        assert result["status"] == "ask"

    def test_length_expansion_matches_its_own_pattern(self) -> None:
        result = evaluate_bash_command("echo ${#x}", {"*": "ask", "allowed_cmds_regex": [r"^echo\s+\$\{#x\}$"]})
        assert result["status"] == "allow"

    def test_length_expansion_does_not_match_the_bare_param_pattern(self) -> None:
        # `${#x}` is a different expression from `$x`; an allow pattern written
        # for `$x` must not auto-approve it.
        result = evaluate_bash_command("echo ${#x}", {"*": "ask", "allowed_cmds_regex": [r"^echo\s+\$x$"]})
        assert result["status"] == "ask"

    def test_blocked_pattern_sees_the_length_sigil(self) -> None:
        result = evaluate_bash_command("echo ${#x}", {"*": "allow", "blocked_cmds_regex": [r"^echo\s+\$\{#x\}$"]})
        assert result["status"] == "deny"

    def test_indirect_expansion_matches_its_own_pattern(self) -> None:
        result = evaluate_bash_command("echo ${!x}", {"*": "ask", "allowed_cmds_regex": [r"^echo\s+\$\{!x\}$"]})
        assert result["status"] == "allow"

    def test_indirect_expansion_does_not_match_the_bare_param_pattern(self) -> None:
        # `${!x}` is a different expansion from `$x`.  This is the direction the
        # fix moves: before it, the rendered text was `$x`, so this pattern
        # *did* auto-approve the indirect expansion (fail-open).  Now it asks.
        result = evaluate_bash_command("echo ${!x}", {"*": "ask", "allowed_cmds_regex": [r"^echo\s+\$x$"]})
        assert result["status"] == "ask"

    def test_blocked_pattern_sees_the_indirect_sigil(self) -> None:
        result = evaluate_bash_command("echo ${!x}", {"*": "allow", "blocked_cmds_regex": [r"^echo\s+\$\{!\w*\}$"]})
        assert result["status"] == "deny"
