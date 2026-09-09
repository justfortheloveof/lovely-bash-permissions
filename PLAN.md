# Plan: Implement deferred `parse_segments()` node-type coverage

## Status of prior work
- Steps 1–3 (empty-segment wildcard policy + generic reason fix) are ✅ implemented and committed. All 640 tests pass.
- The remaining work is adding handler cases to `_extract_segments()` (segments.py) so that currently-unhandled AST node types produce segments instead of silently returning `[]`.

## Unsupported node types (from audit)
| Node type | Example | Currently returns |
|---|---|---|
| DeclClause | `export/unset/alias` | 0 segments |
| CaseClause | `case x in a) cmd;; esac` | 0 segments |
| ForClause | `for i in ...; do done` | 0 segments |
| **CStyleLoop** | `for ((i=0;i<10;i++)); do echo x; done` | **0 segments** |
| Subshell | `( ls )` | 0 segments |
| **TestClause** (`[[ ]]`) | `[[ -d foo && -e bar ]]` | **0 segments** (note: `[ ]` works) |
| TimeClause | `time sleep 1` | 0 segments |
| ArithmCmd / LetClause | `(())`, `let x=1` | 0 segments |
| CoprocClause | `coproc mycmd` | 0 segments |

---

## Step 4a: Add logging import and unhandled-node warning to `_extract_segments()` (segments.py)

**Goal**: For any node type not matched by existing `if/elif` branches, log a warning identifying the type — better than silent fallback to wildcard policy.

**Changes in `src/lovely_bash_permissions/segments.py`**:
1. Add import near top of file (after `from __future__ import annotations`, line ~18):
```python
import logging
_logger = logging.getLogger(__name__)
```
2. Add a catch-all `else` clause just before the final `return segments`:
```python
else:
    _logger.warning("Unhandled AST node type '%s' — returning 0 segments", type(node).__name__)
```

**Verification**: run `uv run pytest tests/test_evaluate.py -q` — no new failures expected (this is just a warning, behavior unchanged).

---

## Step 4b: Add DeclClause handler to `_extract_segments()` (segments.py)

**Goal**: Extract command name from `export/unset/alias` statements so they produce segments instead of 0.

**How DeclClause nodes look (from shfmt JSON)**:
- Has `kind` field: `"export"`, `"unset"`, or `"alias"`
- For export/unset with args: has `args` list (CallExpr-style), first arg is command name
- For `export VAR=val`: only an Assign node, no real "command" — skip it (return [])

**Changes**: add a new `elif isinstance(node, DeclClause):` block **before** the existing `Stmt` branch (around line ~109). Logic:
```python
elif isinstance(node, DeclClause):
    if node.kind in ("export", "unset") and node.args:
        cmd_name = _word_value(node.args[0])
        segments.append({"command": cmd_name, "arguments": [], "redirections": []})
    # alias and export-without-args: skip (no real command to check)
```

**Verification**: add test `test_declclause_export_segment_extracted` in `tests/test_evaluate.py`:
```python
def test_declclause_export_segment_extracted(self):
    result = evaluate_bash_command("export BOGUS=true bogus", make_config(allowed=["^bogus"]))
    assert result["status"] == "allow"  # now matches allowed pattern instead of wildcard ask
```

---

## Step 4c: Add CaseClause handler to `_extract_segments()` (segments.py)

**Goal**: Extract commands from case branches.

**How CaseClause nodes look**: has `branches` list, each branch has `items` (CaseItem) and each item has a `cmd` (CallExpr).

**Changes**: add `elif isinstance(node, CaseClause):`:
```python
elif isinstance(node, CaseClause):
    for branch in node.branches:
        if hasattr(branch, "items") and branch.items:
            for item in branch.items:
                if hasattr(item, "cmd") and item.cmd:
                    segments.extend(_extract_segments(item.cmd))
```

**Verification**: add test `test_case_clause_extracted`:
```python
def test_case_clause_extracted(self):
    result = evaluate_bash_command(
        "case x in a) ls;; b) cp src dst;; esac", make_config(allowed=["^ls$"])
    )
    assert result["status"] == "allow"  # 'ls' matches pattern
```

---

## Step 4d: Add ForClause handler to `_extract_segments()` (segments.py)

**Goal**: Extract commands from loop bodies.

**How ForClause nodes look**: has `body` list of Stmt, each stmt may contain CallExpr or compound bodies.

**Changes**: add `elif isinstance(node, ForClause):`:
```python
elif isinstance(node, ForClause):
    if hasattr(node, "body") and node.body:
        for stmt in node.body:
            segments.extend(_extract_segments(stmt))
```

**Verification**: add test `test_for_clause_extracted`:
```python
def test_for_clause_extracted(self):
    result = evaluate_bash_command(
        "for i in 1 2; do echo $i; done", make_config(allowed=["^echo$"])
    )
    assert result["status"] == "allow"  # 'echo' matches pattern
```

---

## Step 4e: Add Subshell handler to `_extract_segments()` (segments.py)

**Goal**: Recurse into subshell body `(...)` — note: brace groups `{ }` (Block) already work.

**How Subshell nodes look**: has `body` list of Stmt (same shape as ForClause).

**Changes**: add `elif isinstance(node, Subshell):`:
```python
elif isinstance(node, Subshell):
    if hasattr(node, "body") and node.body:
        for stmt in node.body:
            segments.extend(_extract_segments(stmt))
```

**Verification**: add test `test_subshell_extracted`.

---

## Step 4e2: Add CStyleLoop handler (segments.py)

**Goal**: Handle c-style for loops `for ((i=0; i<10; i++)); do ... done`.

**How CStyleLoop nodes look**: same shape as ForClause — has `body` list of Stmt.

**Changes**: add alongside ForClause in same elif block:
```python
elif isinstance(node, (ForClause, CStyleLoop)):
    if hasattr(node, "body") and node.body:
        for stmt in node.body:
            segments.extend(_extract_segments(stmt))
```

**Verification**: add test `test_cstyle_loop_extracted`:
```python
def test_cstyle_loop_extracted(self):
    result = evaluate_bash_command(
        "for ((i=0;i<10;i++)); do echo x; done", make_config(allowed=["^echo$"])
    )
    assert result["status"] == "allow"
```

---

## Step 4e3: Add TestClause handler (segments.py)

**Goal**: Handle `[[ ... ]]` tests — note `[ ]` (bracket form) already works via CallExpr, but `[[ ]]` parses as TestClause.

**How TestClause nodes look**: has `test_expr` (UnaryTest/BinaryTest/ParenTest) and possibly a body. For simple tests like `[[ -d foo ]]` there's no body — skip (no command to extract). For test-with-body forms, recurse.

**Changes**: add `elif isinstance(node, TestClause):`:
```python
elif isinstance(node, TestClause):
    # Recurse into test expression — UnaryTest/BinaryTest may contain commands in args
    if hasattr(node, "test_expr") and node.test_expr:
        segments.extend(_extract_segments(node.test_expr))
```

**Verification**: add test `test_testclause_extracted`:
```python
def test_testclause_extracted(self):
    result = evaluate_bash_command("[[ -d /tmp && ls ]]; echo done", make_config(allowed=["^ls$"])
    )
    assert result["status"] == "allow"
```
```python
def test_subshell_extracted(self):
    result = evaluate_bash_command("( ls )", make_config(allowed=["^ls$"]))
    assert result["status"] == "allow"  # 'ls' inside parens matches pattern
```

---

## Step 4f: Add remaining handlers (TimeClause, ArithmCmd/LetClause, CoprocClause) (segments.py)

**Goal**: Cover the last three unsupported node types.

**Changes**: add one `elif` block per type before `return segments`:
```python
elif isinstance(node, TimeClause):
    # time <cmd> — extract the command from inside
    if hasattr(node, "cmd") and node.cmd:
        segments.extend(_extract_segments(node.cmd))

elif isinstance(node, (ArithmCmd, LetClause)):
    # (( expr )) and let — arithmetic-only, skip (no real command)

elif isinstance(node, CoprocClause):
    # coprocess — extract command if present
    if hasattr(node, "cmd") and node.cmd:
        segments.extend(_extract_segments(node.cmd))
```

**Verification**: add tests `test_time_clause_extracted`, `test_coproc_extracted`:
```python
def test_time_clause_extracted(self):
    result = evaluate_bash_command("time sleep 1", make_config(allowed=["^sleep$"]))
    assert result["status"] == "allow"

def test_coproc_extracted(self):
    result = evaluate_bash_command("coproc mycmd arg", make_config(allowed=["^mycmd$"]))
    assert result["status"] == "allow"
```

---

## Step 4g: Run full test suite and commit

**Goal**: Confirm all existing tests still pass plus new regression tests.

Run `uv run pytest -v` (expect 640+ passing). Commit each step separately:
- "Step 4a: Warn on unhandled AST node types in `_extract_segments()`"
- "Step 4b: Handle DeclClause (export/unset/alias) in `_extract_segments()`"
- "Step 4c: Handle CaseClause (case statements) in `_extract_segments()`"
- "Step 4d: Handle ForClause (for loops) in `_extract_segments()`"
- "Step 4e: Handle Subshell (parens) in `_extract_segments()`"
- "Step 4e2: Handle CStyleLoop (c-style for loops) in `_extract_segments()`"
- "Step 4e3: Handle TestClause ([[ ]]) in `_extract_segments()`"
- "Step 4f: Handle TimeClause, ArithmCmd/LetClause, CoprocClause"
- "Step 4g: Verify full suite passes (650+ tests)"

## Notes for implementers
- `_extract_segments()` is in `src/lovely_bash_permissions/segments.py`, line ~68.
- Each handler should call `_extract_segments()` recursively on nested nodes (same pattern as existing handlers).
- Use `hasattr(node, "body")` checks since not all node types have every attribute.
- `_word_value()` is imported from `.inspect`; use it to extract command names.
- Tests go in `tests/test_evaluate.py`, use existing `make_config()` helper and `evaluate_bash_command()`.
- Run tests per step: `uv run pytest tests/test_evaluate.py -v --tb=short`
