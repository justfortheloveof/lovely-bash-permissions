# Implementation Plan: bugs #4 + #7 + #8 + #9 + #10 (verify #5 + #6)

> **Status: 🔧 IN PROGRESS — not yet implemented.**
>
> **For the implementing agent:** every step is self-contained and small. Do ONE
> step per iteration. Locate edit sites by the exact **"Find" code blocks** (line
> numbers are approximate pre-edit references and drift between steps — never
> trust line numbers, trust the code text). Do not modify anything outside the
> files listed for the step. All probes/verification must be run from the repo
> root with `uv run ...` (the package is NOT pip-installed; a bare
> `python -c "import lovely_bash_permissions"` fails).

> **Orchestrator notes (carried over / pre-existing):**
>
> - **Commit hygiene (hard rule): NEVER commit `.fuzz/` or anything inside it**
>   (untracked fuzz artifacts). When committing a step, stage ONLY the files
>   listed for that step (e.g. `git add src/lovely_bash_permissions/rules.py
>   PLAN.md`) — never `git add -A` / `git add .`. `.fuzz/` is added to
>   `.gitignore` in Step 0b. Other untracked noise (`.coverage`, etc.) must
>   also never be committed.
> - Probe snippets below are written as `uv run python -c "..."` with `\$`
>   escapes for illustration. Wherever a probe contains `$`, a quoted heredoc
>   (`uv run python <<'EOF'`) is safer — create probe files via a
>   single-quoted heredoc so the shell does not touch anything, and keep the
>   plain `$`.
> - `uv run ruff format --check .` fails **only** on PLAN.md itself (markdown
>   code fences) — this predates all steps. Every step's format check should be
>   interpreted as "all real source/test files clean; PLAN.md may remain
>   flagged."
> - `uv run ruff check .`, `uv run mypy --strict .`, and
>   `uv run pytest -m 'not linting' -q` are green at the plan's base commit
>   (`bba7849`).

## Bugs being fixed

### Bug #4 — 🟠 deeply nested `$( ... )` crashes the converter with `RecursionError`

`converter.py` recurses `node_from_json → _convert_call_expr → _convert_word →
_convert_part → _convert_cmd_subst → _convert_stmt → node_from_json`. Measured
(valid bash, shfmt parses fine): OK at 164 nested levels, `RecursionError` at
165 under the default interpreter limit. `parse_ast`, `parse_segments` and
`evaluate_bash_command` all blow up; `lovely-bash-inspection --string` dies with
a raw traceback, exit 1.

### Bug #7 — 🔴 `$( ... )` inside a standalone `(( ... ))` bypasses the `subshell` policy

`segments.py` `ArithmCmd` handler emits no segments, so
`(( x[$(rm -rf /etc/x)] ))` takes the empty-segment fallback in `evaluate.py`,
which only runs blocked-path/heredoc scans and then defaults to the wildcard.
`has_subshell` is already computed correctly but never consulted. Measured:
`{"*": "allow"}` and `{"*": "allow", "subshell": "deny"}` both → **allow**
(bypass). Combined with a real command (`ls; (( x[$(rm)] ))`) the segments
exist and the subshell pass fires correctly — only **zero-segment** commands
(standalone arithmetic, incl. `time (( ... ))`) hit the gap.

### Bug #8 — 🟡 `$( ... )` in a `case` word or branch pattern is not a segment

`segments.py` `CaseClause` handler recurses only into branch *bodies*.
`case $(evil) in a) echo 1;; esac` → `['echo']` (misses `evil`);
`case $x in $(evil)) echo hit;; esac` → `['echo']` (misses pattern).
Accuracy class like #5 (the subshell pass still denies under `subshell: deny`).

### Bug #9 — 🟠 `RecursionError` crash surface is wider: nested `if`, `&&`/`||` chains, nested `while`

Same root cause as #4. Thresholds: `if` 246/247; `&&`/`||` chain 329/330;
`while` 328/329; `;`/pipes/`{ }` fine to thousands. A ~400-command
`a && a && …` script (or ~250 nested ifs) crosses the threshold — no exotic
nesting required. Impact on the *evaluation* path: in hook mode under
`{"*": "allow"}` without an explicit `error` key, an over-threshold command is
**silently auto-allowed with no analysis** (`hook._error_action` maps the crash
to `config.get("error") or config.get("*")`), which makes #9 a security
concern, not just a crash.

### Bug #10 — ⚪ compound-command redirections are attributed to every inner segment

`IfClause`/`WhileClause`/`ElifBranch` handlers pass the *inherited* statement
redirections into every contained stmt. `while :; do echo a; done < /etc/shadow`
→ reason `"input redirection allowed from /etc/shadow, /etc/shadow"`. Applies to
while, until, if, `{ }`. Over-attribution only (no bypass); user-visible impact
is duplicated/misattributed reason text and doubled per-command checks.

### Bugs #5 + #6 — already fixed, verify only

`for`-loop lists / test left-operands (`['seq','echo']`, `['pwd','echo']`) and
`$( ... )` test right-operands (`['cmd']`, no more `$(...)` pseudo-segment) were
implemented and verified in prior commits. Step 0 re-confirms; no code changes.

---

## Execution order & dependency notes

Step 0b is a one-line repo-hygiene change; Steps 1 → 2 → 3 → 4 are code
changes; 5–6 add tests; 7 is final verification.
Each step's acceptance probe stands on its own.

**Test-insertion rule (Steps 5–6):** all new test code is *appended at the
end of its file* as a new class — no reflowing or interleaving of existing
tests. Existing imports cover everything needed (verified at plan time);
do not add imports unless a probe proves one is missing.

**Expected-red window: none known.** Audited the existing suite: every current
empty-segment test in `tests/config/test_evaluate.py` is either `[[ -f x ]]`
(no subshell — Step 2 leaves it on the wildcard path unchanged) or a C-style
`for (( ... ))` (produces segments — never enters the empty-segment block).
No `case` tests exist in `tests/parsing/test_segments.py`. No test asserts
duplicated redirection reasons. **If any existing test does turn red after a
step, STOP and report — do not "fix" the test.**

Note: Step 1 touches `sys.setrecursionlimit` (process-global, raised
monotonically, never lowered). Under `pytest -n auto` each worker is its own
process; the elevated limit only ever applies to a worker that parsed a deep
command. The recursive *consumer* passes (`_extract_segments`, inspection CLI
render) run after `node_from_json` in the same process and rely on the limit
staying raised — do not restore/lower it after conversion.

---

## Step 0 — verify bugs #5 + #6 are already fixed (no code changes)

**Status: done pre-plan** (confirmed by probes in the investigation).

**Changes:** none.

**Acceptance (all must hold, run from repo root):**

```bash
uv run python <<'EOF'
from lovely_bash_permissions.segments import parse_segments

def cmds(c):
    return [s["command"] for s in parse_segments(c)]

assert cmds("for i in $(seq 3); do echo $i; done") == ["seq", "echo"]
assert cmds("if [[ $(pwd) == /root* ]]; then echo root; fi") == ["pwd", "echo"]
assert cmds("[[ x == $(cmd) ]]") == ["cmd"]
assert cmds("[[ -f x && $(c2) ]] && echo and") == ["c2", "echo"]
print("ok")
EOF
```

---

## Step 0b — repo hygiene: never commit `.fuzz/` (one-line change)

**Status: done** (committed `0774495`; both acceptance checks verified)

**File:** `.gitignore` (only file touched)

**Why:** `.fuzz/` is currently untracked (`git status` shows `?? .fuzz/`) and
holds fuzz artifacts that must never be committed (user requirement).

**Change:** append the line `.fuzz/` at the end of `.gitignore`.

Find (tail of the file):

```
dist/
build/
venv/
```

Replace with:

```
dist/
build/
venv/
.fuzz/
```

**Acceptance:**

1. `git status --short` no longer shows `?? .fuzz/`.
2. `git check-ignore -v .fuzz/` prints the `.gitignore` rule.

---

## Step 1 — `converter.py`: recursion headroom + fail-closed `ParseError` guard (bugs #4 + #9)

**Status: done** — all acceptance checks pass except probe 4's last assertion, which is
blocked by a **pre-existing** segments.py limitation (verified at depth 2 on unmodified
HEAD `bba7849`: `parse_segments("echo $($(true))") == ['echo', '$(...)']`). The CallExpr
handler extracts `node.args[0]` as the command word and recurses only into `args[1:]`,
so a command substitution used *as the command word* yields a phantom `$(...)` segment
instead of descending to `true`. Accuracy-class (like #8), NOT a bypass: the subshell
pass still gates it. Fixing it is outside Step 1's converter-only scope — logged as a
known limitation; probe 4's assertion is to be read as "no crash / conversion succeeds".
Two byte-level deviations from the plan block, both ruff-mandated: `max_depth =
max(max_depth, depth)` (PLR1730) and the `raise ParseError(...) from exc` collapsed to
one line (format). ruff/ruff-format/mypy clean; 1060 tests green.

**File:** `src/lovely_bash_permissions/converter.py` (only file touched)

**Why:** the converter recurses roughly linearly in the shfmt JSON container
depth. Measuring the *maximum JSON container nesting* iteratively (no recursion,
so it cannot itself blow up) lets us size `sys.setrecursionlimit` to the input
*before* any conversion recursion happens. The report explicitly sanctions
"bump `sys.setrecursionlimit` relative to input depth".

Frame budget measured against the live converter (default limit 1000):

- `$( ... )` nesting crashes at depth ~165 (≈ 6 stack frames/level; JSON
  container depth ≈ 6× level) → ≈ 1 stack frame per JSON container level.
- `if`/`&&`/`while` are cheaper per level (crash 247/330/329).

Using `_FRAMES_PER_JSON_LEVEL = 2` gives a 2× safety margin on the worst shape;
`_MIN_RECURSION_LIMIT = 2000` is the floor (harmless; only ever raised);
`_MAX_RECURSION_LIMIT = 20000` caps support at roughly 1000+ `$( )` levels,
2400+ nested ifs, or 5000+ `&&`-chained commands — an order of magnitude above
every measured crash threshold while keeping the C-stack profile conservative.
Inputs beyond the cap (or where a `RecursionError` still escapes) become a
`ParseError` — the fail-closed path callers already route to the `error` policy
(`cli.py` prints the message and returns 3; `hook._error_action` maps it).

Because the limit is raised inside `node_from_json` at the **top-level** call
(depth counter == 0), it covers all three entry points uniformly: `parse_ast`,
`parse_segments`, and any direct `node_from_json` caller — and the elevated
limit then stays in force for the recursive `_extract_segments` / CLI-render
phases that run afterwards in the same process.

**Change 1 — add the `sys` import.**

Find:

```python
from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable
from typing import Any
```

Replace with:

```python
from __future__ import annotations

import contextlib
import logging
import sys
from collections.abc import Callable
from typing import Any
```

**Change 2 — replace `node_from_json` (module-level constants, an iterative
depth helper, and the guarded body).**

Find (the whole current function):

```python
def node_from_json(data: dict[str, Any] | None) -> Node | None:
    """Convert shfmt JSON node data to a typed AST node.

    Returns None when *data* is None (key absent in JSON).

    Uses the ``_CONVERTERS`` dispatch table to map shfmt's ``Type`` field
    to a converter function.
    """
    if data is None:
        return None

    node_type = data.get("Type", "")

    # Handle nodes that have 'Cmd' but no 'Type' (wrapped statements)
    if not node_type and "Cmd" in data:
        return node_from_json(data["Cmd"])

    converter = _CONVERTERS.get(node_type)
    if converter is not None:
        return converter(data)

    # Unknown type — wrap in a generic Node
    pos, end = _parse_pos_end(data)
    return Node(type=node_type, pos=pos, end=end)
```

Replace with:

```python
# degenerate commands (deeply nested $()/if/&&-chains/while) exceed
# the interpreter's default recursion limit and crash with a raw traceback.
# The top-level node_from_json call measures the maximum JSON container nesting
# iteratively and raises sys.setrecursionlimit to cover it; inputs nested beyond
# a safe cap (or a RecursionError that still escapes) fail closed with a
# ParseError, which callers route to the configured `error` policy.
_MIN_RECURSION_LIMIT = 2000
_FRAMES_PER_JSON_LEVEL = 2
_MAX_RECURSION_LIMIT = 20000
_json_conversion_depth = 0


def _measure_nesting_depth(top: dict[str, Any] | list[Any]) -> int:
    """Measure the maximum container nesting depth of a JSON tree, iteratively."""
    max_depth = 0
    stack: list[tuple[dict[str, Any] | list[Any], int]] = [(top, 1)]
    while stack:
        obj, depth = stack.pop()
        if depth > max_depth:
            max_depth = depth
        if isinstance(obj, dict):
            for value in obj.values():
                if isinstance(value, (dict, list)):
                    stack.append((value, depth + 1))
        else:
            for item in obj:
                if isinstance(item, (dict, list)):
                    stack.append((item, depth + 1))
    return max_depth


def node_from_json(data: dict[str, Any] | None) -> Node | None:
    """Convert shfmt JSON node data to a typed AST node.

    Returns None when *data* is None (key absent in JSON).

    Uses the ``_CONVERTERS`` dispatch table to map shfmt's ``Type`` field
    to a converter function.
    """
    if data is None:
        return None

    global _json_conversion_depth
    if _json_conversion_depth == 0:
        depth = _measure_nesting_depth(data)
        needed = _MIN_RECURSION_LIMIT + _FRAMES_PER_JSON_LEVEL * depth
        if needed > _MAX_RECURSION_LIMIT:
            from .parser import ParseError

            raise ParseError(
                f"command structure is nested too deeply to analyze safely "
                f"(nesting depth {depth} exceeds the safe limit)"
            )
        if needed > sys.getrecursionlimit():
            sys.setrecursionlimit(needed)

    _json_conversion_depth += 1
    try:
        node_type = data.get("Type", "")

        # Handle nodes that have 'Cmd' but no 'Type' (wrapped statements)
        if not node_type and "Cmd" in data:
            return node_from_json(data["Cmd"])

        converter = _CONVERTERS.get(node_type)
        if converter is not None:
            return converter(data)

        # Unknown type — wrap in a generic Node
        pos, end = _parse_pos_end(data)
        return Node(type=node_type, pos=pos, end=end)
    except RecursionError as exc:
        from .parser import ParseError

        raise ParseError(
            "command structure is nested too deeply to analyze safely"
        ) from exc
    finally:
        _json_conversion_depth -= 1
```

Notes:

- We only ever raise the limit (`needed > sys.getrecursionlimit()`) and never
  restore it. This is deliberate: `_extract_segments` and the inspection CLI
  render recurse on the same deep tree immediately afterwards and rely on the
  limit staying raised.
- `ParseError` is imported locally to avoid a module cycle (converter already
  imports `.parser` locally in `parse_ast`).
- Over-the-cap input is rejected with a *clean* error before any conversion —
  no traceback, no process crash, exit code 3 from the CLI.

**Acceptance (all must hold):**

1. `uv run ruff check .` and `uv run ruff format --check .` (ignore PLAN.md
   itself) — clean. `uv run mypy --strict src/lovely_bash_permissions` — clean.
2. Deep-shape probes (quoted heredoc; previously each crashed):

```bash
uv run python <<'EOF'
from lovely_bash_permissions.converter import parse_ast
from lovely_bash_permissions.segments import parse_segments

deep = "echo " + "$(" * 200 + "true" + ")" * 200
ast = parse_ast(deep)
segs = parse_segments(deep)
assert segs[-1]["command"] == "true", [s["command"] for s in segs]

parse_ast("if :; then " * 300 + "true" + "; fi" * 300)
chain = " && ".join(["a"] * 400)
assert len(parse_segments(chain)) == 400
parse_ast("while :; do " * 400 + "true" + "; done" * 400)
print("ok")
EOF
```

1. Over-the-cap guard (fail closed, no RecursionError):

```bash
uv run python <<'EOF'
import lovely_bash_permissions.converter as conv
from lovely_bash_permissions.errors import LovelyDevinPermissionsError

old = conv._MAX_RECURSION_LIMIT
conv._MAX_RECURSION_LIMIT = 2000
try:
    from lovely_bash_permissions.converter import parse_ast
    try:
        parse_ast("echo " + "$(" * 400 + "true" + ")" * 400)
        raise SystemExit("expected ParseError")
    except LovelyDevinPermissionsError:
        pass
finally:
    conv._MAX_RECURSION_LIMIT = old
print("ok")
EOF
```

1. CLI no-crash fix (must exit 0, render normally — no traceback):

```bash
cmd=$(python -c "print('echo ' + '\$('*180 + 'true' + ')'*180)")
uv run lovely-bash-inspection --string "$cmd"; echo "exit=$?"
#   before: raw traceback, exit 1
#   after:  renders the inspection tree, exit 0
```

---

## Step 2 — `evaluate.py`: apply the resolved `subshell` policy in the empty-segment fallback (bug #7)

**Status: done** (full matrix + time/ls/+=/literal variants verified; `[[ -f x ]]` wildcard path unchanged; linters clean; 1060 tests green)

**File:** `src/lovely_bash_permissions/evaluate.py` (only file touched)

**Why:** the `if not segments:` block (line ~304) computes `has_subshell`
correctly but never consults the `subshell` policy. Per the report's fix:
deny → deny / ask → ask, applied *before* the wildcard default; only an
explicit `"allow"` falls through to the wildcard. The blocked-paths and heredoc
scans (already above this point) stay untouched.

**Policy resolution (important — the report is internally inconsistent here):**
`evaluate_bash_command` already computes `rules["subshell"]` via
`_resolve_level(config, "subshell")` (line ~284), which *inherits the wildcard*
when `subshell` is unset. Two consequences, resolved as follows:

- `{"*": "allow"}` with unset `subshell` → resolved "allow". The report's *matrix*
  requires **ask** for this row (fail-closed for an unanalyzable, zero-segment
  command), while its *fix text* ("apply the resolved subshell policy") would
  give allow. **Follow the matrix**: an *inherited* allow (unset subshell under
  a permissive wildcard) is downgraded to **ask** for this gate. Explicit
  `subshell: "allow"` still falls through to the wildcard.
- `{"*": "deny"}` with unset `subshell` → resolved "deny" (inherited). Keep the
  resolved deny — do **not** use a literal `config.get("subshell", "ask")`
  here, or a deny-everything config would downgrade to ask.

**Change:** replace the empty-segment tail.

Find:

```python
        if _empty_reasons:
            _empty_reason = "; ".join(dict.fromkeys(_empty_reasons))
        else:
            _empty_status = _wildcard
            _empty_reason = (
                f"<empty command> produced no parseable segments — defaulting to wildcard policy ({_wildcard})"
            )
        return {"status": _empty_status, "reason": _empty_reason, "segments": []}
```

Replace with:

```python
        if _empty_reasons:
            _empty_status = "deny"
            _empty_reason = "; ".join(dict.fromkeys(_empty_reasons))
        elif has_subshell:
            # standalone arithmetic like `(( x[$(rm -rf /etc/x)] ))`
            # produces no segments, so the fallback auto-approved it under
            # "*": "allow" even when subshell policy is "deny". Gate it by the
            # resolved subshell policy; only an explicit "allow" falls through
            # to the wildcard default. An *inherited* allow (unset subshell
            # under a permissive wildcard) becomes ask: the command produced no
            # segments, so we cannot analyse what runs — default fail-closed.
            _sub_policy = rules["subshell"]
            if _sub_policy == "allow" and "subshell" not in config:
                _sub_policy = "ask"
            if _sub_policy == "allow":
                _empty_status = _wildcard
                _empty_reason = (
                    f"<empty command> produced no parseable segments — defaulting to wildcard policy ({_wildcard})"
                )
            else:
                _empty_status = _sub_policy
                _empty_reason = "subshell or command substitution requires approval"
        else:
            _empty_status = _wildcard
            _empty_reason = (
                f"<empty command> produced no parseable segments — defaulting to wildcard policy ({_wildcard})"
            )
        return {"status": _empty_status, "reason": _empty_reason, "segments": []}
```

Notes:

- `_sub_policy` is `ask` or `deny` at the `else`; assigning it directly to
  `_empty_status` is safe.
- `"subshell or command substitution requires approval"` matches the reason
  already used by the per-segment subshell pass (asserted at
  `tests/config/test_evaluate.py` line ~631).
- `rules["subshell"]` is defined before the empty-segment block (line ~284); no
  new locals to declare.
- Post-fix behavior for the report's matrix (`(( x[$(rm -rf /etc/x)] ))`):

| config (`*` / `subshell`) | before | after |
| --- | --- | --- |
| allow / deny | allow ❌ | **deny** |
| allow / ask | allow ❌ | **ask** |
| allow / (unset) | allow ❌ | **ask** (matrix row; explicit-override rule above) |
| ask / deny | ask "for the wrong reason" | **deny** (subshell wins over wildcard, consistent with `test_explicit_option_overrides_wildcard`) |
| deny / allow | deny | deny (unchanged) |
| deny / (unset) | deny | **deny** (no downgrade — resolved deny kept) |

  Note the discrepancy: the matrix's "expected" column for `ask / deny` says
  *ask*, but per the report's own Fix (deny → deny) `subshell: deny` is more
  restrictive than `*: ask` and must deny. This plan follows the Fix text for
  that row; the matrix for the `allow / (unset)` row. Both divergences are
  called out here so the reviewer can weigh in.

- Explicit `subshell: "allow"` under any wildcard still falls through to the
  wildcard (inheritance preserved for commands that *do* resolve to segments —
  `test_subshell_inherits_wildcard_allow` is unaffected either way).

**Acceptance (all must hold):**

```bash
uv run python <<'EOF'
from lovely_bash_permissions.evaluate import evaluate_bash_command

def s(config):
    return evaluate_bash_command("(( x[$(rm -rf /etc/x)] ))", config)["status"]

assert s({"*": "allow", "subshell": "deny"}) == "deny"
assert s({"*": "allow"}) == "ask"
assert s({"*": "allow", "subshell": "ask"}) == "ask"
assert s({"*": "allow", "subshell": "allow"}) == "allow"
assert s({"*": "ask", "subshell": "deny"}) == "deny"
assert s({"*": "deny", "subshell": "allow"}) == "deny"
assert s({"*": "deny"}) == "deny"
assert evaluate_bash_command("time (( x[$(rm z)] ))", {"*": "allow", "subshell": "deny"})["status"] == "deny"
assert evaluate_bash_command("ls; (( x[$(rm)] ))", {"*": "allow", "subshell": "deny"})["status"] == "deny"
assert evaluate_bash_command("(( y += $(rm z) ))", {"*": "allow", "subshell": "deny"})["status"] == "deny"
assert evaluate_bash_command("(( x = 5 ))", {"*": "allow", "subshell": "deny"})["status"] == "allow"
print("ok")
EOF
```

1. Also confirm `[[ -f x ]]` under `{"*": "ask"}` still reports
   `"wildcard policy (ask)"` in the reason (unchanged path).

---

## Step 3 — `segments.py`: recurse the `case` subject word and branch patterns (bug #8)

**Status: done** — all bug-related probes pass. Note: the plan's original expected value
`["a","b","c"]` for `case $(a) in $(b)) echo c;; esac` was a typo in this plan; the
correct expectation is `["a","b","echo"]` (the body command is `echo`, segment
commands are the command names). Plan corrected. Linters clean; 1060 tests green.

**File:** `src/lovely_bash_permissions/segments.py` (only file touched)

**Why:** the `CaseClause` handler extracts only branch bodies. The subject word
(`node.expr`, the typed-AST name for the report's `node.word`) and each branch's
`patterns` (list of `Word`) must be walked so nested `$( ... )` surface as
segments — the same pattern as the `ForClause` handler's `words` recursion.

**Change:** replace the `CaseClause` branch of `_extract_segments`.

Find:

```python
    elif isinstance(node, CaseClause):
        # case/switch: extract commands from each branch body
        if hasattr(node, "branches") and node.branches:
            for branch in node.branches:
                if hasattr(branch, "body") and branch.body:
                    for stmt in branch.body:
                        segments.extend(_extract_segments(stmt, redirs))
```

Replace with:

```python
    elif isinstance(node, CaseClause):
        # case/switch: the subject word (node.expr) and each branch's match
        # patterns can embed command substitutions that bash evaluates before
        # the body runs — surface them alongside the branch bodies (bug #8).
        if getattr(node, "expr", None) is not None:
            segments.extend(_extract_segments(node.expr, redirs))
        if hasattr(node, "branches") and node.branches:
            for branch in node.branches:
                if hasattr(branch, "patterns") and branch.patterns:
                    for pattern in branch.patterns:
                        segments.extend(_extract_segments(pattern, redirs))
                if hasattr(branch, "body") and branch.body:
                    for stmt in branch.body:
                        segments.extend(_extract_segments(stmt, redirs))
```

**Acceptance (all must hold):**

```bash
uv run python <<'EOF'
from lovely_bash_permissions.segments import parse_segments

def cmds(c):
    return [s["command"] for s in parse_segments(c)]

assert cmds("case $(evil) in a) echo 1;; esac") == ["evil", "echo"]
assert cmds("case $x in $(evil)) echo hit;; esac") == ["evil", "echo"]
assert cmds("select x in $(evil); do echo $x; done") == ["evil", "echo"]
assert cmds("case $x in a) echo 1;; esac") == ["echo"]  # unchanged
assert cmds("case $(a) in $(b)) echo c;; esac") == ["a", "b", "echo"]
print("ok")
EOF
```

1. `uv run ruff check .` / `uv run ruff format --check .` (source files only)
   and `uv run mypy --strict src/lovely_bash_permissions` — clean.
2. `uv run pytest -m 'not linting' -q` — all green (no existing `case` tests;
   expected-red window: none).

---

## Step 4 — `rules.py`: dedupe compound-command redirections in segment checks (bug #10)

**Status: done** — see the plan-correction note at the end of this section (the `N`-is-a-dict
fix). All probes pass; linters clean; 1060 tests green (including the ~125 that the broken
verbatim block had crashed).

**File:** `src/lovely_bash_permissions/rules.py` (only file touched)

**Why:** compound-command redirections are attributed to every inner segment,
so `while :; do echo a; done < /etc/shadow` yields two identical
`< /etc/shadow` entries → reason `"input redirection allowed from
/etc/shadow, /etc/shadow"`. Dedupe by (op, fd, target) at collection time;
distinct redirections (different fds/targets/ops) are preserved, so no check is
ever lost.

**Change 1 — output redirections.** In `_check_segments_output_redirs`, replace
the collection loop.

Find:

```python
    redirections: list[dict[str, Any]] = []
    for seg in segments:
        for r in seg.get("redirections", []):
            if r.get("Op") in WRITE_REDIRECT_OPS:
                redirections.append(r)

    if not redirections:
        return {"status": "allow", "matched": False, "reason": "no output redirection"}
```

Replace with:

```python
    # compound-command redirections (while/until/if/{ } group) are
    # attributed to every inner segment — the same redirection appears once per
    # segment. Dedupe by (op, fd, target); distinct descriptors are preserved.
    redirections: list[dict[str, Any]] = []
    seen_output: set[tuple[str, str, str]] = set()
    for seg in segments:
        for r in seg.get("redirections", []):
            if r.get("Op") in WRITE_REDIRECT_OPS:
                word = r.get("Word", {})
                parts = word.get("Parts", [])
                target = parts[0].get("Value", "") if parts else ""
                # segment redirection dicts serialize the fd as a dict
                # ({} when absent, {"Value": "2"} for `2>`) — extract the scalar
                # fd so the dedupe key is hashable.
                n = r.get("N")
                fd = (
                    n.get("Value", "") if isinstance(n, dict) else ("" if n is None else str(n))
                )
                key = (r.get("Op", ""), fd, target)
                if key not in seen_output:
                    seen_output.add(key)
                    redirections.append(r)

    if not redirections:
        return {"status": "allow", "matched": False, "reason": "no output redirection"}
```

**Change 2 — input redirections.** In `_check_segments_input_redirs`, replace
the collection loop.

Find:

```python
    input_redirs: list[dict[str, Any]] = []
    for seg in segments:
        for r in seg.get("redirections", []):
            if r.get("Op") in ("<", "<<", "<<<", "<&"):
                word = r.get("Word", {})
                target = ""
                parts = word.get("Parts", [])
                if parts:
                    target = parts[0].get("Value", "")
                input_redirs.append({"op": r["Op"], "target": target})
```

Replace with:

```python
    # dedupe by (op, target) — compound-command redirections are
    # attributed to every inner segment.
    input_redirs: list[dict[str, Any]] = []
    seen_input: set[tuple[str, str]] = set()
    for seg in segments:
        for r in seg.get("redirections", []):
            if r.get("Op") in ("<", "<<", "<<<", "<&"):
                word = r.get("Word", {})
                target = ""
                parts = word.get("Parts", [])
                if parts:
                    target = parts[0].get("Value", "")
                key = (r["Op"], target)
                if key not in seen_input:
                    seen_input.add(key)
                    input_redirs.append({"op": r["Op"], "target": target})
```

**Acceptance (all must hold):**

```bash
uv run python <<'EOF'
from lovely_bash_permissions.evaluate import evaluate_bash_command

r = evaluate_bash_command("while :; do echo a; done < /etc/shadow", {"*": "allow", "input_redirection": "allow"})
assert r["status"] == "allow", r
assert "/etc/shadow" in r["reason"]
assert r["reason"].count("/etc/shadow") == 1, r["reason"]

r = evaluate_bash_command("until :; do echo a; done > /tmp/out", {"*": "allow", "output_redirection": "allow"})
assert r["reason"].count("/tmp/out") == 1, r["reason"]

r = evaluate_bash_command("if :; then echo a; fi < /etc/shadow > /tmp/out", {"*": "allow", "input_redirection": "allow", "output_redirection": "allow"})
assert r["reason"].count("/etc/shadow") == 1 and r["reason"].count("/tmp/out") == 1, r["reason"]
print("ok")
EOF
```

1. `uv run ruff check .` / `uv run ruff format --check .` and
   `uv run mypy --strict src/lovely_bash_permissions` — clean.
2. `uv run pytest -m 'not linting' -q` — all green (no test asserts duplicated
   redirection reasons).

**Plan correction (found during Step 4 implementation):** the original Change-1 block keyed
the dedupe set on `r.get("N")` directly, but segment redirection dicts serialize the fd as a
*dict* (`{}` when absent, `{"Value": "2"}` for `2>`, see `_redir_dicts` in segments.py),
which is unhashable — verbatim application crashed ~125 existing tests with `TypeError` at
the set lookup. Fix: extract the scalar fd first (applied; in the committed code the fd
expression sits on one line to satisfy `ruff format` at line-length 120):

---

## Step 5 — `tests/config/test_evaluate.py`: regressions for bugs #7 + #10

**Status: pending** (after Steps 2 and 4)

**File:** `tests/config/test_evaluate.py` (only file touched)

Two insertions, both exact:

1. **Bug #7 matrix** — append the `TestEmptySegmentSubshellPolicy` class
   (below) at the **end of the file**. It uses plain dicts for the config
   argument (explicit-key scenarios), not `make_config`.
2. **Bug #10 dedup test** — add the `test_compound_input_redirection_not_duplicated`
   method (below) to the **existing** `TestCompoundCommandRedirections` class.
   Locate it with:
   `rg -n "class TestCompoundCommandRedirections" tests/config/test_evaluate.py`
   and insert the method as the **first method inside that class** (right
   after the class line / its docstring), so it stays indented 4 spaces as a
   method. Do not touch any other test.

No new imports are needed (`evaluate_bash_command` is already imported at the
top of the file).

Tests to add:

```python
class TestEmptySegmentSubshellPolicy:
    """standalone (( ... $(...) )) is gated by the subshell policy."""

    CMD = "(( x[$(rm -rf /etc/x)] ))"

    def test_allow_wildcard_deny_subshell(self) -> None:
        assert evaluate_bash_command(self.CMD, {"*": "allow", "subshell": "deny"})["status"] == "deny"

    def test_allow_wildcard_default_subshell_asks(self) -> None:
        assert evaluate_bash_command(self.CMD, {"*": "allow"})["status"] == "ask"

    def test_allow_wildcard_explicit_ask(self) -> None:
        assert evaluate_bash_command(self.CMD, {"*": "allow", "subshell": "ask"})["status"] == "ask"

    def test_allow_wildcard_explicit_subshell_allow(self) -> None:
        assert evaluate_bash_command(self.CMD, {"*": "allow", "subshell": "allow"})["status"] == "allow"

    def test_ask_wildcard_deny_subshell(self) -> None:
        assert evaluate_bash_command(self.CMD, {"*": "ask", "subshell": "deny"})["status"] == "deny"

    def test_deny_wildcard_allow_subshell(self) -> None:
        assert evaluate_bash_command(self.CMD, {"*": "deny", "subshell": "allow"})["status"] == "deny"

    def test_deny_wildcard_unset_subshell(self) -> None:
        """No downgrade: an inherited deny (unset subshell) still denies."""
        assert evaluate_bash_command(self.CMD, {"*": "deny"})["status"] == "deny"

    def test_time_wrapped_arithmetic(self) -> None:
        assert evaluate_bash_command(
            "time (( x[$(rm z)] ))", {"*": "allow", "subshell": "deny"}
        )["status"] == "deny"

    def test_followed_by_real_command(self) -> None:
        assert evaluate_bash_command(
            "ls; (( x[$(rm)] ))", {"*": "allow", "subshell": "deny"}
        )["status"] == "deny"

    def test_plus_equals_variant(self) -> None:
        assert evaluate_bash_command(
            "(( y += $(rm z) ))", {"*": "allow", "subshell": "deny"}
        )["status"] == "deny"

    def test_literal_arithmetic_unaffected(self) -> None:
        assert evaluate_bash_command(
            "(( x = 5 ))", {"*": "allow", "subshell": "deny"}
        )["status"] == "allow"
```

And the bug #10 test (goes inside `TestCompoundCommandRedirections`, indented
as a method):

```python
    def test_compound_input_redirection_not_duplicated(self) -> None:
        """< file on a while loop is attributed once, not per segment."""
        result = evaluate_bash_command(
            "while :; do echo a; done < /etc/shadow",
            {"*": "allow", "input_redirection": "allow"},
        )
        assert result["status"] == "allow"
        assert result["reason"].count("/etc/shadow") == 1
```

**Acceptance:** `uv run pytest tests/config/test_evaluate.py -q` — new + existing
all green.

---

## Step 6 — `tests/parsing/test_segments.py`, `tests/parsing/test_parser.py`, `tests/config/test_evaluate.py`: regressions for bugs #8, #4, #9

**Status: pending** (after Steps 1 and 3)

**Files:** `tests/parsing/test_segments.py`, `tests/parsing/test_parser.py`,
`tests/config/test_evaluate.py`

1. **Bug #8** — in `tests/parsing/test_segments.py`, append this class at the
   **end of the file** (the tests use `self`, so they must live in a class;
   there is no existing case-test class — `parse_segments` is already
   imported at the top of the file):

```python
class TestCaseCommandSubstitution:
    """case subject word and branch patterns are segments."""

    def test_case_word_command_substitution_extracted(self) -> None:
        """bug #8: the case subject word is a segment."""
        result = parse_segments("case $(evil) in a) echo 1;; esac")
        assert [s["command"] for s in result] == ["evil", "echo"]

    def test_case_branch_pattern_command_substitution_extracted(self) -> None:
        """bug #8: branch patterns are segments too."""
        result = parse_segments("case $x in $(evil)) echo hit;; esac")
        assert [s["command"] for s in result] == ["evil", "echo"]
```

1. **Bugs #4/#9** — two more append-at-end-of-file classes.

   In `tests/parsing/test_parser.py`, append (`parse_ast` is already imported
   at the top of the file):

```python
class TestDeepNestingRecursion:
    """deep nesting must convert instead of raising RecursionError."""

    def test_deep_cmdsubst_does_not_crash(self) -> None:
        deep = "echo " + "$(" * 200 + "true" + ")" * 200
        parse_ast(deep)

    def test_deep_compound_does_not_crash(self) -> None:
        parse_ast("if :; then " * 300 + "true" + "; fi" * 300)
        chain = " && ".join(["a"] * 400)
        assert len(parse_segments(chain)) == 400
        parse_ast("while :; do " * 400 + "true" + "; done" * 400)
```

   In `tests/config/test_evaluate.py`, append (`pytest` and
   `LovelyDevinPermissionsError` are already imported at the top of the file):

```python
class TestDeepNestingRecursion:
    """deep nesting converts and evaluates; past the cap, fail closed."""

    def test_deep_command_substitution_evaluates_without_crash(self) -> None:
        """deep nesting converts and evaluates instead of RecursionError."""
        deep = "echo " + "$(" * 180 + "true" + ")" * 180
        result = evaluate_bash_command(deep, {"*": "allow"})
        assert result["status"] == "allow"

    def test_over_cap_command_fails_closed(self, monkeypatch) -> None:
        """past the cap we fail closed with a parse error, never recurse-crash."""
        import lovely_bash_permissions.converter as conv
        monkeypatch.setattr(conv, "_MAX_RECURSION_LIMIT", 2000)
        deep = "echo " + "$(" * 400 + "true" + ")" * 400
        with pytest.raises(LovelyDevinPermissionsError):
            conv.parse_ast(deep)
```

**Acceptance:** `uv run pytest tests/parsing/test_segments.py tests/parsing/test_parser.py tests/config/test_evaluate.py -q` — green.

---

## Step 7 — Full verification & plan wrap-up

**Status: pending**

Run from the repo root; all must pass:

1. `uv run ruff check .`
2. `uv run ruff format --check .` (source files; PLAN.md fences are a
   pre-existing, accepted failure)
3. `uv run mypy --strict .`
4. `uv run pytest -m 'not linting' -q`
5. Security probe (must print `deny ok`):

```bash
uv run python <<'EOF'
from lovely_bash_permissions.evaluate import evaluate_bash_command

r = evaluate_bash_command("(( x[$(rm -rf /etc/x)] ))", {"*": "allow", "subshell": "deny"})
assert r["status"] == "deny", r
r = evaluate_bash_command("while :; do echo a; done < /etc/shadow", {"*": "allow", "input_redirection": "allow"})
assert r["reason"].count("/etc/shadow") == 1, r["reason"]
print("deny ok")
EOF
```

1. CLI no-crash probe (exits 0, no traceback — the over-the-cap exit-3 path is
   covered by the guard unit test in Step 6 instead):

```bash
cmd=$(python -c "print('echo ' + '\$('*180 + 'true' + ')'*180)")
uv run lovely-bash-inspection --string "$cmd" >/dev/null 2>&1; test $? -eq 0
```

1. Mark every step in this plan `Status: done`.

---

## Resulting behaviors (reference table)

| Command / config | before | after |
| --- | --- | --- |
| `echo $(…$(true)…)` ×165+ | `RecursionError` crash (exit 1) | converts; up to ~cap depth, else clean parse error (exit 3) |
| ~400 × `a && a && …` | `RecursionError` | converts fine |
| `(( x[$(rm -rf /etc/x)] ))` with `"*": "allow"` | allow ❌ | ask |
| `(( x[$(rm -rf /etc/x)] ))` with `"*": "allow", "subshell": "deny"` | allow ❌ | deny |
| `time (( x[$(rm z)] ))` with deny subshell | allow ❌ | deny |
| `(( x = 5 ))` with deny subshell | allow | allow (unchanged) |
| `case $(evil) in a) echo 1;; esac` | `['echo']` | `['evil', 'echo']` |
| `case $x in $(evil)) echo hit;; esac` | `['echo']` | `['evil', 'echo']` |
| `while :; do echo a; done < /etc/shadow` | reason `…from /etc/shadow, /etc/shadow` | `…from /etc/shadow` (once) |

## Invariants deliberately preserved (do not change while implementing)

- Bugs #5/#6 segment behaviors (`['seq','echo']`, `['cmd','echo']`, no
  `$(...)` phantoms) stay as verified in Step 0.
- The empty-segment blocked-paths and heredoc scans run first and still deny —
  the new subshell branch only changes the *default* when those scans are
  silent (reasons match existing strings: `"wildcard policy (ask)"`,
  `"subshell or command substitution requires approval"`).
- Subshell-policy inheritance (`subshell: allow` → wildcard) is preserved in
  the empty-segment path AND the per-segment path is untouched.
- The recursion headroom is monotonic and never lowered (process-wide), so the
  recursive segment-extraction and CLI-render passes after conversion keep their
  headroom; the cap + `RecursionError`→`ParseError` guard guarantee fail-closed
  behavior rather than a crash.
- `case` handlers that currently produce only body segments with no
  substitutions are unchanged (`["echo"]`); `select`/`ForClause` behavior is
  unchanged (already fixed by #5).
- Redirection dedup keeps distinct (op, fd, target) entries — no check is lost;
  blocked-path checks still run per retained target.
- `converter.py` keeps a local import of `.parser` (no new module-level cycle);
  `ParseError` still subclasses `LovelyDevinPermissionsError` so CLI exit-3 and
  hook error-policy routing are unchanged.
