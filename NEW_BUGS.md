# NEW BUGS

Fresh parse/evaluation bugs found by testing `lovely-devin-permissions`
(parsing backend + segment extraction + evaluation) against a corpus of valid
bash commands, each validated with `bash -n` before being fed to the library
(`parse_segments`, `evaluate_bash_command`, converter) and to the CLIs
(`lovely-devin-permissions -t`, `lovely-bash-inspection --string`).

Method: ~150 real-world and adversarial commands (quoting, here-docs/strings,
control flow, arithmetic, substitutions, process substitution, coproc,
functions, decls, redirections, exotic expansions) run through the library
and compared against ground-truth command extraction from the shfmt AST;
plus targeted security-behavior probes under multiple configs, and a
deep-nesting stress test.

Severity: 🔴 security bypass · 🟠 high · 🟡 medium · ⚪ low.

---

## 2. 🟠 Standalone `[[ ... ]]` / `(( ... ))` statements produce zero segments — early return skips every security pass, mislabels command as empty

> **Status: ✅ FIXED** — the empty-segment path no longer fabricates an `allow`
> when both regex lists are empty. The subshell/heredoc blocked-path scans now
> run *before* the early return, so `[[ $(cat /etc/passwd) == x ]]` resolves to
> the real wildcard (`ask` by default) and denies under `blocked_paths_regex`.
> The reason text carries the actual wildcard, never a fabricated `allow`.

**Area:** `src/lovely_bash_permissions/segments.py` (`_extract_segments` emits
nothing for a top-level `TestClause`/`ArithmCmd` statement with no
redirection) + `src/lovely_bash_permissions/evaluate.py` (the
`if not segments:` early return at the top of `evaluate_bash_command`).

Reproduction:

```python
evaluate_bash_command("[[ $(cat /etc/passwd) == x ]]", {"*": "ask"})
#   -> ALLOW   BUG — "<empty command> produced no parseable segments —
#                   defaulting to wildcard policy (allow)"
#   control: 'x=$(cat /etc/passwd)' under the same config -> ask

evaluate_bash_command("[[ $(cat /etc/passwd) == x ]]", {"*": "ask", "blocked_paths_regex": [r"/etc"]})
#   -> ask, NOT deny — the subshell blocked-path scan is skipped by the
#      early return; an approving user authorizes reading /etc/passwd
#   control: 'x=$(cat /etc/passwd)' under the same config -> deny

evaluate_bash_command("[[ $(f) == bar ]] && [[ $(g) == baz ]]", cfg)
evaluate_bash_command("((a++)) && ((b--))", cfg)
evaluate_bash_command('[[ -n "$x" ]]', cfg)
#   all -> 0 segments, same "<empty command>" early return
```

End-to-end with the real user config (patterns present, so it fails to "ask"
instead): `uv run lovely-devin-permissions -t '[[ $(cat /etc/passwd) == x ]]'`
returns the approval prompt labeled

```
[♡ perms: 💛 REQUIRES-USER-APPROVAL] <empty command> produced no parseable
segments — defaulting to wildcard policy (ask)
```

— the command is clearly *not* empty, and the prompt gives no indication that
it contains a command substitution.

Note: *nested* test clauses are fine (`while [[ -n $(cat /etc/passwd) ]]` →
deny, `if [[ ... ]]; then f; fi` extracts `f`); only top-level statements that
consist solely of test/arithmetic clauses fall into this path.

**Impact:** (a) patternless configs auto-allow `[[ $(arbitrary command) ]]`;
(b) with blocked-path rules the verdict downgrades from deny to a vague ask;
(c) misleading "<empty command>" diagnosis for any pure-test/arithmetic
statement.

**Fix:** emit a synthetic segment for bare test/arithmetic statements (analog
of the existing `[[ … ]] > file` synthetic-segment logic) and/or move the
empty-segment early return to *after* the subshell/heredoc security passes.

## 4. 🟠 Deeply nested command substitution crashes the converter with `RecursionError` (valid bash, shfmt parses it fine)

**Area:** `src/lovely_bash_permissions/converter.py` — recursive
`_convert_word → _convert_part → _convert_cmd_subst` chain.

Reproduction (bash-valid, `shfmt --to-json` succeeds):

```
cmd = "echo " + "$(" * 180 + "true" + ")" * 180

uv run lovely-bash-inspection --string "$cmd"
#   -> raw traceback, exit 1:
#      converter.py line 321 _convert_word → line 339 _convert_part
#      → line 138 _convert_cmd_subst ... RecursionError: maximum recursion
#      depth exceeded
```

Threshold: OK at 150 nested levels, `RecursionError` at ~180–200 (Python
default recursion limit). `node_from_json`, `parse_segments` and therefore
`evaluate_bash_command` all blow up.

In hook mode this is caught by the blanket `except Exception` and routed to
the `error` policy (default ask — fail-closed), so no bypass; but the
inspection CLI crashes with a traceback and any legitimately deep command
(e.g. generated tooling output) can never be parsed.

**Fix:** convert iteratively (or bump `sys.setrecursionlimit` relative to
input depth / increase default; ~4 frames per nesting level ⇒ depth × 4 must
fit under the limit).

---

## 5. 🟡 Commands in `for`-loop lists and test left-operands are not extracted as segments

**Area:** `src/lovely_bash_permissions/segments.py` — `_extract_segments`:

- `ForClause` only recurses into `body`, never the loop *list* word;
- `BinaryTest` only recurses into the *right* operand.

Reproduction:

```python
parse_segments("for i in $(seq 3); do echo $i; done")
#   -> [{'command': 'echo', ...}]      # `seq` runs, but is not a segment
parse_segments("if [[ $(pwd) == /root* ]]; then echo root; fi")
#   -> [{'command': 'echo', ...}]      # `pwd` runs, but is not a segment
```

The executed commands do appear in ground-truth AST extraction and are still
covered by the subshell-policy pass (verified: `for x in $(rm -rf x); do :;
done` with `subshell: deny` → deny), so this is an *accuracy* bug, not a
bypass — but the segment list (and anything built on it, e.g. per-command
UX, `lovely-bash-inspection`) silently under-reports actually-executed
commands.

---

## 6. 🟡 `$( cmd )` as a test right-operand is emitted as a literal `$(...)` pseudo-segment

**Area:** `src/lovely_bash_permissions/segments.py`, `Word`/`Lit` handling in
test-expression context (`_in_test_expr`) — the whole word value (including
the `$(...)` placeholder from `_word_value`) becomes a "command name".

Reproduction:

```python
evaluate_bash_command("[[ -f x && $(cmd) ]]", {"*": "ask", "allowed_cmds_regex": [r"^-f$"], "subshell": "allow"})
#   segments: [{'command': '$(...)', 'allowed': False}, ...]
#   -> ask, reason: '"$..." command does not match allowed patterns;
#                    "cmd" commands inside subshell do not match allowed
#                    patterns'
```

The pseudo-command `$(...)` can never match an allowed pattern, so such
commands always ask with a confusing reason that names a nonexistent command
`$(...)`. (Over-ask, not under-ask — `cmd` itself is still evaluated via the
subshell pass.)

---

## 7. ⚪ Misleading approval reason: `allow` verdicts cite "wildcard policy (ask)"

> **Status: ✅ FIXED** — this was a *status* fail-open, not just wording: with
> `allowed_cmds_regex` empty the segment loop auto-allowed every command, and
> the wildcard override carried a `not blocked_patterns` escape hatch, so a
> blocked-only config under `"*": "ask"` approved everything not blocked. The
> wildcard is now the per-command baseline — a command is approved only by an
> allow-pattern match or an explicit `"*": "allow"` — so blocked-only+ask asks,
> all specific policies add constraints only, and the residual fallback reason
> quotes the wildcard only when it actually is `allow`.

**Area:** `src/lovely_bash_permissions/evaluate.py` — fallback
`reason_str = f"allowed by wildcard policy ({_wp})"` is used whenever no
reason accumulated, even when the wildcard policy was never applied.

Reproduction:

```python
evaluate_bash_command("echo ${x%@/etc/*}", {"*": "ask", "blocked_paths_regex": [r"/etc"]})
#   -> status: allow, reason: "allowed by wildcard policy (ask)"
```

Status `allow` plus a reason quoting an `ask` wildcard is self-contradictory
for any config without `allowed_cmds_regex`.

---

## Verified working (no bug found)

- Pipes/`|&`, `&&`, `||`, `;`, backgrounding, line continuations, CRLF
  line endings.
- Pipes/`&&`/`;` inside single/double quotes, `$'...'`, adjacent quotes,
  escaped `\;` — never mis-split into segments.
- Here-docs (quoted/unquoted/`<<-`), here-strings, all redirection forms
  (`1>&2`, `&>`, `<>`, `2> >(…)`), process substitution on both sides.
- `if`/`elif`/`else`, `while`/`until` (cond + body), `for`, `case`,
  `select`, functions, `time`, coproc, `export`/`declare -A`/`let`,
  arithmetic `$(( ))`/`(( ))` in word context, backticks.
- Subshells in assignment values, double-quoted args, `Exp`-form parameter
  expansions (blocked-path + subshell passes fire correctly there).
- `bash -n`-invalid input (unclosed quotes, stray extglob `!(x)`) is
  rejected by shfmt and routed to the fail-closed error policy — correct.
