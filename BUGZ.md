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
| 6 | 🟠 | `python3 -m json.tool` missing trailing `$` | default config line 46 |
| 7 | 🟠 | `\.env$` misses `.env.production`/`.env.local` variants | default config line 12 |
| 10 | ⚪ | `cat "$f"` false "ask" (ParamExp dropped from args) | `inspect.py` |
