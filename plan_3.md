
Plan 3: Code Consistency & Cleanliness (Node Coverage Follow-up)
=================================================================

**Status:** Plan 2 complete — all 30 missing node types implemented, 221 tests passing.
**Goal:** Fix code quality issues discovered during plan_2 implementation: dead code, naming inconsistency, duplication.
**Total files affected:** ast.py, inspect.py, __init__.py (3 source files)

## Priority 1: Dead/unused visitor methods in Visitor class (HIGH)

The `Visitor` class defines methods that are never dispatched from its `visit()` method:

- `visit_word(node)` — defined (line ~105) but never reached; Word is handled by `visit_part`
- `visit_redir(node)` — defined but never reached; Redir handled in walk() directly
- `visit_lit(node)` — defined but only reachable when Lit is isinstance'd; should dispatch from visit() for consistency

**Fix:** Either remove unused methods or wire them into `visit()`'s dispatch chain. Recommend wiring in, since they're documented public API.

## Priority 2: Duplicate docstring in `walk()` (MEDIUM)

inspect.py line ~378 has the walk() docstring repeated twice — first a proper one, then another identical block right above `self.visit(node)`.

**Fix:** Remove the duplicate.

## Priority 3: Inconsistent field naming across node types (HIGH)

Different node types use different names for equivalent concepts:

| Concept | Names in use |
|---|---|
| Opening position | `left`, `lparen`, `lbrace`, `op_pos` (inconsistent) |
| Closing position | `right`, `rparen`, `rbrace` (inconsistent) |
| Child expression | `x`, `body`, `stmt`, `cond` (inconsistent) |
| Position field | some use `pos`, others use `position` (Stmt has both!) |

**Fix:** Standardize — recommend `left_pos`/`right_pos`, and rename `position` → `pos` (or vice versa) for consistency.

## Priority 4: Redundant traversal functions (HIGH)

`inspect.py` has near-duplicates:
- `_collect_commands()` and `_find_commands()` — same traversal logic, one returns strings, other returns nodes
- `_collect_arguments()` and `_find_arguments()` — same pattern
- `_collect_redirections()` and `_collect_target_files()` — partially overlapping

**Fix:** Keep public API (get_commands/find_commands, get_arguments/find_arguments) but refactor internals into a shared `_traverse(node, visitor_fn)` helper.

## Priority 5: Inconsistent `extra` usage (MEDIUM)

Only `CallExpr` uses an `extra` dict (`{"assigns": [...]}`); all other nodes use direct fields.

**Fix:** Either add `extra` to nodes that need it (Assign, FuncDecl) or move assigns into a proper field.

## Priority 6: `__init__.py` exports miss some types (MEDIUM)

`DeclClause` is in NODE_TYPES but not exported. `BraceExp`, `ArrayExpr`, `ArrayElem` are in __all__ but check they're importable. Some types referenced in tests (ArithmCmd, LetClause) should be verified exported.

**Fix:** Verify every NODE_TYPES key has a corresponding __all__ entry and import.

## Priority 7: Print statements in docstrings (LOW)

Many docstrings contain `print(...)` examples — cosmetic but unusual for library code. Replace with doctest-style assertions or remove.

## Priority 8: No separate visitor.py (LOW, plan-mentioned)

Plan_2 file organization mentions `types/words.py`, `types/commands.py`, etc. — none exist. Consider whether splitting is worth it or just document why monolithic is preferred.

## Implementation Order
1. Priority 2 (duplicate docstring — one line fix)
2. Priority 1 (wire dead visitor methods into dispatch)
3. ~~Priority 4 (deduplicate traversal helpers — biggest win)~~ ✅ Done — committed as 6edd368, file reduced ~1250→790 lines
4. Priority 6 (fix exports)
5. Priority 3 (field naming — large refactor, do last)
6. Priority 5 (extra field consistency)
7. Priority 7 (print statements — cosmetic, optional)
8. Priority 8 (visit split decision — document, don't implement)
