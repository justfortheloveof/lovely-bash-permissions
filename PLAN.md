# Plan: Align Python implementation with TypeScript reference (lovely-devin-permissions)

## Objective
Make the Python `lovely-bash-permissions` have the **exact same user experience** as the TypeScript reference (`../jftlo/lovely-devin-permissions/`) in terms of:
- Config file loading and precedence
- Auto-approve/auto-deny behavior
- User permission prompting
- CLI output formatting
- Hook event processing

## Reference Implementation
- **TypeScript (reference):** `../jftlo/lovely-devin-permissions/`
- **Python (to align):** `src/lovely_bash_permissions/`

Key TypeScript files:
- `src/config/loader.ts` — config loading (3 locations, deep merge)
- `src/config/devin.ts` — Devin Exec regex loading
- `src/config/effective-bash.ts` — merge lovely config + Devin exec
- `src/main.ts` — main entry, processes hook events, generates responses
- `src/evaluate-bash.ts` — evaluate commands against rules

## Comparison Results

### ✅ Aligned (No Changes Needed)
| Feature | Python | TypeScript | Status |
|---------|--------|------------|--------|
| Config sources (3 locations) | `~/.config/devin/`, `.devin/`, `.devin/.local` | Same | ✅ Same |
| Wildcard default | `ask` | `ask` | ✅ Same |
| Auto-approve (PreToolUse, allowed) | `updatedInput` with 💚 label | Same | ✅ Same |
| Auto-deny (PreToolUse, denied) | `updatedInput` with ❤️ label | Same | ✅ Same |
| User prompting (PreToolUse, ask) | `updatedInput` with 💛 label | Same | ✅ Same |
| PermissionRequest: allow → approve | `{decision: approve}` | Same | ✅ Same |
| PermissionRequest: deny → block | `{decision: block, reason}` | Same | ✅ Same |
| PermissionRequest: ask → prompt | `None` (skip) | Same | ✅ Same |
| --setup flag | Yes | Same | ✅ Same |
| --test flag | Yes | Same | ✅ Same |
| --show-config flag | Yes | Same | ✅ Same |
| Hook event structure | `hook_event_name`, `tool_name`, `tool_input` | Same | ✅ Same |
| Exit codes | 0 (approve/skip), 1 (error), 2 (block) | Same | ✅ Same |

### ❌ Differences (Need Alignment)
| # | Feature | Python (Current) | TypeScript (Reference) | Impact |
|---|---------|-----------------|----------------------|--------|
| 1 | CLI setup output | `[♡ perms: Added label exec permission to /path]` | `Added "Exec(: '[♡ perms:)" to /path so Devin auto-approves the hook's ":" no-op label` | User-visible message differs |
| 2 | Setup label format | Adds `"label exec"` to config | Adds `"Exec(: '[♡ perms:)"` to config | **Critical** - different permission granted |
| 3 | Allowed patterns reason | `command "ls" matches allowed pattern` | `command matches allowed pattern <pattern>` (includes matched regex) | User-visible reason differs |
| 4 | Blocked patterns reason | `command matches blocked patterns` | `Blocked by bash permissions: <details>. The tool has not been run.` | User-visible reason differs |
| 5 | Ask patterns reason | `command "ls" does not match allowed patterns` | `"ls" command does not match allowed patterns` (different phrasing) | User-visible reason differs |
| 6 | Hook label in deny (PreToolUse) | Label includes reason in updatedInput.command | Label is `"[♡ perms: ❤️ auto-rejected]"` only, reason is in separate `reason` field | **Critical** - user-visible label differs |
| 7 | DEVIN_GLOBAL_CONFIG_DIR | Not used by loader.py | Used via `getDevinGlobalConfigDir()` (respects APPDATA/DEVIN_GLOBAL_CONFIG_DIR) | Config discovery differs |

### ✅ Already Aligned (No Changes Needed)
| # | Feature | Python | TypeScript | Status |
|---|---------|--------|------------|--------|
| A | JSON output format | Pretty-printed (indent=2) | Pretty-printed (null, 2) | ✅ Already aligned |
| B | PermissionRequest deny format | Includes reason in response | Includes reason in response | ✅ Already aligned |
| C | Hook label regex | Uses `HOOK_LABEL_REGEX` from devin.py | Same | ✅ Already aligned |
| D | Error prefix | `[♡ perms: ERROR]` | `[♡ perms: ERROR]` | ✅ Already aligned |
| E | Background execution detection | AST Background field | lovely-bash-permissions library | ✅ Behavior aligned |
| F | Subshell detection | CmdSubst/ProcSubst in AST | lovely-bash-permissions library | ✅ Behavior aligned |
| G | Wildcard default policy | `ask` | `ask` | ✅ Already aligned |
| H | Effective config construction | Merges lovely + Devin exec | Same | ✅ Already aligned |

## Implementation Plan

### [x] Step 0: Replace Unicode Escapes with Actual Emoji Characters
**Files:** `src/lovely_bash_permissions/hook.py`, `src/lovely_bash_permissions/devin_cli.py`
- Python currently emits literal `\uXXXX` escapes (e.g., `[\u2661 perms: \ud83d\udc9b...]`) in shell commands
- TypeScript reference emits **actual emoji characters** (💚, ❤️, 💛, ♡)
- Change Python to use actual emoji characters in all label strings:
  - `"[♡ perms: 💚 auto-approved]"`
  - `"[♡ perms: ❤️ auto-rejected]"`
  - `"[♡ perms: 💛 REQUIRES-USER-APPROVAL]"`
- This makes the Python output match the TypeScript reference and displays correctly in real shells
- **Priority:** High (visible in all CLI output and affects label display)

### [x] Step 1: Fix CLI Setup Label
**File:** `src/lovely_bash_permissions/config/effective_bash.py`
- Change `LABEL_EXEC_NAME` from `"label exec"` to `"Exec(: '[♡ perms:)"`
- This ensures the Python setup adds the same permission as TypeScript
- **Priority:** High (critical UX difference)

### [x] Step 2: Fix CLI Setup Output Message
**File:** `src/lovely_bash_permissions/devin_cli.py`
- Change `handle_setup()` success output from `[♡ perms: Added label exec permission to <path>` to:
  `Added "Exec(: '[♡ perms:)" to <path> so Devin auto-approves the hook's ":" no-op label`
- Change already-present message from `[♡ perms:Label exec permission already present in <path>` to:
  `The Devin permission "Exec(: '[♡ perms:)" is already present in <path>`
- **Priority:** High (user-visible)

### [x] Step 3: Fix Auto-Rejected Label (PreToolUse)
**File:** `src/lovely_bash_permissions/hook.py`
- Remove reason from PreToolUse auto-rejected label
- Change from `[♡ perms: ❤️ auto-rejected] ${reason}` to `[♡ perms: ❤️ auto-rejected]` (no reason)
- **Priority:** High (user-visible)

### [x] Step 4: PermissionRequest Deny Reason — Already Aligned ✅
**File:** `src/lovely_bash_permissions/hook.py`
- TypeScript includes the reason in the deny response: `reason: "${HOOK_LABEL_PREFIX} ❤️ auto-rejected] ${result.reason}"`
- Python already does this: `label = f"[♡ perms: ❤️ auto-rejected] {reason}"` for PermissionRequest
- **No change needed** — behavior is already aligned.

### [x] Step 5: Fix Evaluate Allow Reason Format
**File:** `src/lovely_bash_permissions/evaluate.py`
- Change allowed reason from `command "ls" matches allowed pattern` to `command matches allowed pattern <pattern>` (single) or `command matches allowed patterns <patterns>` (multiple)
- Match TypeScript: include the matched regex pattern name(s), e.g., `command matches allowed pattern ^git`
- **Priority:** Medium (user-visible)

### [x] Step 6: Fix Evaluate Deny Reason Format
**File:** `src/lovely_bash_permissions/evaluate.py`
- Change blocked reason from `command matches blocked patterns` to `Blocked by bash permissions: <details>. The tool has not been run.`
- **Priority:** Medium (user-visible)

### [x] Step 7: Fix Evaluate Ask Reason Format (duplicate reason removed)
**File:** `src/lovely_bash_permissions/evaluate.py`
- Change ask reason from `command "ls" does not match allowed patterns` to `"ls" command does not match allowed patterns`
- For multiple commands: join with commas, use `commands` instead of `command`
- **Priority:** Medium (user-visible)

### [x] Step 8: JSON Output Format — Already Aligned ✅
**File:** `src/lovely_bash_permissions/devin_cli.py`
- TypeScript uses `JSON.stringify(obj, null, 2)` (pretty-printed with indent=2) for `--test` and `--show-config`
- Python already uses `json.dumps(response, indent=2)` (same behavior)
- **No change needed** — both are pretty-printed.

### [x] Step 9: Add DEVIN_GLOBAL_CONFIG_DIR Support to Loader
**Files:** `src/lovely_bash_permissions/config/loader.py`
- TypeScript's loader.ts uses `getDevinGlobalConfigDir()` which respects `DEVIN_GLOBAL_CONFIG_DIR` and `APPDATA` environment variables
- Python's loader.py hardcodes `Path.home() / ".config" / "devin"`
- Python's devin.py and devin_cli.py already support it, but loader.py does not
- Add import of `get_devin_global_config_dir()` from devin.py and use it for global config path
- **Priority:** Medium (config discovery)

### [x] Step 10: Add Background/Subshell Detection Parity Tests
**Files:** `tests/test_evaluate.py`, `tests/test_rules.py`
- Verify that Python's AST-based background execution detection matches TypeScript's library behavior
- Verify that Python's AST-based subshell detection matches TypeScript's library behavior
- Test background execution: `cmd &`, `cmd && cmd &`, pipes with background
- Test subshell: `$(cmd)`, backtick substitution, `{ cmd; }`
- **Priority:** Medium (ensure behavior parity)

### [x] Step 11: Add Comprehensive UX Tests
**Files:** `tests/test_cli.py`, `tests/test_evaluate.py`, `tests/test_hook.py`
- Add tests for exact output format (string comparison)
- Test CLI setup output matches: `Added "Exec(: '[♡ perms:)" to <path>...`
- Test hook event responses match TypeScript exactly
- Test reason formatting for allowed, ask, deny
- **Priority:** High (ensure regression protection)

### [x] Step 12: Update Documentation
**Files:** `docs/lovely-devin-permissions.md`, `README.md`
- Updated CLI documentation to match TypeScript behavior
- Added examples showing exact output format (💚/❤️/💛 labels, reason strings)
- Updated setup output messages
- **Priority:** Low (completed)

## Testing Strategy
1. **Side-by-side comparison:** Run both Python and TypeScript implementations with identical inputs, compare outputs
2. **Exact string matching:** Test that output strings match TypeScript reference exactly
3. **Integration tests:** Test full hook event flow (hook event → permission manager → evaluate → response)
4. **Config file tests:** Test config loading from all 3 locations
5. **Edge cases:** Empty config, missing files, malformed JSON

## Acceptance Criteria
For each UX area, the Python implementation must:
1. Produce **identical output** to the TypeScript reference
2. Use **identical config file paths and names**
3. Apply **identical auto-approve/auto-deny logic**
4. Generate **identical hook event responses**
5. Have **identical CLI flag behavior**
6. Pass all existing tests + new UX tests

## Priority Order
**Done:** Steps 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12

**Status:** Complete. All 12 implementation steps finished. Python fully aligns with TypeScript reference (lovely-devin-permissions). 448/448 tests pass. Verified: emoji labels, setup output, eval reasons, DEVIN_GLOBAL_CONFIG_DIR loader integration, all UX tests pass. Harmony pass 4 verification complete — no further implementation steps required.