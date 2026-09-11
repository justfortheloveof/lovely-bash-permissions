# Bash Permission Parser — Bug Documentation Log

Each entry records a reported candidate bug, its actual behavior, and the review verdict.
Entries pending review are added as they surface; verdicts are filled in by the orchestrator.

## Review Tracker

- Bugs **1–8** (PLAN "Bugs Found So Far"): confirmed and **fixed** (see git history, PLAN.md). ⚠️ **Re-reviewed 2026-09-11 — see BUGZ-015: #1–#3, #6–#8 verified working; #4 PARTIAL; #5 NOT FIXED.**
- Bugs **9–22** (Phase 9 candidates, "special builtins in env3"): re-reviewed. **#9–#22 except #14 = NOT BUGS** (false positives: commands not in env3 allow-list → "ask" is correct). #14's review surfaced genuine bugs **#23 `[[ ]]` drops redirections** (security-relevant) and **#24 `[[ x =~ regex ]]` miscategorizes regex RHS as command**. Details below.
- **Phase 13 coproc (#25): CONFIRMED REAL BUG → FIXED** (background_execution policy bypass) — BUGZ-013. Fix also closed the same root-cause gap for all compound-command `&` forms (`{ …; } &`, `( … ) &`, `if/for/while … done &`).
- **Phase 14 (#26–#31): all reviewed = NOT BUGS** (false positives) — see summary below.
- **Phase 1 `<>` (#32): CONFIRMED REAL BUG, FIXED** (added `<>` to `WRITE_REDIRECT_OPS`) — BUGZ-014.
- **Phase 4 (#1–#3) and Phase 7 (17): re-reviewed = NOT BUGS** (ask reasons trace to output_redirection / variable_assignment policy defaults; all 17 Phase 7 patterns approve under the matching config).
- **Confirmed REAL bugs to date: #23, #24, #25, #32. All fixed 2026-09-11 (BUGZ-011, BUGZ-012, BUGZ-013, BUGZ-014).**

---

## Entry: BUGZ-011 — `[[ ]]` conditional drops attached redirections (output_redirection policy bypass)

**Status:** ✅ FIXED (2026-09-11) — `segments.py` Stmt handler now emits a synthetic redirection-only segment whenever a statement carries redirections but produces no command segments (incl. `[[ ]]`, `(( ))`, bare `> f`); the test-expression handlers no longer need redirs propagation since inner test nodes are pseudo-commands. REPRO VERIFIED: `[[ -f file ]] > /tmp/out` → ❤️ auto-rejected "output redirection denied".

**DISCOVERED:** reviewing PLAN.md Bug #14 (`[[ -f file ]]` builtin not recognized)

**COMMAND:** `[[ -f file ]] > /tmp/out`

**ENV:** `/tmp/bughunt-review/deny` — config `{"bash":{"*":"allow","output_redirection":"deny","allowed_cmds_regex":[]}}` (global via env `DEVIN_GLOBAL_CONFIG_DIR`).

**TOOL OUTPUT:**
```
perms: 💚 auto-approved] <empty command> produced no parseable segments — defaulting to wildcard policy (allow
```

**EXPECTED:** ❤️ auto-rejected — `> /tmp/out` is an output redirection and `output_redirection` is `deny`. Control: `echo hi > /tmp/out`, `[ -f file ] > /tmp/out`, `cd / > /tmp/out` all correctly → `auto-rejected (output redirection denied)`.

**ROOT CAUSE:**
- shfmt parses `[[ -f file ]]` as a **`TestClause`** (not a `CallExpr` like `[ -f file ]`).
- `segments.py::_extract_segments` — the `TestClause` branch (segments.py:371-374) and the `UnaryTest`/`BinaryTest` branches do **not propagate the statement's `redirs`** into the test-expression recursion (compare with `IfClause`/`WhileClause`, which pass `redirs`).
- Result: `parse_segments('[[ -f file ]] > /tmp/out')` returns `[]`. The empty-segment short-circuit in `evaluate.py:177-185` returns the wildcard policy **before** the redirection checks at `evaluate.py:289-313` ever run, so the write is never classified.

**SECURITY IMPACT:** any `[[ ... ]] > file` (or `[[ ... ]] >> file`, `[[ ... ]] 2> file`, etc.) skips `output_redirection` — and `input_redirection`/`background_execution` — policies entirely. **Confidentiality breach potential**: e.g. `[[ cond ]] > /etc/shells` auto-approved under `*:allow` + `output_redirection:deny`.

**EVIDENCE:**
```
# parse_segments / AST
'[[ -f file ]] > /tmp/out'  -> segments: []   (Stmt.Redirs present in raw AST)
'[ -f file ] > /tmp/out'    -> segments: [{"command": "[", "arguments": ["-f","file","]"], "redirections": [{"Op": ">", ...}]}]
```

---

## Entry: BUGZ-012 — `[[ x =~ regex ]]` treats regex RHS as a command name

**Status:** ✅ FIXED (2026-09-11) — `segments.py` `BinaryTest` handler is now operator-aware: only `&&`/`||` right operands are treated as commands; `=~` (and `==`/`!=`/`-eq`/`<`/...) right operands are recursed WITHOUT test-expr context so only nested `$(...)` are extracted. REPRO VERIFIED: `[[ $var =~ pattern ]] > /tmp/out` → ❤️ auto-rejected, no phantom `"pattern"` report.

**DISCOVERED:** reviewing PLAN.md Bug #14

**COMMAND:** `[[ $var =~ pattern ]] > /tmp/out`

**ENV:** `/tmp/bughunt-review/deny` (same deny config as BUGZ-011).

**TOOL OUTPUT:**
```
perms: 💚 auto-approved] "pat" command does not match allowed patterns.' ; [[ $var =~ pat ]] > /tmp/out"
```

**EXPECTED:** `[[ $var =~ pattern ]]` is a conditional test; `pattern` is the regex operand, not a command. Plus (as in BUGZ-011) the trailing `> /tmp/out` should be subject to `output_redirection:deny` → auto-reject.

**ROOT CAUSE:**
- In the test-expression context, `segments.py` treats every `Word` as a command name (segments.py:490-491: `if _in_test_expr: segments.append({"command": _word_value(node), ...})`).
- For `BinaryTest` (node for `$var =~ pattern`), the right operand `pattern` is a `Word` → emitted as a pseudo-command "pattern".
- Same redirection-drop as BUGZ-011 (TestClause branch doesn't pass `redirs`).

**EVIDENCE:**
```
'[[ $var =~ pat ]] > /tmp/out' -> segments: [{"command": "pat", "arguments": [], "redirections": []}]
```

**SECURITY IMPACT:** misleading "command does not match" report + same redirection-policy bypass as BUGZ-011.

---

## Entry: BUGZ-013 — `coproc` bypasses `background_execution` policy

**Status:** ✅ FIXED (2026-09-11) — `check_background_execution` now also gates `CoprocClause`, and `_find_background_flags` was replaced with a generic subtree walker that collects inner command names for any compound command type. This also fixed a same-root-cause bypass for all compound-command `&` forms: `{ …; } &`, `( … ) &`, `if … fi &`, `for/while … done &` were all silently allowed under `background_execution: deny`.

**REPORTED:** PLAN.md Phase 13 (canonical bug #25).

**COMMAND:** `coproc myproc { echo hi; }`

**ENV:** `/tmp/bughunt-review/env2` (allow: `^ls`, `^true`, `^echo`, `^cat`, `^grep`, `^find`); also `/tmp/bughunt-review/denybg` with `{"bash":{"*":"allow","background_execution":"deny"}}`.

**TOOL OUTPUT (env2):**
```
decision: approve
command: ": '[♡ perms: 💚 auto-approved] command matches allowed pattern ^echo.' ; coproc myproc { echo hi; }"
```

**EXPECTED:** coproc is an asynchronous background process; `background_execution` policy should apply → env2 (default "ask") should REQUIRE approval; `background_execution:deny` should auto-reject.

**CONTROL COMPARISONS (denybg config, wildcard allow + background_execution deny):**
```
echo hi &             → ❤️ auto-rejected (background execution denied)
myf(){ :; }; myf &    → ❤️ auto-rejected
coproc myproc { echo hi; }        → 💚 auto-approved   ← BYPASS
coproc myproc { echo hi > /tmp/out; } → 💛 REQUIRES (output redirection still caught)
```

**ROOT CAUSE:**
- `coproc` parses to a **`CoprocClause`** AST node.
- `rules.py::check_background_execution` only inspects `stmt.get("Background")`, and `rules.py::_find_background_flags` only handles `CallExpr`/`BinaryCmd`/`AndCmd`/`OrCmd` — `CoprocClause` is never visited.
- `segments.py` correctly recurses into the coproc body (`CoprocClause` → stmt → Block → CallExpr `echo`), so the inner command matches `^echo` and the tool approves — masking the missing background check.

**SECURITY IMPACT:** under `background_execution: deny/ask`, an asynchronous coprocess (typically a long-lived interactive/consumer loop) is started with no approval, while the functionally equivalent `cmd &` is gated.

**REPRO:**
```bash
mkdir -p /tmp/bughunt-review/denybg/{global,project/.devin}
echo '{"bash":{"*":"allow","background_execution":"deny"}}' > /tmp/bughunt-review/denybg/global/lovely-permissions.jsonc
echo '{}' > /tmp/bughunt-review/denybg/project/.devin/lovely-permissions.jsonc
DEVIN_GLOBAL_CONFIG_DIR=/tmp/bughunt-review/denybg/global \
DEVIN_PROJECT_DIR=/tmp/bughunt-review/denybg/project \
uv run lovely-devin-permissions --test 'coproc myproc { echo hi; }'
# → auto-approved (should be denied)
```

---

## Phase 14 batch — canonical bugs #26–#31 (all processed, NOT BUGS)

| # | Reported (provisional) | Verdict |
|---|---|---|
| #26 | `[`/`[[` in conditionals not auto-approved (env2) | ❌ NOT A BUG — `[` not in env2 allow-list → ask correct (same Phase 9 premise) |
| #27 | `while read...; done <(echo hi)` → "ParseError" | ❌ NOT A BUG — command is **invalid bash** (`bash -n -c` exit 2). Valid form `done < <(echo hi)` parses/evaluates. |
| #28 | `'single' > /tmp/out` "creates file named single" | ❌ NOT A BUG — quoted word is a valid command name; correct |
| #29 | whitespace-only command asks approval | ❌ NOT A BUG — safe conservative no-op default (cosmetic) |
| #30 | `cat << EOF \| grep pattern > /tmp/out` "cat/grep not matched" | ❌ NOT A BUG — single-line heredoc is unclosed/invalid; valid multiline form parses and correctly asks for the `> /tmp/out` output redirection |
| #31 | `if $(test -f <(echo hi)); then ...` → "ParseError" | ❌ NOT A BUG — not reproducible (parses fine); asks correctly (`test` not allowed inside substitution; `> /tmp/out`) |

Phase 14 contributed **0 real bugs**.

---

## Entry: BUGZ-014 — `<>` truncate redirection bypasses `output_redirection`

**Status:** ✅ FIXED (2026-09-11) — `"<>"` added to `WRITE_REDIRECT_OPS` in `rules.py`; `<>` is now classified as an output (write) redirection and gated by `output_redirection` policy. Tests added for deny/ask policies.

**REPORTED:** PLAN.md Phase 1 (canonical bug #32).

**COMMAND:** `cat <> /tmp/out`

**ENV:** `/tmp/bughunt-review/denyout` — config `{"bash":{"*":"allow","output_redirection":"deny","allowed_cmds_regex":["^cat"]}}`.

**TOOL OUTPUT:**
```
perms: 💚 auto-approved] command matches allowed pattern ^cat.' ; cat <> /tmp/out"
```

**EXPECTED:** ❤️ auto-rejected — `<>` opens the file read-write **and truncates** it, so it is an output (write) redirection and `output_redirection` is `deny`.

**CONTROL COMPARISONS (same config):**
```
cat < /tmp/out    → 💛 REQUIRES (input redirection asks — correct: `<>` is NOT the same as `<`)
cat > /tmp/out    → ❤️ auto-rejected (output redirection denied)
cat >> /tmp/out   → ❤️ auto-rejected
true > /tmp/out   → ❤️ auto-rejected
cat <> /tmp/out   → 💚 auto-approved  ← BYPASS
```

**ROOT CAUSE:** `rules.py:14` — `WRITE_REDIRECT_OPS = {">", ">>", ">|", "&>", ">&", "&>>"}` does **not** include `<>`. The input check (`_check_segments_input_redirs`) only matches `"<"` and `"<<"`. So `<>` matches neither category, is treated as a non-redirection, and only the command pattern (`^cat`) is evaluated → approve.

**SECURITY IMPACT:** under `output_redirection: deny/ask`, `<>` (create+truncate read/write) is silently allowed. E.g. `cat <> /etc/shells` auto-approved where `cat > /etc/shells` is denied. Bash precedence: redirection opens/truncates BEFORE the command runs.

**FIX (proposed in Phase 1, not applied):** add `"<>"` to `WRITE_REDIRECT_OPS` in `src/lovely_bash_permissions/rules.py` (and ensure `classify_output_redirection` classifies it as a write).

**REPRO:**
```bash
mkdir -p /tmp/bughunt-review/denyout/{global,project/.devin}
echo '{"bash":{"*":"allow","output_redirection":"deny","allowed_cmds_regex":["^cat"]}}' > /tmp/bughunt-review/denyout/global/lovely-permissions.jsonc
echo '{}' > /tmp/bughunt-review/denyout/project/.devin/lovely-permissions.jsonc
DEVIN_GLOBAL_CONFIG_DIR=/tmp/bughunt-review/denyout/global \
DEVIN_PROJECT_DIR=/tmp/bughunt-review/denyout/project \
uv run lovely-devin-permissions --test 'cat <> /tmp/out'
# → auto-approved (should be denied)
```

---

## Phase 4 & Phase 7 review summary (2026-09-11)

- **Phase 4 #1** `cat $(echo files.txt)` in env3 → asks. NOT A BUG (known limitation): `_command_string` only builds the full command line for patterns when an arg holds a real value; opaque `$(...)` placeholder → name-only matching (`^cat\s+.*` fails). Conservative-by-design; prevents `^cat\s+.*` from gating `cat $(rm -rf /)`.
- **Phase 4 #2** `$(echo hello) > output.txt` in env2 → asks for **output redirection** (correct; env2 output_redirection=ask). NOT A BUG.
- **Phase 4 #3** `var=$(echo hello)` in env2 → asks for **variable_assignment** (correct; env2 default ask). NOT A BUG.
- **Phase 7 (17 patterns)** — under a config matching the agent's described env (variable_assignment allow, output_redirection allow/ask, echo/cat/etc. allowed) **all 17 auto-approve today**; the env2 asks reproduce with reasons `variable assignment requires approval: ['VAR=value']` and `output redirection requires approval` — identical to plain non-substitution commands. #16 (`cmd $(...)`) asks because `cmd` isn't allowed. NOT A BUG / 0 real.

---

## Entry: BUGZ-015 — Re-review of "fixed" bugs #1–#8 (review-of-fixed)

**Status:** ✅ Reviewed 2026-09-11 — **#1–#3, #6–#8 VERIFIED WORKING. #4 PARTIAL. #5 NOT FIXED.**

**CONTEXT:** PLAN.md's "Bugs Found So Far" lines 1–8 were each flagged `(fixed)` in a single collation commit (a1b0add); no per-bug "fix" commit exists for most of them. Re-reviewed via git history + live CLI repros (envs under `/tmp/bughunt-review/{write,kinds,pattern,var,block}`).

### #1 `>` vs `>>` indistinguishable — ✅ FIXED & VERIFIED
`WRITE_REDIRECT_OPS = {">", ">>", ">|", "&>", ">&", "&>>"}` (rules.py:14) — all detected write ops. Repro config `{"bash":{"*":"allow","output_redirection":"deny"}}`:
```
echo hi > /tmp/a    → ❤️ auto-rejected   (output redirection denied)
echo hi >> /tmp/a   → ❤️ auto-rejected
echo hi >| /tmp/a   → ❤️ auto-rejected
```
`>|` added later (a25ce78). No truncate-vs-append policy kind exists in the config model (only `*`/`stderr_to_stdout`/`stdout_to_dev_null`/`stderr_to_dev_null`), so `>` vs `>>` are policy-identical **by design** — nothing to distinguish.

### #2 `> file1 >> file2` treated as single write — ✅ FIXED & VERIFIED
Multi-target redirections are collected as a list; reason enumerates all targets:
```
echo hi > /tmp/a >> /tmp/b  → ❤️ auto-rejected  (output redirection denied to /tmp/a, /tmp/b)
```

### #3 `2> /dev/null` treated as stdout redirect — ✅ FIXED & VERIFIED
`classify_output_redirection` is fd-aware (rules.py:224-269). Per-kind policy config `{"*":"allow","output_redirection":{"*":"ask","stdout_to_dev_null":"allow","stderr_to_dev_null":"deny","stderr_to_stdout":"ask"}}`:
```
echo hi > /dev/null        → 💚 auto-approved   (stdout_to_dev_null: allow)
echo hi 2> /dev/null      → ❤️ auto-rejected   (stderr_to_dev_null: deny)
echo hi &> /dev/null      → ❤️ auto-rejected   (combined → both kinds)
echo hi 2>&1 > /dev/null  → 💛 REQUIRES       (stderr_to_stdout: ask)
```

### #4 `tee` writes multiple targets — ⚠️ PARTIAL / residual
VERIFIED WORKING: `tee` file args are checked against `blocked_paths_regex` (rules.py check_blocked_patterns), incl. inside pipes:
```
block config: {"*":"allow","output_redirection":"ask","blocked_paths_regex":[".*\\.sh$","/etc"]}
tee /etc/passwd            → ❤️ blocked (Argument "/etc/passwd" matches /etc)
cat x | tee /tmp/secret.sh → ❤️ blocked (Argument "/tmp/secret.sh" matches .*\.sh$)
```
RESIDUAL: `output_redirection` policy does NOT gate `tee`'s file write-targets:
```
{"*":"allow","output_redirection":"deny"}
tee /tmp/out      → 💚 auto-approved   (writes/truncates /tmp/out, policy bypassed)
```
So "writes multiple targets" is only half-handled: blocked-path protection yes; output_redirection write-gating no.

### #5 `tee -a` recognized as append — ❌ NOT FIXED
No `tee -a`/append handling anywhere in the codebase (`rg tee` → only segments/tests). Behavior identical to plain `tee` under every policy. There is no append-kind in the config model either, so the claim is unverifiable as a fix; the residual from #4 (output_redirection not gating tee) applies equally to `tee -a`.

### #6 `cp` doesn't match patterns — ✅ WORKS
`allowed_cmds_regex:["^cp","^rm$"]`:
```
cp file1 file2   → 💚 auto-approved
cp -r dir dest   → 💚 auto-approved
rm /tmp/x        → 💛 REQUIRES   (^rm$ does not match args)
```
Anchors fully respected; `_command_string` matches name+args via `re.match`.

### #7 `rm -r` matches more broadly than needed — ✅ WORKS / NOT A BUG
```
allowed_cmds_regex:["^rm$"]  → rm /tmp/x, rm -r /tmp/x, rm -rf /tmp/x all 💛 REQUIRES
allowed_cmds_regex:["rm -r"] → rm -r /tmp/x 💚; rm 💛; rm -rf /tmp/x 💚 (prefix match)
allowed_cmds_regex:["^rm -r$"] → rm -r 💚; rm -r /tmp/x 💛; rm -rf /tmp/x 💛
```
The "broader than needed" behavior is standard raw-regex prefix semantics (`rm -r` matches `rm -rf ...`); use `^rm -r$` or `^rm -r\s` to scope it. Not a code bug.

### #8 `variable_assignment` config key rejected as unknown — ✅ FIXED & VERIFIED
schema.py:54 declares the field; evaluate.py:158/194+ implements the policy; tests at test_evaluate.py:879+. A typo (`variable_assignment_typo`) warns `unknown config key`; the real key parses to a PermissionLevel. Runtime: `{"variable_assignment":"deny"}` → `FOO=bar` ❤️ `variable assignment denied: ['FOO=bar']`; `FOO=bar cat x` ❤️; `echo hi` 💚.

### ROOT-CAUSE NOTES
- #1–#3 addressed by the per-kind output-redirection rework (569eada) + `>|` add (a25ce78) + fd-aware classification.
- #8 has a real dedicated fix (dd113cf schema + 886b48a runtime).
- #4/#5 residual gap: **argument-based write targets (`tee`, `cp`, etc.) are only validated by `blocked_paths_regex`, never by the `output_redirection` policy** — a security-policy-parity gap vs. redirections. Tied to bug #32 (`<>`): both are write-behaviors the `output_redirection` policy fails to cover.

> **ACTION (optional):** consider documenting/handling tee-style argument write-targets vs. `output_redirection`; `<>` fix proposes adding it to WRITE_REDIRECT_OPS (BUGZ-014).

### PROPERNESS ASSESSMENT (2026-09-11) — are the fixes *implemented soundly*?

Re-probed each claimed fix directly via `evaluate_bash_command` with adversarial variants:

**#1/#2 — collection & classification: PROPER.** All write ops incl. `2>>` (stderr append), `&>>` (both-append), `>|` (noclobber) are denied under `output_redirection: deny`. Multi-redir + pipe-wide collection verified: `ls > /tmp/a | cat > /tmp/b` → deny listing BOTH targets. Redirect-target extraction robust to quoting/spacing (`'> "/etc/my file"'` → target `/etc/my file` → blocked) and even partial expansions (`/etc/$SUFFIX` → `/etc/` flagged, conservative). Blocked-path enforcement on targets present in both raw-tree and segment paths.

**#3 — fd-aware kinds: PROPER for every key the real config uses.** Per-kind resolution verified (`>/dev/null` allow vs `2>/dev/null` deny vs `&>/dev/null` deny vs `2>&1` ask). The real `~/.config/devin` config uses exactly `*`, `stderr_to_dev_null`, `stderr_to_stdout` — all honored. One minor note: `stdout_to_stderr` (i.e. `1>&2` / `>&2`) is NOT a classified kind (`stdout_to_stderr` appears nowhere in the repo) — `1>&2` falls to "other"/wildcard, and a config key `stdout_to_stderr` is **silently ignored** (pydantic `extra=ignore`, no warning — unlike ToolConfig which does warn). No impact on the real config; flag only for schema strictness.

**#6 — pattern matching: PROPER.** Anchored `^cp$`/`^rm$` fully honored (their variants rejected); unanchored prefix behavior is standard `re.match` semantics. `_command_string` matches name+args.

**#7 — "rm -r broader": NOT A BUG (semantics correct).** `rm -r` prefix-matching `rm -rf` is expected raw-regex behavior; `^rm -r$` scopes it exactly. No defect in the matcher.

**#8 — variable_assignment: PROPER.** Verified intended purpose end-to-end: real-config style `{"variable_assignment":"allow"}` → `REGION=us-east-1` 💚 allow, `REGION=... aws cloudformation deploy` 💚 allow, unmatched `ls` still 💛 (ask). `deny` path rejects `x=1`, `x=1 echo hi`, and `let x=1`; `echo hi x=1` (trailing arg) correctly NOT treated as an assignment. Dedicated tests at test_evaluate.py:879+. Adjacent observations (non-claim): standalone `((x=1))` yields "no parseable segments" → wildcard (arith-command segment gap, unrelated to #1–#8).

**#4/#5 — tee: PARTIAL / NOT FIXED (see above).** The only claims that fail properness: tee's file targets are gated by `blocked_paths_regex` but not by `output_redirection`, and `tee -a` has no append handling. Considered the most defensible follow-up, together with `<>` (#32).

**Unrelated debt noticed:** `tests/test_phase13_advanced_bash.py` fails `ruff check`, `ruff format`, and `mypy --strict` (pre-existing; 3 test failures on clean tree). No source files affected.

---
