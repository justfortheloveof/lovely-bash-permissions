Fix Priority 6: __init__.py exports miss some types.

Task: Verify every NODE_TYPES key has a corresponding __all__ entry and import in __init__.py.

Specifics:
1. Read ast.py to find all node type classes defined (every class with `type = "..."` or subclass of Node).
2. Read __init__.py and compare: every class from ast.py should be importable via `from lovely_bash_permissions import ClassName`.
3. Specifically check: DeclClause is in NODE_TYPES but may not be exported; BraceExp, ArrayExpr, ArrayElem are in __all__ — verify they're actually imported from ast; ArithmCmd, LetClause referenced in tests — verify exported.
4. Fix __init__.py so all node types from ast.py are importable (add missing imports and __all__ entries).
5. After fixing: run uv run pytest — must pass 221 tests

Reply only with confirmation that tests pass.
