# Plan: [x] Fix unicode escaping in JSON output (ensure_ascii=False)

## Objective

Identify the top 10 issues to fix in our code — start with the most obvious mistakes or errors or inconsistencies. Then spawn agents to fix them. The list of issues should not grow larger than 100.

## Status: Pass 8 — Config error reporting improved.

All TS/Python parity issues resolved, linting clean (461 tests passing).

### Pass 8 — Fix invalid config error messages
- Improved `read_jsonc_file` to print per-file parse errors (which file failed, why)
- Updated `load_permissions_config` to include specific failed paths in raised FileNotFoundError
- Verified: 461 tests passing, mypy --strict clean (16 source files), ruff linting clean

## ISSUES — all fixed

1–16. [x] See passes 4–10 for resolved issues (type annotations, parity fixes, linting). Zero remaining.

## Next steps

17. [x] Add tests for config error reporting (invalid JSONC file detection)
18. [x] Review remaining TODO items and any edge cases
- TODO item "Invalid Config should raise" resolved — covered by step 17 tests
- Edge cases added: null value treated as invalid, encoding error handling verified
- 470 tests passing, ruff clean
