# Implementation Plan: bugs #5 + #6 + C-style-loop prelude extraction

> **Status: 📝 PROPOSED** — plan for review; not yet implemented.
>
> Line numbers below are pre-edit references into the current `main` tree.

## Bugs being fixed

### Bug #5 — commands in `for`-loop lists and test left-operands are not extracted as segments (🟡 accuracy)

**Symptom:**
```
parse_segments("for i in $(seq 3); do echo $i; done")   # -> ['echo']   (seq missing)
parse_segments("[[ $(pwd) == /root* ]]")                # -> []         (pwd missing)
```

**Root cause:** `_extract_segments` (`segments.py`):
- `ForClause` branch (372–376) recurses only `node.body`, never the loop-*list* `node.words`;
- `BinaryTest` branch (393–401) recurses only `node.right`, never `node.left`.

The executed commands do appear in shfmt ground-truth extraction and are still
covered by the independent subshell/allowed/blocked passes, so this is an
accuracy bug — but segment lists (and anything built on them: per-command UX,
`lovely-bash-inspection`) silently under-report executed commands.

### Bug #6 — `$( cmd )` as a test operand is emitted as a literal `$(...)` pseudo-command (🟡 over-ask)

**Symptom:**
```
evaluate_bash_command("[[ -f x && $(cmd) ]]", {"*": "ask", "allowed_cmds_regex": [r"^-f$"], "subshell": "allow"})
#   segments: [{'command': '$(...)', 'allowed': False}, ...]   (fake command '$('...')')
```
The pseudo-command `$(...)` can never match an allowed pattern, so the command
always asks with a confusing reason naming a nonexistent command.

**Root cause:** `Word` (490–498) and `DblQuoted` (511–518) handlers emit
`_word_value(node)` / `node.value` — which render `CmdSubst` as the literal
placeholder `$(...)` — as a "command name" pseudo-segment instead of recursing
into the word parts to surface the real command.

### Bug (NEW) — C-style `for ((init; cond; post))` prelude is dropped at conversion (🔴 security bypass)

**Symptom:** `rm -rf /etc/passwd` in a C-style loop init completely bypasses
every security pass:
```
evaluate_bash_command("for ((i=$(rm -rf /etc/passwd); i<1; i++)); do :; done",
                      {'*': 'allow', 'subshell': 'deny', 'blocked_paths_regex': ['/etc']})
#   -> allow          (bypass — the init command substitution actually runs)

# compare the regular for-list form (works correctly):
evaluate_bash_command("for i in $(rm -rf /etc/passwd); do :; done", ...)   # -> deny
```

**Root cause:** shfmt represents `for ((...))` as `ForClause` whose `Loop` is
`{Type: "CStyleLoop", Init, Cond, Post, ...}`. `_convert_for_clause`
(converter.py:545–569) only reads `Loop.Name`/`Loop.Items` (the `WordIter`
foreach form) and ignores `Init`/`Cond`/`Post`. The prelude's command/process
substitutions are therefore **dropped from the typed AST entirely**, and every
typed-AST pass misses them:
- `_has_cmd_subst` → `False` ⇒ the subshell policy does not fire;
- `_extract_subshell_contents` → `[]` ⇒ the blocked-path scan of subshell args
  is skipped;
- `_extract_segments` never sees the inner `CallExpr` ⇒ no segment is emitted.

This is a fail-open security issue, not just an accuracy gap.

### Dead code — `_convert_word_iter` is unreachable

`_convert_word_iter` (converter.py:819–830) + its dispatch entry
`"WordIter": _convert_word_iter` (`_CONVERTERS`, line 899) are never invoked:
shfmt emits `Type: "WordIter"` only inside `ForClause.Loop`, and
`_convert_for_clause` reads `Loop.Name`/`Loop.Items` inline, never routing the
loop through `node_from_json`. `node_from_json` is not exported, so no external
caller can reach the dispatch either. Remove the function, the dispatch entry,
and its now-unused import.

---

## Changes

### 1. `src/lovely_bash_permissions/ast.py` — `ForClause` gains a `cstyle` field

Add one field to `ForClause` (after `body`, ~line 453) so the C-style prelude
survives conversion and is reachable by every generic traversal
(`iter_children`, `_node_repr`, `structurally_equal`):

```python
@dataclass(slots=True, repr=False)
class ForClause(Node):
    var: str | None = None
    words: list[Word] = field(default_factory=list)
    body: list[Stmt] = field(default_factory=list)
    cstyle: CStyleLoop | None = None      # C-style for ((init; cond; post)) prelude
```

- `from __future__ import annotations` is present (line 25), so the forward
  reference to `CStyleLoop` (defined later, line 716) is safe.
- Appended last ⇒ no positional-construction call sites shift (all existing
  construction is keyword-based).
- `CStyleLoop` itself is unchanged: `init`, `cond`, `post` (no `body` — the
  loop body stays on `ForClause`).

### 2. `src/lovely_bash_permissions/converter.py`

**a. `_convert_for_clause` (545–569): preserve the C-style prelude.**

Branch on the loop payload type: `CStyleLoop` → route the whole `Loop` dict
through `node_from_json` (dispatches to the existing `_convert_cstyle_loop`,
833–841, which already tolerates absent `Init`/`Cond`/`Post` — `for ((;;))`
verified); otherwise keep the existing inline `WordIter` parsing:

```python
def _convert_for_clause(data: dict[str, Any]) -> ForClause:
    loop = data.get("Loop", {})
    var_name: str | None = None
    items: list[Word] = []
    cstyle: CStyleLoop | None = None

    if isinstance(loop, dict):
        if loop.get("Type") == "CStyleLoop":
            # for ((init; cond; post)): keep init/cond/post so their command
            # substitutions stay visible to every pass (security-critical).
            if (converted := node_from_json(loop)) is not None and isinstance(converted, CStyleLoop):
                cstyle = converted
        else:
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
    return ForClause(pos=pos, end=end, var=var_name, words=items, body=body, cstyle=cstyle)
```

**b. Remove the dead `WordIter` converter.**
- Delete `_convert_word_iter` (lines 819–830).
- Delete `"WordIter": _convert_word_iter,` from `_CONVERTERS` (line 899).
- Remove the now-unused `WordIter,` from the `from .ast import (...)` block
  (line 67).

Kept: the `WordIter` AST dataclass (ast.py:708) and its `__init__.py`
import/`__all__` entry (public, README-documented type), and the inline
`Loop.Name`/`Loop.Items` parsing above (the live path).

### 3. `src/lovely_bash_permissions/segments.py` — `_extract_segments`

**a. `ForClause`/`CStyleLoop` branch (372–376): recurse prelude, list, body.**

```python
elif isinstance(node, (ForClause, CStyleLoop)):
    # C-style prelude: for ((init; cond; post)) arithmetic may embed command
    # substitutions that bash evaluates — surface them before the body.
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

The `BinaryArithm`/`UnaryArithm`/`ParenArithm`/`ArithmExp` handlers (543–560)
already recurse operands and extract nested `CmdSubst`/`ProcSubst`; plain
literal arithmetic (e.g. `i=0`, `i<10`, `i++`) produces no segments.

**b. `BinaryTest` branch (393–401): also recurse the left operand.**

The left operand is the comparison *subject* (a value, regex, glob, number —
never a command to check), so recurse it **without** test-expr context so only
nested substitutions are extracted:

```python
elif isinstance(node, BinaryTest):
    # Left operand is the comparison subject (value/glob/regex/number) —
    # recurse WITHOUT test-expr context so nested command substitutions are
    # extracted but the operand itself is not emitted as a command.
    if hasattr(node, "left") and node.left:
        segments.extend(_extract_segments(node.left, _in_test_expr=False))
    if hasattr(node, "right") and node.right:
        in_test_expr = node.op in ("&&", "||")
        segments.extend(_extract_segments(node.right, _in_test_expr=in_test_expr))
```

**c. `Word` branch (490–498): drop the pseudo-command; always recurse parts.**

```python
elif isinstance(node, Word):
    # Word nodes (arguments) may contain CmdSubst/ProcSubst in their parts.
    # Always recurse: inside test expressions _in_test_expr is passed down so
    # bare Lit/SglQuoted/DblQuoted fragments still surface as pseudo-commands
    # while embedded substitutions are extracted as the real commands they run
    # (bug #6: no more "$(...)" / "$var" / "" phantom command names).
    for part in node.parts:
        segments.extend(_extract_segments(part, _in_test_expr=_in_test_expr))
```

**d. `DblQuoted` branch (511–518): same treatment.**

```python
elif isinstance(node, DblQuoted):
    # Double-quoted text may embed CmdSubst/ProcSubst/ParamExp parts.
    for part in node.parts:
        segments.extend(_extract_segments(part, _in_test_expr=_in_test_expr))
```

### 4. `tests/parsing/test_segments.py` — new regression tests

- `TestForLoopListSegments`:
  - `for i in $(seq 3); do echo $i; done` → `['seq', 'echo']`
  - `for f in a $(ls) b; do echo $f; done` → `['ls', 'echo']`
  - literal no-regression: `for i in 1 2 3; do echo hi; done` → `['echo']`
- `TestCStyleLoopSegments`:
  - `for ((i=$(seq 3); i < $n; i++)); do echo $i; done` → `seq` and `echo`
  - literal no-regression: `for ((i=0; i<10; i++)); do echo x; done` → `['echo']`
  - degenerate no-regression: `for ((;;)); do :; done` → `[':']` (`:` builtin body)
- `TestTestClauses` additions:
  - left-operand cmdsub: `[[ $(pwd) == /root* ]]` → `['pwd']`
  - both sides: `[[ $(a) == $(b) ]]` → `['a', 'b']`
  - no left phantom: `[[ -d /tmp && ls ]]` does not emit `d`/`tmp`
- Bug #6 regressions (in `TestTestClauseRegexOperands` / a dedicated class):
  - `[[ $(cmd) ]]` → `['cmd']` (was `['$(...)']`)
  - `[[ -f x && $(c2) ]] && echo and` → `['c2', 'echo']` (was `['$(...)', 'echo']`)
  - `[[ cond && "$(cmd)" ]]` → `['cmd']` (was `['']`)
  - `[[ $var ]]` / `[[ "$var" ]]` → `[]` (phantom `$var`/`''` removed)
  - confirm preserved: `[[ -d /tmp && ls ]]` → `['ls']`; `[[ foo ]]` → `['foo']`;
    `[[ $var =~ $(cmd) ]]` → `['cmd']`; `[[ $var =~ pat ]]` → `[]`

### 5. `tests/config/test_evaluate.py` — update + new regression tests

- Repoint `test_empty_segment_wildcard_ask` (line 269): the bug-#2 repro
  `[[ $(cat /etc/passwd) == x ]]` now produces a real `cat` segment and leaves
  the empty-segment path; use `[[ -f x ]]` instead and keep asserting
  `status == "ask"` and `"wildcard policy (ask)" in reason` (still exercises
  the empty-segment wildcard fallback).
- Add: `[[ $(cat /etc/passwd) == x ]]` under `{"*": "ask"}` → `ask` and
  `'"cat" command is not allowlisted' in reason` (bug #2 scenario now resolved
  via the normal segment path; verdict unchanged after the fix).
- Keep `test_empty_segment_blocked_subshell_denied` (line 278) — still `deny`
  (now via the real `cat` segment's blocked-path check); update docstring only.
- Add the 🔴 bypass regression: `for ((i=$(rm -rf /etc/passwd); i<1; i++));
  do :; done` with `{"*": "allow", "subshell": "deny", "blocked_paths_regex":
  [r"/etc"]}` → `deny` (assert it was previously `allow` in the docstring).
- Add: `_has_cmd_subst(parse('for ((i=$(date); i<1; i++)); do :; done'))` is
  `True` (prelude substitutions are visible again).

---

## Resulting segment behaviors (verified via in-memory simulation on real ASTs)

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

Verdict impact of removing the `$var`/`''` phantom pseudo-segments: **none** —
`[[ $var ]]` resolves identically in every wildcard config (ask/allow/deny)
via the empty-segment path; only segments/reasons change (consistent with the
bug #6 "don't name nonexistent commands" goal).

---

## Verification

1. `uv run ruff check .`
2. `uv run ruff format --check .`
3. `uv run mypy --strict .`
4. `uv run pytest -m 'not linting' -q` — expect all green; the two
   in-place-updated tests (`test_empty_segment_wildcard_ask`) are the only
   intentional assertion changes.
5. Manual security probe from the C-style bypass section confirms `deny`.

## Edge cases to keep intact

- Bare literal `[[ ... && ls ]]` / `[[ foo ]]` / `[[ cond && 'ls' ]]` still
  emit pseudo-command segments (via `Lit`/`SglQuoted` with `_in_test_expr`) —
  conservative `&&`/`||` right-operand behavior unchanged.
- Opaque `$(...)` handling in **arguments** (`evaluate._command_string` /
  `_match_allowed_patterns`) uses `_word_raw` placeholders — untouched; only
  test-expression pseudo-commands are affected.
- `subshell`/allowed/blocked passes in `evaluate.py` operate on the typed AST
  independently of segments; they now *also* see C-style preludes (strictly
  more coverage).
- Literal C-style arithmetic (`for ((i=0; i<10; i++))`) produces no segments —
  `test_cstyle_loop_extracted` and the devin CLI `-t` C-style tests unchanged.
- `rules.py` scans raw shfmt JSON (already saw prelude cmdsubs) — untouched.
- C-style prelude is baked into `ForClause.cstyle`; `iter_children`-based
  helpers (`get_commands`, `has_variable`, `has_pipe`, `get_redirections`,
  CLI tree) now traverse it too — matches shfmt ground truth.