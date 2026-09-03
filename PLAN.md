# Plan: Comply with ruff check config

## Objective

We need to comply with `ruff check`'s current configuration and ensure that running: `uv run ruff check` passes with 0 warnings or errors.

We must also ensure that we do not break or change any behavior by confirming the tests still pass after any change by running: `uv run pytest --ignore tests/test_ruff.py`

Once and only once the above is clean, all tests, including ruff, should also pass: `uv run pytest`

You MUST NOT change pyproject.toml nor test_ruff.py

### Workflow

You are the orchestrator and you MUST spawn agents to investigate the issues and make the appropriate changes.
You MUST NOT make the changes yourself.
You must give the smallest work item possiblessible to agents, and spawn as many of them as you need, sequentially.
When an agent finishes verify and commit its changes and spawn another agent to fix the next ruff reported issue.
