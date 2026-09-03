# Plan: [x] Fix unicode escaping in JSON output (ensure_ascii=False)

## Objective

Identify the top 10 issues to fix in our code — start with the most obvious mistakes or errors or inconsistencies. Then spawn agents to fix them.

## Status: Pass 4 — All 7 identified issues fixed, no blockers remain.

All code quality issues found have been implemented. 450 tests pass, working tree clean.

No next steps — objective complete (7 of 10 target issues found; none remaining). If new issues are discovered in future passes, add them to the ISSUES list and fix sequentially.

## ISSUES (all done)

1. [x] **`import re` inside functions** — moved to module level in `evaluate.py` and `effective_bash.py`.
2. [x] **Invalid config silently returns empty dict** — errors now propagate instead of swallowing.
3. [x] **Unused constant `HOOK_LABEL_PREFIX`** — moved to `devin_cli.py` where consumed.
4. [x] **Duplicate `_word_value()`** — cli.py imports from inspect, no duplicate.
5. [x] **`read_jsonc_file()` silently wraps non-object JSON** — returns `None` for non-dict values.
6. [x] **Empty `config/__init__.py`** — deleted dead file.
7. [x] **Redundant dict-branch in `_extract_segments()`** — removed, parse_segments() handles conversion.
