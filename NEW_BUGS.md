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
