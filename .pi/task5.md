Fix Priority 5: Inconsistent `extra` usage across node types.

Task: Only CallExpr uses an `extra` dict (`{"assigns": [...]}`); all other nodes use direct fields. Standardize this pattern.

Specific changes:
1. In ast.py, CallExpr has `extra` field for assigns (variable assignments before commands like "x=1 ls").
2. FuncDecl also has variable assignment context (function body may have assigns). Assign node is separate but related.
3. Decide: either add `extra` to nodes that need it, OR move assigns into a proper direct field.

Recommended approach: Add `assigns` as a direct field (like CallExpr's extra["assigns"]) to FuncDecl, so function declarations with assigns are consistent. Keep CallExpr's extra["assigns"] as-is since it works well and many places reference it.

Actually, better approach: Make CallExpr's assigns a direct field `assigns: List['Assign'] = None` instead of stored in extra["assigns"]. Then update all references to `node.extra["assigns"]` → `node.assigns`.

In parser.py, update the CallExpr parsing to populate `assigns` directly.
In inspect.py, update all `_collect_commands`, `_find_commands`, etc. to use `node.assigns` instead of `node.extra["assigns"]`.

After changes: run uv run pytest — must pass 221 tests.

Reply only with confirmation that tests pass.
