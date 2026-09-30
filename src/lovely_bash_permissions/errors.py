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
"""


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
