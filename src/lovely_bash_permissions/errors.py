"""Shared exception types for lovely-devin-permissions.

A single error type, :class:`LovelyDevinPermissionsError`, is raised by any
code path that cannot reach a permission decision - bash parse failures,
missing shfmt binary, shfmt subprocess failures.  The top-level hook handler
catches it and maps the decision to the configurable ``error`` policy
(``bash.error``), defaulting to the bash wildcard.

:class:`ParseError` subclasses it so existing ``except ParseError`` handlers
keep working while ``except LovelyDevinPermissionsError`` catches everything.
"""

from __future__ import annotations


class LovelyDevinPermissionsError(Exception):
    """Represents any failure that prevented a permission decision.

    Wraps the underlying message so the real cause (e.g. shfmt's stderr, a
    missing binary, a timeout) is relayed verbatim to the user.
    """
