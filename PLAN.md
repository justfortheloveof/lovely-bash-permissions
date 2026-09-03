# Plan: [x] Fix unicode escaping in JSON output (ensure_ascii=False)

## Objective

Identify the top 10 issues to fix in our code — start with the most obvious mistakes or errors or inconsistencies. Then spawn agents to fix them. The list of issues should not grow larger than 100.

## Status: Pass 5 — Working on remaining 3 issues.

450 tests pass. Three new issues identified in this pass; fixing them now.

## ISSUES

### Fixed (pass 4)
1. [x] **`import re` inside functions** — moved to module level in `evaluate.py` and `effective_bash.py`.
2. [x] **Invalid config silently returns empty dict** — errors now propagate instead of swallowing.
3. [x] **Unused constant `HOOK_LABEL_PREFIX`** — moved to `devin_cli.py` where consumed.
4. [x] **Duplicate `_word_value()`** — cli.py imports from inspect, no duplicate.
5. [x] **`read_jsonc_file()` silently wraps non-object JSON** — returns `None` for non-dict values.
6. [x] **Empty `config/__init__.py`** — deleted dead file.
7. [x] **Redundant dict-branch in `_extract_segments()`** — removed, parse_segments() handles conversion.

### In progress (pass 5)
8. [x] **`handle_load_error()` in hook.py is redundant** — only called twice within same file; inlined.
9. [x] **Duplicate `get_devin_global_config_dir()`** — exists in both config/devin.py (returns Path) and devin_cli.py (returned str); consolidated into config.devins version, removed duplicate from devin_cli.py.
10. [x] **`PermissionsManager.reload()` never called from source** — only used by tests; verified no source callers missing it, kept as public API.
11. [ ] Bug with output redirection not asking for approval even though global config is configured for it to ask
here is how you can reproduce:
```
❯ uv run lovely-devin-permissions --test 'echo ; ls | grep bla > /tmp/deleteme'
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "updatedInput": {
      "command": ": '[♡ perms: 💚 auto-approved] command matches allowed pattern ^echo(\\s+.*)?$; command matches allowed pattern ^ls(\\s+.*)?$; command matches allowed pattern ^grep\\s+.+$' ; echo ; ls | grep bla > /tmp/deleteme"
    }
  }
}
```
