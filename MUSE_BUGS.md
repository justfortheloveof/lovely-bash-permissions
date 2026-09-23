Tested `lovely-devin-permissions` via its CLI (`--test` + `lovely-bash-inspection`) against the effective config in this repo (`"*": "ask"`, `blocked_paths_regex = ["\\/etc", "\\.env$", "\\.envrc$"]`, `allowed_cmds_regex` incl. `^echo(\s+.*)?$`, `^cat\s+.+$`). All repros pass `bash -n`. Found 3 new mis-parsed/mis-evaluated cases (prior `NEW_BUGS.md` #1, #3, #4 and `BUGZ.md` #10 verified fixed; `BUGZ.md` #6 `python3 -m json.toolx` unanchored still reproduces).

## 1. Blocked paths inside `${...}` operands are dropped → false APPROVE

```bash
uv run lovely-devin-permissions --test 'echo /etc/passwd'            # → BLOCK (correct)
uv run lovely-devin-permissions --test 'echo ${BAR:-/etc/passwd}'    # → APPROVE (BUG)
uv run lovely-devin-permissions --test 'echo ${BAR:-foo.env}'        # → APPROVE (BUG, cf. `echo foo.env` → BLOCK)
uv run lovely-bash-inspection --string 'echo ${BAR:-/etc/passwd}'
# statement 1 `echo ${BAR:-/etc/passwd}`:
#   cmd: echo
#   args: $BAR        <-- default word lost
```

Same for `:- - :+ # % / //` forms (`${BAR-/etc/passwd}`, `${BAR+/etc/passwd}`, `${BAR#*/etc/*}`, `${x/a/\/etc\/passwd}` all APPROVE) and in assignments (`FOO=${BAR:-/etc/passwd}` → segments `['FOO=$BAR']`, blocked path lost; scalar `FOO=/etc/passwd` correctly BLOCKs).

**Root:** `inspect.py` `_word_value/_word_raw/_word_exec` render `ParamExp` as `$PARAM`; `evaluate.py` `_extract_subshell_contents` only extracts inner *commands*, never literal `exp.word`/`orig`/`replacement`/`index`/`slice` words. Fix: scan ParamExp operand words against `blocked_paths_regex` (or preserve them in segment args).

## 2. Array literals collapsed to `(...)` → blocked path missed

```bash
uv run lovely-devin-permissions --test 'FOO=/etc/passwd'  # → BLOCK (correct)
uv run lovely-devin-permissions --test 'A=(/etc/passwd)'  # → ASK (BUG; ALLOW under `"*": "allow"`)
uv run lovely-devin-permissions --test 'export A=(/etc/passwd foo)'  # → ASK (BUG; `export FOO=/etc/passwd` → BLOCK)
uv run lovely-bash-inspection --string 'A=(/etc/passwd)'
# statement 1 `A=(/etc/passwd)`:
#   assign: A=(...)   <-- elements lost
```

In-process with `"*": "allow"`: `A=(/etc/passwd)` → `allow`, `FOO=/etc/passwd` → `deny`.

**Root:** `segments.py` renders arrays as `f"{name}=(...)"` (`CallExpr` assigns, `DeclClause` operands). Blocked-path scan sees only the placeholder. Fix: include array element word values in the segment args / blocked scan.

## 3. `[[ ... ]]` operands produce no segments and skip blocked-path scan

```bash
uv run lovely-devin-permissions --test '[ -f /etc/passwd ]'    # → BLOCK (correct)
uv run lovely-devin-permissions --test 'test -f /etc/passwd'   # → BLOCK (correct)
uv run lovely-devin-permissions --test '[[ -f /etc/passwd ]]'  # → ASK (BUG; ALLOW under `"*": "allow"`)
uv run lovely-devin-permissions --test '[[ -f .env ]]'         # → ASK (BUG; `test -f .env` → BLOCK)
uv run lovely-bash-inspection --string '[[ -f /etc/passwd ]]'
# (no commands found)
```

**Root:** `segments.py` `UnaryTest`/`BinaryTest` recurse with `_in_test_expr=False`, so operands yield zero segments; `evaluate.py` empty-segment fallback only scans subshell contents + heredoc bodies, not test operands. Fix: run the blocked-path scan over `[[ ]]` operand words (or emit them as scannable values).
