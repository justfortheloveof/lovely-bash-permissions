# lovely-devin-permissions Implementation Plan

Port the TypeScript `lovely-devin-permissions` tool to Python, leveraging the existing bash parser in this repo.

## Reference Implementation
- Source: `../jftlo/lovely-devin-permissions/`
- Key files: `src/evaluate-bash.ts`, `src/main.ts`, `src/cli.ts`, `src/config/`

## Goal
Create a Devin CLI permission hook (`lovely-devin-permissions`) that evaluates bash commands against configurable rules (allow/ask/deny) and decides whether to approve, block, or prompt for approval.

## Step 1a: JSONC Parser [COMPLETE]

* Implementation: parse_jsonc() and read_jsonc_file() with regex-based comment stripping
* Tests: 25 passing (line comments, block comments, trailing commas, BOM, empty/missing files)
**Files:** `src/lovely_bash_permissions/config/__init__.py`, `config/jsonc.py`
- Create `config` subpackage
- Implement JSONC parser: read JSON files, strip `//` comments, parse with `json.load()`
- Handle both `.json` and `.jsonc` files
- Return `dict` for valid JSON, `None` for missing/empty files
- Return `{}` for empty objects
**Acceptance:** JSONC parsing tests pass for comments, empty files, missing files

## Step 1b: Lovely-Permissions Config Loader [COMPLETE]
**Files:** `src/lovely_bash_permissions/config/loader.py`
- Load from three locations (highest precedence last):
  1. `~/.config/devin/lovely-permissions.jsonc` (global)
  2. `{project}/.devin/lovely-permissions.jsonc` (project)
  3. `{project}/.devin/lovely-permissions.local.jsonc` (local)
- Use deep merge: objects merged recursively, arrays concatenated, scalars override
- Load missing files as `{}`
- Return merged config dict
**Acceptance:** Config loading tests pass for all three sources and merge behavior

## Step 1c: Devin Config Loader [COMPLETE]
**Files:** `src/lovely_bash_permissions/config/devin.py`
- Load from three locations (highest precedence last):
  1. `~/.config/devin/config.json` (global)
  2. `{project}/.devin/config.json` (project)
  3. `{project}/.devin/config.local.json` (local)
- Extract `permissions.allow` entries
- Parse `Exec(...)` patterns: match regex `^Exec\(([^()]*)\)$`
- Convert `Exec(prefix)` to anchored regex: `^` + escaped prefix + `(\s|$)`
- Handle malformed `Exec(...)` entries as errors
- Deduplicate resulting regexes
**Acceptance:** Devin config loading tests pass for all three sources, Exec parsing, regex generation

## Step 1d: PermissionsManager [COMPLETE]
**Files:** `src/lovely_bash_permissions/config/manager.py`
- Create PermissionsManager class
- Constructor takes project directory
- Loads both lovely-permissions config and Devin config
- Provides `get_lovely_config()` and `get_devin_exec_regexes()` methods
- Handles errors gracefully (invalid config, missing files)
- Provides `is_valid()` and `get_error()` methods
- Reloads config on demand
**Acceptance:** PermissionsManager tests pass for loading, error handling, reload

## Step 2a: Bash Segment Parser [COMPLETE]
**Files:** `src/lovely_bash_permissions/segments.py`
- Implement bash command segment extraction using existing `parse_ast()`
- Parse command string to AST
- Extract segments from AST:
  - Pipes (`|`): treat each side separately
  - And (`&&`): treat each side separately
  - Or (`||`): treat each side separately
  - Background (`&`): treat the command before `&`
  - Statements: sequential commands
- Return list of segments, each containing: command name, arguments, redirections
**Acceptance:** Segment parser tests pass for pipes, &&, ||, background, statements

## Step 2b1: Allowed Pattern Matching [COMPLETE]
**Files:** `src/lovely_bash_permissions/rules.py`
- Implement `check_allowed_patterns(command_name, allowed_patterns)`
- Test command name against each allowed_cmds_regex pattern
- Return True if command matches any pattern
- Use Python's `re.search()` for regex matching
**Acceptance:** Pattern matching tests pass

## Step 2b2: Blocked Path Matching [COMPLETE]
**Files:** `src/lovely_bash_permissions/rules.py`
- Implement `check_blocked_patterns(args, blocked_patterns)`
- Test each argument against blocked_paths_regex patterns
- Return True if any argument matches a blocked pattern
**Acceptance:** Blocked path tests pass

## Step 2b3: Output Redirection Rules [COMPLETE]
**Files:** `src/lovely_bash_permissions/rules.py`
- Implement `check_output_redirection(tree, rules)`
- Extract output redirections from AST (using existing `get_redirections()`)
- Apply allow/ask/deny rules per redirection pattern
- Return decision with reason
**Acceptance:** Output redirection tests pass

## Step 2b4: Input Redirection Rules [COMPLETE]
**Files:** `src/lovely_bash_permissions/rules.py`
- Implemented `check_input_redirection(tree, rules)` following same pattern as check_output_redirection
- Extracts input redirections (< and <<) from AST and applies allow/ask/deny policy
- Added comprehensive tests: no input redir, allowed/denied/ask input, heredoc, mixed rules, multiple input redirs, default policy, object form wildcard
- All 370 tests pass (358 existing + 12 new)
**Acceptance:** Input redirection tests pass ✓

## Step 2b5: Background Execution Rules [COMPLETE]
**Files:** `src/lovely_bash_permissions/rules.py`
- Implemented `check_background_execution(tree, rules)` following same pattern as other rules
- Detects background execution (trailing `&`) from AST via Background field on statements
- Applies allow/ask/deny policy; extracts and reports command names in reason string
- Added comprehensive tests: no background, allowed/denied/ask, distinct from && chaining, multiple background commands, default policy, object form wildcard
- All 379 tests pass (370 existing + 9 new)
**Acceptance:** Background execution tests pass ✓

## Step 2c: Permission Evaluator [COMPLETE]
**Files:** `src/lovely_bash_permissions/evaluate.py`
- Implemented main evaluation function:
  ```python
  def evaluate_bash_command(command: str, config: dict) -> dict:
      """Evaluate a bash command against permission rules.
      Returns: {"status": "allow"|"ask"|"deny", "reason": str, "triggers": [...]}
      """
  ```
- Parse command using `parse_ast()`
- Extract segments using `segments.py`
- For each segment, evaluate rules using `rules.py`
- Aggregate results:
  - If all segments allowed → return allow
  - If any segment denied → return deny
  - If any segment asks → return ask
- Handles subshell/command substitution as separate segments via AST traversal
- **Implementation status**: Created evaluate.py with evaluate_bash_command(); runs against parse_ast(), parse_segments(), and all check_* functions; aggregates allow/deny/ask across segments and rules. All 379 tests pass.
**Acceptance:** Evaluation tests pass for all rule types and aggregation ✓

## Step 3a: Hook Event Processing [COMPLETE]
**Files:** `src/lovely_bash_permissions/hook.py`
- Implement hook event processing
- Read JSON from stdin
- Parse event: `{"hook_event_name": "PreToolUse"|"PermissionRequest", "tool_name": "exec", "tool_input": {"command": ...}}`
- If `tool_name` is not "exec" → return skip (no action)
- If command is empty → return skip
- Load config using PermissionsManager
- If config invalid → return block with error reason
- Evaluate command using `evaluate_bash_command()`
- Handle errors gracefully
- **Implementation status**: Created hook.py with handle_load_error() and process_hook_event(); uses PermissionsManager and evaluate_bash_command(). All 379 tests pass.
**Acceptance:** Hook event processing tests pass for all event types ✓

## Step 3b: Hook Response Generation [COMPLETE]
**Files:** `src/lovely_bash_permissions/hook.py`
- Implement hook response generation
- PreToolUse: approve with label → `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "updatedInput": {"command": ": '[♡ perms: 💚 auto-approved] ...' ; <original>"}}}`
- PreToolUse: deny → `{"decision": "block", "reason": "[♡ perms: ❤️ auto-rejected] ..."}`
- PermissionRequest: approve → `{"decision": "approve"}`
- PermissionRequest: deny → `{"decision": "block", "reason": "[♡ perms: ❤️ auto-rejected] ..."}`
- Return skip for non-exec events or empty commands
- **Implementation status**: Added generate_hook_response() to hook.py handling all event/response types with heart emoji labels. All 379 tests pass.
**Acceptance:** Hook response generation tests pass for all response formats ✓

## Step 3c: CLI Commands — New `lovely-devin-permissions` CLI
**Files:** `src/lovely_bash_permissions/devin_cli.py`, `pyproject.toml`

Create a **separate** Devin hook CLI (`lovely-devin-permissions`), leaving the existing `lovely-bash-inspection` CLI unchanged. Replicate the TypeScript reference (`../jftlo/lovely-devin-permissions/src/main.ts`).

### CLI Commands
1. **`--setup` / `-s`**: Add `Exec(: '[♡ perms:)` to Devin's global config (`~/.config/devin/config.json`).
   - Read existing config (or create `{}` if missing)
   - Check if `LABEL_EXEC_PERMISSION` already in `permissions.allow` array
   - If already present: print "already present" message, exit 0
   - Otherwise: append to array, write config, print success message, exit 0
   - On error (read/write failure): print error to stderr with `[♡ perms: ERROR]` prefix, exit 1

2. **`--test <command>`**: Test a command as a PreToolUse event.
   - Create synthetic PreToolUse event with the command
   - Process through `handle_pre_tool_use()` (same as hook mode)
   - If no response generated: print "No response generated for the test command", exit 0
   - Otherwise: pretty-print the hook response JSON, exit with the response's exit code

3. **`--show-config`**: Display effective config and considered files.
   - List all permissions config file paths (global, project, local) and Devin config file paths
   - For each file, include `path` and `exists` boolean
   - Build PermissionsManager, check validity
   - On invalid: print error with `[♡ perms: ERROR]` prefix to stderr, exit 1
   - Otherwise: compute effective bash config, print JSON with `{ files: [...], effectiveConfig: {...} }`
   - Exit 0

### Mode Detection
- **CLI mode**: argv contains `--setup`, `--test`, or `--show-config`
- **Hook mode**: no CLI flags AND stdin has data (non-empty)
- **No input**: no CLI flags AND stdin empty → exit 0 silently
- CLI flags take precedence over stdin

### Hook Mode Behavior
- Read entire stdin, parse as JSON HookEvent
- Validate structure: must have `hook_event_name` (`PermissionRequest` or `PreToolUse`), `tool_name`, `tool_input`
- If `tool_name != "exec"` or `command` missing/empty → no response (exit 0)
- Build PermissionsManager with project directory from `DEVIN_PROJECT_DIR` env or cwd
- Evaluate command, generate response
- `PermissionRequest`: only approve/block, no label injection
- `PreToolUse`: inject `: '[♡ perms: ...]'` label into command via `updatedInput`
- Exit codes: 0 (approve/skip), 1 (config error), 2 (block/eval error)

### Constants
- `HOOK_LABEL_PREFIX = "[♡ perms: "`
- `LABEL_EXEC_PERMISSION = "Exec(: '[♡ perms:)"`

### Help Text
- `lovely-devin-permissions [options]`
- `--setup, -s`: Add the required Devin permission for the hook label
- `--show-config`: Print the effective bash permission configuration and considered files
- `--test <command>`: Test a command as a PreToolUse event and pretty print the response
- `--help, -h`: Show help

### Add to pyproject.toml
Add new entry: `lovely-devin-permissions = "lovely_bash_permissions.devin_cli:main"`

**Acceptance:** CLI tests pass for all commands, mode detection, exit codes, and label injection

## Step 4a: Config Tests
**Files:** `tests/test_config.py`
- Tests for JSONC parsing, file loading, merge, schema validation
**Acceptance:** Config tests pass

## Step 4b: Segment Tests
**Files:** `tests/test_segments.py`
- Tests for pipes, &&, ||, background, statements
**Acceptance:** Segment tests pass

## Step 4c: Rule Tests
**Files:** `tests/test_rules.py`
- Tests for allowed patterns, blocked patterns, redirections
**Acceptance:** Rule tests pass

## Step 4d: Evaluation Tests
**Files:** `tests/test_evaluate.py`
- Tests for all rule types, aggregation, subshell handling
**Acceptance:** Evaluation tests pass

## Step 4e: Hook Tests
**Files:** `tests/test_hook.py`
- Tests for event parsing, response generation, error handling
**Acceptance:** Hook tests pass

## Step 4f: CLI Tests
**Files:** `tests/test_cli.py`
- Tests for all commands, mode detection
**Acceptance:** CLI tests pass

## Step 5: Documentation
**Files:** `README.md`, `docs/lovely-devin-permissions.md` (new)
- Add lovely-devin-permissions usage section to README
- Add docs/ directory with detailed documentation
- Include config examples
- Include setup instructions
- Explain dual-mode design (hook vs CLI)
**Acceptance:** Documentation is clear and complete

## Dependency Order
1a → 1b → 1c → 1d → 2a → 2b1 → 2b2 → 2b3 → 2b4 → 2b5 → 2c → 3a → 3b → 3c → 4a → 4b → 4c → 4d → 4e → 4f → 5

## Implementation Notes
- Use existing `parse_ast()` from lovely-bash-permissions (shfmt-based)
- Replicate TypeScript functionality exactly (behavior, config format, CLI flags)
- Each step must be completable within a single ~70k context agent pass
- Use existing code quality standards (ruff, pytest, type hints)
- Keep bash parsing separate from evaluation for reusability (future lovely-pi-permissions)