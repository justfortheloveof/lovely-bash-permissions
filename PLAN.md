# Implementation Plan: bugs #5 + #6 + C-style-loop prelude extraction

> **Status: 📝 PROPOSED** — plan for review; not yet implemented.
>
> **For the implementing agent:** every step is self-contained and small. Do ONE
> step per iteration. Locate edit sites by the **exact "Find" code blocks** (line
> numbers are approximate pre-edit references and drift between steps — never
> trust line numbers, trust the code text). Do not modify anything outside the
> files listed for the step. All probes/verification must be run from the repo
> root with `uv run ...` (the package is NOT pip-installed; a bare
> `python -c "import lovely_bash_permissions"` fails).

## Bugs being fixed

### Bug #5 — commands in `for`-loop lists and test left-operands are not extracted as segments (🟡 accuracy)
```
parse_segments("for i in $(seq 3); do echo $i; done")   # -> ['echo']   (seq missing)
parse_segments("[[ $(pwd) == /root* ]]")                # -> []         (pwd missing)
```

### Bug #6 — `$( cmd )` as a test operand is emitted as a literal `$(...)` pseudo-command (🟡 over-ask)
```
evaluate_bash_command("[[ -f x && $(cmd) ]]", {"*": "ask", ...})
#   segments: [{'command': '$(...)', ...}]  — a command name that can never match
```

### Bug (NEW) — C-style `for ((init; cond; post))` prelude is dropped at conversion (🔴 security bypass)
```
evaluate_bash_command("for ((i=$(rm -rf /etc/passwd); i<1; i++)); do :; done",
                      {'*': 'allow', 'subshell': 'deny', 'blocked_paths_regex': ['/etc']})
#   -> allow  (bypass — the init command substitution actually runs)
```
shfmt emits `ForClause.Loop = {Type: "CStyleLoop", Init, Cond, Post, ...}`;
`_convert_for_clause` only reads `Loop.Name`/`Loop.Items` (the `WordIter`
foreach form), so prelude substitutions are dropped from the typed AST and every
typed-AST pass (`_has_cmd_subst`, `_extract_subshell_contents`,
`_extract_segments`) misses them.

### Dead code — `_convert_word_iter` is unreachable
`_convert_word_iter` + dispatch entry `"WordIter"` are never invoked (shfmt emits
`Type: "WordIter"` only inside `ForClause.Loop`, which `_convert_for_clause`
parses inline; `node_from_json` is not exported).

---

## Execution order & dependency notes

Steps 1 → 2 → 3 → 4 → 5 → 6 are code changes; 7–8 add/adjust tests; 9 is final
verification. Each step's acceptance probe stands on its own.

**Expected-red window:** after Step 5 (and until Step 8), exactly ONE existing
test fails: `tests/config/test_evaluate.py::TestWildcardIsBaseline::test_empty_segment_wildcard_ask`
(once the left operand of `[[ $(cat ...) == x ]]` is recursed, it produces a
real `cat` segment, so the reason changes from the wildcard fallback to the
allowlist-miss naming `cat`; Step 8 rewrites the test). Do not "fix" it before
Step 8 — no other test may be red at any point.

---

## Step 1 — `ast.py`: give `ForClause` a `cstyle` field

**Status: done** (commit 5846954)

**File:** `src/lovely_bash_permissions/ast.py` (only file touched)

**Why:** the C-style prelude must survive conversion. Traversal helpers
(`_traverse` in `inspect.py`, `_has_cmd_subst` in `evaluate.py`,
`structurally_equal` at ast.py:~818) iterate `dataclasses.fields()` generically,
so a plain dataclass field is automatically picked up everywhere — no other code
changes are needed for traversal coverage.

**Change:** replace the `ForClause` dataclass (line ~442) — add one docstring line
and one field, appended LAST so no positional call sites shift (the only
constructor call site is converter.py, which uses keywords):

Find:
```python
class ForClause(Node):
    """A for loop statement.

    Attributes:
        var: The loop variable name as a string
        words: List of Word objects to iterate over
        body: List of Stmt objects executed in each iteration
    """

    var: str | None = None
    words: list[Word] = field(default_factory=list)
    body: list[Stmt] = field(default_factory=list)
```

Replace with:
```python
class ForClause(Node):
    """A for loop statement.

    Attributes:
        var: The loop variable name as a string
        words: List of Word objects to iterate over
        body: List of Stmt objects executed in each iteration
        cstyle: C-style for ((init; cond; post)) prelude, when this is a
            C-style loop (the loop body stays in ``body``)
    """

    var: str | None = None
    words: list[Word] = field(default_factory=list)
    body: list[Stmt] = field(default_factory=list)
    cstyle: CStyleLoop | None = None
```

Notes: `CStyleLoop` is defined later in the same file (line ~716); this is safe
because `from __future__ import annotations` is present (line 25). Do NOT touch
`CStyleLoop`, `WordIter`, or anything else in this file.

**Acceptance (all must hold):**
1. `uv run ruff check .` and `uv run ruff format --check .` — clean.
2. `uv run mypy --strict src/lovely_bash_permissions` — clean.
3. `uv run pytest -m 'not linting' -q` — all green (behavior unchanged; converter
   does not set the field yet, so it is always `None`).
4. Probe:
```bash
uv run python -c "
from dataclasses import fields
from lovely_bash_permissions.ast import ForClause, CStyleLoop
f = ForClause(var='i', cstyle=None)
assert 'cstyle' in {a.name for a in fields(ForClause)}
print('ok')"
```

---

## Step 2 — `converter.py`: preserve the C-style prelude in `_convert_for_clause`

**Status: done** (commit 1742da9)

> **Orchestrator note on probes:** wherever this plan's probe snippets are written as
> `uv run python -c "..."` with `\$` escapes, the `\$` is bash shell escaping for `-c` —
> the python source itself must contain a plain `$`. Workers should create probe files via
> a single-quoted heredoc so the shell does not touch anything, and keep the plain `$`.

> **Orchestrator note (pre-existing, do not fix in a step):** `uv run ruff format --check .` fails
> ONLY on PLAN.md itself (markdown code fences) — this predates all implementation steps. Every
> step's format check should be interpreted as "all real source/test files clean; PLAN.md may
> remain flagged."

**File:** `src/lovely_bash_permissions/converter.py` (only file touched)

**Why:** shfmt represents `for ((...))` as `ForClause` with
`Loop = {Type: "CStyleLoop", Init, Cond, Post, ...}` (verified against live
shfmt output). Route the whole `Loop` dict through `node_from_json`, which
dispatches to the existing `_convert_cstyle_loop` (already handles absent
`Init`/`Cond`/`Post` — `for ((;;))` works). `CStyleLoop` and `node_from_json`
already exist in this module (import at line ~35; `node_from_json` at line ~915);
no import changes needed.

**Change:** replace the entire `_convert_for_clause` function (line ~545).

Find:
```python
def _convert_for_clause(data: dict[str, Any]) -> ForClause:
    loop = data.get("Loop", {})
    var_name: str | None = None
    items: list[Word] = []

    if isinstance(loop, dict):
        name_info = loop.get("Name", {})
        if isinstance(name_info, dict):
            var_name = name_info.get("Value")
        for w in loop.get("Items", []):
            if isinstance(w, dict):
                word = _convert_word(w)
                if word is not None:
                    items.append(word)

    body = _parse_stmt_list(data.get("Do", []))

    pos, end = _parse_pos_end(data)
    return ForClause(
        pos=pos,
        end=end,
        var=var_name,
        words=items,
        body=body,
    )
```

Replace with:
```python
def _convert_for_clause(data: dict[str, Any]) -> ForClause:
    loop = data.get("Loop", {})
    var_name: str | None = None
    items: list[Word] = []
    cstyle: CStyleLoop | None = None

    if isinstance(loop, dict):
        if loop.get("Type") == "CStyleLoop":
            # for ((init; cond; post)): keep init/cond/post so their command
            # substitutions stay visible to every typed-AST pass
            # (subshell policy, blocked-path scan, segment extraction).
            converted = node_from_json(loop)
            if isinstance(converted, CStyleLoop):
                cstyle = converted
        else:
            # foreach form: Loop is a WordIter-shaped dict {Name, Items}
            name_info = loop.get("Name", {})
            if isinstance(name_info, dict):
                var_name = name_info.get("Value")
            for w in loop.get("Items", []):
                if isinstance(w, dict):
                    word = _convert_word(w)
                    if word is not None:
                        items.append(word)

    body = _parse_stmt_list(data.get("Do", []))

    pos, end = _parse_pos_end(data)
    return ForClause(
        pos=pos,
        end=end,
        var=var_name,
        words=items,
        body=body,
        cstyle=cstyle,
    )
```

(If `node_from_json(loop)` ever returned something other than a `CStyleLoop` for
a `Type: "CStyleLoop"` dict — it can't today, but guard anyway — `cstyle` stays
`None` and the command degrades to the previous behavior, never crashes.)

**Acceptance (all must hold):**
1. `uv run ruff check .`, `uv run ruff format --check .`,
   `uv run mypy --strict src/lovely_bash_permissions` — clean.
2. `uv run pytest -m 'not linting' -q` — all green.
3. Probe (this is the 🔴 bypass un-blocking step):
```bash
uv run python -c "
from lovely_bash_permissions.parser import parse
from lovely_bash_permissions.converter import node_from_json
from lovely_bash_permissions.evaluate import _has_cmd_subst

raw = parse('for ((i=\$(date); i<1; i++)); do :; done', 'bash')
ast = node_from_json(raw)
fc = ast.stmts[0].cmd
assert fc.cstyle is not None, 'cstyle prelude dropped'
assert _has_cmd_subst(raw) is True, '_has_cmd_subst still misses prelude'

raw2 = parse('for i in a b; do echo; done', 'bash')
ast2 = node_from_json(raw2)
assert ast2.stmts[0].cmd.cstyle is None
assert ast2.stmts[0].cmd.var == 'i'
print('ok')"
```
   (Before this step, both asserts in the middle fail.)

---

## Step 3 — `converter.py`: remove dead `WordIter` code

**Status: done**

*Worker deviation (accepted): also reworded the Step-2 comment "WordIter-shaped dict" to
"dict" in `_convert_for_clause` — required by this step's own acceptance check #1
(`rg WordIter` must print nothing).*

**File:** `src/lovely_bash_permissions/converter.py` (only file touched)

**Why:** `_convert_word_iter` is unreachable — shfmt emits `Type: "WordIter"`
only inside `ForClause.Loop`, which Step 2's code (and the pre-existing code)
parses inline; `node_from_json` is not exported. **Keep** the public
`WordIter` dataclass in `ast.py` and its `__init__.py` export — only the
converter-internal pieces are removed.

**Change — three deletions in one file:**

1. Delete the function (line ~819):
```python
def _convert_word_iter(data: dict[str, Any]) -> WordIter:
    pos, end = _parse_pos_end(data)
    name_data = data.get("Name")
    name_node = (
        _convert_lit(name_data) if isinstance(name_data, dict) else Lit(value=str(name_data) if name_data else "")
    )
    return WordIter(
        pos=pos,
        end=end,
        name=name_node,
        items=[w for i in data.get("Items", []) if (w := _convert_word(i)) is not None],
    )
```

2. Delete the dispatch entry in `_CONVERTERS` (line ~899):
```python
    "WordIter": _convert_word_iter,
```

3. Delete `    WordIter,` from the `from .ast import (...)` block (line ~67).
   This makes `WordIter` unused in converter.py; leave `_convert_lit` — it is
   still used elsewhere.

**Acceptance (all must hold):**
1. `rg -n "_convert_word_iter|WordIter" src/lovely_bash_permissions/converter.py`
   — **no output**.
2. `uv run ruff check .`, `uv run ruff format --check .`,
   `uv run mypy --strict src/lovely_bash_permissions` — clean (ruff/mypy will
   flag any leftover unused import).
3. `uv run pytest -m 'not linting' -q` — all green (the Step 2 probe from its
   acceptance still passes: foreach loops parse identically).

---

## Step 4 — `segments.py`: extract commands from C-style preludes and for-loop lists

**Status: done**

**File:** `src/lovely_bash_permissions/segments.py` (only file touched)

**Why (bug #5 part 1):** the `ForClause` branch recurses only `node.body` —
never the loop-list `node.words`, and never the C-style prelude. Prelude
`init`/`cond`/`post` nodes are arithmetic (`BinaryArithm`/`UnaryArithm`, etc.)
wrapping `Word`s whose parts may contain `CmdSubst`; the existing arithmetic
handlers (lines ~543–560) already recurse those operands and extract nested
substitutions, so merely feeding them the prelude is sufficient. Plain literal
arithmetic (`i=0`, `i<10`, `i++`) produces no segments.

**Change:** replace the loop branch (line ~372).

Find:
```python
    elif isinstance(node, (ForClause, CStyleLoop)):
        # Extract commands from loop body
        if hasattr(node, "body") and node.body:
            for stmt in node.body:
                segments.extend(_extract_segments(stmt, redirs))
```

Replace with:
```python
    elif isinstance(node, (ForClause, CStyleLoop)):
        # C-style prelude: for ((init; cond; post)) arithmetic may embed
        # command substitutions that bash evaluates — surface them first.
        prelude = node if isinstance(node, CStyleLoop) else getattr(node, "cstyle", None)
        if prelude is not None:
            for attr in ("init", "cond", "post"):
                child = getattr(prelude, attr, None)
                if child is not None:
                    segments.extend(_extract_segments(child, redirs))
        # Loop-list words (for i in $(...); ...) are evaluated before the body.
        if hasattr(node, "words") and node.words:
            for w in node.words:
                segments.extend(_extract_segments(w, redirs))
        # Body statements.
        if hasattr(node, "body") and node.body:
            for stmt in node.body:
                segments.extend(_extract_segments(stmt, redirs))
```

The `hasattr` guards keep a bare `CStyleLoop` node (no `words`/`body`) working,
and are forward-compatible in both directions.

**Acceptance (all must hold):**
1. `uv run ruff check .`, `uv run ruff format --check .`,
   `uv run mypy --strict src/lovely_bash_permissions` — clean.
2. `uv run pytest -m 'not linting' -q` — all green (existing tests only assert
   on body extraction and literal loops, which are unchanged).
3. Probes:
```bash
uv run python -c "
from lovely_bash_permissions.segments import parse_segments
assert [s['command'] for s in parse_segments('for i in \$(seq 3); do echo \$i; done')] == ['seq', 'echo']
assert [s['command'] for s in parse_segments('for f in a \$(ls) b; do echo \$f; done')] == ['ls', 'echo']
assert [s['command'] for s in parse_segments('for i in 1 2 3; do echo hi; done')] == ['echo']
assert [s['command'] for s in parse_segments('for ((i=\$(seq 3); i < \$n; i++)); do echo \$i; done')] == ['seq', 'echo']
assert [s['command'] for s in parse_segments('for ((i=0; i<10; i++)); do echo x; done')] == ['echo']
assert [s['command'] for s in parse_segments('for ((;;)); do :; done')] == [':']
print('ok')"
```

---

## Step 5 — `segments.py`: recurse `BinaryTest` left operand

**Status: done**

> ⚠️ **Expected-red window now OPEN:** `tests/config/test_evaluate.py::TestWildcardIsBaseline::
> test_empty_segment_wildcard_ask` fails (1 failed, 1040 passed) until Step 8 rewrites it.
> Do NOT "fix" it before Step 8; no other test may be red.

**File:** `src/lovely_bash_permissions/segments.py` (only file touched)

**Why (bug #5 part 2):** only `node.right` is recursed, so `[[ $(pwd) == /root* ]]`
extracts nothing. The left operand is the comparison *subject* (a value, regex,
glob, number — never a command to check), so recurse it **without** test-expr
context: only nested substitutions inside it are extracted, the operand itself
is never emitted as a pseudo-command.

**Change:** replace the `BinaryTest` branch (line ~393).

Find:
```python
    elif isinstance(node, BinaryTest):
        # Test expression: only the right operand of a logical && / || is a
        # "command" to check. Every other operator's right operand is a value
        # (regex for =~, literal/glob for ==/!=, number for -eq, ...), never a
        # command name — recurse WITHOUT test-expr context so only nested
        # command substitutions inside it are extracted.
        if hasattr(node, "right") and node.right:
            in_test_expr = node.op in ("&&", "||")
            segments.extend(_extract_segments(node.right, _in_test_expr=in_test_expr))
```

Replace with:
```python
    elif isinstance(node, BinaryTest):
        # Test expression: only the right operand of a logical && / || is a
        # "command" to check. Every other operator's right operand is a value
        # (regex for =~, literal/glob for ==/!=, number for -eq, ...), never a
        # command name — recurse WITHOUT test-expr context so only nested
        # command substitutions inside it are extracted.
        # The left operand is likewise the comparison subject (value/glob/
        # regex/number) — recurse it WITHOUT test-expr context too, so nested
        # command substitutions (e.g. [[ $(pwd) == /root* ]]) surface but the
        # operand itself is not emitted as a command.
        if hasattr(node, "left") and node.left:
            segments.extend(_extract_segments(node.left, _in_test_expr=False))
        if hasattr(node, "right") and node.right:
            in_test_expr = node.op in ("&&", "||")
            segments.extend(_extract_segments(node.right, _in_test_expr=in_test_expr))
```

**Acceptance (all must hold):**
1. `uv run ruff check .`, `uv run ruff format --check .`,
   `uv run mypy --strict src/lovely_bash_permissions` — clean.
2. `uv run pytest -m 'not linting' -q` — everything green EXCEPT the expected
   single failure `test_evaluate.py::TestWildcardIsBaseline::test_empty_segment_wildcard_ask`
   (see the Expected-red window above; it turns green again only in Step 8).
   No other test may be red.
3. Probe (quoted heredoc so bash does not touch the `$` — do NOT rewrite it as
   a `python -c "..."` one-liner):
```bash
uv run python <<'EOF'
from lovely_bash_permissions.segments import parse_segments

assert [s['command'] for s in parse_segments("[[ $(pwd) == /root* ]]\")] == ["pwd"]
assert [s['command'] for s in parse_segments("[[ $a == *.txt ]]\")] == []
print("ok")
EOF
```

---

## Step 6 — `segments.py`: stop emitting `$(...)`/`$var`/`''` phantom test commands (bug #6)

**Status: done** (red window still open: exactly 1 failed, 1040 passed)

**File:** `src/lovely_bash_permissions/segments.py` (only file touched)

**Why:** the `Word` and `DblQuoted` handlers render the word via
`_word_value(node)` / `node.value` — which show `CmdSubst` as the literal
placeholder `$(...)` — and emit that string as a "command name". Such
pseudo-commands can never match an allowed pattern, so the verdict is always
`ask` naming a nonexistent command. Fix: stop emitting the rendered word and
always recurse into the parts, passing `_in_test_expr` down. Inside test
expressions the `Lit`/`SglQuoted` handlers (unchanged) still surface bare
literal fragments as pseudo-commands — preserving the conservative
`[[ cond && ls ]]` → `['ls']` behavior — while `ParamExp` (already guarded by
`if not _in_test_expr`) no longer yields the `$var` phantom, and `CmdSubst`
(unguarded handler) extracts the real command. Deliberate, accepted edge-case
change: mixed words like unquoted `a$(b)` now surface as `['a', 'b']` (real
command extracted, adjacent literal still conservative) instead of one
unmatchable `a$(...)` phantom — strictly more segments, never fewer.

**Change 1 of 2** — replace the `Word` branch (line ~490):

Find:
```python
    elif isinstance(node, Word):
        # Word nodes (arguments) may contain CmdSubst/ProcSubst in their parts.
        # Recurse into each part to find nested redirections (only outside test expr context).
        if not _in_test_expr:
            for part in node.parts:
                segments.extend(_extract_segments(part, _in_test_expr=False))
        # Inside test expressions, word values are command names
        if _in_test_expr:
            segments.append({"command": _word_value(node), "arguments": [], "redirections": []})
```

Replace with:
```python
    elif isinstance(node, Word):
        # Word nodes (arguments) may contain CmdSubst/ProcSubst in their parts.
        # Always recurse, passing the test-expr context down: inside test
        # expressions bare Lit/SglQuoted fragments still surface as
        # pseudo-commands while embedded substitutions are extracted as the
        # real commands they run (bug #6: no more "$(...)" / "$var" phantom
        # command names).
        for part in node.parts:
            segments.extend(_extract_segments(part, _in_test_expr=_in_test_expr))
```

**Change 2 of 2** — replace the `DblQuoted` branch (line ~511):

Find:
```python
    elif isinstance(node, DblQuoted):
        # Double-quoted text may embed CmdSubst/ProcSubst/ParamExp parts.
        if _in_test_expr:
            if node.value:
                segments.append({"command": node.value, "arguments": [], "redirections": []})
        else:
            for part in node.parts:
                segments.extend(_extract_segments(part))
```

Replace with:
```python
    elif isinstance(node, DblQuoted):
        # Double-quoted text may embed CmdSubst/ProcSubst/ParamExp parts —
        # always recurse so embedded substitutions surface as real commands.
        for part in node.parts:
            segments.extend(_extract_segments(part, _in_test_expr=_in_test_expr))
```

**Acceptance (all must hold):**
1. `uv run ruff check .`, `uv run ruff format --check .`,
   `uv run mypy --strict src/lovely_bash_permissions` — clean. (`_word_value`
   stays imported — it is still used by the `LetClause` handler at ~line 448 and
   elsewhere; do not remove the import.)
2. `uv run pytest -m 'not linting' -q` — everything green **except exactly one
   expected failure** (same test that has been red since Step 5):
   `tests/config/test_evaluate.py::TestWildcardIsBaseline::test_empty_segment_wildcard_ask`
   (its reason-string assertion encodes the pre-fix behavior; Step 8 rewrites
   it). If ANY other test fails, the change is wrong — revert and re-examine.
3. Probe (quoted heredoc, as in Step 5 — do NOT convert to a `python -c`
   one-liner; the semantic assertions are what matter):
```bash
uv run python <<'EOF'
from lovely_bash_permissions.segments import parse_segments

def cmds(c):
    return [s['command'] for s in parse_segments(c)]

assert cmds("[[ $(cmd) ]]")) == ["cmd"]                        # was ['$(...)']
assert cmds("[[ -f x && $(c2) ]] && echo and") == ["c2", "echo"]  # was ['$(...)', 'echo']
assert cmds("[[ $var ]]")) == []                                # was ['$var']
assert cmds("[[ $a == *.txt ]]")) == []                         # unchanged
assert cmds("[[ $var =~ $(cmd) ]]")) == ["cmd"]                 # unchanged
print("ok")
EOF
```

---

## Step 7 — `tests/parsing/test_segments.py`: regression tests for bugs #5 + #6

**Status: done**

**File:** `tests/parsing/test_segments.py` (only file touched)

The file imports `from lovely_bash_permissions.segments import parse_segments`
(line 5) — no new imports needed. Append the following classes at the end of the
file (after `TestErrorHandling`):

```python
class TestForLoopListSegments:
    """for-loop list words are evaluated before the body (bug #5)."""

    def test_cmdsubst_in_loop_list_extracted(self) -> None:
        assert [s["command"] for s in parse_segments("for i in $(seq 3); do echo $i; done")] == ["seq", "echo"]

    def test_cmdsubst_among_literal_words(self) -> None:
        assert [s["command"] for s in parse_segments("for f in a $(ls) b; do echo $f; done")] == ["ls", "echo"]

    def test_literal_loop_list_unchanged(self) -> None:
        assert [s["command"] for s in parse_segments("for i in 1 2 3; do echo hi; done")] == ["echo"]


class TestCStyleLoopSegments:
    """C-style for ((init; cond; post)) preludes are extracted (security-critical)."""

    def test_prelude_cmdsubst_extracted(self) -> None:
        segs = parse_segments("for ((i=$(seq 3); i < $n; i++)); do echo $i; done")
        assert [s["command"] for s in segs] == ["seq", "echo"]

    def test_literal_prelude_unchanged(self) -> None:
        assert [s["command"] for s in parse_segments("for ((i=0; i<10; i++)); do echo x; done")] == ["echo"]

    def test_degenerate_prelude(self) -> None:
        assert [s["command"] for s in parse_segments("for ((;;)); do :; done")] == [":"]


class TestBinaryTestLeftOperand:
    """Left operands of [[ ]] binary tests hold nested substitutions (bug #5)."""

    def test_left_operand_cmdsubst_extracted(self) -> None:
        assert [s["command"] for s in parse_segments("[[ $(pwd) == /root* ]]")] == ["pwd"]

    def test_both_sides_cmdsubst(self) -> None:
        assert [s["command"] for s in parse_segments("[[ $(a) == $(b) ]]")] == ["a", "b"]

    def test_literal_left_operand_still_no_phantom(self) -> None:
        commands = [s["command"] for s in parse_segments("[[ -d /tmp && ls ]]")]
        assert "ls" in commands
        assert "d" not in commands and "tmp" not in commands


class TestNoPhantomTestCommands:
    """$(...)/$var inside [[ ]] are not emitted as literal command names (bug #6)."""

    def test_cmdsubst_operand_is_real_command(self) -> None:
        assert [s["command"] for s in parse_segments("[[ $(cmd) ]]")] == ["cmd"]

    def test_cmdsubst_after_logical_and(self) -> None:
        assert [s["command"] for s in parse_segments("[[ -f x && $(c2) ]] && echo and")] == ["c2", "echo"]

    def test_quoted_cmdsubst(self) -> None:
        assert [s["command"] for s in parse_segments("[[ cond && \"$(cmd)\" ]]")] == ["cmd"]

    def test_bare_param_exp_not_a_command(self) -> None:
        assert parse_segments("[[ $var ]]") == []

    def test_quoted_param_exp_not_a_command(self) -> None:
        assert parse_segments("[[ \"$var\" ]]") == []

    def test_logical_and_literal_operand_still_extracted(self) -> None:
        commands = [s["command"] for s in parse_segments("[[ -d /tmp && ls ]]")]
        assert "ls" in commands

    def test_bare_literal_operand_still_extracted(self) -> None:
        assert [s["command"] for s in parse_segments("[[ foo ]]")] == ["foo"]
```

**Acceptance (all must hold):**
1. `uv run pytest tests/parsing/test_segments.py -q` — all green.
2. `uv run ruff check .` and `uv run ruff format --check .` — clean (adjust the
   two long `assert` lines to fit the line length if ruff format reflows them;
   semantics must stay identical).

---

## Step 8 — `tests/config/test_evaluate.py`: re-point bug-#2 tests + add 🔴 bypass regression

**Status: not started**

**File:** `tests/config/test_evaluate.py` (only file touched)

Uses the module's existing imports (`evaluate_bash_command`, `make_config`).
Make these four changes:

**1. Re-point `test_empty_segment_wildcard_ask`** (line ~269). The old bug-#2
repro `[[ $(cat /etc/passwd) == x ]]` now produces a real `cat` segment, so it
no longer exercises the *empty-segment* wildcard fallback. Replace its body with
`[[ -f x ]]`, which still yields no segments:

Find:
```python
    def test_empty_segment_wildcard_ask(self) -> None:
        """bug #2: `[[ $(cat /etc/passwd) == x ]]` under "*": "ask" no longer default-allows."""
        result = evaluate_bash_command(
            "[[ $(cat /etc/passwd) == x ]]",
            {"*": "ask"},
        )
        assert result["status"] == "ask"
        assert "wildcard policy (ask)" in result["reason"]
```

Replace with:
```python
    def test_empty_segment_wildcard_ask(self) -> None:
        """No-segment commands under "*": "ask" fall back to the wildcard (ask)."""
        result = evaluate_bash_command(
            "[[ -f x ]]",
            {"*": "ask"},
        )
        assert result["status"] == "ask"
        assert "wildcard policy (ask)" in result["reason"]

    def test_cmdsubst_in_test_clause_resolves_to_real_segment(self) -> None:
        """bug #2/#6: `[[ $(cat ...) == x ]]` now yields a real `cat` segment.

        Verdict is unchanged (ask under "*": "ask"), but the reason now names
        the real command instead of falling through the empty-segment path.
        """
        result = evaluate_bash_command(
            "[[ $(cat /etc/passwd) == x ]]",
            {"*": "ask"},
        )
        assert result["status"] == "ask"
        assert '"cat" command is not allowlisted' in result["reason"]
```

(If the exact reason string differs — check the allowlist-miss message in
`evaluate.py` and match it there; the assertion must name `cat` and NOT contain
the wildcard-fallback phrase.)

**2. Update `test_empty_segment_blocked_subshell_denied`'s docstring only** (line
~278) — the command and assertions stay; prepend to its docstring:

```python
        """bug #2: blocked-path scan denies before the empty-segment return.

        Post bug #6 fix this now fires via the real `cat` segment's
        blocked-path check rather than the empty-segment subshell scan —
        verdict and reason are unchanged.
        """
```

**3. Add the 🔴 C-style bypass regression and the prelude-visibility test** as
new tests inside the class that owns `test_cstyle_loop_extracted` (search for
`def test_cstyle_loop_extracted`, line ~121; append after it in the same class):

```python
    def test_cstyle_prelude_cmdsubst_not_bypassed(self) -> None:
        """🔴 regression: prelude substitutions in for ((...)) are no longer dropped.

        Before the ForClause.cstyle fix this returned `allow` — the rm ran in
        the loop init and every typed-AST pass (subshell policy, blocked-path
        scan, segment extraction) missed it. The foreach form
        `for i in $(rm ...)` was already correctly denied.
        """
        result = evaluate_bash_command(
            "for ((i=$(rm -rf /etc/passwd); i<1; i++)); do :; done",
            {"*": "allow", "subshell": "deny", "blocked_paths_regex": [r"/etc"]},
        )
        assert result["status"] == "deny"

    def test_cstyle_prelude_cmdsubst_visible_to_subshell_pass(self) -> None:
        from lovely_bash_permissions.converter import node_from_json
        from lovely_bash_permissions.evaluate import _has_cmd_subst
        from lovely_bash_permissions.parser import parse

        raw = parse("for ((i=$(date); i<1; i++)); do :; done", "bash")
        assert node_from_json(raw) is not None
        assert _has_cmd_subst(raw) is True
```

(If `_has_cmd_subst`/`parse` imports are cleaner at module top rather than
function-local, that's fine — match the file's existing style.)

**4. Run and confirm.**

**Acceptance (all must hold):**
1. `uv run pytest -m 'not linting' -q` — **entire suite green** (this step
   closes the expected-red window from Step 6).
2. `uv run ruff check .` and `uv run ruff format --check .` — clean.

---

## Step 9 — Full verification & plan wrap-up

**Status: not started**

Run from the repo root; all must pass:

1. `uv run ruff check .`
2. `uv run ruff format --check .`
3. `uv run mypy --strict .`
4. `uv run pytest -m 'not linting' -q` — all green.
5. Security probe (must print `deny`):
```bash
uv run python -c "
from lovely_bash_permissions.evaluate import evaluate_bash_command
r = evaluate_bash_command(
    'for ((i=\$(rm -rf /etc/passwd); i<1; i++)); do :; done',
    {'*': 'allow', 'subshell': 'deny', 'blocked_paths_regex': ['/etc']},
)
assert r['status'] == 'deny', r
print('deny ok')"
```
6. Final segment behavior spot-checks (quoted heredoc — do NOT convert to a
   `python -c "..."` one-liner; must print `ok`):
```bash
uv run python <<'EOF'
from lovely_bash_permissions.segments import parse_segments

def cmds(c):
    return [s['command'] for s in parse_segments(c)]

assert cmds("for i in $(seq 3); do echo $i; done") == ["seq", "echo"]
assert cmds("if [[ $(pwd) == /root* ]]; then echo root; fi") == ["pwd", "echo"]
assert cmds("[[ $(cmd) == x ]] && echo ok") == ["cmd", "echo"]
assert cmds("[[ -d /tmp && ls ]]") == ["ls"]
assert cmds("[[ $var ]]") == []
assert cmds("for ((i=$(init); i<n; i++)); do echo; done") == ["init", "echo"]
print("ok")
EOF
```
7. Mark every step in this plan `Status: done`.

---

## Resulting segment behaviors (reference table)

| Command | before | after |
|---|---|---|
| `for i in $(seq 3); do echo $i; done` | `['echo']` | `['seq', 'echo']` |
| `for f in a $(ls) b; do echo $f; done` | `['echo']` | `['ls', 'echo']` |
| `if [[ $(pwd) == /root* ]]; then echo root; fi` | `['echo']` | `['pwd', 'echo']` |
| `[[ $(cmd) == x ]]` | `[]` | `['cmd']` |
| `[[ x == $(cmd) ]]` | `['cmd']` | `['cmd']` (unchanged) |
| `[[ -f x && $(c2) ]] && echo and` | `['$(...)', 'echo']` | `['c2', 'echo']` |
| `[[ $(cmd) ]]` | `['$(...)']` | `['cmd']` |
| `[[ cond && "$(cmd)" ]]` | `['']` | `['cmd']` |
| `for ((i=$(init); i<n; i++)); do echo; done` | `['echo']` | `['init', 'echo']` |
| `[[ -d /tmp && ls ]]` | `['ls']` | `['ls']` (unchanged) |
| `[[ foo ]]` | `['foo']` | `['foo']` (unchanged) |
| `[[ $var ]]` / `[[ "$var" ]]` | `['$var']` / `['']` | `[]` |
| `[[ $var =~ $(cmd) ]]` | `['cmd']` | `['cmd']` (unchanged) |
| `[[ $var =~ pat ]]`, `[[ $n -eq 5 ]]`, `[[ $a == *.txt ]]` | `[]` | `[]` (unchanged) |

Verdict impact of removing `$var`/`''` phantoms: **none** — `[[ $var ]]`
resolves identically in every wildcard config via the empty-segment path; only
segments/reasons change.

## Invariants deliberately preserved (do not change while implementing)

- Bare literal `[[ ... && ls ]]` / `[[ foo ]]` / `[[ cond && 'ls' ]]` still emit
  pseudo-command segments via `Lit`/`SglQuoted` under `_in_test_expr`.
- Opaque `$(...)` handling in **arguments** (`evaluate._command_string` /
  `_match_allowed_patterns`) uses `_word_raw` placeholders — untouched.
- `subshell`/allowed/blocked passes in `evaluate.py` operate on the typed AST
  independently of segments; they now *also* see C-style preludes (more
  coverage, not different logic).
- Literal C-style arithmetic produces no segments — `test_cstyle_loop_extracted`
  and the devin CLI C-style test (`tests/cli/lovely-devin-permissions/test_devin_cli.py::test_cstyle_loop_body_extracted`) stay green.
- `rules.py` scans raw shfmt JSON (already saw prelude cmdsubs) — untouched.
- The public `WordIter` dataclass (`ast.py`) and its `__init__.py` export stay.
- The `Word`/`DblQuoted` branches do NOT pass the inherited `redirs` into their
  part recursion (matches pre-existing behavior) — keep it that way.
