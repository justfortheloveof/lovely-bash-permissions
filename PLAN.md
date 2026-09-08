# Plan: Fix empty-segment auto-approval and generic reason message

## Bugs

Two related bugs in `evaluate_bash_command()` (src/lovely_bash_permissions/evaluate.py):

**Bug 1 — empty segments auto-approved**: Commands whose AST parses as `DeclClause` (e.g. `export BOGUS=true bogus`) produce an empty segments list from `parse_segments()`. Since no segments are checked against allowed patterns, `any_segment_not_allowed` stays False and `overall_status` defaults to "allow" → auto-approved. Should instead fall back to wildcard policy (ask/deny).

**Bug 2 — generic "command matches allowed pattern" message**: When status=allow but `all_matched_patterns` is empty (because no segments were checked at all), the reason string falls through to `reason_str = "command matches allowed pattern"` — a generic message with no actual pattern shown. Misleading for auto-approved commands that never matched anything.

**Root cause**: `parse_segments()` only handles `CallExpr` nodes, not `DeclClause`. The empty-segment case needs a wildcard-policy fallback.

**Remaining issue (deferred)**: When `parse_segments()` returns empty, the reason shows `<empty command>` instead of the real command name (e.g. "bogus"). Fixing this requires extending `parse_segments()` to handle `DeclClause` nodes (export/alias/unset statements). Worth doing in a follow-up, lower priority.

## Files affected
- `src/lovely_bash_permissions/evaluate.py` (both fixes)
- `tests/test_evaluate.py` (new tests)

---

## Step 1: Fix empty-segment commands to use wildcard policy (evaluate.py)

**Status**: ✅ Implemented and committed.

**Goal**: When `parse_segments()` returns an empty list and allowed patterns exist, treat the command as non-matching → apply wildcard policy instead of auto-approving.

**Changes in `evaluate_bash_command()`**:
After extracting segments, add a guard:

```python
segments = parse_segments(command)

if not segments and allowed_patterns:
    # No command segments found (e.g. "export VAR=val cmd" parses as DeclClause)
    # Treat as non-matching; apply wildcard policy
    overall_status = config.get("*", "ask")
    non_matching = ["<empty command>"]
    reasons.append(f"{non_matching[0]} produced no parseable segments — defaulting to wildcard policy ({config.get('*', 'ask')}).")
    # Skip the segment loop entirely
else:
    # ... existing segment loop and rest of function
```

Note: move the "commands not matching allowed patterns" block (`if allowed_patterns and any_segment_not_allowed:`) **after** this guard, or merge its logic into the new empty-segment path.

**Tests to add (`tests/test_evaluate.py`):**
1. `test_empty_segments_with_allowed_patterns_asks` — `export BOGUS=true bogus` with allowed patterns → status=ask (not allow)
2. `test_empty_segments_wildcard_allow` — same command, wildcard=allow → status=allow (only when wildcard explicitly allows)
3. `test_empty_segments_wildcard_deny` — same command, wildcard=deny → status=deny
4. `test_empty_segments_no_patterns_allows` — no allowed patterns, empty segments → allow (existing behavior preserved)
5. `test_empty_segments_reason_message` — reason contains "wildcard policy" text

## Step 2: Fix generic "command matches allowed pattern" reason string (evaluate.py)

**Status**: ✅ Implemented and committed.

**Goal**: When status=allow and there are matched patterns, show them. When status=allow but no patterns matched (empty segments), show the wildcard-policy reason instead of generic message.

**Changes in `evaluate_bash_command()`** — fix the reason_str construction at end of function:

```python
# Replace the existing block:
if overall_status == "allow" and all_matched_patterns:
    noun = "pattern" if len(all_matched_patterns) == 1 else "patterns"
    approval_reason = f"command matches allowed {noun} {', '.join(all_matched_patterns)}"
    reasons.append(approval_reason)

if reasons:
    reason_str = "; ".join(r.rstrip(".!? ") for r in reasons)
    if len(reasons) == 1:
        reason_str += "."
elif all_matched_patterns:
    noun = "pattern" if len(all_matched_patterns) == 1 else "patterns"
    reason_str = f"command matches allowed {noun} {', '.join(all_matched_patterns)}"
else:
    reason_str = "command matches allowed pattern"  # BUG — generic, no patterns

# New logic:
if all_matched_patterns and overall_status == "allow":
    noun = "pattern" if len(all_matched_patterns) == 1 else "patterns"
    reason_str = f"command matches allowed {noun} {', '.join(all_matched_patterns)}"
if not reasons and overall_status == "allow":
    reason_str = f"allowed by wildcard policy ({config.get('*', 'ask')})"
if reasons:  # reason from segment checks takes priority over wildcard text
    reason_str = "; ".join(r.rstrip(".!? ") for r in reasons)
    if len(reasons) == 1:
        reason_str += "."
```

Actually, restructure more cleanly — the approval reason is now added in step 1's empty-segment path, and for matching commands it's added when patterns match. Consolidate:

```python
# Build reason_str from reasons list (populated by segment checks AND empty-segment path)
if overall_status == "allow" and all_matched_patterns:
    noun = "pattern" if len(all_matched_patterns) == 1 else "patterns"
    approval_reason = f"command matches allowed {noun} {', '.join(all_matched_patterns)}"
    reasons.append(approval_reason)

reason_str = "; ".join(r.rstrip(".!? ") for r in reasons) if reasons else "allowed by wildcard policy"
if len(reasons) == 1:
    reason_str += "."
```

**Tests to add (`tests/test_evaluate.py`):**
1. `test_allow_reason_shows_patterns` — matching command → reason contains actual pattern(s)
2. `test_empty_segment_reason_not_generic` — empty segments → reason NOT "command matches allowed pattern"
3. `test_empty_segment_reason_contains_wildcard_info` — reason mentions wildcard policy

## Step 3: Verify existing tests pass and add regression test for reported commands

**Status**: ✅ Implemented and committed. All 73 tests pass (including 10 new regression tests).

**Goal**: Confirm all existing tests still pass, and add a regression test covering the exact reported commands.

**Tests to add (`tests/test_evaluate.py`):**
1. `test_bogus_command_rejected` — `"bogus"` → ask (existing behavior, verify)
2. `test_export_bogus_rejected` — `"export BOGUS=true bogus"` → ask (regression for bug 1)
3. `test_export_bogus_reason_not_auto_approved` — reason should NOT contain "auto-approved" or "matches allowed pattern" (regression for bug 2)

Then run `uv run pytest -v` to confirm all tests pass.

---

## Order of execution
1. **Step 1** — empty-segment wildcard fallback (core fix) ✅
2. **Step 2** — reason string cleanup (dependent on step 1's reasons list) ✅
3. **Step 3** — verification + regression tests ✅ (all 640 tests pass)

## Deferred
- **Detect unhandled node types in `_extract_segments()`**: For every unsupported node type (DeclClause, CaseClause, etc.), instead of silently returning `[]`, detect the type and raise/log a warning like "Parser DeclClause handling is not implemented" — gives visibility into what's unsupported rather than silent fallback to wildcard policy. Implement in a follow-up.
- **`parse_segments()` coverage gaps**: Currently 0-segment (returns `[]`) for these node types:
  - **DeclClause**: `export/unset/alias` statements → shows `<empty command>`
  - **CaseClause**: `case x in a) cmd;; esac`
  - **ForClause / CStyleLoop**: `for i in ...; do ... done`, `{ cstyle loop }`
  - **Subshell**: `( ls )` — note: brace groups `{ ls; cd; }` DO work (2 segments)
  - **TestClause**: `[[ ... ]]` — note: `[ ]` works fine (1 segment)
  - **TimeClause**: `time sleep 1`
  - **ArithmCmd / LetClause**: `(())`, `let x=1`
  - **CoprocClause**: coprocess statements
  - Leading pipes `| ls` and semicolons `; cmd`
- **Impact**: these all fall through to wildcard policy (ask/deny) instead of being evaluated against allowed patterns. Fixing requires adding handler cases to `_extract_segments()` (segments.py) — lower priority, implement in a follow-up.

## Commit messages
- "Step 1: Empty-segment commands use wildcard policy instead of auto-approve"
- "Step 2: Fix generic 'command matches allowed pattern' reason string"
- "Step 3: Regression tests for reported empty-segment bugs"
