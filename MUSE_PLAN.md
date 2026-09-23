# MUSE_PLAN — Rename `blocked_paths_regex` → `blocked_cmds_regex` and unify matching logic with `allowed_cmds_regex`

## 0. Progress

- [x] 5.1 `config/schema.py`
- [x] 5.2 `config/effective_bash.py`
- [ ] 5.3 New unified blocked matcher
- [ ] 5.4 Call-site replacements in `evaluate.py`
- [ ] 5.5 Reason-string and `rules.py` updates
- [ ] 5.6 Docs and example configs
- [ ] 5.7 Tests
- [ ] 6. Verification

## 1. Background and goal

The bash permission hook evaluates each shell command against two regex lists in
`lovely-permissions.jsonc` (`bash` scope):

- `allowed_cmds_regex`: approves a command segment when a pattern matches.
- `blocked_paths_regex`: denies when a pattern matches. Despite the name it is
  already used for more than paths (e.g. `curl`, `rm`, `\.env$` matched against
  `echo foo.env`, redirection targets, heredoc bodies).

Problem: the two lists use different matching logic.

- Allowed (`src/lovely_bash_permissions/evaluate.py::_match_allowed_patterns`,
  via `_command_string` at `evaluate.py:175`): joins one segment to a single
  string `"name arg1 arg2"` (raw args and quote-normalized `normalized_args` /
  executed form) and runs `re.search(pattern, joined_line)`. Anchoring is
  honored literally, exactly like the user wrote it.
- Blocked (`src/lovely_bash_permissions/rules.py::check_blocked_patterns`,
  called at `evaluate.py:519,523,360,373,551,609`): loops **per value**
  (`command_name`, then each `arg` separately). Heredoc bodies get extra
  special handling (whole body **plus** each stripped line,
  `evaluate.py:544-561`, plus quote/backslash-stripped variants via
  `_block_scan_variants` at `evaluate.py:150`).

Consequence: an end-anchored pattern such as `\.env$` behaves differently per
list. Today `echo foo.env bar` is **denied** (per-arg `"foo.env"` matches
`\.env$`), while the joined line `"echo foo.env bar"` does not end in `.env`.
After unification it must behave like allowed patterns: anchoring is honored
literally, so `\.env$` no longer fires mid-line. That is accepted: users fix
their patterns themselves (e.g. `\.env$` → `\.env` or `\b\.env\b`).

Goal of this plan:

1. **Hard rename** `blocked_paths_regex` → `blocked_cmds_regex` everywhere
   (no alias, no migration shim, no special error for the old key).
2. **Unify blocked matching** to the same joined-line logic as allowed,
   honoring anchoring literally.
3. Update reason strings, docs, and tests.

Out of scope: fixing the extraction gaps in `MUSE_BUGS.md` (`${VAR:-word}`
operands dropped to `$VAR`, arrays collapsed to `(...)`, `[[ ... ]]`
operands yielding zero segments). This plan does not change segment
extraction; it only changes how the (already extracted) segment text is
matched. Those extraction bugs stay open as follow-ups.

## 2. Agreed decisions (do not revisit without asking)

- Hard rename, no back-compat alias.
- **No special handling of the renamed-field error.** The old key
  `blocked_paths_regex` simply becomes an unknown key handled by the existing
  generic path in `config/schema.py::ToolConfig._warn_extra_fields`
  (currently: `log.warning("unknown config key ...")`, `extra="allow"`).
  Do not add a custom `ValueError`, hint message, or migration warning.
- Honor anchoring literally. Do not add per-arg / per-line fallbacks to
  preserve old `\.env$`-mid-line behavior. Document the pattern change
  instead.
- Deny still wins over allow/ask in aggregation.

## 3. Current behavior (reference)

### 3.1 Allowed matching

File: `src/lovely_bash_permissions/evaluate.py:175-268`.

```python
def _command_string(name, args):
    cleaned = [_strip_quotes(a) for a in args]
    if any("$(...)" not in a for a in cleaned):
        return name if not cleaned else " ".join([name, *cleaned])
    return name
```

`_match_allowed_patterns(name, args, allowed_patterns, normalized_args)`:

- `full = _command_string(name, args)`
- `norm_full = _command_string(name, normalized_args)` when provided
  (`normalized_args` = executed form from `segments.py`, quotes removed,
  backslashes unescaped).
- For each pattern: `hit = re.search(pattern, norm_full)`; if miss and the
  pattern has no `(?!`, fall back to `re.search(pattern, full)`.
- Skip hits when an opaque `$(...)` arg could invalidate a line-spanning
  lookahead or bare-name anchor (`_opaque_match_unreliable`).

Called per segment (`evaluate.py:495`) and per nested `CallExpr` in the AST
walk (`evaluate.py:450`).

### 3.2 Blocked matching (to be replaced)

Files: `src/lovely_bash_permissions/rules.py:71-87,212-238`,
`src/lovely_bash_permissions/evaluate.py:517-534,543-561,358-383,603-615`.

- `check_blocked_patterns(cmd, args, patterns)`:
  `re.search` on `cmd`, then on **each arg individually**. Returns
  `(matched, pattern, value)` where `value` is the single matching arg.
- Segment loop calls it twice: once with raw `args`, once with
  `normalized_args` if different (`evaluate.py:519-523`).
- Substitution contents: each extracted text checked as `("", [text])`.
- Heredoc bodies: whole body plus each non-empty stripped line, each with
  raw + quote/backslash-stripped variants (`_block_scan_variants`).
- Redirection targets in `rules.py` (`check_output_redirection`,
  `check_input_redirection`, `_check_segments_output_redirs`,
  `_check_segments_input_redirs`): single-value `_find_blocked_path(target)`.
- Reason strings (must all change, see §5):
  - `'Blocked by bash permissions: Argument "{value}" matches blocked path pattern {pattern}. ...'`
  - `'Heredoc body contains "{snippet}" matching blocked path pattern ...'`
  - `'Redirect target "{target}" matches blocked path pattern {pattern}'`

### 3.3 Config plumbing

- `config/schema.py:56`: `blocked_paths_regex: list[str] = []`; validator at
  line 69 covers `("blocked_paths_regex", "allowed_cmds_regex")`; line 44-48
  error hint for `deny` mentions `'blocked_paths_regex'`.
- `config/effective_bash.py:27,42,66,73`: docstring, read from
  `bash.get("blocked_paths_regex", [])`, output keys
  `"blocked_paths_regex": ...` (both branches).
- `evaluate.py:322-333`: `blocked_patterns = config.get(...)`, stored as
  `rules["blocked_paths_regex"]`; docstring line 305.
- `rules.py:332,446,519,572`: `rules.get("blocked_paths_regex", [])`.

## 4. Desired behavior with examples

After the change, blocked matching for a segment with `name="echo"`,
`args=["foo.env", "bar"]`, `normalized_args` same:

- Pattern `\.env$`: `re.search` on `"echo foo.env bar"` → **no match**
  (honored literally; ends in `bar`). User rewrites to `\.env` or
  `\b\.env\b` to block mid-line mentions.
- Pattern `\.env(\s|$)`: matches → deny, `value` reported as the joined line
  `"echo foo.env bar"`, not the single arg.
- Pattern `^echo`: matches joined line → deny (previously also denied via
  per-value `cmd` check; same outcome, different `value` in reason).
- Heredoc body `"line1\nfoo.env\n"`: matched as **one** string
  (plus its quote-stripped variant, see §5.3), not per line. A body where the
  secret is mid-body only matches unanchored patterns; users needing per-line
  `$` semantics must use `(?m)` flag themselves.

## 5. Implementation steps

### 5.1 `config/schema.py`

- Rename field line 56: `blocked_paths_regex: list[str] = []` →
  `blocked_cmds_regex: list[str] = []`.
- Validator line 69: `@field_validator("blocked_paths_regex",
  "allowed_cmds_regex", ...)` →
  `@field_validator("blocked_cmds_regex", "allowed_cmds_regex", ...)`.
- Line 44-48 `deny` hint: `'blocked_paths_regex'` → `'blocked_cmds_regex'`.
- Do nothing else. The old key is now an ordinary unknown extra key:
  existing `_warn_extra_fields` logs a warning and keeps it in
  `model_extra`. No new error, no alias, no merge.

### 5.2 `config/effective_bash.py`

- Line 27 docstring: `"blocked_paths_regex" list` → `"blocked_cmds_regex" list`.
- Line 42: `bash.get("blocked_paths_regex", [])` →
  `bash.get("blocked_cmds_regex", [])`.
- Lines 66, 73: output key `"blocked_paths_regex"` → `"blocked_cmds_regex"`.
- Note: `return {**bash, ..., "blocked_cmds_regex": blocked_patterns}` spreads
  the raw bash dict; since there is no alias, a stale `blocked_paths_regex`
  entry in user config would pass through untouched inside `**bash` while the
  evaluator reads only the new key (effectively ignored, plus the
  schema-level unknown-key warning if validated). That is the accepted hard-
  rename behavior — do not add filtering.

### 5.3 New unified blocked matcher

Recommended location: `src/lovely_bash_permissions/evaluate.py` next to
`_match_allowed_patterns` (it needs `_command_string`; alternatively put it
in `rules.py` and import `_command_string` — pick one, keep all blocked
join logic in that single helper).

Specification for `_match_blocked_patterns(name, args, blocked_patterns,
normalized_args=None) -> tuple[bool, str | None, str | None]`:

1. Build `full = _command_string(name, args)` using the **same**
   `_command_string` as allowed (including its `$(...)`-placeholder rule).
2. Build `norm_full = _command_string(name, normalized_args)` when
   `normalized_args is not None`, else `None`.
3. For each pattern in order: `hit = False`; if `norm_full is not None`,
   `hit = re.search(pattern, norm_full) is not None`; if not hit,
   `hit = re.search(pattern, full) is not None`. (Unlike allowed, always try
   both forms — OR semantics. Rationale: a miss-to-allow is unsafe for
   allow; a hit-to-deny is the safe direction for block, and trying both
   preserves the existing quote-split protection where raw and executed
   forms differ. Use cached compilation via existing
   `rules._compile_pattern`; let invalid patterns behave as today —
   `rules._match_pattern` swallows `ValueError` → no hit.)
4. On first hit return `(True, pattern, norm_full if hit-on-norm else full)`.
   The returned `value` is the **joined line**, which flows into the reason
   string (see §5.5). If no pattern hits return `(False, None, None)`.

Non-goals for the helper: no `(?!`-conditional fallback, no
`_opaque_match_unreliable` exclusion (that guard exists to avoid unsafe
**approval**; unsafe **denial** needs no such guard).

### 5.4 Call-site replacements in `evaluate.py`

- Lines 322-333: `blocked_patterns = config.get("blocked_cmds_regex", [])`;
  `rules = {..., "blocked_cmds_regex": blocked_patterns}`; docstring line 305
  updated.
- Segment loop lines 517-534: replace the two `check_blocked_patterns`
  calls (raw + norm retry) with one call:
  `_match_blocked_patterns(cmd_name, args, blocked_patterns, norm_args)`.
  Keep `segment_result["blocked"]` True/False bookkeeping and deny
  aggregation unchanged.
- Empty-segment path lines 354-383:
  - Substitution-contents check (line 358-366): replace
    `check_blocked_patterns("", [text], ...)` with matching each `text`
    through the unified helper as a single value. Simplest faithful
    approach: `_match_blocked_patterns("", [text], blocked_patterns)` —
    with empty name, `_command_string` returns just the text, so semantics
    equal a plain `re.search` on the text. Keep the deny + reason behavior.
  - Heredoc check (lines 367-383): **remove** the per-line split
    (`for ln in [body, *body.splitlines()...]`) and match each body once:
    candidates = `_block_scan_variants(body)` (keep the raw + stripped
    pair — this is quote/backslash normalization, not anchoring compensation;
    dropping it would regress the fixed quote-split bypass). For each
    candidate call the unified helper as `("", [candidate])`. Keep snippet
    truncation and reason format (with new wording).
- Substitution-contents check lines 607-615: same single-value replacement
  as above.
- Heredoc main-path lines 543-561: same as empty-path heredoc — one match
  per body (raw + stripped variant), no per-line loop.
- Update module/function docstrings mentioning `blocked_paths_regex`
  (lines 77, 305).

### 5.5 Reason-string and `rules.py` updates

- `evaluate.py` lines 364, 528, 613:
  `'... Argument "{value}" matches blocked path pattern {pattern}. ...'` →
  `'... Argument "{value}" matches blocked pattern {pattern}. ...'`.
  (`value` is now the joined command line.)
- `evaluate.py` lines 380, 558:
  `'Heredoc body contains "{snippet}" matching blocked path pattern ...'` →
  `'... matching blocked pattern ...'`.
- `rules.py` redirection-target checks (lines 331-340, 446-454, 519-527,
  572-580): rename `rules.get("blocked_paths_regex", [])` →
  `rules.get("blocked_cmds_regex", [])`; reason
  `'Redirect target "{target}" matches blocked path pattern {pattern}'` →
  `'Redirect target "{target}" matches blocked pattern {pattern}'`.
  Target matching itself stays single-value (`_find_blocked_path`) — a
  target is already one string, so joined-line semantics trivially hold.
- `rules.py:79` `_find_blocked_path` docstring: "blocked path pattern" →
  "blocked pattern" (optional but consistent).
- `rules.py:212-238` `check_blocked_patterns`: either delete it (preferred —
  remove the old per-value API so no caller can regress) or keep as a thin
  wrapper. If deleted, remove its import in `evaluate.py:23` and fix all
  callers per §5.4. If kept, it must not be used by the evaluator.
- `rules.py:215,401,408` docstrings mentioning `blocked_paths_regex` →
  `blocked_cmds_regex`.

### 5.6 Docs and example configs

- `README.lovely-devin-permissions.md`:
  - Line 96: "`allowed_cmds_regex` and `blocked_paths_regex`" →
    "`allowed_cmds_regex` and `blocked_cmds_regex`".
  - Line 121 example: `"blocked_paths_regex": ["^/etc"]` →
    `"blocked_cmds_regex": ["^/etc"]`.
  - Line 130: regex-list-keys sentence + defaults.
  - Row 150 table: key `blocked_paths_regex`, description
    "Regexes that block a command when matched in arguments or redirection
    targets. Unanchored substrings - anchor as needed" → key
    `blocked_cmds_regex`, description "Regexes that deny a command when
    matched against the full command line of each segment (same joined-line
    semantics as `allowed_cmds_regex`). Unanchored substrings — anchor with
    `^`/`$`/`\b` as needed; end-anchored patterns only match at the end of
    the segment line (e.g. use `\.env` or `\b\.env\b` instead of `\.env$` to
    block mid-line mentions). Also applied to redirection targets,
    substitution contents, and heredoc bodies."
  - Line 152 `error` note: "both `allowed_cmds_regex` and
    `blocked_paths_regex` are skipped" → new key name.
  - Line 356 example config: `"blocked_paths_regex": [...]` → new key.
  - Consider adding the `echo foo.env bar` + `\.env$` vs `\.env` example
    from §4.
- Check `README.md`, `PLAN.md`, `.devin/` example configs, and any shipped
  `lovely-permissions.jsonc` sample for the old key and rename (history docs
  `BUGZ.md` / `NEW_BUGS.md` / `MUSE_BUGS.md` describe past findings — leave
  untouched).

### 5.7 Tests

Existing tests referencing the old key (non-exhaustive — grep before
editing): `tests/config/test_evaluate.py` (lines ~139,155,216,224,234,242,
248,324,1262,1277,1291,1314,1435,1443,2514,2540,2575),
`tests/config/test_rules.py` (~776,785), `tests/config/test_schema.py`
(~17,49,54,87,135,138,142,152,238), `tests/config/test_effective_bash.py`
(~36-80), `tests/config/test_permissions_manager.py`
(~36,49,85,114,188,223,320,328), `tests/config/test_config_loader.py`
(~285), `tests/cli/lovely-devin-permissions/test_devin_cli.py`
(~335,383,403,428,448), `tests/cli/.../conftest.py` (~26),
`tests/integrations/test_hook_integration.py` (~284).

- Mechanical rename in all test configs/expectations + expected reason
  substrings `"matches blocked path pattern"` → `"matches blocked pattern"`.
- Behavior-change tests to add (in `tests/config/test_evaluate.py` or
  equivalent):
  - `echo foo.env bar` with `blocked_cmds_regex=[r"\.env$"]` → **not**
    denied (documents honored anchoring); with `[r"\.env"]` → denied.
  - `echo /etc/passwd extra` with `[r"\/etc"]` → denied (unanchored still
    fires anywhere on the joined line).
  - `^echo`-style anchored blocked pattern matches only at line start.
  - Heredoc body with secret mid-body + end-anchored pattern → not denied;
    unanchored → denied.
  - Normalized-form block still works: quote-split `/e"tc"/passwd` arg
    denied via `norm_full` even though raw joined line differs.
  - Old key ignored: config with only `blocked_paths_regex` behaves as if
    no blocked list (plus schema warning) — assert no deny from it.
- Keep/extend quote-split tests (`test_rules.py:776,785`,
  `test_evaluate.py:940-963` area) to prove the OR (raw + executed) matching
  did not regress.

## 6. Verification

1. `rg blocked_paths_regex src tests README.lovely-devin-permissions.md pyproject.toml .devin` → zero hits outside historical docs (`BUGZ.md`, `NEW_BUGS.md`, `MUSE_BUGS.md`, `PLAN.md` intentionally left).
2. `rg blocked_cmds_regex` → hits in schema, effective_bash, evaluate,
   rules, README, tests.
3. `rg "blocked path pattern"` → zero hits (all reason strings migrated).
4. `uv run pytest` (full suite) green; `uv run ruff check` / format clean
   if configured.
5. Manual CLI checks with a config using `blocked_cmds_regex`:
   `uv run lovely-devin-permissions --test 'echo /etc/passwd'` → block;
   `--test 'echo foo.env bar'` with `\.env$` → no block, with `\.env` →
   block; `--show-config` prints `blocked_cmds_regex`.

## 7. Risks and notes

- **Silent weakening for existing users**: any deployed
  `lovely-permissions.jsonc` still using `blocked_paths_regex` stops
  blocking entirely (key ignored + warning only), and any migrated
  end-anchored pattern (`\.env$`, `^/etc`-style) narrows under joined-line
  semantics. This is the accepted hard-rename cost — call it out in release
  notes with the `\.env$` → `\.env` rewrite rule.
- **`**bash` spread in `get_effective_bash_config`**: `{**bash, ...}`
  passes unknown keys through; stale `blocked_paths_regex` will appear in
  the effective dict but is never read. Do not filter it (would be special
  handling); the schema warning is the only signal.
- **Heredoc multiline**: single-string matching means `$` without `(?m)`
  matches only at the very end of the body. Intentional per §4; document
  the `(?m)` workaround.
- **No `$(...)` exclusion for blocked**: unlike allowed, blocked must fire
  even when the joined line contains `$(...)` placeholders. Do not apply
  `_opaque_match_unreliable` to the deny path.
