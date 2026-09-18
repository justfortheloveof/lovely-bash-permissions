# Implementation Plan: bug #7 fail-open + bug #2 empty-segment fail-open

> **Status: ✅ IMPLEMENTED** — all changes applied and verified
> (`ruff check` ✓ · `ruff format --check` ✓ · `mypy --strict` ✓ ·
> `pytest -m 'not linting'` → 1041 passed / 0 failed).
>
> One deviation from the test list below: "Subshell + allow-listed outer
> command" (`echo $(date)` + `allowed_cmds_regex: [r"^echo(\s+.*)?$"]`) does
> **not** allow — the *inner* `date` is not allow-listed, so the existing
> nested-validation pass asks. The regression test asserts that; a positive
> case requires listing both `echo` and `date` (verified → allow). This
> matches the "all checks always apply" principle.

## Principle

The wildcard (`*`) is the baseline for every command. A command may be
auto-approved **only** by:
- matching an entry in `allowed_cmds_regex`, **or**
- an explicit `"*": "allow"`.

Every other policy (`subshell`, `variable_assignment`, `output_redirection`,
`input_redirection`, `background_execution`, `blocked_paths_regex`) **adds
constraints only** — it can deny, ask, or approve its own specific construct,
but it never grants a blanket allow for commands that are otherwise not
approved. Blocked paths are always checked. Deny always wins, ask wins over
default allow; a command that is neither allow-listed nor explicitly
wildcard-`"allow"` resolves to the wildcard (`ask`/`deny`).

---

## Bugs being fixed

### Bug #7 — blocked-paths-only configs silently auto-allow everything

**Symptom:** `evaluate_bash_command("echo ${x%@/etc/*}", {"*": "ask",
"blocked_paths_regex": [r"/etc"]})` → `status: allow`, reason
`"allowed by wildcard policy (ask)"`.

**Root cause:** `evaluate.py:517-529` gates the wildcard override on
`and not blocked_patterns`; with `allowed_cmds_regex` empty, the segment loop
auto-allows every command (`else: segment_result["allowed"] = True`, line 398),
so a blocked-paths-only config under `"*": "ask"` approves everything not
blocked (e.g. `curl example.com` → allow).

### Bug #2 — empty-segment fail-open

**Symptom:** `evaluate_bash_command("[[ $(cat /etc/passwd) == x ]]",
{"*": "ask"})` → `status: allow`, reason
`"<empty command> produced no parseable segments — defaulting to wildcard
policy (allow)"`. Also with blocked paths present → `ask` (not `deny`): the
subshell/blocked-path scans are skipped by the early return.

**Root cause:** `evaluate.py:301-308` flips the empty-segment decision to
`allow` when both regex lists are empty, and returns before the
subshell/heredoc security passes run.

---

## Changes

### 1. `src/lovely_bash_permissions/evaluate.py` — ✅ done

**a. Per-command wildcard approval (kills the blanket allow).**

In the segment loop, replace the `else:` auto-allow:

```python
else:
    segment_result["allowed"] = True
```

with a wildcard-conditional default:

```python
else:
    # No allow-list configured. A command is approved only by an
    # explicit "*": "allow" wildcard; otherwise it is left to the
    # wildcard (ask/deny) below.
    if wildcard == "allow":
        segment_result["allowed"] = True
    else:
        segment_result["allowed"] = False
        any_segment_not_allowed = True
```

**b. Apply the wildcard to any not-allowed command, with or without a pattern
list.**

Change the aggregation gate at `evaluate.py:461`:

```python
if allowed_patterns and any_segment_not_allowed:
```

to:

```python
if any_segment_not_allowed:
```

and add a truthful reason variant for the no-pattern case (keep the existing
`"{name}" command does not match allowed patterns` text intact when
`allowed_patterns` is present):

```python
if allowed_patterns:
    ...existing "does not match allowed patterns" message...
else:
    if len(non_matching) == 1:
        reasons.append(f'"{non_matching[0]}" command is not allowlisted; wildcard policy is {wildcard}')
    else:
        names = ", ".join(f'"{n}"' for n in non_matching)
        reasons.append(f"{names} commands are not allowlisted; wildcard policy is {wildcard}")
```

**c. Remove the post-loop wildcard-override block (`evaluate.py:517-529`) and
its now-dead bookkeeping:**

- `_redir_matched`, `_input_matched`, `_bg_matched` (lines 513-515)
- `_va_applied` / `_va_segment_evaluated` (line 516, and the assignment at 318)
- `_subshell_allowed` (set at 510, previously read only by the guard)

After (a)+(b), any command that needs the wildcard is handled at aggregation,
so this block is unreachable; deleting it removes the escape hatches
(`not blocked_patterns`, `not _subshell_allowed`, `not _va_applied`) instead of
leaving them as landmines.

`_subshell_allowed` is set at `evaluate.py:510` and read **only** at line 522
(inside the removed guard) — so it becomes dead. Simplify the subshell-ask
branch (lines 505-510) to:

```python
if overall_status == "allow" and subshell_policy != "allow":
    overall_status = subshell_policy
    reasons.append("subshell or command substitution requires approval")
```

i.e. subshell `"allow"` adds no constraint (it never blanket-approves the
command); subshell `ask`/`deny` behave exactly as today.

**d. Empty-segment early return (`evaluate.py:301-308`) — bug #2.**

- Remove the default-allow flip:

```python
_wildcard = config.get("*", "ask")
if not allowed_patterns and not blocked_patterns:
    _wildcard = "allow"
```

so the empty-segment verdict is simply the wildcard (`ask` by default).

- Move the subshell/heredoc security passes *before* the empty-segment early
  return so `[[ $(cat /etc/passwd) == x ]]` is scanned for blocked paths and
  command substitution even when no segments are produced:
  - compute `has_subshell = _has_cmd_subst(raw_tree)` (already done at line
    295) and, if the segments list is empty, still run the
    `_extract_subshell_contents` blocked-path scan (and the heredoc-body
    scan) before returning.
  - reason text becomes truthful: `"<empty command> produced no parseable
    segments — defaulting to wildcard policy ({_wildcard})"` now carries the
    real wildcard (never fabricated `allow`).

**e. Truthful fallback reason (`evaluate.py:545-547`).**

```python
else:
    _wp = config.get("*", "ask")
    if _wp == "allow":
        reason_str = "allowed by wildcard policy (allow)"
    else:
        reason_str = "allowed"  # defensive; unreachable for a real wildcard-ask
```

**f. `variable_assignment: allow` reason.** In the va-allow branch
(`evaluate.py:362-366`), when it is the deciding policy (no `allowed_patterns`),
append `reasons.append(f"variable assignment allowed: {args}")` so the
standalone `FOO=bar` case no longer cites the wildcard.

### 2. `tests/config/test_evaluate.py` — ✅ done

Flip the two asserts that codified the deny-list footgun:
- `test_blocked_pattern_no_match` (line ~141): `ls /var/log` +
  `make_config(blocked=["/etc/passwd"])` → expect `"ask"` (was `"allow"`),
  update docstring.
- `test_multiple_commands_none_blocked` (line ~170): `ls && cat file.txt` +
  `make_config(blocked=["/etc/passwd"])` → expect `"ask"`, update docstring.

Add regression tests:
- Bug #7 repro: `echo ${x%@/etc/*}` with `{"*": "ask", "blocked_paths_regex":
  [r"/etc"]}` → `ask`.
- `curl example.com` with blocked-only + `"*": "ask"` → `ask`.
- `echo hi` with blocked-only + `"*": "ask"` → `ask`, reason contains
  the no-pattern message (not `allowed by wildcard policy`).
- Subshell does not blanket-approve: `echo $(date)` with
  `{"*": "ask", "subshell": "allow"}` → `ask` (echo not allow-listed).
- Subshell + allow-listed outer command: `echo $(date)` with
  `{"*": "ask", "subshell": "allow", "allowed_cmds_regex": [r"^echo(\s+.*)?$"]}`
  → `allow`.
- Va does not blanket-approve the command: `FOO=bar curl x` with
  `{"*": "ask", "variable_assignment": "allow"}` → `ask` (curl not
  allow-listed).
- Standalone va allow truthful reason: `FOO=bar` with
  `{"*": "ask", "variable_assignment": "allow"}` → `allow`, reason contains
  `variable assignment allowed` and not `wildcard policy (ask)`.
- Deny-list still works via explicit wildcard: `{"*": "allow",
  "blocked_paths_regex": [r"/etc"]}` → `echo hi` allow; `cat /etc/passwd`
  deny.
- Bug #2: `evaluate_bash_command("[[ $(cat /etc/passwd) == x ]]",
  {"*": "ask"})` → `ask` (not allow); with `{"*": "ask",
  "blocked_paths_regex": [r"/etc"]}` → `deny` (blocked-path scan runs before
  the empty-segment return).
- Whist with wildcard `"allow"` and no patterns: `ls` → `allow`, reason
  `allowed by wildcard policy (allow)`.

### 3. `NEW_BUGS.md` — ✅ done

Mark bugs #2 and #7 as fixed (`Status: ✅ FIXED`), each with a one-paragraph
note: #7 was a status fail-open (reason string was the symptom); #2's fix
stops the empty-segment default-allow and runs the subshell/blocked-path
scans before the early return.

### 4. `PLAN.md` — ✅ done

This file — mark items done as they complete.

---

## Verification

1. `uv run ruff check .`
2. `uv run ruff format --check .`
3. `uv run mypy --strict .`
4. Full suite: `uv run pytest -m 'not linting' -q`
   - Expect all green except any test that intentionally codified the old
     auto-allow; those are updated in-place (they are behavior changes, not
     regressions).
5. Manual repros from the Bugs sections above confirm: blocked-only+ask now
   asks; `[[ $(cat /etc/passwd) == x ]]` under `{"*":"ask"}` now asks and
   under blocked-paths denies.

## Edge cases to keep intact

- Hook `:` label segments stay exempt (inert wrapper) — payload commands after
  `;` are still evaluated normally.
- Redirection/background per-kind `"allow"` still produces its own truthful
  reasons (they were already appended when matched and overall was `allow`).
- Subshell `ask`/`deny` behavior unchanged (`echo $(cat x)` default → ask;
  subshell deny → deny).
- Explicit `"*": "deny"` with no patterns denies non-blocked commands at
  aggregation (reason: `... is not allowlisted; wildcard policy is deny`).