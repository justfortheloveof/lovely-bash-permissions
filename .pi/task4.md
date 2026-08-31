Fix Priority 4: Deduplicate traversal helpers in inspect.py.

Task: The file has near-duplicate internal functions with identical traversal logic — same recursion over File/Stmt/BinaryCmd/etc. but different leaf operations (collect strings vs find nodes vs collect redirections/target files). Refactor into a shared helper.

Specific changes to inspect.py:
1. Create a new _traverse(node, visitor) helper function at module level (after imports). This function handles all node-type dispatching (File, Stmt, CallExpr, BinaryCmd, Word, Redir, Lit, Part, CmdSubst, Subshell, IfClause, ForClause, WhileClause, AndCmd, OrCmd, CaseClause) and calls visitor(node) at each leaf type (CallExpr for commands/args, Redir for redirections/targets).
2. Rewrite _collect_commands() to use a visitor lambda that collects command names from CallExpr nodes.
3. Same for _find_commands(), _collect_arguments(), _find_arguments(), _collect_redirections(), _collect_target_files() — each becomes a thin wrapper calling _traverse with its specific visitor.
4. Keep all public API unchanged (get_commands, find_commands, get_arguments, find_arguments, get_redirections, get_target_files, has_variable, has_pipe).
5. Leave _has_variable_recursive() and _has_pipe_recursive() as-is (they return booleans, different pattern).

Important notes:
- The visitor pattern in _traverse should handle all node types that appear in the existing implementations (File, Stmt, CallExpr, BinaryCmd, Word, Redir, Lit, Part, CmdSubst, Subshell, IfClause, ForClause, WhileClause, AndCmd, OrCmd, CaseClause)
- Each leaf operation becomes a small lambda/closure
- After changes: run uv run pytest — must pass 221 tests

Reply only with confirmation that tests pass.
