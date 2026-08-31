Fix Priority 8: Visit split decision — document, don't implement.

Task: Plan_2 file organization mentions splitting code into types/words.py, types/commands.py, etc. None of these files exist. Document whether splitting is worth it or just document why monolithic is preferred.

Specific:
1. Read plan_2_nodes.md to understand the original file organization suggestion
2. Write a doc comment at the top of ast.py explaining why the monolithic approach is preferred (small project, all types serve inspection/traversal use cases, splitting adds complexity without clear benefit)
3. If any of the suggested split files (types/words.py etc.) are referenced elsewhere, add a note about it
4. Run uv run pytest — must pass 221 tests

Reply only with confirmation that tests pass.
