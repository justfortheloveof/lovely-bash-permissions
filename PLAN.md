# Top 5 code cleanup tasks

1. ~~Massive duplicated traversal logic~~ (highest impact) ✅ DONE
`inspect.py` had two nearly-identical recursive traversal functions: `_traverse()` (~130 lines) and `Visitor.walk()` (~130 more lines). They contained the same 20+ `isinstance` branches for every node type.

**Fix:** Made `Visitor.walk()` delegate to `_traverse()`. Renamed walk's body to a thin wrapper: `def walk(self, node): _traverse(node, self.visit)`. Removed the 130-line recursive body from walk() — all recursion logic now lives only in `_traverse()`.

**Discovery:** `_traverse()` originally skipped recursing into CallExpr args (the `pass` branch). Since walk() must visit Word/Lit nodes inside command arguments (e.g. `file.txt` in `cat file.txt`), added a `recurse_call_expr_args: bool = False` parameter to `_traverse()` — walk() passes `True`, all other callers pass `False` (preserving original behavior for get_commands, find_arguments, etc.).

**Files changed:** `src/lovely_bash_permissions/inspect.py`
**Tests affected:** `tests/test_phase2.py` (TestVisitorPattern) — all 5 visitor tests pass. Full suite: 221/221 passed.

2. ~~Dead code: unused imports~~ ✅ DONE
Removed `Any`, `Dict` (typing) and `SglQuoted` (ast) from inspect.py imports. Kept `DblQuoted` (used in VariableVisitor). Rewrote `has_variable()` using `_traverse()` visitor pattern — created `VariableVisitor` class that collects Var/ParamExp/CmdSubst nodes, deleted ~100-line `_has_variable_recursive()` function.

**Tests:** 221/221 passed.

3. **Dead code: `Range` class and unused node classes**
The `ast.py` module defines 49 dataclasses (102 classes total including functions), but `Range` is never referenced anywhere else in the codebase. Several node types (`FlagsArithm`, `LetClause`, `TimeClause`, `CoprocClause`, `TestDecl`, `Comment`, `Assign`, `CaseItem`, `WordIter`, `CStyleLoop`, `ArrayExpr`, `ArrayElem`) have **zero tests covering them** — they're likely dead code from an early shfmt feature dump.

**Fix:** Remove `Range` (or add tests if it's needed); audit and remove/unexport node types that no shfmt version produces, or add tests for them.

4. **Inconsistency: `Part` and `Redir` lack `@dataclass`**
Most node types use `@dataclass`, but `Part` (line ~421), `Redir` (~681), and `Stmt` (~1047) are plain classes with manual `__init__`-style defaults via dataclass-like field annotations. This is inconsistent — they should either all be `@dataclass` or none.

**Fix:** Add `@dataclass` decorator to these classes for consistency.

5. **Bug-prone: inconsistent `@dataclass` placement on `TestClause`**
On line ~705, there's a stray `@dataclass` followed by `class TestClause(Node):` — but looking more carefully, there are **two `@dataclass` decorators** before it (the second is actually for something else, but the formatting looks suspicious — check exact lines 703–710). Also, `Redir` lacks `@dataclass`, meaning it doesn't get auto-generated `__eq__`, `__repr__`, etc., which will cause subtle bugs in tests that compare redirection objects.

**Fix:** Audit and fix the `@dataclass` decorators; ensure all comparable node classes get them.
