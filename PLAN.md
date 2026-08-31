# Plan: Add Ruff for Linting and Formatting

Project: lovely-bash-permissions (Python project managed with uv)
Goal: Configure ruff for linting and formatting, integrated into the development workflow.

## Step 1 — Install ruff via uv ✅

- Added `ruff` to `[dependency-groups.dev]` in `pyproject.toml`
- Ran `uv sync` — installed ruff 0.16.5
- Verified: `uv run ruff --version` returns `ruff 0.16.5`, success

## Step 2 — Configure ruff in pyproject.toml ✅

- Add a `[tool.ruff]` section with:
  - `line-length = 88` (PEP-8 common default; adjust if project style differs).
  - `target-version = "py314"` (matches `.python-version` / project requires-python).
- Add a `[tool.ruff.lint]` section with a curated rule set:
  - `select = ["E", "F", "W", "I", "UP", "B", "SIM"]` — common sensible defaults:
    - `E/W`: pycodestyle errors/warnings
    - `F`: pyflakes (unused imports, undefined names)
    - `I`: isort (import ordering)
    - `UP`: pyupgrade (modernize syntax)
    - `B`: flake8-bugbear (common bugs)
    - `SIM`: flynt/SIM (simplify code)
  - `ignore = ["E501"]` — let formatter handle line length, so linting doesn't fight formatting.
- Add a `[tool.ruff.format]` section with:
  - `quote-style = "double"` (consistent style; match existing code).

## Step 3 — Run ruff check and fix any lint errors ✅

- Ran `uv run ruff check src/ tests/` — found 11 issues (2×F841, 3×SIM101, 1×SIM102, 1×B904, 4×B017).
- All fixed: removed unused variables, merged isinstance calls, combined nested ifs, added `raise ... from e`, replaced blind `pytest.raises(Exception)` with `pytest.raises(ParseError)`.
- Verification: `uv run ruff check src/ tests/` → "All checks passed!"

## Step 4 — Run ruff format to style all code ✅

- Ran `uv run ruff format src/ tests/` — all files already formatted (9 files already formatted).
- Verified with `uv run ruff format --check src/ tests/` — all clean.
- No new files to commit (already in sync).

## Step 5 — Add a lint check to tests ✅

- Created `tests/test_ruff.py` with two tests:
  - `test_ruff_check()`: runs `ruff check src/ tests/` and asserts success
  - `test_ruff_format_check()`: runs `ruff format --check src/ tests/` and asserts success
- Both tests pass: `uv run pytest tests/test_ruff.py` → 2 passed

- Extend `[tool.pytest.ini_options]` in `pyproject.toml`:
  - Add an option for ruff check so CI can verify style: `addopts = ["--strict-markers", "-vv"]` (keep existing, add ruff check step separately).
- Create a `tests/test_ruff.py` (or inline in an existing test file) that runs:
  ```python
  import subprocess, sys

  def test_ruff_check():
      result = subprocess.run(
          [sys.executable, "-m", "ruff", "check", "src/", "tests/"],
          capture_output=True, text=True,
      )
      assert result.returncode == 0, f"ruff check failed:\n{result.stdout}\n{result.stderr}"

  def test_ruff_format_check():
      result = subprocess.run(
          [sys.executable, "-m", "ruff", "format", "--check", "src/", "tests/"],
          capture_output=True, text=True,
      )
      assert result.returncode == 0, f"ruff format --check failed:\n{result.stdout}\n{result.stderr}"
  ```

## Step 6 — Pre-commit hook (optional but recommended)

- Add `.pre-commit-config.yaml` if not present, with a ruff hook:
  ```yaml
  repos:
    - repo: https://github.com/astral-sh/ruff-pre-commit
      rev: v0.9.x
      hooks:
        - id: ruff-check
          args: [--fix]
        - id: ruff-format
  ```
- If `.pre-commit-config.yaml` exists, merge these hooks in.

## Step 7 — Verify everything passes

- Run `uv run pytest` to confirm all tests (including new ruff tests) pass.
- Run `uv run ruff check src/ tests/` and `uv run ruff format --check src/ tests/` — both must succeed clean.
- Commit all changes.
