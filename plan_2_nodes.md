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

3. ~~Dead code: `Range` class and unused node classes~~ ✅ DONE
Removed unused `Range` class (never referenced or exported). Audited other node types — some have zero tests but are used internally by shfmt JSON parsing, so left them.

4. ~~Inconsistency: `Part` and `Redir` lack `@dataclass`~~ ✅ DONE
Verified Part, Redir, and Stmt already have @dataclass decorators (plan was based on older version).

5. ~~Bug-prone: inconsistent `@dataclass` placement on `TestClause`~~ ✅ DONE
Removed duplicate @dataclass decorator from TestClause (two decorators, second shadowed first — clearly a mistake).
