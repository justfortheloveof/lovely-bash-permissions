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

## 1. 🔴 Command substitution inside `${var/pat/rep}` / `${var//pat/rep}` is invisible to ALL security passes — allow-list bypass

> **Status: ✅ FIXED** — `_convert_param_exp` now keeps `Repl.Orig`/`Repl.With` as
> typed `Word` nodes (`ParamExp.orig` / `ParamExp.replacement`, plus
> `ParamExp.all`), and the generic traversals (`iter_children` / `_traverse`),
> segment extraction, and the inspection passes all descend into them.

**Area:** `src/lovely_bash_permissions/converter.py`,
`_convert_param_exp()` (line ~116) — the shfmt `Repl` field (pattern
replacement: `Repl.Orig`, `Repl.Replacement`) is **dropped entirely** when
building the typed AST. `ParamExp` only keeps `exp` (default/slice/trim ops)
and `index`.

Consequence: a `$( cmd )` hidden in the pattern *or* replacement part of a
parameter expansion is never seen by:

- segment extraction (`parse_segments`),
- blocked-path scanning (segments, subshell-content, heredoc passes),
- `_has_cmd_subst` / subshell policy,
- `get_commands` / the inspection CLI.

Bash *does* execute such substitutions (verified: `x=abc; h(){ echo RAN-H; };
echo "${x//b/$(h)}"` prints `aRAN-Hc`).

Reproduction (all valid bash, all auto-approved):

```python
# config: allowed_cmds_regex = [r"^echo(\s+.*)?$"],
#         blocked_paths_regex = [r"/etc"], subshell = "deny"
evaluate_bash_command('echo "$(rm -rf x)"', cfg)
#   -> deny     (control: direct $(...) is denied as intended)

evaluate_bash_command("echo ${x//a/$(rm -rf x)}", cfg)
#   -> ALLOW    BUG — "command matches allowed pattern: ^echo(\s+.*)?$"

evaluate_bash_command("echo ${x//$(recon_cmd)/y}", cfg)
#   -> ALLOW    BUG — sub in the *pattern* part, same hole

evaluate_bash_command("echo ${x//a/$(cat /etc/passwd)}", {"*": "ask", "blocked_paths_regex": [r"/etc"]})
#   -> ALLOW    BUG — a blocked path is read, no block fires

evaluate_bash_command(
    "echo ${x//a/$(cat /etc/passwd)}",
    {"*": "ask", "allowed_cmds_regex": [r"^echo(\s+.*)?$"], "blocked_paths_regex": [r"/etc"], "subshell": "allow"},
)
#   -> ALLOW    BUG
```

Contrast — the *other* expansion forms are caught (their sub sits under
`Exp.Word`, which the segments handler does inspect):

```
'echo "${z%$(cat /etc/passwd)}"'   -> deny
'echo "${w:-$(cat /etc/passwd)}"'  -> deny
```

**Impact:** any command (arbitrary code, blocked-path reads) can be smuggled
inside an allow-listed command's argument via `${var/…/$(cmd)}` or
`${var//…/$(cmd)}`, bypassing allowed-pattern validation, blocked-path
scanning, *and* `subshell: deny`.

**Fix:** convert the `Repl` field in `_convert_param_exp` (keep it as typed
nodes or a raw dict) and make the generic traversals (`iter_children` /
`_traverse`, `_extract_segments`, `_word_value`/`_word_raw`) descend into it.

---

## 2. 🟠 Standalone `[[ ... ]]` / `(( ... ))` statements produce zero segments — early return skips every security pass, mislabels command as empty

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

---

## 3. 🟠 `ParamExp.exp` is stored as a raw dict — generic traversals never descend into it, so subshells in `${var:-…}` etc. evade the `subshell` policy

> **Status: ✅ FIXED** — `ParamExp.exp` is now a typed `ParamExpExp` node
> (`op` + `word`) and `Slice` is kept as a typed `ParamExpSlice` node
> (`offset`/`length`); both are descended into by the generic traversals, so
> `_has_cmd_subst`, `_extract_subshell_contents`, `get_commands`, and
> `has_variable` all see substitutions inside `${var:-…}`, `${var%…}`,
> `${var:off}` / `${var:off:len}`, etc.

**Area:** `src/lovely_bash_permissions/converter.py` `_convert_param_exp`
stores `exp` as `dict | None`; `ParamExp.exp` is typed `dict[str, Any] | None`
in `ast.py`. `iter_children`/`_traverse` only yield typed `Node` children, so
`CmdSubst` inside `${var:-$(…)}`, `${var%$(…)}`, `${arr[i]}`, … is invisible
to `_has_cmd_subst`, `_extract_subshell_contents`, `get_commands`, and
`has_variable`.

Reproduction (`subshell: "deny"`, allowed `^echo(\s+.*)?$`):

```python
evaluate_bash_command('echo "$(rm -rf x)"', cfg)  # -> deny   (intended)
evaluate_bash_command('echo "${y:-$(rm -rf x)}"', cfg)  # -> ask    BUG:
# downgraded to wildcard ask
#   _has_cmd_subst(parse('echo "${y:-$(h)}"')) is False
#   get_commands(...) -> ['echo']  (inner command never reported)
```

Segment extraction happens to recover `Exp.Word` substitutions (so blocked
paths still fire for these forms), but the *subshell policy level itself* is
not enforced: `subshell: deny` behaves as "ask" for every parameter-expansion
embedding, and the inspection CLI under-reports commands.

**Fix:** convert `Exp` (and `Index` words' parts) into typed nodes so
traversal is uniform — or make the ParamExp handler reachable from
`iter_children`.

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

## 7. ⚪ Misleading approval reason: `allow` verdicts cite "wildcard policy (ask)"

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

## Out of scope (pre-existing, unrelated)

- ~~`test_ruff_format_check` failed at baseline — `ruff format` wanted a
  comment-spacing fix in `README.md:36`.~~ Resolved while updating this doc
  (and README.md): the aligned inline comments in README's Python examples
  were normalized by `ruff format`; `ruff format --check .` is now clean.
