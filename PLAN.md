# Top 5 code cleanup tasks

1. **Massive duplicated traversal logic** (highest impact)
`inspect.py` has two nearly-identical recursive traversal functions: `_traverse()` (~130 lines) and `Visitor.walk()` (~130 more lines). They contain the same 20+ `isinstance` branches for every node type. The comment in `_traverse()` explicitly says it "replaces the near-duplicate traversal logic previously spread across" several functions, but `walk()` is still a duplicate. This is ~260 lines of near-identical code maintained in two places — a bug magnet (fix one, forget the other).

**Analysis of duplication:** Both functions share identical child-recursion logic for these 14 node types: File, Stmt, CallExpr, BinaryCmd, Word, Redir, Lit, Part, CmdSubst (via Part.type check), Subshell, IfClause, ForClause, WhileClause, AndCmd, OrCmd, CaseClause. The only difference is that `walk()` dispatches through `self.visit(node)` before recursing, while `_traverse()` calls a passed-in visitor callable.

**Fix:** Make `Visitor.walk()` delegate to `_traverse()`. Strategy:
- Keep `_traverse(node, visitor)` as the single canonical traversal function (it's used by `get_commands`, `find_commands`, `_has_variable_recursive`'s callers, `get_redirections`, `get_arguments`, `find_arguments`, `get_target_files`).
- Rewrite `walk()` to become a thin wrapper: `def walk(self, node): _traverse(node, self.visit)`.
- Remove the 130-line recursive body from `walk()` — all recursion logic now lives only in `_traverse()`.
- The visitor subclasses (CountVisitor, WordCountVisitor, etc. in test_phase2.py) override `visit_*()` methods; those continue to work because `_traverse()` calls the visitor callable on each node.

**Implementation steps:**
a. In `Visitor.walk()`, replace the entire method body with just:
   ```python
   def walk(self, node: Node):
       """Walk the entire AST tree, visiting all nodes recursively."""
       _traverse(node, self.visit)
   ```
b. Delete all the `if isinstance(...)` recursion branches from inside `walk()` (lines ~208–315).
c. Verify all tests pass (`uv run pytest`) — the Visitor subclasses in test_phase2.py will still work because `_traverse()` calls `self.visit(node)` on each node.
d. Run the full test suite to confirm behavior is unchanged: `uv run pytest tests/test_phase2.py::TestVisitorPattern -v`.

**Files changed:** `src/lovely_bash_permissions/inspect.py`
**Tests affected:** `tests/test_phase2.py` (TestVisitorPattern) — verify they still pass.

2. **Dead code: unused imports**
`inspect.py` imports `Any`, `Dict`, `SglQuoted`, and `DblQuoted` from `.ast`. Only `DblQuoted` is used (once in `_has_variable_recursive`). `Any`, `Dict`, and `SglQuoted` are dead imports. Also, `_has_variable_recursive()` is a ~100-line function that uses string-based type checking (`node.type == "DeclClause"`) and manual recursion — it duplicates the traversal logic in a very different style from `_traverse()`.

**Fix:** Remove unused imports; rewrite `has_variable` to use the shared `_traverse()` visitor pattern (a simple visitor that checks for `"Var"`, `"ParamExp"`, `"CmdSubst"` types).

3. **Dead code: `Range` class and unused node classes**
The `ast.py` module defines 49 dataclasses (102 classes total including functions), but `Range` is never referenced anywhere else in the codebase. Several node types (`FlagsArithm`, `LetClause`, `TimeClause`, `CoprocClause`, `TestDecl`, `Comment`, `Assign`, `CaseItem`, `WordIter`, `CStyleLoop`, `ArrayExpr`, `ArrayElem`) have **zero tests covering them** — they're likely dead code from an early shfmt feature dump.

**Fix:** Remove `Range` (or add tests if it's needed); audit and remove/unexport node types that no shfmt version produces, or add tests for them.

4. **Inconsistency: `Part` and `Redir` lack `@dataclass`**
Most node types use `@dataclass`, but `Part` (line ~421), `Redir` (~681), and `Stmt` (~1047) are plain classes with manual `__init__`-style defaults via dataclass-like field annotations. This is inconsistent — they should either all be `@dataclass` or none.

**Fix:** Add `@dataclass` decorator to these classes for consistency.

5. **Bug-prone: inconsistent `@dataclass` placement on `TestClause`**
On line ~705, there's a stray `@dataclass` followed by `class TestClause(Node):` — but looking more carefully, there are **two `@dataclass` decorators** before it (the second is actually for something else, but the formatting looks suspicious — check exact lines 703–710). Also, `Redir` lacks `@dataclass`, meaning it doesn't get auto-generated `__eq__`, `__repr__`, etc., which will cause subtle bugs in tests that compare redirection objects.

**Fix:** Audit and fix the `@dataclass` decorators; ensure all comparable node classes get them.
