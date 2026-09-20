# NEW BUGS

Fresh parse/evaluation bugs found by testing `lovely-devin-permissions`
(parsing backend + segment extraction + evaluation) against a corpus of valid
bash commands, each validated with `bash -n` before being fed to the library
(`parse_segments`, `evaluate_bash_command`, converter) and to the CLIs
(`lovely-devin-permissions -t`, `lovely-bash-inspection --string`).

Method: ~230 real-world and adversarial commands (quoting, here-docs/strings,
control flow, arithmetic, substitutions, process substitution, coproc,
functions, decls, redirections, exotic expansions) run through the library
and compared against ground-truth command extraction from the shfmt AST;
plus targeted security-behavior probes under multiple configs, and a
depth-threshold stress test across nesting shapes.

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

## 7. 🔴 Command substitution inside a standalone `(( ... ))` arithmetic command bypasses the `subshell` policy

**Area:**
- `src/lovely_bash_permissions/segments.py` — `ArithmCmd` handler
  ("arithmetic only — skip") emits **no segments**; a standalone `(( ... ))`
  therefore takes the empty-segment fallback path;
- `src/lovely_bash_permissions/evaluate.py` — the no-segments fallback
  (the `if not segments:` block, ~line 301) runs only the blocked-paths and
  heredoc scans, then defaults to the wildcard. It never consults the
  `subshell` policy, even though `has_subshell` is correctly computed.

Reproduction (bash-valid; bash *executes* the substitution — verified:
`a=(); (( a[$(echo 2)] = 42 )); echo ${a[2]}` prints `42`, and a variant
with a marker-file-creating substitution actually ran it):

```python
evaluate_bash_command("(( x[$(rm -rf /etc/x)] ))", {"*": "allow"})
# -> allow, "<empty command> produced no parseable segments — defaulting to wildcard policy (allow)"
```

Measured matrix for `(( x[$(rm -rf /etc/x)] ))` (same for
`(( y += $(...) ))` and `time (( x[$(rm z)] ))`):

| config (`*` / `subshell`) | expected | actual |
|---|---|---|
| allow / deny | deny | **allow** |
| allow / ask  | ask  | **allow** |
| allow / (unset → ask) | ask | **allow** |
| ask / deny   | ask  | ask (via wildcard, for the wrong reason) |
| deny / allow | deny | deny (via wildcard) |

The `ask`/`deny` wildcard rows hide the bug only accidentally; any config
with a permissive `*` (which exists precisely to trust commands while the
`subshell` key restricts substitutions) auto-approves a command that
executes arbitrary `$(...)`. When the arithmetic is *combined* with a real
command (`ls; (( x[$(rm)] ))`) the segments exist and the subshell pass
fires correctly — only commands that produce **zero** segments (standalone
arithmetic, including `time`-wrapped) hit the gap.

**Fix:** in the empty-segments fallback, when `has_subshell`, apply the
resolved `subshell` policy (deny → deny / ask → ask) before falling through
to the wildcard default; keep the existing blocked-paths/heredoc scans.

---

## 8. 🟡 `$( ... )` in a `case` word or branch pattern is not extracted as a segment

**Area:** `src/lovely_bash_permissions/segments.py` — `CaseClause` handler
(~line 364) recurses only into each branch *body*; `node.word` and the
branch *patterns* are never walked.

Reproduction:

```python
parse_segments("case $(evil) in a) echo 1;; esac")
#   -> [{'command': 'echo', ...}]   # `evil` runs, but is not a segment
parse_segments("case $x in $(evil)) echo hit;; esac")
#   -> [{'command': 'echo', ...}]   # pattern substitution missed too
```

Not a bypass: the subshell pass sees it through the typed AST (verified:
both → `deny` under `subshell: deny`), so this is the same *accuracy*
class as bug #5 — segment lists, inspection output, and per-sub-command
allowlist reporting silently under-report executed commands. `select x in
$(evil)` is unaffected (goes through the `ForClause` list, fixed by #5).

**Fix:** also recurse into `node.word` and each branch's pattern word in
the `CaseClause` handler.

---

## 9. 🟠 `RecursionError` crash surface is wider than bug #4: nested `if`, `&&`/`||` chains, and nested `while` all crash

**Area:** same as #4 — pure recursion in `converter.py`
(`node_from_json` / `_convert_binary_cmd` / `_convert_if_clause` /
`_convert_while_clause`). Depth thresholds measured (bash-valid, shfmt
parses fine; OK at left, `RecursionError` at right):

| shape | OK | crash |
|---|---|---|
| nested `$( ... )` (bug #4) | 164 | 165 |
| nested `if :; then … fi` | 246 | 247 |
| `a && a && …` / `a \|\| a` chain | 329 cmds | 330 cmds |
| nested `while :; do … done` | 328 | 329 |
| `;`-chain, pipes, nested `{ }` blocks | fine to 5000 / 3000 / 2000 | — |

New angle vs #4: a **plain, generated script** of ~400 `&&`-joined commands
(or ~250 nested ifs) crosses the threshold — no exotic nesting required.
In hook mode the crash is mapped to the `error` policy
(`hook.py::_error_action`: `config.get("error") or config.get("*") or
"ask"`), so with the default wildcard it fails closed — **but** under a
`"*": "allow"` config without an explicit `error` key, the over-threshold
command is silently **auto-allowed with no analysis at all**.

**Fix:** convert flat lists and binary-command chains iteratively (shfmt
generates left-deep `BinaryCmd` chains); as a guard, raise
`ParseError`(→ error policy) when input length implies depth × ~4 frames
exceeds the limit, instead of letting `RecursionError` escape.

---

## 10. ⚪ Compound-command redirections are attributed to every inner segment → duplicated reason strings

**Area:** `src/lovely_bash_permissions/segments.py` — `IfClause` /
`WhileClause` / `ElifBranch` handlers pass the *inherited* statement
redirections into every contained stmt (same group-approximation as
`Block`), while the raw-tree path reports the same redirection again.

Reproduction:

```python
parse_segments("while :; do echo a; done < /etc/shadow")
#   -> both the cond segment `:` and the body segment `echo` carry `< /etc/shadow`
# evaluate reason: "input redirection allowed from /etc/shadow, /etc/shadow"
```

Applies to `while`, `until`, `if` (and, as the documented approximation,
`{ }` groups). Over-attribution only — extra checks never remove checks, so
no bypass; the user-visible impact is duplicated/misattributed reason text
and doubled per-command checks. `for` and `{ }` report once because their
redirections are not additionally carried by a raw-path statement node.

---

## Verified working (no bug found)

- Pipes/`|&`, `&&`, `||`, `;`, backgrounding, line continuations, CRLF
  line endings.
- Pipes/`&&`/`;` inside single/double quotes, `$'...'`, adjacent quotes,
  escaped `\;` — never mis-split into segments.
- Here-docs (quoted/unquoted/`<<-`), here-strings, all redirection forms
  (`1>&2`, `&>`, `<>`, `2> >(…)`), process substitution on both sides.
- `if`/`elif`/`else`, `while`/`until` (cond + body), `for`, `case`
  (branch bodies; word/pattern substitutions — see #8),
  `select` (including `in $( ...)`), functions, `time`, coproc,
  `export`/`declare -A`/`let`, arithmetic `$(( ))` in word context,
  standalone `(( ))` without substitution, backticks.
- Subshells in assignment values, double-quoted args, `Exp`-form parameter
  expansions (blocked-path + subshell passes fire correctly there).
- `bash -n`-invalid input (unclosed quotes, stray extglob `!(x)`) is
  rejected by shfmt and routed to the fail-closed error policy — correct.
