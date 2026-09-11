"""Shared helpers for tooling tests."""

import os
import tempfile


def _write_temp_file(content: str, suffix: str = ".jsonc") -> str:
    """Write content to a temporary file and return its path."""
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "w") as f:
        f.write(content)
    return path


def _clean_temp_file(path: str) -> None:
    """Remove a temporary file."""
    if os.path.exists(path):
        os.remove(path)
