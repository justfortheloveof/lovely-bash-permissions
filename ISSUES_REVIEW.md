# Top 10 Code Quality Issues

## 1. Redundant redirection collection in `rules.py` (medium)
**File:** `src/lovely_bash_permissions/rules.py`, `_find_redirs()` (~line 38)

`_find_redirs()` re-collects `X.Redirs`, `Y.Redirs`, and node-level `Redirs` — but the converter already splits these into per-side fields (`left_redirs`, `right_redirs`) and a merged `redirs`. Since `BinaryCmd.redirs` already holds the merged list, re-extracting from X/Y wrappers duplicates work and risks double-counting if the merge ever changes. The docstring in `ast.py` even says consumers should use per-side fields instead of the merged one.

## 2. Empty redirections in `segments.py` (high)
**File:** `src/lovely_bash_permissions/segments.py`, `_extract_segments()` (~line 48)

```python
"redirections": [],   # ← always empty!
```

The CallExpr branch never extracts redirections — it hardcodes an empty list. The module docstring claims segments contain "redirections" but this function never populates them. This means `parse_segments()` loses all redirection information, which is probably why the permission rules engine has a separate code path for redirection checks.

## 3. Duplicate blocked-pattern logic (medium)
**Files:** `effective_bash.py` (`_deny_item_to_regex`) and `rules.py` (`check_blocked_patterns`)

Both modules reimplement blocked-path matching — one converts deny-list items to regexes, the other does pattern matching against command names and args. The logic overlaps: `_deny_item_to_regex` builds patterns, `check_blocked_patterns` applies them. A single source of truth would be better.

## 4. Duplicate aggregation logic in `evaluate.py` (high)
**File:** `src/lovely_bash_permissions/evaluate.py`, two blocks (~lines 158–176 and ~183–204)

The status-aggregation for output/input/background redirections is written **twice**: once right after collecting segment results, and again later. Both blocks do identical `deny → overall_status = "deny"` + reason-appending logic. The second block's output/input/background checks are dead code (the first block already mutated the variables). Easy to fix, but it's confusing.

## 5. Raw-JSON traversal instead of typed AST in `evaluate.py` (medium)
**File:** `src/lovely_bash_permissions/evaluate.py`, `_extract_subshell_contents()` and `_has_cmd_subst()`

Both functions manually walk shfmt JSON dicts (`node.get("Type")`, `isinstance(node, dict)`) instead of using the typed AST from `converter.py`. This means they miss CmdSubst/ProcSubst nodes nested inside Word parts (e.g., `$( echo $(ls) )` — inner substitution may be missed). The typed `iter_children()` in `inspect.py` handles this correctly.

## 6. Bare `except Exception` with noqa suppression (low–medium)
**Files:** `hook.py`, `manager.py`, `devin_cli.py`

Multiple locations catch all exceptions with `except Exception as e: # noqa: BLE001` — the noqa comment suppresses the lint warning rather than fixing it. E.g., `PermissionsManager._load()` swallows any error from config loading without distinguishing file-not-found from parse errors. Should catch specific exceptions (FileNotFoundError, ValueError) so callers get actionable error info.

## 7. `_word_value` helper duplicated across files (low)
**Files:** `inspect.py`, imported by `segments.py` and `cli.py`

The `_word_value()` helper lives in `inspect.py` but is re-implemented conceptually in `_extract_subshell_contents()` and elsewhere. If the literal-concatenation logic ever needs updating (e.g., handling new node types), all copies must be updated. It should be the single source of truth (it already is, but `evaluate.py` ignores it).

## 8. `_resolve_output_level` semantics are confusingly documented (low)
**File:** `src/lovely_bash_permissions/rules.py`, `_resolve_output_level()`

The docstring says "Any-asks semantics" but then describes a deny-first priority ("if ANY redirect resolves to deny, return deny; if any resolve to ask …"). The implementation matches the deny-first priority, but a reader reading "any-asks" would expect ask-to-deny escalation. The docstring and function name are misleading relative to the actual precedence rule.

## 9. Stale `find_shfmt()` cache (low)
**File:** `src/lovely_bash_permissions/parser.py`, `find_shfmt()`

The `lru_cache` caches the shfmt path but warns it's stale if the binary moves. However, there's no fallback — once cached, a removed/moved binary causes silent `FileNotFoundError` on every call until the process restarts. Callers rarely call `.cache_clear()`. A small `exists()` check before use would be safer.

## 10. Unused converter section in `converter.py` (low)
**File:** `src/lovely_bash_permissions/converter.py`, ~line 37

There's an empty section labeled `# Type mapping from shfmt's JSON to our dataclasses` followed by a separator line, then the actual converters start later. It's dead space — likely leftover from an earlier design where converters were registered inline. The large `_CONVERTERS` dispatch table is fine, but the orphaned header section adds noise.

---

**Summary by severity:**
- **High impact (2):** segments.py loses redirection info (#2), duplicate aggregation logic (#4)
- **Medium impact (3):** redundant redir collection (#1), duplicate blocked-pattern logic (#3), raw-JSON traversal (#5)
- **Low–medium (1):** bare excepts with noqa (#6)
- **Low / documentation (4):** confusing docstring (#8), stale cache (#9), duplicated helper awareness (#7), unused section header (#10)
