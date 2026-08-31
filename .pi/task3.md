Fix Priority 3: Standardize inconsistent field naming across node types.

Background: Different node types use different names for equivalent concepts. This is a large refactoring task — rename fields consistently across ast.py, inspect.py, and any code that accesses these fields.

Target naming convention:
- Opening position → `left_pos` (was: left, lparen, lbrace)
- Closing position → `right_pos` (was: right, rparen, rbrace)  
- Child expression/inner content → `body` (was: x where it means "child", body, stmt)
- Opening operator position → `op_pos` (keep this — it's specific to operators, not positions)

Specific renames needed in ast.py:
1. Block: `lbrace` → `left_pos`, `rbrace` → `right_pos`
2. Subshell: no opening/closing fields (only stmts) — skip
3. IfClause: `cond` → `cond_stmts`, `then` → `then_stmts`, `else_branch` → `else_stmts` (make naming consistent — all end in `_stmts`)
4. ForClause: `var` stays, `words` stays, `body` stays — check consistency
5. WhileClause: `cond` → `cond_stmts`, `body` stays — same pattern as IfClause
6. BinaryCmd: `x` → `left`, `y` → `right` (these are operands)
7. AndCmd: same — `x` → `left`, `y` → `right`
8. OrCmd: same — `x` → `left`, `y` → `right`
9. CaseClause: `expr` stays, branches/default stay (they're dict-based)
10. TestClause: `left` → `left_pos`, `right` → `right_pos`, `x` → `body`
11. ArithmCmd: `left` → `left_pos`, `right` → `right_pos`, `x` → `body`
12. ParenTest: `lparen` → `left_pos`, `rparen` → `right_pos`, `x` → `body`
13. ParenArithm: `lparen` → `left_pos`, `rparen` → `right_pos`, `x` → `body`
14. CoprocClause: rename `coproc_pos` to match pattern — keep as-is (it's operator position)
15. TimeClause: `time_pos` stays (operator position)

In inspect.py, update all field references to match new names. In parser.py, update json→object mapping field names.

Important notes:
- Keep `op_pos` for operator positions (it's specific to operators) — don't rename it
- `pos`, `end` on Position class stay as-is (they're standard)
- For IfClause/WhileClause, rename `cond` → `cond_stmts`, `then` → `then_stmts`, `else_branch` → `else_stmts` for consistency
- After changes: run uv run pytest — must pass 221 tests

Reply only with confirmation that tests pass.
