# Implementation Plan: NEW_BUGS.md bugs 1–4

Base commit: `23341cc`. All steps build on it.

> **For the implementing agent:** every step is self-contained and small. Do ONE
> step per iteration. Locate edit sites by the exact **"Find"** code blocks —
> line numbers are approximate and drift; trust the code text, not numbers.
> Do not modify anything outside the files listed for the step. Verify with the
> **Probes** section before marking the step `done`.

## Hard rules (every step)

- **Commit hygiene:** NEVER commit `.fuzz/` or anything inside it (already in
  `.gitignore`). When committing a step, stage ONLY the files listed for that
  step (e.g. `git add src/lovely_bash_permissions/inspect.py PLAN.md`) —
  never `git add -A` / `git add .`. Other untracked noise (`.coverage`, etc.)
  must also never be committed.
- Run everything from the repo root with `uv run ...` (package is NOT
  pip-installed; bare `python -c "import lovely_bash_permissions"` fails).
- Probes containing `$`/quotes: use a quoted heredoc (`uv run python <<'EOF'`)
  so the shell touches nothing.
- Green gates at every step end: `uv run ruff check .` and
  `uv run mypy --strict .`. (`uv run ruff format --check .` may flag PLAN.md's
  markdown fences only — treat as OK if all real files are clean.)
- `uv run pytest -m 'not linting' -q` must be fully green at the end of every
  step (fix any test you broke; only a test may be changed if it encoded the
  bug being fixed, per that step's instructions).

## Bugs (from NEW_BUGS.md) and design decisions

1. **🔴 #1** quote-split (`/e"tc"/passwd`) and backslash-escape (`-ex\ec`)
   bypass `blocked_paths_regex` and negative-lookahead guard patterns, because
   `inspect.py:_word_raw` preserves interior quotes/backslashes and
   `evaluate.py:_strip_quotes` strips only whole-word outer quotes.
2. **🟠 #2** plain `( ... )` subshells are invisible to the `subshell` policy;
   that key actually gates only CmdSubst (`$(...)`, backticks) + ProcSubst
   (`<(...)`, `>(...)`).
3. **🔴 #3** redirection-only operands of `&&`/`||`/`|`/`|&`
   (e.g. `> /etc/x && cat file`) are dropped: shfmt emits them as operand
   dicts with `Redirs` but **no `Type` and no `Cmd`**, so
   `converter.py:node_from_json` degrades them to a generic `Node` and
   `segments.py` logs "Unhandled AST node type 'Node' - returning 0 segments".
4. **🟡 #4** redirection targets are rebuilt from `parts[0]` only in
   `rules.py` (6 sites), truncating multi-part targets (`"$DIR/out"`,
   `"/dev""/null"`, `$(pwd)/x`) — wrong reasons and a blocked-path dodge.

### Confirmed design decisions (do not revisit)

- **D1 — executed-form matching (bug #1):** allowed patterns are matched
  against the quote-normalized "executed" string **first**; this is what closes
  the negative-lookahead guard bypass, because the guard is evaluated on the
  text bash actually runs (`find /tmp -exec rm` trips `-e"x"ec`'s guard).
  A raw-form match is honored **only** when the pattern has no negative
  lookahead (`"(?!"` not in the pattern — the only shape interior
  quote-splits/backslash-escapes can dodge), which preserves patterns written
  with explicit quotes. **Union matching (raw OR norm, either counts) is
  WRONG and must NOT be used** — the raw form always satisfies the guard, so
  union still auto-approves the bypass (verified by replaying the regexes).
  Blocked-path checks (Step 3 item 5) are the exception: there "either form
  denies" is correct, since they are deny-style checks.
- **D2 — the "executed" form (`_word_exec`, bug #1/#4):**
  shfmt JSON facts (verified): an unquoted word `/e"tc"/passwd` parses to
  `Parts: [Lit("/e"), DblQuoted(Parts=[Lit("tc")]), Lit("/passwd")]`;
  `find /tmp -ex\ec` parses to a single `Lit("-ex\\ec")` (backslash literal in
  JSON); `cat "/e\tc/passwd"` parses to `DblQuoted(Parts=[Lit("/e\\tc/passwd")])`;
  a here-string `cat <<< /etc/shadow` has its text in `Word.Parts` (NOT `Hdoc`).
  `_word_exec(word: Word) -> str` rules per part:
  - `Lit` (top-level, unquoted): strip backslash escapes —
    `re.sub(r"\\([^\n])", r"\1", value)` (bash unquoted: `\x` → `x`).
  - `SglQuoted`: value verbatim (no unescaping, no expansion).
  - `DblQuoted`: if it has nested `parts`, recurse `_word_exec`-style over each
    nested part (nested `Lit`s get DOUBLE-QUOTE-context unescaping: only
    `\\([$`"\\]) → \1`, since inside `"..."` bash keeps other backslashes);
    if no nested parts, unescape its `.value` in double-quote context.
  - `ParamExp` → `$<param>`; `CmdSubst` → `$(...)`; `ArithmExp` → `$(( ... ))`;
    `ExtGlob` → its pattern text (keep the op if present, else just the
    pattern); `BraceExp` → `{...}`; `ProcSubst` → `<(...)` or `>(...)`.
  The result for `/e"tc"/passwd` is `/etc/passwd`; for `-ex\ec` it is `-exec`.
- **D3 — bug #2 key rework, NO backwards compatibility** (project unreleased,
  0 users): config keys become three: `command_substitution` (gates
  `$(...)`/backticks), `process_substitution` (gates `<(...)`/`>(...)`), and
  `subshell` (gates `( ... )`). The old single `subshell` key semantics is
  dropped; no alias, no deprecation. Every place that reads/writes the old key
  (schema, effective config, evaluator, tests, docs) is updated.
- **D4 — out of scope:** BUGZ.md bugs #6 and #10 are explicitly NOT fixed here
  (no tests assert their buggy behavior, so nothing breaks). Note: executed-form
  matching (Step 3) *incidentally* fixes #10 (`cat "$f"` → executed `cat $f`
  matches `^cat\s+.+$`). That is an acceptable bonus — do not add a regression
  test asserting the old false-ask.
  `rules.py:_find_background_flags` also uses `parts[0]` (line ~131) for the
  background *command name* — that is not a redirection target; leave it.
- **D5 — guard-authoring contract (documents D1's precondition):** negative-
  lookahead guards in `allowed_cmds_regex` must be written in **executed
  form** — the text after de-quoting and backslash unescaping. Flags that can
  be quote-split are covered with a character class (`["x]`, as in D1's
  `-e["x]ec`) or a plain executed-form token (as in
  `^find(?!.*\s-(exec|delete|ok)\b)`). A guard containing a **literal** quote
  character (e.g. `(?!.*-e"xec)`) can never trip on the normalized text,
  which contains no quotes, so the pattern would auto-approve its own target
  (and a backslash-escaped spelling dodges it in the raw form too, so
  intersection matching would not save it either). This is a pattern-authoring
  error; the convention is documented in Step 7, not enforced in code.

---

## Step 0 — Baseline gate

**Status:** done — all gates green (1078 passed, ruff/mypy clean, `.fuzz` IGNORED), all 4 bug repros confirmed.

**Files:** none (verification only; commit `PLAN.md` only).

1. From repo root run and confirm all green:
   - `uv run pytest -m 'not linting' -q`
   - `uv run ruff check .`
   - `uv run mypy --strict .`
   - `git check-ignore -q .fuzz && echo IGNORED` (must print IGNORED; if not,
     the `.fuzz/` line is missing from `.gitignore` — report and stop.)
2. Confirm the bug repros still reproduce (expected today):
   ```bash
   uv run python <<'EOF'
   from lovely_bash_permissions.evaluate import evaluate_bash_command as ev
   print(ev('cat /e"tc"/passwd',  {"*":"allow","blocked_paths_regex":["\\/etc"]}))
   # today: allow  (should be deny after step 3)
   print(ev('( rm x )', {"*":"allow","subshell":"deny"}))
   # today: allow  (should be deny after step 6)
   print(ev('> /etc/x && cat file', {"*":"allow","blocked_paths_regex":["\\/etc"],
         "allowed_cmds_regex":["^cat\\s+.+$"]}))
   # today: allow  (should be deny after step 5)
   print(ev('echo hi > "$DIR/out.txt"', {"*":"allow","output_redirection":"allow"}))
   # today: allow ... to /out.txt (should be ... to $DIR/out.txt after step 4)
   EOF
   ```

**Acceptance:** commands pass, repros confirmed. **Commit:** `git add PLAN.md` →
commit `plan: NEW_BUGS 1-4 implementation plan`.

---

## Step 1 — `inspect.py`: add `_word_exec` (executed-form renderer)

**Status:** done — `_word_exec`/`_exec_part`/`_unescape_lit` added; TestWordExec (9 cases) passes; probes verified; suite 1087 passed; ruff/mypy clean.

**Files:** `src/lovely_bash_permissions/inspect.py`,
`tests/parsing/test_inspect.py`

**What to do:**

1. Add, right after the `_word_raw` function (Find anchor — insert after its
   closing `return "".join(parts)`):

   ```python
   def _word_raw(word: Word) -> str:
       """Get the raw text of a word, preserving quotes.

       Unlike _word_value, this includes quote characters for quoted parts,
       so patterns like ^echo\\s+'hello' can match quoted arguments.
       """
   ```

   add these two helpers (place BEFORE `_word_raw` so it can call `_word_exec_part`):

   ```python
   _UNESCAPE_UNQUOTED = re.compile(r"\\([^\n])")
   _UNESCAPE_DBLQUOTED = re.compile(r"\\([$`\"\\])")


   def _unescape_lit(value: str, *, in_double_quotes: bool) -> str:
       """Bash-style backslash unescaping for a Lit value.

       Unquoted: a backslash drops the next character (bash rule).
       Double-quoted: a backslash is only special before $, `, ", \\ (and
       newline); elsewhere it is literal.
       """
       if in_double_quotes:
           return _UNESCAPE_DBLQUOTED.sub(r"\1", value)
       return _UNESCAPE_UNQUOTED.sub(r"\1", value)
   ```

   and add `import re` at the top of the module.

2. Add `_word_exec(word: Word) -> str` immediately after `_word_raw`:
   - docstring: "Best-effort *executed* form of a word: the string bash would
     produce after quote removal and backslash unescaping (placeholders kept
     for expansions). Used for security pattern matching so quote-split or
     backslash-escaped spellings of a path/flag cannot bypass the raw form."
   - implementation: iterate `word.parts`; for each part:
     - `Lit` → `_unescape_lit(part.value, in_double_quotes=False)`
     - `SglQuoted` → `part.value`
     - `DblQuoted` → if `part.parts` non-empty: recurse into each nested part
       using the same rule table as the outer level but with
       `in_double_quotes=True` for nested `Lit`s and skipping SglQuoted/other
       wrappers (a `DblQuoted` nested inside a `DblQuoted` is treated like its
       own part list); otherwise
       `_unescape_lit(part.value or "", in_double_quotes=True)`
     - `ParamExp` → `f"${part.param}"`
     - `CmdSubst` → `"$(...)"`
     - `ArithmExp` → `"$(( ... ))"`
     - `ExtGlob` → `part.pattern.value if part.pattern else ""`
     - `BraceExp` → `"{...}"`
     - `ProcSubst` → `f"{part.op}...)"`
   - Simplest faithful structure: implement a small recursive helper
     `_exec_part(part: Node, in_double_quotes: bool) -> str` and have
     `_word_exec(word)` join `_exec_part(p, False)` for each part.

3. Tests — append a `TestWordExec` class to `tests/parsing/test_inspect.py`.
   Build words with `parse_ast` from `lovely_bash_permissions.converter` and
   pull the argument Word out of the CallExpr (there are existing helpers in
   that test file — mirror its style), OR build dataclasses directly
   (`Word(parts=[Lit(value="...")])` — `Lit`, `SglQuoted`, `DblQuoted` all
   accept plain values; a nested-part DblQuoted is
   `DblQuoted(parts=[Lit(value="tc")], value=None)`). Cases:
   - `Lit("/e") + DblQuoted(Lit "tc") + Lit("/passwd")` → `/etc/passwd`
   - single `Lit("-ex\\ec")` (Python literal `-ex\ec`) → `-exec`
   - `DblQuoted(parts=[Lit("/e\\tc/passwd")])` (JSON/Python `/e\tc/passwd`) →
     `/e\tc/passwd` UNCHANGED: inside `"..."` bash only unescapes `$ \` " \ and
     newline, so `\t` keeps its backslash. Assert exactly the two-char sequence
     `"/e\\tc/passwd"` in Python source.
   - `SglQuoted('"a\\b"')` → `"a\b"` verbatim (no unescaping)
   - `ParamExp(param="DIR") + Lit("/out.txt")` → `$DIR/out.txt`
   - `CmdSubst` part + `Lit("/x")` → `$(...)/x`
   - plain `Lit("hello")` → `hello`

**Probes:**

```bash
uv run python <<'EOF'
from lovely_bash_permissions.ast import Word, Lit, DblQuoted, SglQuoted, ParamExp
from lovely_bash_permissions.inspect import _word_exec
print(_word_exec(Word(parts=[Lit(value="/e"), DblQuoted(parts=[Lit(value="tc")], value=None), Lit(value="/passwd")])))  # /etc/passwd
print(_word_exec(Word(parts=[Lit(value=r"-ex\ec")])))  # -exec
print(_word_exec(Word(parts=[SglQuoted(value=r'"a\b"')])))  # "a\b"
print(_word_exec(Word(parts=[ParamExp(param="DIR"), Lit(value="/out.txt")])))  # $DIR/out.txt
EOF
```

**Acceptance:** probes print the four expected strings; `TestWordExec` passes;
full pytest/ruff/mypy green. **Commit:** stage only the two files + `PLAN.md`.

---

## Step 2 — `segments.py`: normalized args + full redir targets

**Status:** done — `normalized_arguments` + redir `Target` added; tests pass (note: the plan said `normalized_arguments[0] == "-exec"` for `find /tmp -ex\ec rm`, but `/tmp` is index 0 — the agent correctly asserted index 1); suite 1091 passed; ruff/mypy clean.

**Files:** `src/lovely_bash_permissions/segments.py`,
`tests/parsing/test_segments.py`

**What to do:**

1. Import `_word_exec` alongside the existing import:
   Find: `from .inspect import _word_raw, _word_value`
   Replace with: `from .inspect import _word_exec, _word_raw, _word_value`

2. In `_redir_dicts`, add a full reconstructed target per redir.
   Find (inside `_redir_dicts`'s return list comprehension, per-dict body):

   ```python
         {
             "Op": r.op,
             "N": {"Value": str(r.n)} if r.n is not None else {},
             "Word": {"Parts": [{"Value": _part_value(p)} for p in (r.word.parts if r.word else [])]},
         }
   ```

   Convert to an explicit loop that also computes the target:

   ```python
   redir_dicts: list[dict[str, Any]] = []
   for r in redirs or []:
       redir_dicts.append(
           {
               "Op": r.op,
               "N": {"Value": str(r.n)} if r.n is not None else {},
               "Word": {"Parts": [{"Value": _part_value(p)} for p in (r.word.parts if r.word else [])]},
               # Full executed-form target (all word parts, quotes removed,
               # backslashes unescaped) so multi-part targets like "$DIR/out",
               # "/dev""/null" or quote-split paths are identified correctly.
               "Target": _word_exec(r.word) if r.word is not None else "",
           }
       )
   return redir_dicts
   ```

3. In the `CallExpr` branch of `_extract_segments`, the real command segment
   currently is:

   ```python
             segments.append(
                 {
                     "command": _word_value(node.args[0]),
                     "arguments": [_word_raw(arg) for arg in node.args[1:]],
                     "redirections": redir_dicts,
                 }
             )
   ```

   Add a parallel normalized list (raw list unchanged — it is displayed by
   CLI/hook consumers):

   ```python
             segments.append(
                 {
                     "command": _word_value(node.args[0]),
                     "arguments": [_word_raw(arg) for arg in node.args[1:]],
                     "normalized_arguments": [_word_exec(arg) for arg in node.args[1:]],
                     "redirections": redir_dicts,
                 }
             )
   ```

   No other segment kinds (DeclClause/assignment/test pseudo-commands) get
   `normalized_arguments` — they carry no plain Word args; consumers must use
   `.get("normalized_arguments", args)`.

4. Tests in `tests/parsing/test_segments.py`:
   - `parse_segments('cat /e"tc"/passwd')` → one segment whose
     `normalized_arguments == ["/etc/passwd"]` and raw `arguments == [ '/e"tc"/passwd' ]`.
   - `parse_segments('find /tmp -ex\\ec rm')` (write as Python `"find /tmp -ex\\ec rm"`)
     → `normalized_arguments[0] == "-exec"`.
   - `parse_segments('echo hi > "$DIR/out.txt"')` → segment's redirections
     `[0]["Target"] == "$DIR/out.txt"`; `parse_segments('echo hi 2>"/dev""/null"')`
     → `Target == "/dev/null"`.

**Acceptance:** new tests pass; full suite green. **Commit:** the two files + `PLAN.md`.

---

## Step 3 — `evaluate.py`: executed-form matching for argv, guards, heredoc bodies (bug #1)

**Status:** done — all 7 code changes in evaluate.py verified in diff (`_word_exec` import, `_match_allowed_patterns` executed-form matching, AST-walk + per-segment norm args, blocked raw+normalized, subshell-content exec forms, `_block_scan_variants` in both heredoc sites); `TestExecutedFormMatching` (13 table rows + heredoc + safe-find union guard) added; all 14 acceptance probes pass; suite 1105 passed; ruff/mypy clean. (Worker `step3_worker` died on an inference-server 503 after finishing — orchestrator verified and committed independently.)

**Files:** `src/lovely_bash_permissions/evaluate.py`,
`tests/config/test_evaluate.py`

**What to do:**

1. Import `_word_exec` (Find: `from .inspect import _traverse, _word_raw, _word_value, iter_children`
   → add `_word_exec`).

2. Extend `_match_allowed_patterns` for executed-form matching.
   Find:

   ```python
   def _match_allowed_patterns(name: str, args: list[str], allowed_patterns: list[str]) -> list[str]:
       """Return the allowed patterns matched by this command (name + args).

       Matches are rejected when opaque ``$(...)`` arguments could change the
       pattern's verdict - see :func:`_opaque_match_unreliable`.  Such commands
       are treated as not allowed, requesting approval instead of auto-approving.
       """
       full = _command_string(name, args)
       has_opaque = any("$(...)" in a for a in args)
       matched: list[str] = []
       for pattern in allowed_patterns:
           if not re.search(pattern, full):
               continue
           if has_opaque and _opaque_match_unreliable(pattern):
               continue
           matched.append(pattern)
       return matched
   ```

   Replace with a version that takes an optional normalized arg list and matches
   against the executed string first (executed-form matching, NOT raw-OR-norm union):

   ```python
   def _match_allowed_patterns(
       name: str, args: list[str], allowed_patterns: list[str], normalized_args: list[str] | None = None
   ) -> list[str]:
       """Return the allowed patterns matched by this command (name + args).

       Executed-form matching: when *normalized_args* is given the pattern is
       matched against the quote-normalized "executed" command string first, so
       the negative lookaheads (``(?!...``) in guard patterns are evaluated on
       the text bash actually runs - interior quote splits / backslash escapes
       (``-e"x"ec``) therefore cannot dodge them. A raw-only match is honored
       ONLY when the pattern contains no negative lookahead (the only shape a
       split text can fake), preserving patterns written with explicit quotes.

       Matches are rejected when opaque ``$(...)`` arguments could change the
       pattern's verdict - see :func:`_opaque_match_unreliable`.  Such commands
       are treated as not allowed, requesting approval instead of auto-approving.
       """
       full = _command_string(name, args)
       norm_full = _command_string(name, normalized_args) if normalized_args is not None else None
       has_opaque = any("$(...)" in a for a in args)
       matched: list[str] = []
       for pattern in allowed_patterns:
           if norm_full is not None:
               hit = re.search(pattern, norm_full) is not None
               if not hit and "(?!" not in pattern:
                   # Executed form missed but no guard could be faked - honor
                   # a raw-form match (quoted-pattern compatibility).
                   hit = re.search(pattern, full) is not None
           else:
               hit = re.search(pattern, full) is not None
           if not hit:
               continue
           if has_opaque and _opaque_match_unreliable(pattern):
               continue
           matched.append(pattern)
       return matched
   ```

3. In the AST-walk closure (Find: `matched = _match_allowed_patterns(name, raw_args, allowed_patterns)`),
   pass the normalized args:

   ```python
                   raw_args = [_word_raw(a) for a in node.args[1:]]
                   matched = _match_allowed_patterns(name, raw_args, allowed_patterns)
   ```

   becomes:

   ```python
                   raw_args = [_word_raw(a) for a in node.args[1:]]
                   exec_args = [_word_exec(a) for a in node.args[1:]]
                   matched = _match_allowed_patterns(name, raw_args, allowed_patterns, exec_args)
   ```

4. In the per-segment loop (Find: `matched_patterns = _match_allowed_patterns(cmd_name, args, allowed_patterns)`):

   ```python
           norm_args = segment.get("normalized_arguments", args)
           matched_patterns = _match_allowed_patterns(cmd_name, args, allowed_patterns, norm_args)
   ```

5. Blocked-path checks on segment args — check raw AND normalized.
   Find:

   ```python
         if blocked_patterns:
             matched, pattern, value = check_blocked_patterns(cmd_name, args, blocked_patterns)
   ```

   becomes:

   ```python
         if blocked_patterns:
             matched, pattern, value = check_blocked_patterns(cmd_name, args, blocked_patterns)
             if not matched:
                 norm_args = segment.get("normalized_arguments")
                 if norm_args is not None and norm_args != args:
                     matched, pattern, value = check_blocked_patterns(cmd_name, norm_args, blocked_patterns)
   ```

6. Subshell-content extraction (Find: `contents.append(_word_value(arg))` inside
   `_extract_subshell_contents`) — also append the executed form:

   ```python
                   for arg in stmt.cmd.args:
                       raw = _word_value(arg)
                       execd = _word_exec(arg)
                       if raw not in contents:
                           contents.append(raw)
                       if execd != raw and execd not in contents:
                           contents.append(execd)
   ```

7. Heredoc body scanning — add a quote/backslash-stripped variant of each
   candidate in BOTH scan sites. Add a module-level helper near
   `_heredoc_body_texts`:

   ```python
   def _block_scan_variants(text: str) -> list[str]:
       """Raw text plus a conservative quote/backslash-stripped variant.

       Stripping `'`, `"` and backslashes turns split spellings like
       ``/e"tc"/passwd`` into the executed path so blocked patterns catch
       them; it is a superset (it can over-match, never under-match).
       """
       stripped = re.sub(r"['\"\\]", "", text)
       return [text, stripped] if stripped != text else [text]
   ```

   Then at BOTH heredoc scan sites (the empty-segment block — Find:
   `candidates = [body] + [ln.strip() for ln in body.splitlines() if ln.strip()]`
   appears twice; change both occurrences) replace with:

   ```python
                 candidates = []
                 for ln in [body, *[ln.strip() for ln in body.splitlines() if ln.strip()]]:
                     candidates.extend(_block_scan_variants(ln))
   ```

**Tests** (append to `tests/config/test_evaluate.py`; the file has a
`make_config`-style fixture in `tests/config/conftest.py` with params
`wildcard, subshell, ...` — use it or build plain dicts):

With config
`{"*":"ask","blocked_paths_regex":["\\/etc","\\.env$"],"allowed_cmds_regex":[r"^cat\s+.+$", r"^find(?!.*\s-(exec|delete|ok)\b).*$", r"^fd(?!.*\s+(-x|-X)).*$", r"^sort(?!\s+(-o|--output)\b).*$"]}`
(each repro asserts the fixed behavior). Wildcard must be `"ask"` (mirrors the
user's real config): under `"*":"allow"` a guard-tripped command falls through
to the allow wildcard and reads `allow`, not `ask` — use `*:ask` so the intent
"guard-trip → not auto-approved → ask" is observable. Note some rows are `deny`
via the blocked-path check on the *normalized* arg (e.g. `ls -la /e"tc"` →
`/etc`), which is exactly the fix:

| command | expected status |
|---|---|
| `cat /e"tc"/passwd` | deny (blocked `/etc/passwd`) |
| `ls -la /e"tc"` (ls NOT in allowlist) | deny (blocked `/etc` on normalized arg) |
| `grep x /e"tc"/passwd` (grep not allowed) | deny (blocked `/etc/passwd`) |
| `cat .e"nv"` | deny (blocked `.env` on normalized arg) |
| `find /tmp -e"x"ec rm` | ask (guard trips on executed form → not allowed → wildcard) |
| `find /tmp -"exec" rm` | ask |
| `find /tmp -ex\\ec rm` (Python: `"find /tmp -ex\\ec rm"`) | ask |
| `fd -"x" x` | ask |
| `sort -"o" /tmp/out x` | ask |
| contrast: `cat /etc/passwd` | deny (already) |
| contrast: `cat "ok file"` | allow (plain quoted arg still matches `^cat\s+.+$`) |
| `python3`-free heredoc: `"cat f <<EOF\nsecret /e\"tc\"/passwd\nEOF"` | deny |
| `cat .env` | deny (contrast, already) |

For contrast, the pre-existing `test_single_quoted_safe_command_still_allowed`
(`find . -name '*.txt'` → allow) must STILL pass: the executed form
`find . -name *.txt` satisfies the guard, so a safe find remains auto-approved —
only the split/escaped `exec`/`delete`/`ok` spellings stop matching. This also
guards against the union-matching regression (D1).

**Acceptance:** all new tests pass; the pre-existing whole-word quote tests
(`'-exec'` / `"-o"` / `'-X'` block near the end of the file) still pass; full
suite/ruff/mypy green. **Commit:** the two files + `PLAN.md`.

---

## Step 4 — `rules.py`: full redirection targets (bug #4)

**Status:** done — `_raw_word_target`/`_redir_target` added after DEV_NULL; all 6 truncation sites replaced with `_redir_target` (7th `parts[0]` in `_find_background_flags` left untouched, line ~174); 6 tests added to tests/config/test_rules.py; `tests/redirections/test_output_redirection_validation.py` needed no change; all 6 probes pass; suite 1111 passed; ruff/mypy clean.

**Files:** `src/lovely_bash_permissions/rules.py`,
`tests/config/test_rules.py`, and (only if a test encodes the old truncated
behavior) `tests/redirections/test_output_redirection_validation.py`

**What to do:**

1. Add two helpers after `DEV_NULL`:

   ```python
   def _raw_word_target(word: dict[str, Any]) -> str:
       """Reconstruct a full redirection target from a raw shfmt Word dict.

       Joins ALL parts (not just the first) so multi-part targets like
       ``"$DIR/out"`` or ``"/dev""/null"`` are identified. Lit values are
       backslash-unescaped (unquoted context); DblQuoted parts use their
       best-effort ``Value`` or their nested parts.
       """
       import re as _re

       chunks: list[str] = []
       for part in word.get("Parts", []) if isinstance(word, dict) else []:
           if not isinstance(part, dict):
               continue
           ptype = part.get("Type")
           if ptype == "Lit":
               chunks.append(_re.sub(r"\\([^\n])", r"\1", part.get("Value", "")))
           elif ptype == "SglQuoted":
               chunks.append(part.get("Value", ""))
           elif ptype == "DblQuoted":
               if part.get("Parts"):
                   for sub in part["Parts"]:
                       if isinstance(sub, dict):
                           chunks.append(str(sub.get("Value", "")))
               else:
                   chunks.append(part.get("Value") or "")
           else:
               v = part.get("Value")
               if isinstance(v, str):
                   chunks.append(v)
       return "".join(chunks)


   def _redir_target(redir: dict[str, Any]) -> str:
       """Best redirection target for policy decisions.

       Prefers the segment-level ``Target`` key (full executed form, produced
       by segments.py); falls back to reconstructing from raw Word parts.
       """
       t = redir.get("Target")
       if isinstance(t, str) and t:
           return t
       return _raw_word_target(redir.get("Word", {}) or {})
   ```

   (Move `import re` to module top — `re` is already imported there; just use
   it directly and drop the local import.)

2. Replace every redirection-target `parts[0].get("Value", "")` with the
   helper. The 6 sites (verify each by context; the 7th occurrence in
   `_find_background_flags` is a command NAME — DO NOT change it):
   - `classify_output_redirection`: Find
     ```python
         # Determine target value from first part's Value (filename)
         if parts:
             target = parts[0].get("Value", "")
     ```
     replace with `target = _redir_target(redir)` (delete the now-unused
     `parts`/`word` locals above it if they become dead code — keep the `N`
     extraction untouched).
   - `check_output_redirection`: Find
     ```python
         for redir in redirections:
             target_word = redir.get("Word", {})
             parts = target_word.get("Parts", [])
             if parts:
                 targets.append(parts[0].get("Value", ""))
     ```
     → `targets.append(_redir_target(redir))` for each redir.
   - `check_input_redirection`: Find
     ```python
             target = ""
             word = redir.get("Word", {})
             parts = word.get("Parts", [])
             if parts:
                 target = parts[0].get("Value", "")
             redirections.append({"op": op, "target": target})
     ```
     → `redirections.append({"op": op, "target": _redir_target(redir)})`.
   - `_check_segments_output_redirs` (dedupe loop): Find
     ```python
                 word = r.get("Word", {})
                 parts = word.get("Parts", [])
                 target = parts[0].get("Value", "") if parts else ""
     ```
     → `target = _redir_target(r)`.
   - `_check_segments_output_redirs` (targets loop): Find
     ```python
         for redir in redirections:
             word = redir.get("Word", {})
             parts = word.get("Parts", [])
             if parts:
                 targets.append(parts[0].get("Value", ""))
             kinds.extend(classify_output_redirection(redir))
     ```
     → `targets.append(_redir_target(redir)); kinds.extend(...)`.
   - `_check_segments_input_redirs`: Find
     ```python
                 word = r.get("Word", {})
                 target = ""
                 parts = word.get("Parts", [])
                 if parts:
                     target = parts[0].get("Value", "")
     ```
     → `target = _redir_target(r)`.

3. Tests in `tests/config/test_rules.py` (these call `evaluate_bash_command`
   or the rules functions directly — match the file's existing style; if the
   file tests segment-level helpers, use `parse_segments` from
   `lovely_bash_permissions.segments` to build segment input):
   - `evaluate_bash_command('echo hi > "$DIR/out.txt"', {"*":"allow","output_redirection":"allow"})`
     → reason contains `$DIR/out.txt` (not `/out.txt`).
   - `evaluate_bash_command('echo hi > "a""b"', {"*":"allow","output_redirection":"allow"})`
     → reason contains `ab`.
   - `evaluate_bash_command('echo hi 2>"/dev""/null"',
       {"*":"allow","output_redirection":{"*":"ask","stderr_to_dev_null":"allow"}})`
     → status **allow** (classification fixed).
   - `evaluate_bash_command('echo hi > /e"tc"/x', {"*":"allow","blocked_paths_regex":["\\/etc"],"output_redirection":"allow"})`
     → **deny** (quote-split redir target caught).
   - `evaluate_bash_command('cat <<< /e"tc"/shadow', {"*":"allow","input_redirection":"allow","blocked_paths_regex":["\\/etc"]})`
     → **deny** (here-string target caught).
   - `evaluate_bash_command('echo hi > $(pwd)/out.txt', {"*":"allow","output_redirection":"allow"})`
     → reason contains `$(...)/out.txt`.

**Acceptance:** new tests pass; run `uv run pytest tests/redirections -q` and
fix any expectation that hardcoded a truncated target (only such expectations
may change); full suite green. **Commit:** listed files + `PLAN.md`.

---

## Step 5 — `converter.py`: redir-only compound operands (bug #3)

**Status:** done — converter.py redir-only branch (`_convert_stmt` for no-Type+Redirs dicts) and `_find_redirs` no-Type branch added (guarded `not node.get("Type")` — no duplication, confirmed by suite); `TestRedirectionOnlyOperands` added to both test files (segments: 2 segments with `command==""` + `Op==">"` `Target=="/etc/x"`; evaluate: all 7 rows incl. contrast + all-redir); all 10 probes pass; suite 1121 passed; ruff/mypy clean.

**Files:** `src/lovely_bash_permissions/converter.py`,
`src/lovely_bash_permissions/rules.py`,
`tests/parsing/test_segments.py`, `tests/config/test_evaluate.py`

**Background (verified):** shfmt emits `> /etc/x && cat file` as
`BinaryCmd{X: {Redirs: [...]}, Y: {Cmd: CallExpr}}` — the `X` operand dict has
**no `Type` and no `Cmd`**, so `node_from_json` falls through to the generic
`Node` and the redirection vanishes from segments.

**What to do:**

1. `converter.py` — in `node_from_json`, after the existing "Cmd but no Type"
   shortcut. Find:

   ```python
         # Handle nodes that have 'Cmd' but no 'Type' (wrapped statements)
         if not node_type and "Cmd" in data:
             return node_from_json(data["Cmd"])

         converter = _CONVERTERS.get(node_type)
   ```

   insert between the shortcut and the converter lookup:

   ```python
         # Redirection-only operand of a compound (e.g. `> /etc/x && cat f`):
         # shfmt emits a dict with Redirs but no Type and no Cmd. Convert it as
         # a Stmt(cmd=None) so segments.py emits the synthetic redir-only
         # segment it already supports for top-level statements - otherwise the
         # redirection is silently dropped and bypasses all redir/blocked-path
         # checks (NEW_BUGS #3).
         if not node_type and "Redirs" in data:
             return _convert_stmt(data)
   ```

2. `rules.py` — `_find_redirs` parity for the same shape in raw-JSON walks.
   Find:

   ```python
     redirs: list[dict[str, Any]] = []

     # CallExpr has Redirs directly on the node itself
   ```

   insert before the `# CallExpr...` comment:

   ```python
   # Redirection-only compound operand (no Type/Cmd, just Redirs) - see
   # converter.node_from_json handling for `> f && cmd` (NEW_BUGS #3).
   if not node.get("Type") and node.get("Redirs"):
       redirs.extend(node["Redirs"])
   ```

   Note: this branch is belt-and-braces for the raw-JSON walk; `_find_redirs`
   already collects binary X/Y redirs via `x.get("Redirs")` (rules.py:79-80).
   Keep it only if it doesn't duplicate entries for operands that DO carry a
   `Type` (e.g. a redirection on a `CallExpr` operand is handled by the
   `Type == "CallExpr"` branch). Verify no double-collection after adding it;
   delete it if redundant.

   Known cosmetic duplication (DO NOT chase it): after the converter fix, a
   redir-only operand becomes `Stmt(cmd=None)` whose redirs are also lifted into
   `BinaryCmd.left_redirs` by `_convert_binary_cmd` (converter.py:486) *and*
   re-merged by the segments `Stmt` branch (`inherited = redirs + node.redirs`).
   The synthetic segment therefore carries the redirection up to ~3×. Policy
   outcome is unaffected (same redir checked repeatedly; `_check_segments_output_redirs`
   dedupes) and the new tests assert `redirections[0]`, so leave it — but do NOT
   assert the exact `len(redirections)` anywhere.

3. Tests:
   - `tests/parsing/test_segments.py`: `parse_segments('> /etc/x && cat file')`
     → 2 segments; the first has `command == ""`, empty arguments, and one
     redirection with `Op == ">"` and `Target == "/etc/x"`; same check for
     `'true | > /etc/x'` (redir on the second segment) and
     `'cat file || > /etc/x'`.
   - `tests/config/test_evaluate.py` (config
     `{"*":"allow","blocked_paths_regex":["\\/etc"],"allowed_cmds_regex":[r"^cat\s+.+$"]}`):
     | command | expected |
     |---|---|
     | `> /etc/x && cat file` | deny |
     | `> /etc/x \| true` | deny (true not allowlisted → ask on its own, but redir blocked → deny) |
     | `true \| > /etc/x` | deny |
     | `cat file && > /etc/y` | deny |
     | `2>/etc/e \| true` | deny |
     | contrast `> /tmp/ok && cat file` | allow (cat allowed, redir not blocked; output_redirection unset → ask! use config with `"output_redirection":"allow"` to get allow) |
     For the contrast row, include `"output_redirection":"allow"` in that test's config.
   - Also assert the whole-all-redir case with
     `{"*":"allow","blocked_paths_regex":["\\/etc"],"output_redirection":"allow"}`:
     `'> /etc/x && > /etc/y'` → deny (previously fell to wildcard allow).

**Acceptance:** probes show the segments contain the redir; new tests pass;
full suite green (top-level `'> /etc/x'` behavior unchanged — covered by
existing tests). **Commit:** listed files + `PLAN.md`.

---

## Step 6 — bug #2: split config keys (schema, effective config, evaluator)

**Status:** done (two workers: 6a src, 6b tests) — schema/effective_bash/evaluate.py split into `command_substitution`/`process_substitution`/`subshell`; `_subst_flags` detector (3 flags); three independent gates; `Subshell` counts as nesting in the allowed-pattern walk; reason strings updated; `_has_cmd_subst` kept as a thin wrapper (a unit test imports it). Tests remapped semantically (conftest: `command_substitution` param + optional `subshell` param; test_evaluate.py ~60 sites; test_nested_redirections.py 1 site; test_effective_bash.py/test_schema.py left as-is — the `subshell` key is still valid for paren groups, those tests never went red). All 6 step-6 probes pass; suite 1121 passed; ruff/mypy clean.

**Files:** `src/lovely_bash_permissions/config/schema.py`,
`src/lovely_bash_permissions/config/effective_bash.py`,
`src/lovely_bash_permissions/evaluate.py`

**Decisions (D3):** three keys, no back-compat.
- `command_substitution` — gates `$(...)` and backticks (the OLD `subshell`
  behavior for CmdSubst).
- `process_substitution` — gates `<(...)` / `>(...)` (previously lumped into
  old `subshell`).
- `subshell` — NEW: gates `( ... )` paren groups.

**What to do:**

1. `schema.py`. Find:
   ```python
       subshell: PermissionLevel | None = None
       variable_assignment: PermissionLevel | None = None
   ```
   Replace with:
   ```python
       #: Policy for $(...) / backtick command substitutions.
       command_substitution: PermissionLevel | None = None
       #: Policy for <(...) / >(...) process substitutions.
       process_substitution: PermissionLevel | None = None
       #: Policy for ( ... ) subshell groups.
       subshell: PermissionLevel | None = None
       variable_assignment: PermissionLevel | None = None
   ```

2. `effective_bash.py`. Find:
   ```python
             "error": _resolve("error"),
             "subshell": _resolve("subshell"),
   ```
   Replace with:
   ```python
             "error": _resolve("error"),
             "command_substitution": _resolve("command_substitution"),
             "process_substitution": _resolve("process_substitution"),
             "subshell": _resolve("subshell"),
   ```

3. `evaluate.py` — detectors. Replace `_has_cmd_subst` (Find its full def,
   `def _has_cmd_subst(tree: dict[str, Any]) -> bool:` … its `return False`)
   with one detector returning all three flags:

   ```python
   def _subst_flags(tree: dict[str, Any]) -> dict[str, bool]:
       """Detect which of the three substitution/subshell constructs appear.

       Returns ``{"command_substitution": bool, "process_substitution": bool,
       "subshell": bool}`` where the flags mark ``$(...)``/backticks,
       ``<(...)``/``>(...)``, and ``( ... )`` paren groups respectively.
       Uses typed-AST traversal so constructs nested inside quoted strings
       are detected too.
       """
       from .ast import Subshell

       ast = node_from_json(tree)
       if ast is None:
           return {"command_substitution": False, "process_substitution": False, "subshell": False}

       found = {"command_substitution": False, "process_substitution": False, "subshell": False}

       def visitor(node: Node) -> None:
           if isinstance(node, CmdSubst):
               found["command_substitution"] = True
           elif isinstance(node, ProcSubst):
               found["process_substitution"] = True
           elif isinstance(node, Subshell):
               found["subshell"] = True

       _traverse(ast, visitor, recurse_call_expr_args=True)
       return found
   ```

4. `evaluate.py` — rules dict. Find:
   ```python
         "background_execution": _resolve_level(config, "background_execution"),
         "subshell": _resolve_level(config, "subshell"),
   ```
   Replace with:
   ```python
         "background_execution": _resolve_level(config, "background_execution"),
         "command_substitution": _resolve_level(config, "command_substitution"),
         "process_substitution": _resolve_level(config, "process_substitution"),
         "subshell": _resolve_level(config, "subshell"),
   ```

5. `evaluate.py` — main flow. Find:
   ```python
     has_subshell = _has_cmd_subst(raw_tree)
   ```
   Replace with:
   ```python
     subst_flags = _subst_flags(raw_tree)
     has_cmd_subst = subst_flags["command_substitution"]
     has_proc_subst = subst_flags["process_substitution"]
     has_paren_subshell = subst_flags["subshell"]
   ```
   Then update every use of `has_subshell`:
   - Empty-segment fallback (Find: `if has_subshell and blocked_patterns:` and
     the later `elif has_subshell:` block): the blocked-content pre-scan uses
     `_extract_subshell_contents` (CmdSubst/ProcSubst) — gate it on
     `has_cmd_subst or has_proc_subst`. The policy branch currently reads:
     ```python
             _sub_policy = rules["subshell"]
             if _sub_policy == "allow" and "subshell" not in config:
                 _sub_policy = "ask"
     ```
     and its reason `"subshell or command substitution requires approval"`.
     Rewrite this branch: the policy to consult is `command_substitution` when
     `has_cmd_subst`, else `process_substitution` (the only constructs that can
     produce zero-segment trees). With the "inherited allow → ask" rule:
     ```python
     _cs_policy = rules["command_substitution"] if has_cmd_subst else rules["process_substitution"]
     _cs_key = "command_substitution" if has_cmd_subst else "process_substitution"
     if _cs_policy == "allow" and _cs_key not in config:
         _cs_policy = "ask"
     if _cs_policy == "allow":
         _empty_status = _wildcard
         _empty_reason = f"<empty command> produced no parseable segments - defaulting to wildcard policy ({_wildcard})"
     else:
         _empty_status = _cs_policy
         _empty_reason = (
             "command substitution requires approval" if has_cmd_subst else "process substitution requires approval"
         )
     ```
   - Main subshell-policy block (Find: `subshell_policy = rules.get("subshell", "ask")`
     followed by `if has_subshell:`). Rewrite as three independent gates:

     ```python
     # Command substitution / process substitution policy checks; also check
     # inner content against blocked paths and allowed patterns.
     if has_cmd_subst or has_proc_subst:
         subshell_contents = _extract_subshell_contents(raw_tree)

         if blocked_patterns and subshell_contents:
             for text in subshell_contents:
                 matched, pattern, value = check_blocked_patterns("", [text], blocked_patterns)
                 if matched:
                     overall_status = "deny"
                     reasons.append(
                         f'Blocked by bash permissions: Argument "{value}" matches blocked path pattern '
                         f"{pattern}. The tool has not been run"
                     )

         if nested_non_match:
             names_str = ", ".join(f'"{n}"' for n in sorted(nested_non_match))
             reasons.append(f"{names_str} commands inside subshell do not match allowed patterns")
             _sub_policy = (
                 rules.get("command_substitution", "ask") if has_cmd_subst else rules.get("process_substitution", "ask")
             )
             if overall_status == "deny":
                 pass  # already denied by blocked paths
             elif _sub_policy == "allow":
                 overall_status = "ask"
             elif _sub_policy == "deny":
                 overall_status = "deny"
             else:
                 overall_status = _sub_policy

     # $(...) and <(...) each gate independently (ask on either when overall
     # is still allow).
     for _flag, _key, _label in (
         (has_cmd_subst, "command_substitution", "command substitution requires approval"),
         (has_proc_subst, "process_substitution", "process substitution requires approval"),
     ):
         if _flag and overall_status == "allow":
             _pol = rules.get(_key, "ask")
             if _pol != "allow":
                 overall_status = _pol
                 reasons.append(_label)

     # ( ... ) paren-group subshells: inner segments are already scanned above
     # (blocked paths / allowed patterns); the policy gates the construct itself.
     if has_paren_subshell and overall_status == "allow":
         _paren_pol = rules.get("subshell", "ask")
         if _paren_pol != "allow":
             overall_status = _paren_pol
             reasons.append("subshell (...) requires approval")
     ```

     Note the original code had
     `if overall_status == "allow" and subshell_policy != "allow": ...`
     inside `if has_subshell:` — the loop above preserves that (policy only
     consulted when overall still allow).

6. `evaluate.py` — allowed-pattern AST walk: paren groups count as nesting, so
   commands inside `( ... )` that do not match allowed patterns flow through
   the `nested_non_match` machinery like `$(...)` contents. Find:
   ```python
                 new_depth = depth + (1 if isinstance(node, (CmdSubst, ProcSubst)) else 0)
   ```
   Replace with:
   ```python
                 from .ast import Subshell as _Subshell

                 new_depth = depth + (1 if isinstance(node, (CmdSubst, ProcSubst, _Subshell)) else 0)
   ```
   (or import `Subshell` at module top alongside the existing `CallExpr,
   CmdSubst, Node, ProcSubst` import — preferred; then no inline import).

7. `evaluate.py` docstrings: the `evaluate_bash_command` Args list documents
   `'subshell'` (Find: `- 'subshell': allow/ask/deny policy`) — update to list
   all three keys with their meanings. Also fix any other stale
   "subshell" mentions in this file's comments that refer to the old combined
   key (the `# Subshell/command substitution policy check;` comment is replaced
   in step 5 above).

**Tests this step:** update the existing test expectations so the suite is
green AGAIN (behavioral tests for the new keys are written in Step 7):
- `tests/config/conftest.py` (Find: fixture field `subshell: str = "ask"` and
  `config["subshell"] = subshell`): rename the fixture param to
  `command_substitution: str = "ask"` / `config["command_substitution"] = ...`.
  Keep a separate optional `subshell: str = "ask"` param mapped to
  `config["subshell"]` ONLY if needed by untouched tests — check usages first;
  simplest is renaming and updating callers.
- `tests/config/test_evaluate.py` (59 occurrences) and
  `tests/config/test_effective_bash.py` (3),
  `tests/redirections/test_nested_redirections.py` (1),
  `tests/config/test_schema.py` (1): re-map each config dict by semantic:
  constructs under test are `$(...)`/backticks in nearly all of these →
  `"command_substitution"`; any test specifically using `<(...)`/`>(...)` →
  `"process_substitution"`. Grep and re-map deliberately; do not blind-rename.
  `test_effective_bash.py` assertions on the resolved key names change to the
  three new keys.

**Probes:**

```bash
uv run python <<'EOF'
from lovely_bash_permissions.evaluate import evaluate_bash_command as ev
print(ev('echo $(cat x)',  {"*":"allow","command_substitution":"deny"}))   # deny
print(ev('echo $(cat x)',  {"*":"allow","subshell":"deny"}))               # allow (old key no longer gates $(...))
print(ev('echo <(cat x)',  {"*":"allow","process_substitution":"deny"}))   # deny
print(ev('( rm x )',       {"*":"allow","subshell":"deny"}))               # deny
print(ev('time ( rm x )',  {"*":"allow","subshell":"deny"}))               # deny
print(ev('( rm x )',       {"*":"allow","command_substitution":"deny"}))   # allow (different key)
EOF
```

**Acceptance:** probes match; full pytest/ruff/mypy green. **Commit:** listed
files + `PLAN.md`.

---

## Step 7 — bug #2: new behavioral tests + docs

**Status:** done — `TestSubstitutionKeySplit` (8 tests: paren deny + reason, time prefix, inner blocked path, inherited-allow → allow w/o reason, independent cmd/proc gating, zero-segment arithmetic deny + inherited-allow → ask) and `test_substitution_keys_all_resolved` in test_effective_bash.py added; README updated (3-key table rows, inherited-options sentence, both example blocks, guard-authoring D5 bullet in Security notes); suite 1130 passed; ruff/mypy clean.

**Files:** `tests/config/test_evaluate.py`,
`tests/config/test_effective_bash.py`,
`README.lovely-devin-permissions.md`

**What to do:**

1. New tests in `tests/config/test_evaluate.py` (class
   `TestSubstitutionKeySplit`):
   - `( rm x )` with `{"*":"allow","subshell":"deny"}` → deny, reason contains
     "subshell (...) requires approval".
   - `time ( rm x )` same → deny.
   - `( cat /etc/passwd )` with `{"*":"allow","blocked_paths_regex":["\\/etc"]}`
     → deny (inner blocked-path scan still works through the paren group).
   - `( rm x )` with `{"*":"allow"}` (key unset → `subshell` inherits the
     wildcard `allow`) and NO allow-list: the paren group is NOT gated by
     `subshell` (inherited `allow`), and inner `rm` is allowed by the `*`
     wildcard → overall **allow**. Assert `allow` and that the reason does NOT
     contain "requires approval" (the paren construct itself adds no reason
     under an inheriting wildcard). To observe the paren gate at all you must
     set `"subshell": "deny"`/`"ask"` (first two bullets) — a bare
     `{"*":"allow"}` never asks. (Do NOT assert `ask` here; a not-gated,
     wildcard-`allow` command is `allow`.)
   - `$(...)`: `echo $(x)` with `command_substitution: deny` → deny;
     `process_substitution: deny` alone → allow (with `"*":"ask"` it is ask via
     wildcard for `x`; use allowed_cmds_regex for precision:
     `{"*":"allow","allowed_cmds_regex":[r"^echo\s+\$\(.*\)$", r"^x$"]}`...
     simpler: `{"*":"allow","process_substitution":"deny"}` on
     `echo $(true)` → allow; same cmd with `command_substitution: deny` → deny.
   - `<(...)`: `echo <(true)` (allowed list covering echo) with
     `process_substitution: deny` → deny; with only `subshell: deny` → allow.
   - Inherited-allow fail-closed: `(( x[$(rm)] ))` (no segments) with
     `{"*":"allow","command_substitution":"deny"}` → deny; with bare
     `{"*":"allow"}` → ask (inherited allow downgraded — pre-existing rule,
     key renamed).

2. `tests/config/test_effective_bash.py`: assert an effective bash config
   resolves all three keys (unset → wildcard; explicit dict/scalar respected):
   e.g. config with `bash: {"*": "deny", "command_substitution": "allow"}` →
   effective has `subshell == "deny"` (inherited),
   `process_substitution == "deny"`, `command_substitution == "allow"`.

3. `README.lovely-devin-permissions.md` doc updates:
   - Find the table row (line ~135):
     ```
     | `subshell`                              | `"allow" \| "ask" \| "deny"`           | Policy for subshells and command substitutions (`$(...)`, backticks). If omitted, inherits `*` |
     ```
     Replace with three rows:
     ```
     | `command_substitution`                  | `"allow" \| "ask" \| "deny"`           | Policy for `$(...)` / backtick command substitutions. If omitted, inherits `*` |
     | `process_substitution`                  | `"allow" \| "ask" \| "deny"`           | Policy for `<(...)` / `>(...)` process substitutions. If omitted, inherits `*` |
     | `subshell`                              | `"allow" \| "ask" \| "deny"`           | Policy for `( ... )` subshell groups. If omitted, inherits `*` |
     ```
   - Find (line ~127) the sentence listing inherited options:
     `(`error`, `subshell`, `variable_assignment`, redirection, and background
     policies)` → add `command_substitution`, `process_substitution`.
   - Example config blocks (lines ~121 and ~348) containing
     `"subshell": "ask"` / `"subshell": "allow"`: replace with the three keys
     (e.g. `"command_substitution": "ask", "process_substitution": "ask",
     "subshell": "ask"`).
   - (D5) In the `## Security notes` section, Find the first bullet (the one
     about unanchored substring matches):
     ```
     - Patterns in `allowed_cmds_regex` and `blocked_paths_regex` are unanchored substring matches unless you anchor them. For example, `git` also matches `echo git`. Anchor with `^git log$` or similar.
     ```
     and append after it a new bullet:
     ```
     - Guard patterns (negative lookaheads, e.g. `^find(?!.*\s-(exec|delete|ok)\b)`) are matched against the **executed** form of the command, where quotes are removed and backslash escapes are resolved — so write them in executed form, as you would write the command unquoted. Flags that may be quote- or backslash-split (e.g. `find -exec` as `-e"x"ec` / `-ex\ec`) must be covered with a character class such as `-e["x]ec` or a plain executed-form token — a guard with a **literal** quote character (e.g. `(?!.*-e"xec)`) can never trip, because the executed form contains no quotes.
     ```

**Acceptance:** new tests pass; full suite/ruff/mypy green; no remaining
references to the old single-key semantics in `src/` (verify:
`rg -n '"subshell"' src/lovely_bash_permissions/config/*.py` shows only the
new-key context). **Commit:** listed files + `PLAN.md`.

---

## Step 8 — Final regression sweep (all four bugs)

**Status:** done — full acceptance matrix run by worker `step8_worker` (33/33 OK) and RE-RUN independently by the orchestrator (31/31 rows pass: bug #1 15, bug #2 5, bug #3 7, bug #4 4); gates: 1130 passed, ruff clean, mypy --strict clean, `.fuzz` IGNORED. All four NEW_BUGS fixed.

**Files:** none (verification; commit only if a step was left open).

Run the complete NEW_BUGS acceptance matrix in ONE probe script
(`uv run python <<'EOF' ... EOF`), asserting every line:

Bug #1 (config
`{"*":"ask","blocked_paths_regex":["\\/etc","\\.env$","\\.envrc$"],"allowed_cmds_regex":[r"^cat\s+.+$", r"^ls(\s+.*)?$", r"^grep\s+\S+\s+.+$", r"^head\s+.+$", r"^find(?!.*\s-(exec|delete|ok)\b).*$", r"^fd(?!.*\s+(-x|-X)).*$", r"^sort(?!\s+(-o|--output)\b).*$"]}` —
wildcard must be `"ask"`: the guard/find rows resolve to `ask` via the wildcard,
exactly as in the user's real config; under `"*":"allow"` they would read `allow`
via fall-through, which is NOT the intent):
- `cat /e"tc"/passwd` deny · `ls -la /e"tc"` deny · `grep x /e"tc"/passwd`
  deny · `head /e"tc"/passwd` deny · `cat .e"nv"` deny · `cat .e"nvrc"` deny
- `find /tmp -e"x"ec rm -rf /` ask · `find /tmp -"exec" rm -rf /` ask ·
  `find /tmp -ex\ec rm -rf /` ask (Python-escape the backslash) ·
  `fd -"x" rm` ask · `sort -"o" /tmp/out x` ask
- contrasts: `cat /etc/passwd` deny · `find /tmp -exec rm -rf /` ask ·
  `cat "plain file"` allow
- heredoc: `'cat f <<EOF\nsecret /e"tc"/passwd\nEOF'` deny (and the literal
  `'/etc/passwd'` variant stays deny)

Bug #2:
- `( rm x )` + `subshell:deny` deny · `time ( rm x )` + `subshell:deny` deny
- `echo $(echo hi)` + `command_substitution:deny` deny
- `echo <(hi)` + `process_substitution:deny` deny
- `( rm x )` + only `command_substitution:deny` → NOT gated by that key

Bug #3 (config + `"output_redirection":"allow"`):
- `> /etc/x && cat file` deny · `> /etc/x | true` deny ·
  `true | > /etc/x` deny · `cat file && > /etc/x` deny ·
  `2>/etc/e | true` deny · `> /etc/x; cat file` deny (regression: was already
  fine) · `> /tmp/ok && cat file` allow

Bug #4 (config `{"*":"allow","output_redirection":"allow"}`):
- `echo hi > "$DIR/out.txt"` reason contains `$DIR/out.txt`
- `echo hi > "a""b"` reason contains `ab`
- `echo hi > $(pwd)/out.txt` reason contains `$(...)/out.txt`
- `echo hi 2>"/dev""/null"` + per-kind `stderr_to_dev_null:allow` → allow

Then: full `uv run pytest -m 'not linting' -q`, `uv run ruff check .`,
`uv run mypy --strict .`. Mark all earlier step `Status:` fields `done` in
PLAN.md and set this step done. **Commit:** `git add PLAN.md` (plus any test
file that needed a final tweak, listed individually — never `git add -A`).

## Step 9 — stale-comment cleanup after the `subshell` key split

**Status:** done — all 11 stale sites fixed (5 in src: segments/converter/evaluate comments + docstrings + the `commands inside ...` reason string now reads "inside substitution/subshell"; 6 in tests: 4 docstrings + 2 comments). `rg -n "subshell policy" src/ tests/` → no matches; the only remaining "subshell" mentions are about `( ... )` groups / the `subshell` key / the Subshell AST node. Suite 1130 passed; ruff/mypy clean.

Stale sites (Find → replace):
- segments.py: `# Those are "capture output" operations, evaluated via subshell policy, not` → evaluated via the substitution policies (command_substitution / process_substitution)
- converter.py: `# (subshell policy, blocked-path scan, segment extraction).` → `# (command_substitution policy, blocked-path scan, segment extraction).`
- evaluate.py:41: `found inside subshells,` → `found inside command / process substitutions,`
- evaluate.py:82: `by the subshell-content pass.` → `by the substitution-content pass.`
- evaluate.py:622: `commands inside subshell do not match allowed patterns` → `commands inside substitution/subshell do not match allowed patterns`
- test_evaluate.py:133: `(subshell policy, blocked-path` → `(command_substitution policy, blocked-path`
- test_evaluate.py:2387: `gated by the subshell policy.` → `gated by the command_substitution policy.`
- test_evaluate.py:634: `Dangerous commands inside subshells are blocked.` → `Dangerous commands inside $(...) command substitutions are blocked.`
- test_evaluate.py:786: `Blocked paths inside subshell still deny...` → `Blocked paths inside $(...) still deny...`
- test_nested_redirections.py:124: `With subshell policy 'allow',` → `With command_substitution policy 'allow',`
- test_nested_redirections.py:129: `# subshell policy = allow` → `# command_substitution = allow`

**Definition of done:** every step above is `done`, the acceptance matrix
passes verbatim, gates green, and `.fuzz/` remains untracked & ignored.
