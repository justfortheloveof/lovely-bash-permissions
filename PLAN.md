# Plan: [x] Fix unicode escaping in JSON output (ensure_ascii=False)

## Objective

Identify the top 10 issues to fix in our code — start with the most obvious mistakes or errors or inconsistencies. Then spawn agents to fix them. The list of issues should not grow larger than 100.

## Status: Pass 9 — All issues fixed, tests added.

All TS/Python parity issues resolved. Zero remaining TODO items (marked resolved in PASS 8–9).

### Pass 8 — Fix invalid config error messages
- Improved `read_jsonc_file` to print per-file parse errors (which file failed, why)
- Updated `load_permissions_config` to include specific failed paths in raised FileNotFoundError

### Pass 9 — Tests and edge cases
- Added tests for config error reporting (invalid JSONC, non-object values, encoding errors)
- Marked TODO item "Invalid Config should raise" as resolved
- Edge cases: null value treated as invalid, encoding error handling verified

## ISSUES — all fixed (1–16)

All 18 plan steps complete. Zero remaining issues.

## Next steps

No further steps — loop may stop manually.
