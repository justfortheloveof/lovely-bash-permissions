Fix Priority 7: Print statements in docstrings (LOW priority, cosmetic).

Task: Many docstrings contain print(...) examples — replace them with proper doctest-style assertions or remove.

Specific changes:
1. In ast.py, find all docstrings containing print(...) examples and convert them to proper docstring format (either doctest-style with >>> prompts or just descriptive text).
2. In inspect.py, same treatment for docstrings containing print() examples (like the Visitor class example showing commands collection).
3. Also check __init__.py for any print statements in docstrings (the Quick start example uses print, which is fine — only library-level examples need fixing).

Note: keep actual code examples but format them properly (as doctest >>> blocks or just descriptive text).

After changes: run uv run pytest — must pass 221 tests.

Reply only with confirmation that tests pass.
