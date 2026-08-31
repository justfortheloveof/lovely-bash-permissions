import subprocess
import sys


def test_ruff_check():
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "src/", "tests/"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"ruff check failed:\n{result.stdout}\n{result.stderr}"
    )


def test_ruff_format_check():
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "format", "--check", "src/", "tests/"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"ruff format --check failed:\n{result.stdout}\n{result.stderr}"
    )
