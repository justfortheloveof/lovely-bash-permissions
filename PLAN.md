# Plan: Align Python implementation with TypeScript reference (lovely-devin-permissions)

## Objective

We have a bug in lovely-devin-permissions with allowed_cmds_regex not being parsed as expected.

You can reproduce the issue by running:

```
uv run lovely-devin-permissions --test 'echo'  # accepted as expected
uv run lovely-devin-permissions --test 'git log'  # requires user approval but should match global config allowed_cmds_regex
```


### Workflow

Spawn agents to investigate the issues and make the appropriate changes.
You must give the smallest work item possible to agents, and spawn as many of them as you need, sequentially.
When an agent finishes, update this PLAN.md file's Findings and Changes sections accordinly. We need to be able to resume work on this by simply reading this file.

## Findings

The bug is in `src/lovely_bash_permissions/evaluate.py`. The function `evaluate_bash_command()` was matching `allowed_cmds_regex` patterns against the command name only (`cmd_name`), but the TypeScript reference and user config expect patterns to match the FULL command line including arguments. For example, `git log` should match `^git\s+(log|diff|status)...` from the global config, but the Python code only checked `^git$` against the command name "git".

## Changes

- **Modified**: `src/lovely_bash_permissions/evaluate.py` - Changed allowed pattern matching from `re.match(pattern, cmd_name)` to `re.match(pattern, full_command)` where `full_command` is the command name plus all arguments joined with spaces.
- **Added**: 2 new test cases in `tests/test_evaluate.py` (`test_allowed_pattern_full_command_line` and `test_allowed_pattern_mismatch_full_command_line`) to verify the fix.
- **Updated**: Multiple existing test cases in `tests/test_evaluate.py` to use the corrected behavior with full-command-line matching patterns.
- **Modified**: `src/lovely_bash_permissions/evaluate.py` - For single-command segments, use the raw command text (preserving quotes) for allowed pattern matching. For multiple segments (pipelines, etc.), continue using reconstructed text. This ensures quoted argument patterns like `^echo\s+'hello\s+world'` match correctly.

**Current status**: All 450 tests pass (including `test_quoted_arguments`).

**Next steps**: 
1. Verify that `uv run lovely-devin-permissions --test 'git log'` passes with the global config allowed_cmds_regex
2. Run the full test suite with any remaining edge cases
