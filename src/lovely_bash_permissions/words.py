"""Rendering a shell word as text, in three forms.

Every matcher and every display in the package reads words through one of
these, so the three forms are defined once:

- :func:`word_value` - best-effort value, quotes removed (display, command names)
- :func:`word_raw` - the text as written, quotes kept (patterns that match quotes)
- :func:`word_exec` - the *executed* form: quotes removed, backslashes
  unescaped. **Policy is decided on this form**, never on the text as typed;
  see ``docs/ARCHITECTURE.md``.

Expansions whose value is only known at runtime render as placeholders
(:data:`CMD_SUBST_PLACEHOLDER`, :data:`ARITHM_PLACEHOLDER`, ``<(...)``) in all
three forms. The evaluator keys off the ``$(...)`` spelling to decide that a
pattern match is unreliable, so it is a constant rather than a literal.

Depends on ``ast.py`` alone, like ``inspect.py``.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from .ast import (
    ArithmExp,
    CmdSubst,
    DblQuoted,
    ExtGlob,
    Lit,
    Node,
    ParamExp,
    ProcSubst,
    SglQuoted,
    Word,
)

#: What a ``$(...)`` / backtick substitution renders as. Load-bearing: see the
#: module docstring.
CMD_SUBST_PLACEHOLDER = "$(...)"

#: What a ``$(( ... ))`` arithmetic expansion renders as.
ARITHM_PLACEHOLDER = "$(( ... ))"


def _opaque_part(part: Node) -> str:
    """The placeholder for a part whose value only exists at runtime, else ``""``.

    Shared by all three renderers, which agree on these and differ only in how
    they treat quoting.
    """
    if isinstance(part, CmdSubst):
        return CMD_SUBST_PLACEHOLDER
    if isinstance(part, ArithmExp):
        return ARITHM_PLACEHOLDER
    if isinstance(part, ProcSubst):
        return f"{part.op}...)"
    return ""


def _slice_operand_text(node: Node | None, render_word: Callable[[Word], str]) -> str:
    """Render one operand of a ``${var:offset:length}`` slice.

    Slice operands are typed as bare ``Node`` (a Word in practice, but shfmt
    also allows an arithmetic expression), so anything that is not a Word
    falls back to the arithmetic placeholder instead of crashing the renderer.
    """
    if isinstance(node, Word):
        return render_word(node)
    if isinstance(node, ArithmExp):
        return ARITHM_PLACEHOLDER
    return ""


def _param_exp_text(part: ParamExp, render_word: Callable[[Word], str]) -> str:
    """Render a parameter expansion, keeping every operator and operand.

    Operand words are rendered by *render_word* - the caller passes its own
    word renderer so nesting, quoting and the opaque ``$(...)`` placeholder
    behave identically to top-level parts (a ``CmdSubst`` operand must keep
    rendering as ``$(...)``, because ``evaluate`` keys off that exact string
    to decide a pattern match is unreliable).

    A bare ``$VAR`` / ``${VAR}`` keeps its simple ``$VAR`` spelling; every
    other form keeps its full text so a pattern matching the argument still
    sees the whole expansion (e.g. ``${BAR:-/etc/passwd}`` rather than
    ``$BAR``, which would hide the literal path from the matcher).

    ``${#VAR}`` and ``${!VAR}`` keep their leading sigil, which makes them braced
    forms even though they have no operator: the length of ``$x`` is a different
    expression from ``$x`` itself, and ``${!x}`` (indirect expansion - read the
    variable *named* by ``$x``) is a third, as is the prefix form ``${!prefix*}``.
    Rendering any of them as ``$x`` would hand the matcher the wrong expression.
    The sigils are mutually exclusive, so ``length`` takes precedence over
    ``excl``.
    """
    # `${#x}` (string length) and `${!x}` (indirect expansion) are both a
    # *different* expression from `${x}`: dropping the sigil hands the matcher a
    # different expansion than the user wrote, so the sigil must survive
    # rendering.  The two are mutually exclusive in bash (``${#!x}`` is a bad
    # substitution), so ``length`` wins and ``excl`` is only consulted without
    # it - and a sigil of either kind forces the braced spelling, because a bare
    # ``$x`` can carry neither.
    #
    # A prefix expansion's glob (``${!prefix*}``) travels in its own ``Names``
    # key rather than in the parameter name, so it is appended after the sigil
    # and the name.  Only the prefix form sets it: ``${!x}`` has no glob, and in
    # ``${!arr[*]}`` the star is part of the index and is rendered from there.
    if part.length:
        sigil = "#"
    elif part.excl:
        sigil = "!"
    else:
        sigil = ""
    op_text = ""
    exp = part.exp
    if exp is not None and exp.op:
        op_text = f"{exp.op}{render_word(exp.word) if exp.word is not None else ''}"
    if part.orig is not None or part.replacement is not None:
        # `${var/pat/rep}` and `${var//pat/rep}` - ``all`` is set for the ``//``
        # (replace-all) spelling.
        op_text += "//" if part.all else "/"
        if part.orig is not None:
            op_text += render_word(part.orig)
        op_text += "/"
        if part.replacement is not None:
            op_text += render_word(part.replacement)
    suffix = ""
    if part.index is not None:
        suffix += f"[{render_word(part.index)}]"
    if part.slice is not None:
        offset = _slice_operand_text(part.slice.offset, render_word)
        length = _slice_operand_text(part.slice.length, render_word)
        # An absent length is the offset-only spelling `${var:offset}`.
        suffix += f":{offset}:{length}" if part.slice.length is not None else f":{offset}"
    # A prefix expansion's glob rides on the parameter name (`${!prefix*}`), so
    # it is folded in before deciding whether the braced spelling is needed.
    name_text = part.param + part.names
    if not op_text and not suffix:
        if sigil:
            return "${" + sigil + name_text + "}"
        return f"${name_text}"
    return "${" + sigil + name_text + op_text + suffix + "}"


def _value_part(part: Node) -> str:
    """Render one word part in best-effort *value* form (quotes removed).

    Split out of :func:`word_value` so that the per-part dispatch can be
    reused when recursing into a ``"..."`` region's parts.

    :class:`DblQuoted` deliberately does *not* short-circuit on its own
    ``value`` field: that field is lossy (``converter._convert_dbl_quoted``
    splices every non-literal part out of it), so ``"pre${x}y"`` would render as
    the string ``"prey"`` - text the user never typed, which a restrictive
    allowed pattern could then be fooled by.  Recursing keeps the expansion
    visible.  ``DblQuoted.parts`` is a strict sub-tree, so the recursion is
    finite.
    """
    if isinstance(part, (Lit, SglQuoted)):
        return part.value
    if isinstance(part, DblQuoted):
        if part.parts:
            return "".join(_value_part(p) for p in part.parts)
        # No parts (shfmt produced none): fall back to the stored value.
        return part.value or ""
    if isinstance(part, ParamExp):
        return _param_exp_text(part, word_value)
    if isinstance(part, ExtGlob):
        return f"{part.op}{part.pattern.value if part.pattern else ''})"
    return _opaque_part(part)


def word_value(word: Word) -> str:
    """Get the best-effort string value of a word (concatenating all parts).

    Handles Lit, SglQuoted, DblQuoted, ParamExp, CmdSubst, ArithmExp,
    ExtGlob, and ProcSubst parts explicitly (see
    :func:`_value_part`).  Unknown part types render as the empty string.
    """
    return "".join(_value_part(part) for part in word.parts)


_UNESCAPE_UNQUOTED = re.compile(r"\\([^\n])")
_UNESCAPE_DBLQUOTED = re.compile(r"\\([$`\"\\])")


def _unescape_lit(value: str, *, in_double_quotes: bool) -> str:
    """Bash-style backslash unescaping for a Lit value.

    Unquoted: a backslash drops the next character (bash rule).
    Double-quoted: a backslash is only special before $, `, ", \\ (and
    newline); elsewhere it is literal.
    """
    if in_double_quotes:
        return _UNESCAPE_DBLQUOTED.sub(r"\1", value)
    return _UNESCAPE_UNQUOTED.sub(r"\1", value)


def _raw_part(part: Node) -> str:
    """Render one word part in its *raw* form, preserving quote characters.

    Split out of :func:`word_raw` so that the per-part dispatch can be
    reused when recursing into a ``"..."`` region's parts.

    A ``DblQuoted`` recurses into its parts for the same fidelity reason as
    :func:`_value_part` (``DblQuoted.value`` is lossy), wrapping the result in
    the quote characters so the region still reads as quoted - a
    quote-preserving pattern like ``^echo\\s+"\\$\\{x\\}"$`` can then match it.

    Unlike :func:`_exec_part` this does *not* switch backslash handling for
    parts inside ``"..."``: the raw form is the text as written, and
    unescaping is the executed form's job.  A nested ``"..."`` region is just
    another ``DblQuoted``, so it renders recursively and terminates.
    """
    if isinstance(part, Lit):
        return part.value
    if isinstance(part, SglQuoted):
        return f"'{part.value}'"
    if isinstance(part, DblQuoted):
        if part.parts:
            return '"' + "".join(_raw_part(p) for p in part.parts) + '"'
        # No parts (shfmt produced none): fall back to the stored value.
        return f'"{part.value}"' if part.value is not None else ""
    if isinstance(part, ParamExp):
        return _param_exp_text(part, word_raw)
    if isinstance(part, ExtGlob):
        return f"{part.op}{part.pattern.value if part.pattern else ''})"
    return _opaque_part(part)


def word_raw(word: Word) -> str:
    """Get the raw text of a word, preserving quotes.

    Unlike :func:`word_value`, this includes quote characters for quoted
    parts, so patterns like ``^echo\\s+'hello'`` can match quoted arguments.
    A ``DblQuoted`` containing an expansion still keeps its quotes *and* the
    expansion text (see :func:`_raw_part`).
    """
    return "".join(_raw_part(part) for part in word.parts)


def _exec_part(part: Node, in_double_quotes: bool) -> str:
    """Render one word part in its executed form.

    *in_double_quotes* is True when the part occurs inside a ``"..."``
    region (including nested double-quoted regions), which changes how
    backslashes in :class:`Lit` values are unescaped.
    """
    if isinstance(part, Lit):
        return _unescape_lit(part.value, in_double_quotes=in_double_quotes)
    if isinstance(part, SglQuoted):
        if in_double_quotes:
            # Quote characters are literal inside "..."; the content follows
            # double-quote-context backslash rules.
            return _unescape_lit(part.value, in_double_quotes=True)
        return part.value
    if isinstance(part, DblQuoted):
        if part.parts:
            return "".join(_exec_part(p, True) for p in part.parts)
        return _unescape_lit(part.value or "", in_double_quotes=True)
    if isinstance(part, ParamExp):
        return _param_exp_text(part, word_exec)
    if isinstance(part, ExtGlob):
        return part.pattern.value if part.pattern else ""
    return _opaque_part(part)


def word_exec(word: Word) -> str:
    """Best-effort *executed* form of a word: the string bash would produce
    after quote removal and backslash unescaping (placeholders kept for
    expansions). Used for security pattern matching so quote-split or
    backslash-escaped spellings of a path/flag cannot bypass the raw form.
    """
    return "".join(_exec_part(part, False) for part in word.parts)
