# Plan: [x] Fix unicode escaping in JSON output (ensure_ascii=False)

## Objective

Identify the top 10 issues to fix in our code — start with the most obvious mistakes or errors or inconsistencies. Then spawn agents to fix them. The list of issues should not grow larger than 100.

## Status: Pass 2 — Complete. Project fully implemented.

All TS/Python parity issues resolved, linting and type-checking clean (461 tests passing).

### Pass 2: Final review and cleanup
1. Run `ruff` + `mypy --strict` — done, both clean (fixed PYI041 untyped dict return)
2. Check README and docs match current code — reviewed, no changes needed
3. Remove leftover TODOs/dead code/test-only functions — none found
4. Confirm git diff clean except docs/config files — confirmed, committed (e6b6fb9)
5. Mark project complete and stop loop — done; no further passes needed

## ISSUES

### Fixed (pass 4)
1. [x] **`import re` inside functions** — moved to module level in `evaluate.py` and `effective_bash.py`.
2. [x] **Invalid config silently returns empty dict** — errors now propagate instead of swallowing.
3. [x] **Unused constant `HOOK_LABEL_PREFIX`** — moved to `devin_cli.py` where consumed.
4. [x] **Duplicate `_word_value()`** — cli.py imports from inspect, no duplicate.
5. [x] **`read_jsonc_file()` silently wraps non-object JSON** — returns `None` for non-dict values.
6. [x] **Empty `config/__init.py`** — deleted dead file.
7. [x] **Redundant dict-branch in `_extract_segments()`** — removed, parse_segments() handles conversion.

### Fixed (pass 5)
8. [x] **`handle_load_error()` in hook.py is redundant** — only called twice within same file; inlined.
9. [x] **Duplicate `get_devin_global_config_dir()`** — exists in both config/devin.py (returns Path) and devin_cli.py (returned str); consolidated into config.devins version, removed duplicate from devin_cli.py.
10. [x] **`PermissionsManager.reload()` never called from source** — only used by tests; verified no source callers missing it, kept as public API.

### Fixed (pass 6)
11. [x] **Output redirection not asking for approval in pipes** — fixed `check_output/input/background` functions to recursively walk AST (BinaryCmd.X/Y operands); added 11 regression tests.

12. [x] **Bug between TS and Python — list matching regexes joined** — fixed: allow now produces one "command matches allowed patterns" string; added `decision` field to response for approve/block cases (matching TS).
