# Fix: DeclClause Redirection Inheritance Bug

## Background

The lovely-bash-permissions tool parses bash commands via shfmt's JSON AST, extracts command segments, and evaluates permission rules. It detects output redirection (e.g., `>`, `>>`, `>&`) to warn or block commands that write files.

## The Bug

When a declaration builtin (`export`, `declare`, `readonly`, `local`, `typeset`) has redirection, the redirection is **not detected**:

```bash
$ lovely-devin-permissions --test 'echo hi > /tmp/test.txt'
# → flagged: "output redirection requires approval" ✓

$ lovely-devin-permissions --test 'export FOO="bar" > /tmp/out.txt'
# → NOT flagged for redirection, only "export" pattern ✗
```

## Root Cause

In `src/lovely_bash_permissions/segments.py`, the `_extract_segments()` function handles different AST node types:

- **CallExpr** (simple commands): correctly converts inherited redirections from parent Stmt into segment `redirections`
- **DeclClause** (declaration builtins): always sets `redirections: []`, ignoring inherited redirections

This causes the rules engine in `_check_segments_output_redirs()` (rules.py) to never see redirections from DeclClause segments.

## Fix Strategy

Add redirection inheritance to the DeclClause branch, mirroring CallExpr's approach. The inherited `redirs` parameter (passed from the parent Stmt node) must be converted to redir_dicts and attached to the segment.

## Implementation Steps

### Step 1: Add Redirection Inheritance to DeclClause Branch [x]

**File:** `src/lovely_bash_permissions/segments.py`
**Location:** DeclClause branch in `_extract_segments()` (around line ~205)

**Change:** Convert inherited `redirs` to redir_dicts (same as CallExpr does) and pass them to the segment.

**Before (roughly):**
```hemlock
if operands:
    segments.append({"command": node.variant, "arguments": operands, "redirections": []})
```

**After:**
```hemlock
redir_dicts = [
    {
        "Op": r.op,
        "N": {"Value": str(r.n)} if r.n is not None else {},
        "Word": {"Parts": [{"Value": _part_value(p)} for p in (r.word.parts if r.word else [])]},
    }
    for r in (redirs or [])
]
if operands:
    segments.append({"command": node.variant, "arguments": operands, "redirections": redir_dicts})
```

Note: Copy the exact approach from the CallExpr branch (around line 156). It defines an inline `_part_value` helper and converts redirs to redir_dicts. Do the same in the DeclClause branch. You may need to import `Lit` from `.ast` if not already imported. The existing `Word` import in segments.py already covers Word parts.

### Step 2: Add Test Cases [x]

**File:** `tests/test_decl_clause_redirection.py` (new)

Add tests for:
1. `export FOO="bar" > /tmp/out.txt` → flagged as output redirection
2. `readonly FOO="bar" > /tmp/out.txt` → flagged
3. `declare -x FOO="bar" > /tmp/out.txt` → flagged
4. `local FOO="bar" > /tmp/out.txt` (inside function) → flagged
5. `typeset FOO="bar" > /tmp/out.txt` → flagged
6. Simple `echo hi > /tmp/test.txt` → still works (regression)
7. `export FOO=$(echo bar > /tmp/out.txt)` → still flags nested command substitution (regression)

Use the same test pattern as existing tests in `tests/` that use `parse_segments()` or `evaluate_bash_command()`.

### Step 3: Run Existing Tests [x]

Run `uv run pytest` to ensure the change doesn't break any existing tests. The fix should be additive (only affects DeclClause nodes).

### Step 4: Verify Fix [x]

Test with the original failing case:
```bash
$ lovely-devin-permissions --test 'export FOO="bar" > /tmp/out.txt'
# Expected: flagged as "output redirection requires approval"
```

And verify no regression:
```bash
$ lovely-devin-permissions --test 'echo hi > /tmp/test.txt'
# Expected: still flagged
$ lovely-devin-permissions --test 'export FOO="bar"'
# Expected: no redirection flagged (correct)
```

## Files Changed
- `src/lovely_bash_permissions/segments.py` (fix)
- `tests/test_decl_clause_redirection.py` (new test file)

## Why This Works

shfmt parses `export FOO="bar" > /tmp/out.txt` as a Stmt node containing a DeclClause Cmd and one Redir. The segments extraction walks from Stmt → DeclClause, passing the Redir as the inherited `redirs` parameter. By converting those redirs to redir_dicts and attaching them to the segment, the rules engine in `_check_segments_output_redirs()` will detect them just like CallExpr redirections.