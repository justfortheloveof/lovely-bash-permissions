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

## Step 1b: Lovely-Permissions Config Loader
**Files:** `src/lovely_bash_permissions/config/loader.py`
- Load from three locations (highest precedence last):
  1. `~/.config/devin/lovely-permissions.jsonc` (global)
  2. `{project}/.devin/lovely-permissions.jsonc` (project)
  3. `{project}/.devin/lovely-permissions.local.jsonc` (local)
- Use deep merge: objects merged recursively, arrays concatenated, scalars override
- Load missing files as `{}`
- Return merged config dict
**Acceptance:** Config loading tests pass for all three sources and merge behavior

## Step 1c: Devin Config Loader
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

## Step 1d: PermissionsManager
**Files:** `src/lovely_bash_permissions/config/manager.py`
- Create PermissionsManager class
- Constructor takes project directory
- Loads both lovely-permissions config and Devin config
- Provides `get_lovely_config()` and `get_devin_exec_regexes()` methods
- Handles errors gracefully (invalid config, missing files)
- Provides `is_valid()` and `get_error()` methods
- Reloads config on demand
**Acceptance:** PermissionsManager tests pass for loading, error handling, reload

## Step 2a: Bash Segment Parser
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

## Step 2b1: Allowed Pattern Matching
**Files:** `src/lovely_bash_permissions/rules.py`
- Implement `check_allowed_patterns(command_name, allowed_patterns)`
- Test command name against each allowed_cmds_regex pattern
- Return True if command matches any pattern
- Use Python's `re.search()` for regex matching
**Acceptance:** Pattern matching tests pass

## Step 2b2: Blocked Path Matching
**Files:** `src/lovely_bash_permissions/rules.py`
- Implement `check_blocked_patterns(args, blocked_patterns)`
- Test each argument against blocked_paths_regex patterns
- Return True if any argument matches a blocked pattern
**Acceptance:** Blocked path tests pass

## Step 2b3: Output Redirection Rules
**Files:** `src/lovely_bash_permissions/rules.py`
- Implement `check_output_redirection(tree, rules)`
- Extract output redirections from AST (using existing `get_redirections()`)
- Apply allow/ask/deny rules per redirection pattern
- Return decision with reason
**Acceptance:** Output redirection tests pass

## Step 2b4: Input Redirection Rules
**Files:** `src/lovely_bash_permissions/rules.py`
- Implement `check_input_redirection(tree, rules)`
- Extract input redirections from AST
- Apply allow/ask/deny rules per redirection pattern
**Acceptance:** Input redirection tests pass

## Step 2b5: Background Execution Rules
**Files:** `src/lovely_bash_permissions/rules.py`
- Implement `check_background_execution(tree, rules)`
- Detect background execution (trailing `&`) from segments
- Apply allow/ask/deny rules
**Acceptance:** Background execution tests pass

## Step 2c: Permission Evaluator
**Files:** `src/lovely_bash_permissions/evaluate.py`
- Implement main evaluation function:
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
- Handle subshell/command substitution as separate segments
**Acceptance:** Evaluation tests pass for all rule types and aggregation

## Step 3a: Hook Event Processing
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
**Acceptance:** Hook event processing tests pass for all event types

## Step 3b: Hook Response Generation
**Files:** `src/lovely_bash_permissions/hook.py`
- Implement hook response generation
- PreToolUse: approve with label → `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "updatedInput": {"command": ": '[♡ perms: 💚 auto-approved] ...' ; <original>"}}}`
- PreToolUse: deny → `{"decision": "block", "reason": "[♡ perms: ❤️ auto-rejected] ..."}`
- PermissionRequest: approve → `{"decision": "approve"}`
- PermissionRequest: deny → `{"decision": "block", "reason": "[♡ perms: ❤️ auto-rejected] ..."}`
- Return skip for non-exec events or empty commands
**Acceptance:** Hook response generation tests pass for all response formats

## Step 3c: CLI Commands
**Files:** `src/lovely_bash_permissions/cli.py`, `pyproject.toml`
- Implement CLI commands:
  - `--setup` (alias `-s`): add `Exec(: '[♡ perms:)` permission to Devin config
  - `--test <command>`: test command as PreToolUse event, pretty-print response
  - `--show-config`: display effective bash permission config and considered files
- Add CLI to pyproject.toml scripts as `lovely-devin-permissions`
- Mode detection: stdin has data → hook mode, argv has flags → CLI mode
**Acceptance:** CLI tests pass for all commands and mode detection

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