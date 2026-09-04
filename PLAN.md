# Plan

## Objective

We are working on our python devin_cli functionality.

For each project documented below, you MUST orchestrate the implementation by ALWAYS spawning a research agent to investigate implemetation options. You then pick the proper implementation and spawn an agent for implementation of the chosen solution.

Test Examples:

```
uv run lovely-devin-permissions --test 'cmd'
node /home/alx/repos/jftlo/lovely-devin-permissions/dist/hook.js --test 'cmd'
```

## Projects

### 1. Trailing period in reason messages (PER-TOOL config) [x]
**Python**: Includes trailing period inside the quoted pattern — `"command matches allowed pattern ^ls(\\s+.*)?$."` (period INSIDE quotes)
**TS**: No trailing period — `"command matches allowed pattern ^ls(\\s+.*)?$"`
**Impact**: Cosmetic only — reason text differs but decision logic is identical.
**Desired Behaviour**: remove trailing period
**Status**: Completed — strip trailing `.` from patterns in effective_bash.py; approval reasons only shown on auto-approve

### 2. Reason detail in ask decisions (non-redirection asks) [x]
**Python**: Includes matching patterns plus denial — `"command matches allowed pattern ^ls(\\s+.*)?$; \\"rm\\" command does not match allowed patterns"`
**TS**: Only includes denial — `"\"rm\" command does not match allowed patterns"`
**Impact**: Cosmetic — Python shows which segments matched, TS only shows denial.
**Desired Behaviour**: only include denial reasons when asking, approval reasons should only be shown on auto-approve
**Status**: Completed — evaluate.py separates approval/rejection reasons; approval reason only appended when status is allow

### 3. Background execution (`&`) default policy [x]
**Python**: Approves — `background_execution` defaults to "allow" (no project config overrides it)
**TS**: Asks — `background_execution` defaults to "ask" (per effective-bash.ts: `'*': 'ask'`, no explicit background_execution)
**Root cause**: Python's rules.py line 372 defaults `background_execution` to "allow"; TS schema has no default for background_execution, falling back to `'*': 'ask'`.
**Impact**: Behavioral — Python is more permissive for background commands. May need alignment if TS behavior was intentional.
**Desired Behaviour**: Everything should default to ask. This is paramount.
**Status**: Completed — background_execution defaults to "ask" in rules.py and evaluate.py. All tests pass.

### 4. Subshells `(cmd)` handling [x]
**Python**: Approves — `"command is allowed"` (subshell itself passes)
**TS**: Asks — `"subshell or command substitution requires approval"`
**Root cause**: Same as #6 — TS treats subshells the same as command substitutions.
**Impact**: Behavioral — Python allows subshell-wrapped commands without review.
**Desired Behaviour**: This is unexpected. Our python parser sees the cmd in the subshell, even deeply nested.
**Status**: Completed — fixed _has_cmd_subst() detection (Word nodes lack Type key); subshells now always return "ask" matching TS.

### 5. Input redirection (`<`) blocked paths check [x]
**Python**: Approves `cat < /etc/passwd` — does NOT check blocked_paths against redirection targets
**TS**: Blocks `cat < /etc/passwd` — checks blocked_paths against redirect target (`"Redirect target \\"/etc/passwd\\" matches blocked path pattern"`)
**Root cause**: Python's evaluate.py only checks arguments, not redirection targets, against blocked_paths_regex.
**Impact**: Behavioral — Python is more permissive for input redirections to blocked paths. This may be a security concern.
**Desired Behaviour**: This is a problem, we should catch and block this
**Status**: Completed — check_input_redirection checks redirect targets against blocked_paths for all policies; fixed _display_pattern escaping to match TS.

### 6. Heredoc input redirect (`<<`) [x]
**Python**: Approves `cat << EOF` — treats as "empty command" when no args parsed
**TS**: Asks — `"input redirection requires approval because input_redirection is set to ask"`
**Root cause**: Python parser returns empty/whitespace command for heredoc; TS parses it as input redirect.
**Impact**: Behavioral — Python may miss input redirections that should be reviewed.
**Desired Behaviour**: This seems wrong, how is that an empty cmd?
**Status**: Completed — input/output redirection defaults changed to "ask"; heredocs go through approval flow.

### 7. Whitespace-only commands [x]
**Python**: Approves `"empty command"` — treats whitespace as empty, auto-approves
**TS**: Asks — `"bash permission is set to ask"` — treats whitespace as needing approval
**Impact**: Cosmetic/minor — both handle it, but Python approves while TS asks.
**Desired Behaviour**: This is unexpected, all cmds must pass through the approval same flow.
**Status**: Completed — empty/whitespace commands now apply wildcard policy (default "ask") instead of auto-approving.

### 8. Duplicate blocked-pattern logic (issue #3) [x]
**Problem**: Blocked-path matching lived in two places — `effective_bash.py:_deny_item_to_regex()` (converts deny-list items to patterns) and `rules.py:check_blocked_patterns()` + `_find_blocked_path()` (applies them). Conversion and application were separate, with duplicated loop logic.
**Root cause**: Pattern conversion was a config-loading concern; pattern application was rules-engine code. Callers passed the merged list directly, so there was no actual reuse — just duplicated intent.
**Impact**: Semantic drift — deny-list items were escaped+anchored (`^/etc/passwd$`) while raw `blocked_paths_regex` entries were unescaped and applied with `re.search()` (unanchored).
**Fix**: Moved `_deny_item_to_regex` → `rules.py:deny_item_to_pattern()` (public, renamed), and created shared `_match_pattern()` helper. Both call sites now use one internal matcher.
**Tests**: 8 new tests for `deny_item_to_pattern` (bare, quoted, spaces, escaped chars) plus equivalence tests.

### 9. Empty redirections in `segments.py` (issue #2) [x]
**Problem**: `_extract_segments()` hardcoded `"redirections": []` — all segments lost redirection info.
**Root cause**: The function never extracted redirections from typed AST nodes (Stmt.redirs, BinaryCmd.left/right_redirs).
**Impact**: parse_segments() returned segments without any redirection data, defeating the module's documented purpose.
**Fix**: Added `_extract_redirs()` helper that extracts Redir from Stmt and BinaryCmd; threaded redirs through recursive calls so each CallExpr segment carries its inherited redirections. Fixed IfClause/WhileClause to use cond_stmts (not "cond"). Added Block handler for FuncDecl bodies.
**Tests**: 18 new tests covering simple/redir, pipe left/right/both, and-chain/or-chain, sequential, background-on-pipe, complex pipes, if/while/body, func-body.
**Bonus**: Steps into issue #3 — replaced evaluate.py's raw-JSON redirection checks with segment-based `_check_segments_output_redirs()` and `_check_segments_input_redirs()`, making segments the single source of truth for redirection policy evaluation.

### 10. Raw-JSON traversal instead of typed AST (issue #5) [x]
**Problem**: `_extract_subshell_contents()` and `_has_cmd_subst()` in `evaluate.py` manually walked shfmt JSON dicts (`node.get("Type")`, `isinstance(node, dict)`) instead of using the typed AST from `converter.py`. This missed CmdSubst/ProcSubst nodes nested inside Word parts — specifically those hidden inside `DblQuoted`/`SglQuoted` nodes (e.g., `echo "$(cat $(ls))"`).
**Root cause**: The visitor only recursed into `Word.Parts` but not into quoted-string nodes (`DblQuoted`, `SglQuoted`) which also contain nested parts. A CmdSubst inside quotes was invisible to the traversal.
**Impact**: Blocked paths hidden inside quoted command substitutions were silently skipped — a security gap where `echo "$(cat /etc/passwd)"` was allowed while the unquoted equivalent was denied.
**Fix**: Rewrote both functions to use typed AST via `node_from_json()` + `_traverse()` from `inspect.py`, with `recurse_call_expr_args=True` so CallExpr argument children are visited. Added `_Found` sentinel exception for early-termination detection (same pattern as `inspect.py`).
**Tests**: 4 new regression tests — nested-in-quotes blocked, 3-deep-nested-in-quotes blocked, process substitution `<(...)` blocked, deeply nested unquoted blocked. All 539 tests pass including ruff/myPy strict/format lint.
