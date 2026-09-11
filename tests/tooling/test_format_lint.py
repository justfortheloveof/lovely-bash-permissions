"""
Lint and format checks.

These tests ensure that the codebase passes ruff lint and format checks.
Consider running these as a CI step or pre-commit hook instead of (or in
addition to) pytest, so that functional test runs stay fast.
"""

import subprocess
import sys

import pytest


@pytest.mark.linting
def test_ruff_check() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "check"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"`ruff check` failed:\n{result.stdout}\n{result.stderr}"


@pytest.mark.linting
def test_ruff_format_check() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "format", "--check"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"`ruff format --check` failed:\n{result.stdout}\n{result.stderr}"


@pytest.mark.linting
def test_mypy_strict_check() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "mypy", "--strict", "."],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"`mypy --strict .` failed:\n{result.stdout}\n{result.stderr}"
