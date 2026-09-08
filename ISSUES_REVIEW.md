# Top 10 Code Quality Issues

## 1. Redundant redirection collection in `rules.py` (medium) [fixed]
**File:** `src/lovely_bash_permissions/rules.py`, `_find_redirs()` (~line 38)

`_find_redirs()` re-collected `X.Redirs`, `Y.RedDirs`, and node-level `Redirs` — but the converter already splits these into per-side fields (`left_redirs`, `right_redirs`) and a merged `redirs`. Since `BinaryCmd.redirs` already holds the merged list, re-extracting from X/Y wrappers duplicated work and risked double-counting if the merge ever changes. The docstring in `ast.py` even says consumers should use per-side fields instead of the merged one.

**Fix:** Removed the redundant `node.get("Redirs", [])` extraction from BinaryCmd handling. In raw shfmt JSON, `BinaryCmd` has no merged `Redirs` field — redirects live only on X/Y wrapper nodes. Now `_find_redirs()` extracts solely from wrapper-level RedDirs, eliminating the duplication. Added regression test `test_pipe_no_double_counting` verifying pipe redirections are extracted exactly once.

## 2. Empty redirections in `segments.py` (high) [fixed]
**File:** `src/lovely_bash_permissions/segments.py`, `_extract_segments()` (~line 48)

```python
"redirections": [],   # ← was always empty!
```

The CallExpr branch never extracted redirections — it hardcoded an empty list. The module docstring claimed segments contain "redirections" but this function never populated them, so `parse_segments()` lost all redirection info (the rules engine had a separate raw-JSON code path for redirection checks).

**Fix:** Added `_extract_redirs()` helper that extracts `Redir` objects from typed AST nodes (`Stmt.redirs`, `BinaryCmd.left/right_redirs`). Threaded redirs through recursive calls so each CallExpr segment inherits its redirections. Also fixed two pre-existing bugs: IfClause/WhileClause checked nonexistent `"cond"` instead of `cond_stmts`, and Block nodes (FuncDecl bodies) weren't handled. Added 18 regression tests covering simple/redir, pipe left/right/both-sides, and/or chains, sequential, background-on-pipe, complex pipes, if/while/body, func-body. Bonus: replaced `evaluate.py`'s raw-tree redirection checks with segment-based `_check_segments_output_redirs()` and `_check_segments_input_redirs()`, making segments the single source of truth (addresses issue #5's raw-JSON traversal concern for redirections).

## 3. Duplicate blocked-pattern logic (medium) [fixed]
**Files:** `effective_bash.py` (`_deny_item_to_regex`) and `rules.py` (`check_blocked_patterns`)

Both modules reimplement blocked-path matching — one converts deny-list items to regexes, the other does pattern matching against command names and args. The logic overlaps: `_deny_item_to_regex` builds patterns, `check_blocked_patterns` applies them. A single source of truth would be better.

## 4. Duplicate aggregation logic in `evaluate.py` (high) [fixed]
**File:** `src/lovely_bash_permissions/evaluate.py`, two blocks (~lines 158–176 and ~183–204)

The status-aggregation for output/input/background redirections was written **twice**: once right after collecting segment results, and again later. Both blocks did identical `deny → overall_status = "deny"` + reason-appending logic, causing output denial reasons to be appended twice.

**Fix:** Removed the redundant output-redirection-only block (6 lines). Kept the combined aggregation block that handles output/input/background together with deny-first semantics, eliminating double-appending and dead code.

## 5. Raw-JSON traversal instead of typed AST in `evaluate.py` (medium) [fixed]
**File:** `src/lovely_bash_permissions/evaluate.py`, `_extract_subshell_contents()` and `_has_cmd_subst()`

Both functions manually walked shfmt JSON dicts (`node.get("Type")`, `isinstance(node, dict)`) instead of using the typed AST from `converter.py`. This meant they missed CmdSubst/ProcSubst nodes nested inside Word parts — specifically those hidden inside `DblQuoted`/`SglQuoted` nodes (e.g., `echo "$(cat $(ls))"`). A CmdSubst inside quotes was invisible to the traversal, creating a security gap where blocked paths in quoted substitutions were silently skipped.

**Fix:** Rewrote both functions to use typed AST via `node_from_json()` + `_traverse()` from `inspect.py` with `recurse_call_expr_args=True`. Added `_Found` sentinel exception for early termination (same pattern as `inspect.py`). 4 regression tests added: nested-in-quotes blocked, 3-deep-nested blocked, process-substitution `<(...)` blocked, deeply nested unquoted blocked. All 539 tests pass.

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
- **High impact (1):** duplicate aggregation logic (#4)
- **Medium impact (2):** redundant redir collection (#1), duplicate blocked-pattern logic (#3)
- **Low–medium (1):** bare excepts with noqa (#6)
- **Low / documentation (4):** confusing docstring (#8), stale cache (#9), duplicated helper awareness (#7), unused section header (#10)
- **Fixed (4):** redundant redir collection (#1), empty redirections in segments.py (#2), raw-JSON traversal (#5), duplicate blocked-pattern logic (#3)
