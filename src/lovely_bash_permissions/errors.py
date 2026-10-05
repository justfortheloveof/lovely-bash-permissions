"""Shared exception types for the shfmt-backed parser.

:class:`ShfmtError` is the single base for "we could not obtain a
trustworthy parse of this command".  It is raised by the parser library half
of the project: :mod:`~lovely_bash_permissions.parser` for a missing shfmt
binary, a shfmt timeout or an OS error from the subprocess, and
:mod:`~lovely_bash_permissions.converter` when a command is nested too deeply
to analyse safely.  Callers decide what an unparseable command means - the
hook maps it to the configurable ``error`` policy, the inspection CLI reports
it and exits non-zero.

:class:`ShfmtUnavailableError` subclasses it for the one case that is about
the install rather than the command: shfmt could not be found or started.
The ``error`` policy is a judgement about a command that could not be
analysed, so it does not apply to that case - see
:func:`lovely_bash_permissions.decide.error_action`.

:class:`~lovely_bash_permissions.parser.ParseError` subclasses it too.  It is
defined in ``parser.py`` rather than here because it is parser-specific: it
carries the offending ``command`` plus shfmt's ``returncode`` and ``stderr``.
``except ParseError`` therefore catches parse-shaped failures specifically,
while ``except ShfmtError`` catches every way the backend can fail to deliver.

:func:`user_message` is here for the same reason the exceptions are: both hosts
render a verdict to a user - and, through it, to a model - and a config that will
not validate has to produce that text without the developer half of a pydantic
error in it. It is here rather than in either host because the two hosts reach
the same message by different routes, and a message rendered twice renders twice.
"""

import re
from collections.abc import Mapping
from typing import Any


class ShfmtError(Exception):
    """Represents any failure that prevented a permission decision.

    Wraps the underlying message so the real cause (e.g. shfmt's stderr, a
    missing binary, a timeout) is relayed verbatim to the user.
    """


class ShfmtUnavailableError(ShfmtError):
    """shfmt could not be found or started, so *no* command can be analysed.

    Distinct from a parse failure or a timeout, which are about one command:
    this is a broken install, and no config level may turn it into an allow.
    """


#: The trailing ``[type=value_error, input_value=..., input_type=...]`` block
#: pydantic appends to each message. A developer reading a traceback wants it; a
#: user reading a prompt does not, and it is the half that carries a docs URL.
_TYPE_SUFFIX_RE = re.compile(r"\s*\[type=\w[\w.]*.*\]\s*$")

#: pydantic's ``For further information visit https://errors.pydantic.dev/...``
#: line. On its own line, indented, in every multi-error rendering.
_DOCS_LINE_RE = re.compile(r"^\s*For further information visit\s+\S+\s*$")

#: pydantic's ``2 validation errors for PermissionsConfig`` header. The caller already
#: says *what* failed - "invalid permissions config", "invalid bash config" - and
#: the model name is the caller's to name.
_COUNT_HEADER_RE = re.compile(r"^\d+ validation errors? for \S+\s*$")

#: How long an offending value may be before it stops being quoted back. A
#: misspelled level is worth seeing; a list of every regex in the config is the
#: noise this function exists to remove.
_MAX_ECHOED_INPUT = 40


def _echoed_input(error: Mapping[str, Any]) -> str:
    """``" (got 'alow')"`` for a short scalar the user typed, else ``""``.

    pydantic's message for a bad enum value is ``Input should be 'allow', 'deny'
    or 'ask'`` and names nothing the user recognises as their own - the value
    they actually wrote is only in the ``input_value=`` half of the string. So
    dropping that half without this loses the single most useful word in the
    sentence: with eleven valid keys and a typo in one, "which one" is the
    question.

    Scalars only. The list case is the leak this whole function is about:
    ``input_value=['\\/etc', '\\.env$', '\\.envrc$', '[']`` is every pattern the
    user wrote, dumped into a prompt, for an error about one of them.
    """
    value = error.get("input")
    if isinstance(value, (list, dict, tuple, set)) or value is None:
        return ""
    rendered = repr(value)
    if len(rendered) > _MAX_ECHOED_INPUT:
        return ""
    msg = str(error.get("msg", ""))
    return "" if rendered in msg else f" (got {rendered})"


def _trimmed_text(text: str) -> str:
    """One line, with pydantic's per-error bookkeeping removed.

    The fallback for an error that has already been through ``str()``. It has to
    exist because that is the shape the Devin half receives:
    ``config.manager`` re-raises the loader's pre-joined messages as a plain
    ``ValueError``, so by the time a host renders one there is no
    ``ValidationError`` left to ask for ``.errors()``.

    pydantic lays each error out as an unindented location line followed by an
    indented message line, so the two are rejoined with ``": "`` and the result
    reads like the structured route's. Same text either way is the point: the two
    hosts render this into different surfaces, and a message that differed
    between them was a difference the user had to notice rather than read.
    """
    parts: list[str] = []
    for line in text.splitlines():
        if _DOCS_LINE_RE.match(line) or _COUNT_HEADER_RE.match(line):
            continue
        stripped = _TYPE_SUFFIX_RE.sub("", line).strip()
        if not stripped:
            continue
        if line[:1].isspace() and parts:
            # A continuation of the location above it, not a finding of its own.
            parts[-1] = f"{parts[-1]}: {stripped}"
            continue
        parts.append(stripped)
    return "; ".join(dict.fromkeys(parts))


def user_message(exc: BaseException) -> str:
    """The half of *exc* a user should read, naming where each problem is.

    A pydantic ``ValidationError`` rendered with ``str()`` is four lines per
    error: a count header, the location, the message, and a docs link - plus a
    ``type=``/``input_value=``/``input_type=`` block on the message. The link and
    the block are for whoever is debugging the validator. This string is a prompt
    bullet and a model-facing tool result, so it keeps the location and the
    message and drops the rest.

    Both routes to that text are handled, and they have to be, because the two
    hosts arrive differently: ``pi_cli`` validates a block and holds the
    ``ValidationError``, while the Devin half holds a plain ``ValueError`` whose
    message was stringified upstream by ``config.loader``. Asking only for
    ``.errors()`` silently no-ops on the second, which is how a raw
    ``ValidationError`` - docs URL and all - reached a Devin reason.

    Structured errors are rendered with their location, so ``bash.blocked_cmds_regex:
    ...``. That is a gain over the message-only form: with several keys in one
    config file, "which key" is the question the user actually has.

    A value in the text fallback's ``input_value=`` half cannot be recovered, so
    the text route renders a strict subset of what the structured route does. In
    this package that costs nothing: the message is built once, in
    ``config.loader``, where the ``ValidationError`` is still whole, and the text
    route only ever sees it again on its way out.

    Args:
        exc: any exception. An object without ``errors()`` is rendered as text.

    Returns:
        A single-line message. Empty is possible only for an exception whose
        ``str()`` is empty.
    """
    errors = getattr(exc, "errors", None)
    if callable(errors):
        parts: list[str] = []
        for error in errors():
            msg = f"{error.get('msg', '')}{_echoed_input(error)}"
            location = error.get("loc") or ()
            where = ".".join(str(part) for part in location)
            parts.append(f"{where}: {msg}" if where else msg)
        if parts:
            return "; ".join(parts)
    return _trimmed_text(str(exc))
