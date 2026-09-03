# Plan: [x] Fix unicode escaping in JSON output (ensure_ascii=False)

## Objective

Identify the top 10 issues to fix in our code append them to the ISSUES section - start with the most obvious mistakes or errors or inconsistencies.

Then spawn agents to fix them.

You MUST NOT try to implement anything else than CODE QUALITY ISSUES you have found.

[x] 1. **`import re` inside functions** — moved `re` import to module level in `evaluate.py` and `effective_bash.py`.
[x] 2. **Invalid config silently returns empty dict** — improved error handling in `load_permissions_config()` and `PermissionsManager._load()`. Errors now propagate.
[x] 3. **Unused constant `HOOK_LABEL_PREFIX`** — removed from `effective_bash.py`, moved to `devin_cli.py` where it's consumed.
[x] 4. **Duplicate `_word_value()`** — cli.py only imports from inspect (no duplicate definition).
[x] 5. **`read_jsonc_file()` silently wraps non-object JSON** — now returns `None` for non-dict values instead of wrapping into `{}`.
[x] 6. **`config/__init__.py` is empty/dead** — deleted the unused file.
[x] 7. **Redundant dict-branch in `_extract_segments()`** — removed since parse_segments() already converts raw JSON to typed nodes before calling it.
