"""
Bash command segment parser.

This module provides the :func:`parse_segments` function which parses
bash command strings into structured segments. Each segment contains
the command name, arguments, and redirections.

Segment extraction handles:
    - Pipes (|): each side becomes a separate segment
    - And (&&) and Or (||): shfmt reports these as BinaryCmd too, differing
      only in ``op``; each side becomes a separate segment
    - Background (&): the command before & is extracted
    - Statements: each sequential command becomes a segment

If parsing fails, an empty list is returned - so an empty list is ambiguous:
it means either "the command genuinely contains no commands" or "the command
could not be parsed".  See :func:`parse_segments` for why no in-tree caller is
exposed to that, and what a direct caller should do instead.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from typing import Any, TypedDict

from .ast import (
    ArithmCmd,
    ArithmExp,
    ArrayElem,
    ArrayExpr,
    Assign,
    BinaryArithm,
    BinaryCmd,
    BinaryTest,
    Block,
    CallExpr,
    CaseClause,
    CmdSubst,
    CoprocClause,
    CStyleLoop,
    DblQuoted,
    DeclClause,
    ElifBranch,
    ExtGlob,
    File,
    FlagsArithm,
    ForClause,
    FuncDecl,
    IfClause,
    LetClause,
    Lit,
    Node,
    ParamExp,
    ParamExpExp,
    ParamExpSlice,
    ParenArithm,
    ParenTest,
    ProcSubst,
    Redir,
    SglQuoted,
    Stmt,
    Subshell,
    TestClause,
    TimeClause,
    UnaryArithm,
    UnaryTest,
    WhileClause,
    Word,
)
from .converter import node_from_json
from .errors import ShfmtError
from .parser import parse
from .words import CMD_SUBST_PLACEHOLDER, word_exec, word_raw, word_value

_logger = logging.getLogger(__name__)

#: Default shell dialect used for parsing
DEFAULT_DIALECT = "bash"


# ---------------------------------------------------------------------------
# Segment wire types
# ---------------------------------------------------------------------------
#
# ``parse_segments`` is public API and its return value is consumed directly by
# callers (and by ``rules.py``), so its shape is a contract. The field names
# below are the shfmt wire names on purpose: the redirection dicts are the
# shfmt-shaped records the segment producers build, and spelling them the way
# shfmt does keeps the mapping between the two representations obvious instead
# of hiding it behind a translation layer that would then have to be undone.


class SegmentRedirection(TypedDict):
    """One redirection carried by a segment.

    Attributes:
        Op: Redirection operator as bash wrote it, e.g. ``>``, ``>>``, ``2>``
            arrives as ``>`` with ``N`` set.
        N: The explicit file descriptor shfmt extracted from the operator, as
            ``{"Value": "<fd>"}``; the empty dict when the operator carried no
            fd prefix.
        Target: The full executed form of the redirect target: every word part
            joined, quotes removed and backslashes unescaped.  This is what
            policy decisions are made on, because it is the string bash
            actually opens.
    """

    Op: str
    N: dict[str, str]
    Target: str


class Segment(TypedDict, total=False):
    """One command segment.

    ``normalized_arguments`` is the reason this is not ``total``: it is only
    emitted for a real command (the pseudo-command segments - a bare assignment,
    a declaration operand, a redirection-only statement - have no argument
    list to normalize).
    """

    command: str
    arguments: list[str]
    normalized_arguments: list[str]
    redirections: list[SegmentRedirection]


def _array_text(assign: Assign) -> str:
    """Render an array assignment's elements, e.g. ``(a b c)``.

    Falls back to the ``(...)`` placeholder when the array has no elements.
    """
    array = assign.array
    if not isinstance(array, ArrayExpr):
        return "(...)"
    elems: list[str] = []
    for elem in array.elems:
        if not isinstance(elem, ArrayElem) or (elem.value is None and elem.index is None):
            continue
        text = word_raw(elem.value) if elem.value is not None else ""
        if isinstance(elem.index, Word):
            # Sparse array (`A=([0]=x)`): keep the subscript visible so the
            # element is not silently read as a positional one.
            text = f"[{word_raw(elem.index)}]={text}"
        if text:
            elems.append(text)
    if not elems:
        return "(...)"
    return f"({' '.join(elems)})"


def assign_operand_text(assign: Assign) -> str:
    """Render a variable assignment's operand, e.g. ``bar``, ``a[0]=bar``, ``=(a b)``.

    Covers every shape shfmt can produce: scalar, subscripted, array, and
    append (``+=``) in combination with a subscript or an array.  Returns
    ``""`` only when there is genuinely nothing to render.

    Two orderings matter here.  The *array* case has to be resolved before
    ``append`` is consulted, because shfmt reports ``A+=(a b)`` with
    ``append=True`` and the value in ``array`` (not ``value``) - reading
    ``value`` first rendered a bare ``A+=`` and dropped the elements.  And the
    subscript belongs to the whole assignment rather than to the value, so it
    goes between the name and the operator: ``A[i]+=(x y)``.

    Args:
        assign: The ``Assign`` node to render.

    Returns:
        The assignment as written, or ``""`` if there is nothing to render.
    """
    name = assign.name.value if assign.name is not None and assign.name.value else ""
    if assign.naked:
        # A declaration operand with no operator: either a bare name
        # (`export FOO`) or a flag, which shfmt carries as a name-less assign
        # whose value is the flag text (`declare -a`).
        if name:
            return name
        return word_raw(assign.value) if assign.value is not None else ""

    # shfmt types Assign.index as the general Node; every subscript it actually
    # emits is a Word, and anything else has no renderable text.
    index = f"[{word_raw(assign.index)}]" if isinstance(assign.index, Word) else ""
    operator = "+=" if assign.append else "="

    if assign.array is not None:
        operand = _array_text(assign)
    elif assign.value is not None:
        operand = word_raw(assign.value)
    else:
        operand = ""

    if not operand:
        # `A=` / `A+=` with nothing on the right: the operator is all there
        # is. Render it (when there is a name to hang it on) so the assignment
        # still reaches the variable_assignment policy as a segment.
        return f"{name}{index}{operator}" if name else ""
    if not name:
        # No name to hang the operator on - emit the operand on its own rather
        # than dropping the assignment and, with it, the whole segment.
        return operand
    return f"{name}{index}{operator}{operand}"


def _assign_sub_segments(assigns: list[Assign], redirs: list[Redir]) -> list[Segment]:
    """Surface the commands and redirections hidden inside assignment operands.

    An assignment's value, subscript or array elements can contain command
    substitutions, and bash runs them: ``x=$(echo hi > /etc/passwd)`` writes
    the file. Walking them here is what makes the inner command a segment of
    its own, so the allow-list sees it and the redirection policies can see its
    redirections.

    Every path that renders an assignment must call this. It was originally
    present only on the standalone-assignment path, so an assignment *prefix*
    (``x=$(cmd) ls``) hid the whole substitution - the inner command was
    missing from ``parse_segments`` and its redirection escaped
    ``output_redirection`` / ``input_redirection`` entirely.
    """
    out: list[Segment] = []
    for assign in assigns:
        if assign.index is not None:
            out.extend(_extract_segments(assign.index, redirs))
        if assign.value is not None:
            out.extend(_extract_segments(assign.value, redirs))
        if isinstance(assign.array, ArrayExpr):
            for elem in assign.array.elems:
                if isinstance(elem, ArrayElem):
                    if elem.index is not None:
                        out.extend(_extract_segments(elem.index, redirs))
                    if elem.value is not None:
                        out.extend(_extract_segments(elem.value, redirs))
    return out


def _redir_dicts(redirs: list[Redir]) -> list[SegmentRedirection]:
    """Serialize Redir nodes into the segment dict format.

    Mirrors the shape produced for CallExpr/DeclClause/LetClause segments so
    callers (``check_output_redirections`` / ``check_input_redirections``)
    can classify them uniformly. shfmt normalizes fd-prefixed operators into the
    ``N`` field (e.g. ``2>`` -> ``Op: ">", N: {"Value": "2"}``).

    ``Target`` is the only field policy is decided on: the full executed form
    of the target, so multi-part targets like ``"$DIR/out"``, ``"/dev""/null"``
    or quote-split paths are identified correctly.  An earlier shape also
    carried a part-wise ``Word`` projection rebuilt from the raw shfmt JSON;
    it was lossy by construction (it dropped quoting, escapes and expansions)
    and no policy ever read it, so it has been removed.  ``Target`` always
    subsumes it.
    """
    return [
        {
            "Op": r.op,
            "N": {"Value": str(r.n)} if r.n is not None else {},
            "Target": word_exec(r.word) if r.word is not None else "",
        }
        for r in redirs
    ]


def _extract_redirs(node: object) -> list[Redir]:
    """Extract the redirections carried by a compound operand.

    An operand made of redirections and nothing else (as in ``> /etc/x && cat
    f``) reaches the converter as a ``Stmt``, so that is the only shape with
    redirections to hand back.  A ``BinaryCmd`` operand's redirections are
    already split onto its per-side ``left_redirs``/``right_redirs`` fields and
    are read there by the caller, which is what attributes each one to the
    correct side of the pipe.

    Args:
        node: A typed AST node.

    Returns:
        List of Redir objects found on this node; empty for every other shape.
    """
    if isinstance(node, Stmt):
        return list(node.redirs)
    return []


def _arithm_text(node: object) -> str:
    """Render a ``let`` arithmetic expression as the text its segment carries.

    Every expansion is opaque here - an arithmetic expansion renders as the
    command-substitution placeholder and a parameter expansion as ``${...}`` -
    and any other node as ``?``.
    """
    if isinstance(node, ArithmExp):
        return CMD_SUBST_PLACEHOLDER
    if isinstance(node, BinaryArithm):
        return f"({_arithm_text(node.left)}){node.op}({_arithm_text(node.right)})"
    if isinstance(node, UnaryArithm):
        return f"{node.op}{_arithm_text(node.x)}"
    if isinstance(node, ParenArithm):
        return f"({_arithm_text(node.body)})"
    if isinstance(node, FlagsArithm):
        return f"{node.flags}({_arithm_text(node.x)})"
    if isinstance(node, Word):
        return word_value(node)
    if isinstance(node, Lit):
        return node.value
    if isinstance(node, ParamExp):
        return "${...}"
    return "?"


def _each(children: Iterable[object], redirs: list[Redir] | None = None) -> list[Segment]:
    """Extract segments from every child in turn, passing each the same *redirs*."""
    out: list[Segment] = []
    for child in children:
        out.extend(_extract_segments(child, redirs))
    return out


def _present(*children: object) -> list[object]:
    """The children that are not ``None``, in order."""
    return [child for child in children if child is not None]


def _redir_target_segments(redirs: list[Redir]) -> list[Segment]:
    """Segments hidden inside redirection targets and heredoc bodies.

    ``cmd > $(generate_name)`` runs ``generate_name``, and so does
    ``cmd <<EOF\n$(cat /etc/passwd)\nEOF`` for an unquoted heredoc, so both
    are walked for substitutions.
    """
    out: list[Segment] = []
    for r in redirs:
        if r.word is not None:
            out.extend(_extract_segments(r.word))
        if r.hdoc is not None:
            out.extend(_extract_segments(r.hdoc))
    return out


# ---------------------------------------------------------------------------
# Per-node handlers
# ---------------------------------------------------------------------------
#
# One handler per node type, looked up by exact type in ``_HANDLERS``. Every
# handler receives the redirections inherited from an enclosing statement or
# pipe (never ``None``) and returns the segments its node produces, in
# execution order.
#
# Only constructs that actually execute become segments. Inside a ``[[ ]]``
# test *nothing* the operands say is executed - bash compares values - so every
# operand (literal, expansion, arithmetic) is a value and the only commands
# reachable there are the ones a substitution runs.


def _binary_cmd(node: BinaryCmd, redirs: list[Redir]) -> list[Segment]:
    # Pipe / logical-operator commands: each side becomes a separate segment.
    # (``&&`` and ``||`` arrive here too - shfmt reports them as a BinaryCmd
    # whose op is "&&"/"||".)  Redirections live on the per-side fields; also
    # inherit any redirections from a parent compound (e.g. `{ a | b; } > file`).
    left_redirs = [*redirs, *(_extract_redirs(node.left) if node.left else []), *node.left_redirs]
    right_redirs = [*redirs, *(_extract_redirs(node.right) if node.right else []), *node.right_redirs]
    return [*_extract_segments(node.left, left_redirs), *_extract_segments(node.right, right_redirs)]


def _stmt(node: Stmt, redirs: list[Redir]) -> list[Segment]:
    # Merge redirections inherited from a parent compound command
    # (e.g. `{ ...; } > file`) with the statement's own.
    inherited = [*redirs, *node.redirs]
    segments = _extract_segments(node.cmd, inherited) if node.cmd is not None else []
    if inherited and (not segments or isinstance(node.cmd, TestClause)):
        # The statement carries redirections but no command segments (e.g.
        # `> f` alone, `((x)) > f`, or a `[[ ... ]]` whose body has no
        # commands - `[[ -f x ]] > f`). Emit a synthetic segment carrying
        # the redirections so input/output redirection policies apply
        # instead of falling through to the empty-segment wildcard
        # short-circuit. For `[[ ]]` this fires even when the
        # body yielded pseudo-command segments: statement redirections must
        # not be scattered onto test-expression pseudo-commands.
        command = "[[" if isinstance(node.cmd, TestClause) else ""
        segments.append({"command": command, "arguments": [], "redirections": _redir_dicts(inherited)})
    return segments


def _call_expr(node: CallExpr, redirs: list[Redir]) -> list[Segment]:
    segments: list[Segment] = []
    assigns = node.assigns or []
    operands = [operand for operand in (assign_operand_text(a) for a in assigns) if operand]
    if not node.args:
        if assigns:
            # Standalone variable assignment (no Args, only Assigns): a segment
            # so it can be evaluated against allowed patterns.
            segments.append({"command": "", "arguments": operands, "redirections": _redir_dicts(redirs)})
            # Recurse into assignment sub-expressions (values, indexes, arrays)
            # so the redirection in `x=$(echo hi > /etc/passwd)` surfaces for
            # blocked-path checks.
            segments.extend(_assign_sub_segments(assigns, redirs))
        return segments

    # Variable assignments alongside a command (FOO=bar ls) become their own
    # segment, so the `variable_assignment` policy reaches them. This applies
    # to EVERY assignment, including one whose value captures a command's
    # output (`FOO=$(cmd) ls`): it is still an assignment, and the
    # `command_substitution` policy is applied on top of it by the evaluator,
    # so both gates fire rather than one silently standing in for the other.
    if operands:
        segments.append({"command": "", "arguments": operands, "redirections": []})
    segments.append(
        {
            "command": word_value(node.args[0]),
            "arguments": [word_raw(arg) for arg in node.args[1:]],
            "normalized_arguments": [word_exec(arg) for arg in node.args[1:]],
            "redirections": _redir_dicts(redirs),
        }
    )
    # Recurse into arguments to find nested CmdSubst/ProcSubst redirections.
    # args[0] is included deliberately: a command name that is itself an
    # expansion still runs what it expands to, so `$(echo hi > f)` and
    # `${x:-$(cmd)} arg` must surface the inner command - otherwise the
    # inner redirection is invisible to the redirection policies.
    segments.extend(_each(node.args, redirs))
    segments.extend(_redir_target_segments(redirs))
    # And into the assignment operands, so `x=$(cmd > f) ls` surfaces the same
    # segments the standalone form `x=$(cmd > f)` does.
    segments.extend(_assign_sub_segments(assigns, redirs))
    return segments


def _decl_clause(node: DeclClause, redirs: list[Redir]) -> list[Segment]:
    # A declaration builtin's operands are variable assignments - `export
    # FOO=bar` assigns exactly as `FOO=bar` does, and `local x=1` likewise - so
    # they are split into their own variable-assignment segment, the same way
    # the CallExpr handler splits `FOO=bar ls`. The variant keyword stays a
    # command segment in its own right (`export` really does run). Keeping the
    # operands as arguments of the variant segment instead meant
    # `variable_assignment` never reached them, so `export FOO=bar` was
    # approved even under `"variable_assignment": "deny"`.
    segments: list[Segment] = []
    declares = node.assigns or []
    operands = [operand for operand in (assign_operand_text(a) for a in declares) if operand]
    if operands:
        segments.append({"command": "", "arguments": operands, "redirections": []})
        segments.append({"command": node.variant, "arguments": [], "redirections": _redir_dicts(redirs)})
    segments.extend(_redir_target_segments(redirs))
    # Recurse into the declaration's operands (e.g. `export FOO=$(rm x)`).
    segments.extend(_assign_sub_segments(declares, redirs))
    return segments


def _let_clause(node: LetClause, redirs: list[Redir]) -> list[Segment]:
    # let - variable assignment with arithmetic. Extracted as a
    # variable-assignment segment whose arguments are the rendered
    # expressions; each expression is also walked for embedded substitutions.
    segments: list[Segment] = []
    args: list[str] = []
    for expr in node.exprs:
        args.append(_arithm_text(expr))
        segments.extend(_extract_segments(expr))
    if args:
        # Inherit redirections from the parent Stmt (same as CallExpr).
        segments.append({"command": "", "arguments": args, "redirections": _redir_dicts(redirs)})
    return segments


def _case_clause(node: CaseClause, redirs: list[Redir]) -> list[Segment]:
    # The subject word and each branch's match patterns can embed command
    # substitutions that bash evaluates before the body runs - surface them
    # alongside the branch bodies.
    segments = _each(_present(node.expr), redirs)
    for branch in node.branches:
        segments.extend(_each(branch.patterns, redirs))
        segments.extend(_each(branch.body, redirs))
    return segments


def _for_clause(node: ForClause, redirs: list[Redir]) -> list[Segment]:
    # C-style prelude first, then the loop-list words (for i in $(...); ...),
    # which bash evaluates before the body, then the body.
    prelude = _cstyle_loop(node.cstyle, redirs) if node.cstyle is not None else []
    return [*prelude, *_each(node.words, redirs), *_each(node.body, redirs)]


def _cstyle_loop(node: CStyleLoop, redirs: list[Redir]) -> list[Segment]:
    # for ((init; cond; post)) arithmetic may embed command substitutions.
    return _each(_present(node.init, node.cond, node.post), redirs)


def _if_clause(node: IfClause, redirs: list[Redir]) -> list[Segment]:
    # Conditions and every branch body are real executions.
    return _each([*node.cond_stmts, *node.then_stmts, *node.elif_branches, *node.else_stmts], redirs)


def _elif_branch(node: ElifBranch, redirs: list[Redir]) -> list[Segment]:
    return _each([*node.cond, *node.body], redirs)


def _while_clause(node: WhileClause, redirs: list[Redir]) -> list[Segment]:
    return _each([*node.cond_stmts, *node.body], redirs)


def _stmts_with_redirs(node: Subshell | Block, redirs: list[Redir]) -> list[Segment]:
    # A subshell or a curly-brace block: redirections apply to every statement.
    return _each(node.stmts, redirs)


def _func_decl(node: FuncDecl, redirs: list[Redir]) -> list[Segment]:
    # Redirections on the whole definition (`f() { ...; } > file`) apply to
    # the body.
    return _extract_segments(node.body, redirs)


def _substitution(node: CmdSubst | ProcSubst, redirs: list[Redir]) -> list[Segment]:
    return _each(node.stmts, redirs)


def _test_clause(node: TestClause, redirs: list[Redir]) -> list[Segment]:
    # `[[ ]]` never executes its operands, so nothing is emitted for them
    # directly - the recursion exists only to reach substitutions nested
    # inside them. Statement-level redirections (`[[ -f x ]] > file`) are NOT
    # propagated: the Stmt handler's synthetic segment carries them, since a
    # test expression produces no command leaves of its own for them to ride on.
    return _each(_present(node.body))


def _binary_test(node: BinaryTest, redirs: list[Redir]) -> list[Segment]:
    # Every operand of a `[[ ]]` binary test is a value being compared - the
    # subject on the left, and the pattern / regex / number on the right. Bash
    # never runs them, so neither is a command. Both sides are recursed plainly:
    # the only commands found are those a substitution inside an operand runs
    # (`[[ -d $(pwd) ]]`, `[[ $x == $(cmd) ]]`).
    return _each(_present(node.left, node.right))


def _arithm_cmd(node: ArithmCmd, redirs: list[Redir]) -> list[Segment]:
    # `(( expr ))` runs no command of its own, so nothing is emitted for the
    # arithmetic.  But bash still evaluates substitutions inside it -
    # `(( x=$(cmd) ))` really does run `cmd` - so the body is walked to
    # surface them.  Skipping it would hide the command entirely:
    # `(( x=$(rm -rf /) ))` would produce zero segments and fall through
    # the empty-segment path to the wildcard, which under `"*": "allow"`
    # would auto-approve a command nothing had inspected.  Every sibling
    # spelling recurses for the same reason (`x=$(cmd)`, `let x=$(cmd)`,
    # `[[ -n $(cmd) ]]`, `$(( $(cmd) ))`), so `(( ... ))` must too.
    return _each(_present(node.body))


def _param_exp(node: ParamExp, redirs: list[Redir]) -> list[Segment]:
    # Parameter expansion (${x:-default}, ${x/pat/rep}, ${arr[i]}, ${x:0:3},
    # ...) may embed nested command substitutions in its operand, pattern,
    # replacement, index, or slice expressions. Recurse into each so the inner
    # commands surface as segments for allowed-pattern and blocked-path
    # checks. This must happen everywhere, including inside a `[[ ]]` test:
    # `[[ ${x:-$(rm -rf /)} ]]` really does run the inner substitution while
    # evaluating the operand, and suppressing it here yielded no segments at
    # all, so the empty-segment fallback applied the wildcard and approved the
    # whole command.
    children = _present(node.index, node.orig, node.replacement, node.slice)
    if isinstance(node.exp, ParamExpExp) and node.exp.word is not None:
        children.append(node.exp.word)
    return _each(children)


def _nothing(node: Node, redirs: list[Redir]) -> list[Segment]:
    """A node that neither runs a command nor can contain one.

    Explicit rather than absent, because an absent type logs an "Unhandled AST
    node type" warning. A bare literal is only ever a command name when shfmt
    has already put it in command position (the first word of a CallExpr),
    which is handled there; reached as a word part it is data - an argument, a
    glob, an operand under test. Single-quoted text and an extended glob
    cannot hide a substitution.
    """
    return []


def _children(*fields: str) -> Callable[[Any, list[Redir]], list[Segment]]:
    """A handler that walks the named fields and passes no redirections down.

    For the value-bearing nodes - words, quoted text, tests, arithmetic, and
    the single-command wrappers - whose only possible commands are the ones a
    nested substitution runs.
    """

    def handler(node: Any, redirs: list[Redir]) -> list[Segment]:  # noqa: ANN401 - any of the node types below
        children: list[object] = []
        for name in fields:
            value = getattr(node, name)
            if isinstance(value, list):
                children.extend(value)
            elif value is not None:
                children.append(value)
        return _each(children)

    return handler


_HANDLERS: dict[type[Node], Callable[[Any, list[Redir]], list[Segment]]] = {
    BinaryCmd: _binary_cmd,
    Stmt: _stmt,
    CallExpr: _call_expr,
    DeclClause: _decl_clause,
    LetClause: _let_clause,
    CaseClause: _case_clause,
    ForClause: _for_clause,
    CStyleLoop: _cstyle_loop,
    IfClause: _if_clause,
    ElifBranch: _elif_branch,
    WhileClause: _while_clause,
    Subshell: _stmts_with_redirs,
    Block: _stmts_with_redirs,
    FuncDecl: _func_decl,
    CmdSubst: _substitution,
    ProcSubst: _substitution,
    File: _children("stmts"),
    TestClause: _test_clause,
    BinaryTest: _binary_test,
    UnaryTest: _children("x"),
    ParenTest: _children("body"),
    ArithmCmd: _arithm_cmd,
    TimeClause: _children("stmt"),
    CoprocClause: _children("stmt"),
    # Word and double-quoted parts: the bare Lit/SglQuoted fragments emit
    # nothing, while an embedded substitution is a real command. Stopping at
    # the word instead would emit its own text as a command name, producing
    # "$(...)" and "$var" phantom commands.
    Word: _children("parts"),
    DblQuoted: _children("parts"),
    Lit: _nothing,
    SglQuoted: _nothing,
    ExtGlob: _nothing,
    ParamExp: _param_exp,
    # ${x:offset:length}, $(( ... )) and the arithmetic operators: bash runs a
    # substitution in any operand (`${x:$(cmd):3}`, `$(( N + $(cmd) ))`).
    ParamExpSlice: _children("offset", "length"),
    ArithmExp: _children("x"),
    BinaryArithm: _children("left", "right"),
    UnaryArithm: _children("x"),
    ParenArithm: _children("body"),
    FlagsArithm: _children("x"),
}


def _extract_segments(node: object, redirs: list[Redir] | None = None) -> list[Segment]:
    """Recursively extract command segments from a typed AST node.

    Dispatches on the node's exact type through ``_HANDLERS``; see the handlers
    above for what each construct contributes.

    Args:
        node: A typed AST node.
        redirs: Redirections inherited from a parent statement/pipe.

    Returns:
        List of segment dicts (:class:`Segment`), each with:
            - 'command': str - command name
            - 'arguments': list[str] - argument strings
            - 'normalized_arguments': list[str] - argument strings with
              quoting/expansion resolved (real commands only)
            - 'redirections': list[SegmentRedirection] - redirection info
    """
    handler = _HANDLERS.get(type(node))  # type: ignore[arg-type]
    if handler is None:
        _logger.warning("Unhandled AST node type '%s' - returning 0 segments", type(node).__name__)
        return []
    return handler(node, redirs or [])


def segments_from_ast(ast: Node) -> list[Segment]:
    """Extract segments from an already-converted typed AST.

    The half of :func:`parse_segments` that does not need the shfmt subprocess.
    Split out so a caller that has *already* parsed and converted the command
    (:func:`lovely_bash_permissions.evaluate.evaluate_bash_command`, which
    needs the typed tree for its own checks anyway) can reuse that work instead
    of paying for a second parse and a second JSON-to-AST conversion.

    Args:
        ast: The converted typed AST (normally a :class:`~.ast.File`).

    Returns:
        The segment list, in execution order.
    """
    return _extract_segments(ast)


def parse_segments(command: str, dialect: str = DEFAULT_DIALECT) -> list[Segment]:
    """
    Parse a bash command into segments.

    Each segment represents a command with its name, arguments, and
    redirections. Commands are separated by pipes, logical AND/OR
    operators, background execution, and statement separators.

    Args:
        command: The bash command string to parse.
        dialect: Shell dialect for parsing (default: "bash").

    Returns:
        List of :class:`Segment` dicts. Each dict contains:
            - 'command': str - the command name
            - 'arguments': list[str] - the command's arguments
            - 'redirections': list[SegmentRedirection] - redirection info

    Note:
        An empty list is ambiguous: it means either "the command genuinely
        contains no commands" or "the command could not be parsed", because a
        parse failure is swallowed and reported as zero segments. A caller that
        must tell those apart should call :func:`parse` (or :func:`parse_ast`)
        first and handle the exception it raises.

        No in-tree caller is exposed to the ambiguity, so ``[]`` is only
        observable to direct callers of this function: ``evaluate`` parses with
        :func:`parse` (which raises) at the top of its checks and so never
        reaches here with a command it could not parse, and the inspection CLI
        parses with :func:`parse_ast` and reports the failure loudly on stderr
        with a non-zero exit.
    """
    if not command or not command.strip():
        return []

    try:
        raw_ast = parse(command, dialect)
        ast = node_from_json(raw_ast)
    except ShfmtError:
        return []

    if ast is None:
        return []
    return segments_from_ast(ast)
