# Plan: [x] Fix unicode escaping in JSON output (ensure_ascii=False)

## Objective

Identify the top 10 issues to fix in our code append them to the ISSUES section - start with the most obvious mistakes or errors or inconsistencies.

Then spawn agents to fix them.

You MUST NOT try to implement anything else than CODE QUALITY ISSUES you have found.

## ISSUES

1. **`import re` inside functions** — `evaluate.py` imports `re` at runtime inside `evaluate_bash_command()` (line ~81); `effective_bash.py` imports it inside `_deny_item_to_regex()`. Both should be module-level.
2. **Invalid config silently returns empty dict** — TODO.md says "Invalid Config should raise and let the user know". `load_permissions_config()` returns `{}` on failure; `PermissionsManager._load()` catches all exceptions silently. Should raise or at least propagate errors.
3. **Unused constant `HOOK_LABEL_PREFIX`** in `effective_bash.py` — only `HOOK_COMMAND_PREFIX` and `HOOK_LABEL_REGEX` are used.
4. **Duplicate `_word_value()`** — defined in both `inspect.py` and `cli.py`. The cli version is dead code (segments.py imports from inspect).
5. **`read_jsonc_file()` silently wraps non-object JSON** — valid but non-dict values (arrays, strings) become `{}`, swallowing data.
6. **`config/__init__.py` is empty/dead** — no exports, just an unused `__init__`.
7. **Redundant dict-branch in `_extract_segments()`** (segments.py) — converts raw JSON dicts to typed nodes when it could just use the already-typed path.
