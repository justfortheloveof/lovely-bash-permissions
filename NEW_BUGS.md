# NEW_BUGS

Newly found bugs (not yet in `BUGZ.md`) from adversarial CLI + in-process testing
of the effective config `~/.config/devin/lovely-permissions.jsonc`
(`"*": "ask"`, `blocked_paths_regex` = `\/etc`, `\.env$`, `\.envrc$`,
`allowed_cmds_regex` incl. `^cat\s+.+$`, `^find(?!.*\s-(exec|delete|ok)...)$`,
`^fd(?!.*\s+(-x|-X)).*$`, `^sort(?!\s+(-o|--output)\b)...$`).

Severity: 🔴 critical security / severe functional · 🟠 high · 🟡 medium · ⚪ low.

Status: `approve` = allow · `ask` = REQUIRES-USER-APPROVAL · `block` = deny.

All repro commands pass `bash -n`.

---

## 1. 🔴 Quote-split / backslash-escape bypasses `blocked_paths_regex` and negative-lookahead guard patterns

**Area:** `inspect.py` `_word_raw` (line 190) preserves *interior* quotes and
backslashes; `evaluate.py` `_strip_quotes`/`_command_string` (lines 136/150)
strip only a whole-word pair of outer quotes. Bash concatenates the split pieces
at execution time, so the *executed* path/flag differs from the *scanned* text.

The existing whole-word tests (`tests/config/test_evaluate.py` 940–963 for
`'-exec'` / `"-o"` / `'-X'`) still pass; only interior splits evade them.

**argv (blocked paths):**

```bash
uv run lovely-devin-permissions -t 'cat /e"tc"/passwd'    # → approve (reads /etc/passwd)
uv run lovely-devin-permissions -t 'ls -la /e"tc"'        # → approve
uv run lovely-devin-permissions -t 'grep x /e"tc"/passwd' # → approve
uv run lovely-devin-permissions -t 'head /e"tc"/passwd'   # → approve
uv run lovely-devin-permissions -t 'cat .e"nv"'           # → approve  (bypasses \.env$)
uv run lovely-devin-permissions -t 'cat .e"nvrc"'         # → approve  (bypasses \.envrc$)
# literal spellings, for contrast:
uv run lovely-devin-permissions -t 'cat /etc/passwd'      # → block
uv run lovely-devin-permissions -t 'cat .envrc'           # → block
```

**argv (negative-lookahead guards — flags hinted by bash's own deny listed):**

```bash
uv run lovely-devin-permissions -t 'find /tmp -e"x"ec rm -rf /'  # → approve (executes -exec)
uv run lovely-devin-permissions -t 'find /tmp -"exec" rm -rf /'  # → approve
uv run lovely-devin-permissions -t 'find /tmp -ex\ec rm -rf /'   # → approve (backslash-escape; \e → e)
uv run lovely-devin-permissions -t 'fd -"x" rm'                  # → approve   ('fd -x rm' → ask)
uv run lovely-devin-permissions -t 'sort -"o" /tmp/out x'        # → approve   ('sort -o ...' → ask)
# contrast:
uv run lovely-devin-permissions -t 'find /tmp -exec rm -rf /'    # → ask
```

**redirection targets / here-strings / heredoc bodies (same root cause):**

```bash
# with output_redirection: allow — writes to /etc undetected:
echo hi > /e"tc"/x            # in-process: allow "output redirection allowed to /e"
cat <<< /e"tc"/shadow         # in-process: allow   (input redirection)
# heredoc body scan misses the split path:
uv run lovely-devin-permissions -t 'cat file <<EOF
secret /etc/passwd
EOF'                          # → block   (literal text caught)
uv run lovely-devin-permissions -t 'cat file <<EOF
secret /e"tc"/passwd
EOF'                          # → approve (split text missed; cat allowed by ^cat\s+.+$)
```

**Impact:** auto-approval for reading/writing every blocked path and for
`find -exec` / `fd -x` / `sort -o` style flags, including dropping files as
root. Fully reproducible in the shipped config.

**Fix area:** produce quote-normalized raw text for pattern matching
(e.g. resolve `DblQuoted`/`SglQuoted`/`Lit` per-part concatenation + bash-style
`\x` unescaping in `_word_raw` / `_command_string`), instead of
outer-only `_strip_quotes`.

---

## 2. 🟠 Plain `( ... )` subshells are invisible to the `subshell` policy

**Terminology mismatch (config vs bash):** the config key `subshell` does **not**
govern what bash calls a subshell `( ... )`. `evaluate.py:_has_cmd_subst`
(line 113) only detects `CmdSubst` (`$(...)`, `` `...` ``) and `ProcSubst`
(`<( ... )` / `>( ... )`); a `Subshell` / ParenStmt (`( ... )`) node is not an
inner command, so `subshell: deny` never fires for it. In other words the
current `subshell` key is really a **command-substitution** (plus process-
substitution) gate, named after the wrong construct.

```python
evaluate_bash_command("( rm x )", {"*": "allow", "subshell": "deny"})  # → allow  (BUG)
evaluate_bash_command("( echo hi )", {"*": "allow", "subshell": "deny"})  # → allow
evaluate_bash_command("time ( rm x )", {"*": "allow", "subshell": "deny"})  # → allow
evaluate_bash_command("echo $(echo hi)", {"*": "allow", "subshell": "deny"})  # → deny  (CmdSubst caught)
```

Paren groups are the same "run in a child shell" semantic the policy name
implies; the policy simply doesn't see them. Confirmed untested/unreported in
`tests/` and `BUGZ.md`.

**Impact:** configs that set `"subshell": "deny"` to contain `$(...)` output
capture leave `( cmd )` fully unguarded (a text-capture gate is not an
execution-isolation gate). Combined with an `allow` wildcard this lets every
shell command run in a subshell without ever consulting the `subshell` rule (or
its blocked-path / allowed-cmd inner scan).

**Recommended fix (config + parser):** the three constructs are distinct —
`( ... )` forks an isolated child shell but captures nothing (`Subshell`),
`$( ... )` / `` `...` `` capture stdout as text (`CmdSubst`), and `<( ... )` /
`>( ... )` expose a command's output as a `/dev/fd/N` path (`ProcSubst`) — and
should each have their **own** allow/ask/deny config key, with the existing key
renamed since its current name is misleading:

1. Rename the current `subshell` config key (and `_has_cmd_subst` / the empty-
   segment fallback + segment pass in `evaluate.py`) to `command_substitution` —
   it only ever gates `$( ... )` / `` `...` ``.
2. Introduce a new `process_substitution` key gating `<( ... )` / `>( ... )`,
   currently lumped into the old `subshell` key with no separate control.
3. Introduce a new `subshell` key gating `( ... )` / ParenStmt, wired through
   the same `_resolve_level(config, key)` per-level machinery (`evaluate.py`
   `_build_rules` ~line 284) and driving the inner-content blocked-path /
   allowed-cmd scan for paren groups just as `$(...)` gets today.

Optional back-compat: until the rename lands, honor a legacy `subshell` entry as
an alias for `command_substitution` (logging a deprecation warning), so existing
configs keep their current semantics during the transition.

---

## 3. 🔴 Redirection-only operand of `&&`, `||`, `|`, `|&` is dropped entirely

**Area:** `converter.py` `node_from_json` (lines 941–980). shfmt emits a redir-only
statement (`2> /etc/x`, `> /etc/x`) as a Stmt with `Redirs` but *no* `Cmd` and *no*
`Type`. The `not node_type and "Cmd" in data` shortcut (972) doesn't fire and
`_CONVERTERS.get("")` misses, so it degrades to a generic `Node`; `segments.py`
`_extract_segments` then logs
`Unhandled AST node type 'Node' - returning 0 segments` and the redirection
vanishes. A *top-level* redir-only statement works fine because `File.Stmts`
become real `Stmt` nodes (segments.py:180).

```bash
uv run lovely-devin-permissions -t '> /etc/x'               # → block          (fine)
uv run lovely-devin-permissions -t '> /etc/x && cat file'    # → approve (BUG: truncates/creates /etc/x, then cat approved)
uv run lovely-devin-permissions -t '> /etc/x | true'         # → approve (BUG)
uv run lovely-devin-permissions -t 'true | > /etc/x'         # → approve (BUG, Y operand dropped)
uv run lovely-devin-permissions -t 'cat file && > /etc/x'    # → approve (BUG)
uv run lovely-devin-permissions -t '2>/etc/e | true'         # → approve (BUG, even fd-N echo)
uv run lovely-devin-permissions -t '> /etc/x; cat file'      # → block  (top-level ; path intact)
```

When the compound also contains a normal command segment, the whole command is
evaluated with *no* redirections attached → `output_redirection` policy and the
blocked-path scan are never exercised → approve/ask where the result must be
block/ask. With `"*": "allow"` the all-redir variant (e.g.
`> /etc/x && > /etc/y`) also falls through to the wildcard and is allowed
("no parseable segments").

**Impact:** writing/truncating files at any path — including blocked paths —
indoes `echo`-styled compound commands with zero approval, plus
`output_redirection: deny` provides no protection.

**Fix area:** in `node_from_json`, map a Cmd-less `Redirs`-only Stmt to a proper
`Stmt` (with `cmd=None`) so `segments.py:_extract_segments` `Stmt` branch (180)
emits the synthetic redir-only segment it already supports for top-level cases.

---

## 4. 🟡 Redirection targets are rebuilt from the first word part only

**Area:** `rules.py` `classify_output_redirection` (224), `_check_segments_output_redirs`
(467), `_check_segments_input_redirs` (538), plus blocked-path scanning, all use
`parts[0].get("Value", "")`. A multi-part redirection word (`"$DIR/out"`, `a""b`,
`$(pwd)/x`, quote-split `"/dev""/null"`) is truncated to its first part.

```python
evaluate_bash_command('echo hi > "$DIR/out.txt"', {"*":"allow","output_redirection":"allow"})
# → allow  reason: 'output redirection allowed to /out.txt'   (loses $DIR)
evaluate_bash_command('echo hi > "a""b"',        {...same...})
# → allow  reason: 'output redirection allowed to a'
evaluate_bash_command('echo hi > $(pwd)/out.txt', {...same...})
# → allow  reason: 'output redirection allowed to '   (empty)

# benign-impact: breaks stderr_to_dev_null classification
evaluate_bash_command('echo hi 2>"/dev""/null"', {"*":"allow","output_redirection":{"*":"ask","stderr_to_dev_null":"allow"}})
# → ask   ('2>/dev/null' → allow)   (false ask)
```

Same `parts[0]` truncation lets quote-split redirection targets dodge the
blocked-path check (bug 1's redir vector), so this is both a reporting bug and a
guard gap.

**Impact:** wrong/misleading target identification for variables, command
substitution, concatenated words, and quote-split paths in every redirection.

**Fix area:** reconstruct the full target via the same per-part
join/unescape used for arguments (`inspect.py` `_word_value` semantics:
DblQuoted/SglQuoted nested parts + ParamExp/CmdSubst), not `parts[0]`.

---

## Summary

| # | Severity | Bug | Fix area |
| --- | ---------- | ----- | ---------- |
| 1 | 🔴 | quote-split / `\`-escape bypass of blocked paths and negative-lookahead guards (argv, redir targets, here-strings, heredoc bodies) | `inspect.py:_word_raw`, `evaluate.py:_strip_quotes/_command_string` |
| 2 | 🟠 | `( ... )` subshells not covered; current `subshell` key really gates only CmdSubst/ProcSubst → rename to `command_substitution`, add `process_substitution`, re-add `subshell` | `evaluate.py:_has_cmd_subst`/`_build_rules` |
| 3 | 🔴 | redirection-only operands of `&&`/`||`/`|`/`|&` dropped (generic `Node`) | `converter.py:node_from_json`, `segments.py` |
| 4 | 🟡 | redirection targets truncated to first word part | `rules.py` `parts[0]` uses |