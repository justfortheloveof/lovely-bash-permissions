"""Shared exception types for the shfmt-backed parser.

:class:`ShfmtError` is the single base for "we could not obtain a
trustworthy parse of this command".  It is raised by the parser library half
of the project: :mod:`~lovely_bash_permissions.parser` for a missing shfmt
binary, a shfmt timeout or an OS error from the subprocess, and
:mod:`~lovely_bash_permissions.converter` when a command is nested too deeply
to analyse safely.  Callers decide what an unparseable command means - the
hook maps it to the configurable ``error`` policy, the inspection CLI reports
it and exits non-zero.

:class:`~lovely_bash_permissions.parser.ParseError` subclasses it.  It is
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
