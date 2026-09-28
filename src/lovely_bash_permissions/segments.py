"""
Bash command segment parser.

This module provides the :func:`parse_segments` function which parses
bash command strings into structured segments. Each segment contains
the command name, arguments, and redirections.

Segment extraction handles:
    - Pipes (|): each side becomes a separate segment
    - And (&&): each side becomes a separate segment
    - Or (||): each side becomes a separate segment
    - Background (&): the command before & is extracted
    - Statements: each sequential command becomes a segment

If parsing fails, an empty list is returned - so an empty list is ambiguous:
it means either "the command genuinely contains no commands" or "the command
could not be parsed".  See :func:`parse_segments` for why no in-tree caller is
exposed to that, and what a direct caller should do instead.
"""

from __future__ import annotations

import logging
from typing import Any

from .ast import (
    AndCmd,
    ArithmCmd,
    ArithmExp,
    ArrayElem,
    ArrayExpr,
    Assign,
    BinaryArithm,
    BinaryCmd,
    BinaryTest,
    Block,
    BraceExp,
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
    OrCmd,
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
from .errors import LovelyDevinPermissionsError
from .inspect import _word_exec, _word_raw, _word_value
from .parser import parse

_logger = logging.getLogger(__name__)

#: Default shell dialect used for parsing
DEFAULT_DIALECT = "bash"


def _part_value(p: object) -> str:
    """Extract string value from a Word part node."""
    if isinstance(p, Lit):
        return p.value
    elif hasattr(p, "value"):
        v = getattr(p, "value", None)
        return v if isinstance(v, str) else ""
    return ""


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
        text = _word_raw(elem.value) if elem.value is not None else ""
        if isinstance(elem.index, Word):
            # Sparse array (`A=([0]=x)`): keep the subscript visible so the
            # element is not silently read as a positional one.
            text = f"[{_word_raw(elem.index)}]={text}"
        if text:
            elems.append(text)
    if not elems:
        return "(...)"
    return f"({' '.join(elems)})"


def _assign_operand_text(assign: Assign) -> str:
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
        return _word_raw(assign.value) if assign.value is not None else ""

    # shfmt types Assign.index as the general Node; every subscript it actually
    # emits is a Word, and anything else has no renderable text.
    index = f"[{_word_raw(assign.index)}]" if isinstance(assign.index, Word) else ""
    operator = "+=" if assign.append else "="

    if assign.array is not None:
        operand = _array_text(assign)
    elif assign.value is not None:
        operand = _word_raw(assign.value)
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


def _assign_sub_segments(assigns: list[Assign], redirs: list[Redir]) -> list[dict[str, Any]]:
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
    out: list[dict[str, Any]] = []
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


def _redir_dicts(redirs: list[Redir]) -> list[dict[str, Any]]:
    """Serialize Redir nodes into the segment dict format.

    Mirrors the shape produced for CallExpr/DeclClause/LetClause segments so
    callers (``_check_segments_output_redirs`` / ``_check_segments_input_redirs``)
    can classify them uniformly. shfmt normalizes fd-prefixed operators into the
    ``N`` field (e.g. ``2>`` -> ``Op: ">", N: {"Value": "2"}``).
    """
    redir_dicts: list[dict[str, Any]] = []
    for r in redirs or []:
        redir_dicts.append(
            {
                "Op": r.op,
                "N": {"Value": str(r.n)} if r.n is not None else {},
                "Word": {"Parts": [{"Value": _part_value(p)} for p in (r.word.parts if r.word else [])]},
                # Full executed-form target (all word parts, quotes removed,
                # backslashes unescaped) so multi-part targets like "$DIR/out",
                # "/dev""/null" or quote-split paths are identified correctly.
                "Target": _word_exec(r.word) if r.word is not None else "",
            }
        )
    return redir_dicts


def _extract_redirs(node: object) -> list[Redir]:
    """Extract redirections from a typed AST node.

    Handles both wrapped statements (Stmt.redirs) and direct operands whose
    redirections live on the node itself (BinaryCmd left/right_redirs).

    Args:
        node: A typed AST node.

    Returns:
        List of Redir objects found on this node.
    """
    if isinstance(node, Stmt):
        return list(node.redirs)
    elif isinstance(node, BinaryCmd):
        # Per-side split - caller decides how to attribute them
        return []  # handled inline by the caller
    else:
        return []


def _extract_segments(
    node: object,
    redirs: list[Redir] | None = None,
) -> list[dict[str, Any]]:
    """
    Recursively extract command segments from an AST node.

    Only constructs that actually execute become segments. Inside a
    ``[[ ]]`` test *nothing* the operands say is executed - bash compares
    values - so every operand (literal, expansion, arithmetic) is a value and
    the only commands reachable there are the ones a substitution runs.

    Args:
        node: An AST node (raw shfmt JSON dict or Python node).
        redirs: Redirections inherited from a parent statement/pipe.

    Returns:
        List of segment dicts, each with:
            - 'command': str - command name
            - 'arguments': list[str] - argument strings
            - 'redirections': list[dict] - redirection info
    """
    segments: list[dict[str, Any]] = []

    # Handle Python AST nodes
    if isinstance(node, BinaryCmd):
        # Pipe commands: each side becomes a separate segment.
        # Redirections live on the BinaryCmd's per-side fields; also inherit
        # any redirections from a parent compound (e.g. `{ a | b; } > file`).
        left_redirs = list(redirs or [])
        right_redirs = list(redirs or [])
        left_redirs += _extract_redirs(node.left) if node.left else []
        right_redirs += _extract_redirs(node.right) if node.right else []
        if node.left_redirs:
            left_redirs = left_redirs + list(node.left_redirs)
        if node.right_redirs:
            right_redirs = right_redirs + list(node.right_redirs)
        segments.extend(_extract_segments(node.left, left_redirs))
        segments.extend(_extract_segments(node.right, right_redirs))

    elif isinstance(node, AndCmd):
        # Logical AND: each side becomes a separate segment
        left_redirs = list(redirs or [])
        right_redirs = list(redirs or [])
        left_redirs += _extract_redirs(node.left) if node.left else []
        right_redirs += _extract_redirs(node.right) if node.right else []
        segments.extend(_extract_segments(node.left, left_redirs))
        segments.extend(_extract_segments(node.right, right_redirs))

    elif isinstance(node, OrCmd):
        # Logical OR: each side becomes a separate segment
        left_redirs = list(redirs or [])
        right_redirs = list(redirs or [])
        left_redirs += _extract_redirs(node.left) if node.left else []
        right_redirs += _extract_redirs(node.right) if node.right else []
        segments.extend(_extract_segments(node.left, left_redirs))
        segments.extend(_extract_segments(node.right, right_redirs))

    elif isinstance(node, Stmt):
        # Statement: merge redirections inherited from a parent compound
        # command (e.g. `{ ...; } > file`) with the statement's own.
        inherited = list(redirs or []) + list(node.redirs)
        sub: list[dict[str, Any]] = []
        if node.cmd:
            sub = _extract_segments(node.cmd, inherited)
            segments.extend(sub)
        if inherited and (not sub or isinstance(node.cmd, TestClause)):
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

    elif isinstance(node, CallExpr):
        # Simple command: extract command, arguments, and inherited redirections
        if node.args:
            # Variable assignments alongside a command (FOO=bar ls) become
            # their own segment, so the `variable_assignment` policy reaches
            # them. This applies to EVERY assignment, including one whose
            # value captures a command's output (`FOO=$(cmd) ls`): it is still
            # an assignment, and the `command_substitution` policy is applied
            # on top of it by the evaluator, so both gates fire rather than
            # one silently standing in for the other.
            if node.assigns:
                var_assign_args = [_assign_operand_text(a) for a in node.assigns]
                var_assign_args = [arg for arg in var_assign_args if arg]
                if var_assign_args:
                    # Add variable assignment segment before the command segment
                    segments.append({"command": "", "arguments": var_assign_args, "redirections": []})

            redir_dicts = _redir_dicts(redirs or [])
            segments.append(
                {
                    "command": _word_value(node.args[0]),
                    "arguments": [_word_raw(arg) for arg in node.args[1:]],
                    "normalized_arguments": [_word_exec(arg) for arg in node.args[1:]],
                    "redirections": redir_dicts,
                }
            )
            # Recurse into arguments to find nested CmdSubst/ProcSubst redirections.
            # args[0] is included deliberately: a command name that is itself an
            # expansion still runs what it expands to, so `$(echo hi > f)` and
            # `${x:-$(cmd)} arg` must surface the inner command - otherwise the
            # inner redirection is invisible to the redirection policies.
            for arg in node.args:
                segments.extend(_extract_segments(arg, redirs))
            # Recurse into redirection target words so nested command/process
            # substitutions are extracted (e.g. `cmd > $(generate_name)`).
            # Also recurse into heredoc bodies (Hdoc) so command substitutions
            # inside unquoted heredocs (e.g. `cmd <<EOF\n$(cat /etc/passwd)\nEOF`)
            # are discovered by security checks.
            for r in redirs or []:
                if r.word is not None:
                    segments.extend(_extract_segments(r.word))
                if r.hdoc is not None:
                    segments.extend(_extract_segments(r.hdoc))
            # And into the assignment operands, so `x=$(cmd > f) ls` surfaces
            # the same segments the standalone form `x=$(cmd > f)` does.
            segments.extend(_assign_sub_segments(node.assigns or [], redirs or []))
        elif node.assigns:
            # Standalone variable assignment (no Args, only Assigns)
            # Create a segment so it can be evaluated against allowed patterns.
            redir_dicts = _redir_dicts(redirs or [])
            args = [operand for operand in (_assign_operand_text(a) for a in node.assigns) if operand]
            segments.append({"command": "", "arguments": args, "redirections": redir_dicts})
            # Recurse into assignment sub-expressions (values, indexes, arrays) so
            # the redirection in `x=$(echo hi > /etc/passwd)` surfaces for
            # blocked-path checks.
            segments.extend(_assign_sub_segments(node.assigns, redirs or []))

    elif isinstance(node, DeclClause):
        # A declaration builtin's operands are variable assignments - `export
        # FOO=bar` assigns exactly as `FOO=bar` does, and `local x=1` likewise -
        # so they are split into their own variable-assignment segment, the same
        # way the CallExpr handler splits `FOO=bar ls`. The variant keyword stays
        # a command segment in its own right (`export` really does run).
        # Keeping the operands as arguments of the variant segment instead meant
        # `variable_assignment` never reached them, so `export FOO=bar` was
        # approved even under `"variable_assignment": "deny"`.
        redir_dicts = _redir_dicts(redirs or [])
        declares = node.assigns or []

        operands: list[str] = [operand for operand in (_assign_operand_text(assign) for assign in declares) if operand]
        if operands:
            segments.append({"command": "", "arguments": operands, "redirections": []})
            segments.append({"command": node.variant, "arguments": [], "redirections": redir_dicts})
        # Recurse into redirection target words so nested command/process
        # substitutions are extracted (e.g. `export F=$(generate_name)`).
        # Also recurse into heredoc bodies (Hdoc) for the same reason as
        # the CallExpr handler above.
        for r in redirs or []:
            if r.word is not None:
                segments.extend(_extract_segments(r.word))
            if r.hdoc is not None:
                segments.extend(_extract_segments(r.hdoc))
        # Recurse into the declaration's operands (e.g. `export FOO=$(rm x)`).
        segments.extend(_assign_sub_segments(declares, redirs or []))
    elif isinstance(node, CaseClause):
        # case/switch: the subject word (node.expr) and each branch's match
        # patterns can embed command substitutions that bash evaluates before
        # the body runs - surface them alongside the branch bodies (bug #8).
        if getattr(node, "expr", None) is not None:
            segments.extend(_extract_segments(node.expr, redirs))
        if hasattr(node, "branches") and node.branches:
            for branch in node.branches:
                if hasattr(branch, "patterns") and branch.patterns:
                    for pattern in branch.patterns:
                        segments.extend(_extract_segments(pattern, redirs))
                if hasattr(branch, "body") and branch.body:
                    for stmt in branch.body:
                        segments.extend(_extract_segments(stmt, redirs))

    elif isinstance(node, (ForClause, CStyleLoop)):
        # C-style prelude: for ((init; cond; post)) arithmetic may embed
        # command substitutions that bash evaluates - surface them first.
        prelude = node if isinstance(node, CStyleLoop) else getattr(node, "cstyle", None)
        if prelude is not None:
            for attr in ("init", "cond", "post"):
                child = getattr(prelude, attr, None)
                if child is not None:
                    segments.extend(_extract_segments(child, redirs))
        # Loop-list words (for i in $(...); ...) are evaluated before the body.
        if hasattr(node, "words") and node.words:
            for w in node.words:
                segments.extend(_extract_segments(w, redirs))
        # Body statements.
        if hasattr(node, "body") and node.body:
            for stmt in node.body:
                segments.extend(_extract_segments(stmt, redirs))

    elif isinstance(node, Subshell):
        # Recurse into subshell body (...)
        if hasattr(node, "stmts") and node.stmts:
            for stmt in node.stmts:
                segments.extend(_extract_segments(stmt, redirs))

    elif isinstance(node, TestClause):
        # Recurse into the test expression. `[[ ]]` never executes its
        # operands, so nothing is emitted for them directly - the recursion
        # exists only to reach substitutions nested inside them.
        # Note: statement-level redirections (e.g. `[[ -f x ]] > file`) are NOT
        # propagated here - they are surfaced by the Stmt handler's synthetic
        # segment, since a test expression produces no command leaves of its
        # own for them to ride on.
        if hasattr(node, "body") and node.body:
            segments.extend(_extract_segments(node.body))

    elif isinstance(node, BinaryTest):
        # Every operand of a `[[ ]]` binary test is a value being compared -
        # the subject on the left, and the pattern / regex / number on the
        # right. Bash never runs them, so neither is a command. Recurse both
        # sides plainly: the only commands found are those a substitution
        # inside an operand runs (`[[ -d $(pwd) ]]`, `[[ $x == $(cmd) ]]`).
        if hasattr(node, "left") and node.left:
            segments.extend(_extract_segments(node.left))
        if hasattr(node, "right") and node.right:
            segments.extend(_extract_segments(node.right))

    elif isinstance(node, UnaryTest):
        # Unary test op (-d/-n/-z ...): the operand is a path/variable under
        # test. Recurse so a substitution inside it still surfaces.
        if node.x is not None:
            segments.extend(_extract_segments(node.x))

    elif isinstance(node, ParenTest):
        # Parenthesized test: its body holds values, same as any other operand.
        if hasattr(node, "body") and node.body:
            segments.extend(_extract_segments(node.body))

    elif isinstance(node, TimeClause):
        # time <cmd> - extract the command from inside
        if hasattr(node, "stmt") and node.stmt:
            segments.extend(_extract_segments(node.stmt))

    elif isinstance(node, ArithmCmd):
        # `(( expr ))` runs no command of its own, so nothing is emitted for the
        # arithmetic.  But bash still evaluates substitutions inside it -
        # `(( x=$(cmd) ))` really does run `cmd` - so the body is walked to
        # surface them.  Skipping it (as this handler used to) hid the command
        # entirely: `(( x=$(rm -rf /) ))` produced zero segments and so fell
        # through the empty-segment path to the wildcard, which under
        # `"*": "allow"` auto-approved a command nothing had inspected.  Every
        # sibling spelling already recursed (`x=$(cmd)`, `let x=$(cmd)`,
        # `[[ -n $(cmd) ]]`, `$(( $(cmd) ))`); this brings `(( ... ))` in line.
        if node.body is not None:
            segments.extend(_extract_segments(node.body))
    elif isinstance(node, LetClause):
        # let - variable assignment with arithmetic
        # Extract as variable assignment segment, capturing expressions as args.
        # Recurse into exprs to find any embedded CmdSubst/ProcSubst.
        args = []
        for expr in node.exprs:
            # Render the expression as a string

            def _arithm_to_str(node: object) -> str:
                if isinstance(node, ArithmExp):
                    return "$(...)"
                elif isinstance(node, BinaryArithm):
                    return f"({_arithm_to_str(node.left)}){node.op}({_arithm_to_str(node.right)})"
                elif isinstance(node, UnaryArithm):
                    return f"{node.op}{_arithm_to_str(node.x)}"
                elif isinstance(node, ParenArithm):
                    return f"({_arithm_to_str(node.body)})"
                elif isinstance(node, FlagsArithm):
                    return f"{node.flags}({_arithm_to_str(node.x)})"
                elif isinstance(node, Word):
                    return _word_value(node)
                elif isinstance(node, Lit):
                    return node.value
                elif isinstance(node, ParamExp):
                    return "${...}"
                elif isinstance(node, BraceExp):
                    return "{...}"
                else:
                    return "?"

            args.append(_arithm_to_str(expr))
            # Recurse into expr to find embedded CmdSubst/ProcSubst
            segments.extend(_extract_segments(expr))
        if args:
            # Inherit redirections from parent Stmt (same as CallExpr)
            redir_dicts = _redir_dicts(redirs or [])
            segments.append({"command": "", "arguments": args, "redirections": redir_dicts})

    elif isinstance(node, CoprocClause):
        # coprocess - extract command if present
        if hasattr(node, "stmt") and node.stmt:
            segments.extend(_extract_segments(node.stmt))

    elif isinstance(node, IfClause):
        # Conditions and every branch body are real executions.
        for stmt in node.cond_stmts:
            segments.extend(_extract_segments(stmt, redirs))
        for stmt in node.then_stmts:
            segments.extend(_extract_segments(stmt, redirs))
        for elif_branch in node.elif_branches:
            segments.extend(_extract_segments(elif_branch, redirs))
        for stmt in node.else_stmts:
            segments.extend(_extract_segments(stmt, redirs))

    elif isinstance(node, ElifBranch):
        for stmt in node.cond:
            segments.extend(_extract_segments(stmt, redirs))
        for stmt in node.body:
            segments.extend(_extract_segments(stmt, redirs))

    elif isinstance(node, WhileClause):
        for stmt in node.cond_stmts:
            segments.extend(_extract_segments(stmt, redirs))
        for stmt in node.body:
            segments.extend(_extract_segments(stmt, redirs))

    elif isinstance(node, Word):
        # Word nodes (arguments) may contain CmdSubst/ProcSubst in their parts.
        # Recurse into every part: the bare Lit/SglQuoted/DblQuoted fragments
        # emit nothing on their own, while an embedded substitution is a real
        # command (bug #6: no "$(...)" / "$var" phantom command names).
        for part in node.parts:
            segments.extend(_extract_segments(part))

    elif isinstance(node, Lit):
        # A bare literal is only ever a command name when shfmt has already
        # put it in command position (the first word of a CallExpr), which is
        # handled there. Reached as a word part it is data - an argument, a
        # glob, or an operand under test - so nothing is emitted here.
        pass

    elif isinstance(node, SglQuoted):
        # Single-quoted text: no substitutions can hide inside it, so there is
        # nothing to recurse into and nothing to emit.
        pass

    elif isinstance(node, DblQuoted):
        # Double-quoted text may embed CmdSubst/ProcSubst/ParamExp parts -
        # always recurse so embedded substitutions surface as real commands.
        for part in node.parts:
            segments.extend(_extract_segments(part))

    elif isinstance(node, ParamExp):
        # Parameter expansion (${x:-default}, ${x/pat/rep}, ${arr[i]}, ${x:0:3},
        # ...) may embed nested command substitutions in its operand, pattern,
        # replacement, index, or slice expressions. Recurse into each so the
        # inner commands surface as segments for allowed-pattern and
        # blocked-path checks. This must happen everywhere, including inside a
        # `[[ ]]` test: `[[ ${x:-$(rm -rf /)} ]]` really does run the inner
        # substitution while evaluating the operand, and suppressing it here
        # yielded no segments at all, so the empty-segment fallback applied
        # the wildcard and approved the whole command.
        for exp_child in (node.index, node.orig, node.replacement, node.slice):
            if exp_child is not None:
                segments.extend(_extract_segments(exp_child))
        exp = node.exp
        if isinstance(exp, ParamExpExp) and exp.word is not None:
            segments.extend(_extract_segments(exp.word))

    elif isinstance(node, ParamExpSlice):
        # Parameter-expansion slice (${x:offset:length}) - recurse into the
        # operands so command substitutions such as ${x:$(cmd):3} are still
        # extracted (bash runs the substitution at expansion time).
        for slice_child in (node.offset, node.length):
            if slice_child is not None:
                segments.extend(_extract_segments(slice_child))

    elif isinstance(node, ArithmExp):
        # Arithmetic expansion ($(( ... ))) may embed a command substitution
        # (bash runs $( cmd ) inside $(( ))).
        if node.x is not None:
            segments.extend(_extract_segments(node.x))

    elif isinstance(node, (BinaryArithm, UnaryArithm, ParenArithm, FlagsArithm)):
        # Arithmetic sub-expressions: recurse into operands so command
        # substitutions such as `$(( N + $(cmd) ))` are still extracted.
        for child in (
            getattr(node, "left", None),
            getattr(node, "right", None),
            getattr(node, "x", None),
            getattr(node, "body", None),
        ):
            if child is not None:
                segments.extend(_extract_segments(child))

    elif isinstance(node, BraceExp):
        # Brace expansion elements may contain substitutions ({a,$(cmd)}).
        for elem in node.elems:
            segments.extend(_extract_segments(elem))

    elif isinstance(node, ExtGlob):
        # Extended glob pattern is a literal pattern - no substitutions inside.
        pass

    elif isinstance(node, (CmdSubst, ProcSubst)):
        # Command/process substitution: recurse into each stmt, passing inherited redirs.
        if hasattr(node, "stmts") and node.stmts:
            inherited = list(redirs or [])
            for stmt in node.stmts:
                segments.extend(_extract_segments(stmt, inherited))

    elif isinstance(node, FuncDecl):
        # Function body / block: recurse into contained stmts, inheriting any
        # redirections that apply to the whole block (e.g. `f() { ...; } > file`).
        segments.extend(_extract_segments(node.body, redirs))

    elif isinstance(node, Block):
        # Curly-brace block: redirections apply to every contained statement.
        for stmt in node.stmts:
            segments.extend(_extract_segments(stmt, redirs))

    elif isinstance(node, File):
        # File: extract from all statements
        for stmt in node.stmts:
            segments.extend(_extract_segments(stmt))

    else:
        _logger.warning("Unhandled AST node type '%s' - returning 0 segments", type(node).__name__)

    return segments


def parse_segments(command: str, dialect: str = DEFAULT_DIALECT) -> list[dict[str, Any]]:
    """
    Parse a bash command into segments.

    Each segment represents a command with its name, arguments, and
    redirections. Commands are separated by pipes, logical AND/OR
    operators, background execution, and statement separators.

    Args:
        command: The bash command string to parse.
        dialect: Shell dialect for parsing (default: "bash").

    Returns:
        List of segment dicts. Each dict contains:
            - 'command': str - the command name
            - 'arguments': list[str] - the command's arguments
            - 'redirections': list[dict] - redirection info

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
    except LovelyDevinPermissionsError:
        return []

    if ast is None:
        return []
    return _extract_segments(ast)
