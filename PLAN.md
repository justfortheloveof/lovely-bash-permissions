# Plan: [x] Fix unicode escaping in JSON output (ensure_ascii=False)

## Objective

Identify the top 10 issues to fix in our code — start with the most obvious mistakes or errors or inconsistencies. Then spawn agents to fix them. The list of issues should not grow larger than 100.

## Status: Pass 7 — Complete. All previously-known issues fixed.

461 tests pass. All 12 known issues resolved.

[x] Scan for remaining issues — Complete. No remaining issues found; project is complete.

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

### Fixed (pass 7)
12. [x] **Bug between TS and Python — list matching regexes joined (TS does it, Python repeats per command)** — Python now collects matched patterns across all segments and produces one joined reason string, matching TS `summarizeCommandMatches`.
