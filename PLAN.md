# Bash Permission Parser Bug Hunt

## Goal
Systematically find parsing/classification bugs in `lovely-devin-permissions` by testing
`--test '<bash command>'` against a comprehensive exploration space of bash constructs.
Document **50 bugs** before stopping.

## Methodology
For each phase, the orchestrator will spawn an agent that will:
1. Study relevant source code and shfmt's JSON AST
2. Design 20–50 targeted test commands covering edge cases
3. **Test in isolated environment** with full config control:
   - **Test all config combinations** (empty, minimal, complex, precedence) for each command
4.
   - **Inspect existing configs** (global: `~/.config/devin/lovely-permissions.jsonc`, Devin configs)
   - **Create temp project dirs** with fully controlled configs (no global contamination)
   - Test with **empty config** (default behavior)
   - Test with **minimal config** (specific rules only)
   - Test with **complex config** (many rules, overlapping patterns)
   - Test with **config precedence** (global vs project vs local)
   - For completely isolated tests:
     - Create temp project dir (e.g., `/tmp/bughunt-{phase}/project`) and temp global dir
     - Create empty global config: `{}` at `<tmp-global>/lovely-permissions.jsonc`
     - Create test config in project: `<tmp-project>/.devin/lovely-permissions.jsonc`
     - Run: `DEVIN_GLOBAL_CONFIG_DIR=<tmp-global> DEVIN_PROJECT_DIR=<tmp-project> uv run lovely-devin-permissions --test '<cmd>'`
     - This ensures only the temp configs are loaded (no user's actual configs)
4. Validate suspicious results by comparing against raw shfmt AST
5. Document findings in the "Results" section of this plan
6. Handoff to the orchestrator for review and commit

> [!IMPORTANT]
> - The orchestrator also checks what the last agent had trouble with and updates the plan accordingly so that next agents do not suffer from the same challenges.
> - Phase 0 findings are always communicated to newly spawned agents so that they understand the config system without investigating.


## Config Testing Setup (Orchestrator Instructions)

> [!IMPORTANT]
> Every test command must be tested across ALL 5 config environments below. Use the template commands shown.

### Environment Setup Templates
```bash
# Create isolated test environments (one per phase)
rm -rf /tmp/bughunt-{phase} && mkdir -p /tmp/bughunt-{phase}/{empty,env2,env3}/{global,project/.devin}
```

### Config File Contents

```bash
# Empty configs (no rules)
echo '{}' > /tmp/bughunt-{phase}/empty/global/lovely-permissions.jsonc
echo '{}' > /tmp/bughunt-{phase}/empty/project/.devin/lovely-permissions.jsonc

# Minimal: allow common commands
echo '{"bash":{"allowed_cmds_regex":["^ls","^true","^echo","^cat","^grep","^find"]}}' > /tmp/bughunt-{phase}/env2/global/lovely-permissions.jsonc
echo '{}' > /tmp/bughunt-{phase}/env2/project/.devin/lovely-permissions.jsonc

# Complex: allowed + blocked
echo '{"bash":{"allowed_cmds_regex":["^ls .*","^true","^echo"],"blocked_paths_regex":["/etc","\\/home"]}}' > /tmp/bughunt-{phase}/env3/global/lovely-permissions.jsonc
echo '{"bash":{"allowed_cmds_regex":["^cat\\s+.*","^grep\\s+.+","^find\\s+"]}}' > /tmp/bughunt-{phase}/env3/project/.devin/lovely-permissions.jsonc
```

### Run Command Templates

These MUST be sent to all agents spawned, otherwise they'd lose their time figuring it out.

```bash
# Empty config
DEVIN_GLOBAL_CONFIG_DIR=/tmp/bughunt-{phase}/empty/global DEVIN_PROJECT_DIR=/tmp/bughunt-{phase}/empty/project uv run lovely-devin-permissions --test '<cmd>'

# Minimal config
DEVIN_GLOBAL_CONFIG_DIR=/tmp/bughunt-{phase}/env2/global DEVIN_PROJECT_DIR=/tmp/bughunt-{phase}/env2/project uv run lovely-devin-permissions --test '<cmd>'

# Complex config
DEVIN_GLOBAL_CONFIG_DIR=/tmp/bughunt-{phase}/env3/global DEVIN_PROJECT_DIR=/tmp/bughunt-{phase}/env3/project uv run lovely-devin-permissions --test '<cmd>'
```

## Bug Documentation Format (Agent Instructions)
```
BUG: [short title]
COMMAND: <exact --test argument>
TOOL OUTPUT: <paste tool's JSON response>
EXPECTED: <what should have happened>
EVIDENCE: <shfmt AST validation, if available>
```

## Exploration Space (Phases)

### Phase 0: Codebase Study & Config Inspection
**Status:** complete
**Objective:** Understand the architecture AND inspect existing user configs
**Activities:**
- Read `src/lovely_bash_permissions/segments.py` (AST extraction)
- Read `src/lovely_bash_permissions/rules.py` (rule evaluation)
- Read `src/lovely_bash_permissions/shfmt_json.py` (JSON parsing)
- Read `src/lovely_bash_permissions/bash_ast.py` (AST types)
- Read `src/lovely_bash_permissions/command_segs.py` (seg evaluation)
- Read `docs/AST.md` (shfmt AST documentation)
- Read `README.md` (command structure)
- **Inspect global configs:** `~/.config/devin/lovely-permissions.jsonc`, `~/.config/devin/config.json`
- **Inspect local configs:** `.devin/lovely-permissions.jsonc`, `.devin/config.json`, `.devin/config.local.json`
- Document the effective config that would apply in the current environment
**Deliverable:** Full documentation of how the config system works, including all files, keys and possibilities. This is to be documented in this document.

### Phase 1: Simple Redirections
**Status:** complete
**Objective:** Test basic output/input redirection
**Test Families:**
- `echo hi > file`
- `echo hi >> file`
- `cat < file`
- `cat <> file`
- `echo hi 2> file`
- `echo hi &> file`
- `echo hi > file 2> file`
- `echo hi > file 2>&1 > file` (chained)
- `echo hi > file && echo ok`
- `echo hi > file || echo ok`
- `echo hi > file 3> file3` (non-standard fd)
- `echo hi 1> file` (explicit stdout)
- `true < /dev/null > /dev/null` (both devnull)
- `true < /dev/stdin > /dev/stdout` (dev names)
- `true > /dev/fd/0` (fd references)
- `true > /proc/self/fd/1` (proc paths)
- `true > ./file` (relative paths)
- `true > ../file` (parent dir)
- `true > /file` (root)
- `true > ~user/file` (home expansion)
- `true > /path/with spaces/file` (spaces in path)
**Results:** 21 tests run across 3 config environments (empty, env2, env3). 20 confirmed correct, 1 bug found.

BUG: <> (truncate) redirection not detected as output redirection
COMMAND: cat <> file
TOOL OUTPUT: {"decision": "approve", "hookSpecificOutput": {"hookEventName": "PreToolUse", "updatedInput": {"command": ": '[♡ perms: 💚 auto-approved] command matches allowed pattern ^cat.' ; cat <> file"}}}
EXPECTED: Should require approval (ask) because <> opens the file for read/write AND truncates it (writes to the file).
EVIDENCE: shfmt parses <> as: "Op": "<>". The tool's rules.py has WRITE_REDIRECT_OPS = {">", ">>", ">|", "&>", ">&", "&>>"} — does NOT include <>. check_input_redirection only looks for "<" or "<<". Since <> matches neither category, the tool treats it as a non-redirection and only checks the command pattern (^cat), which passes. But in bash, cat <> file creates/truncates file — it's a write operation.
FIX: Add "<>" to WRITE_REDIRECT_OPS in src/lovely_bash_permissions/rules.py.

**Deliverable:** All tests run, results documented, bugs reported

### Phase 2: Complex Redirections
**Status:** complete
**Objective:** Test multiple, fd-specific, and chained redirections
**Test Families:**
- `echo hi > file1 > file2`
- `echo hi 2>&1 > file`
- `echo hi > file 2>&1`
- `cmd > file1 2> file2`
- `cmd > file1 2> file2 &> file3`
- `cmd < file1 > file2`
- `cmd < file1 > file2 < file3`
- `ls > file 2> file2 < file3`
- `cat file1 > file2 < file3`
**Results:** 9 tests run across 3 config environments (empty, env2, env3). All passed. 0 bugs found.

All tests correctly required approval or allowed based on config. The tool correctly handles chained redirections, stderr duplication (2>&1), mixed input/output redirections, and respects config policies. No parsing/classification bugs found.

**Deliverable:** All tests run, results documented, bugs reported

### Phase 3: Command Composition
**Status:** complete
**Objective:** Test semicolons, &&, ||, pipelines
**Test Families:**
- `echo hi > file; cat file`
- `echo hi > file && cat file`
- `echo hi > file || cat file`
- `echo hi > file | grep hi`
- `echo hi > file | grep hi > file2`
- `ls > file; cat file | grep hi`
- `true && echo hi > file`
- `false || echo hi > file`
- `echo hi > file1; echo hi > file2`
- `echo hi > file1 && echo hi > file2`
**Results:** Tested compound commands with output redirections. All correctly detected: `true && cat file > output`, `true || cat file > output`, `(cat file > output)`, `(true && cat file > output)` all require approval. No bugs found.

**Deliverable:** All tests run, results documented, bugs reported

### Phase 4: Command Substitution
**Status:** complete
**Objective:** Test $(...) and backtick substitution
**Test Families:**
- `echo $(cat file)`
- `echo "$(cat file)"`
- `echo `cat file``
- `echo $(echo hi > file)`
- `echo "$(echo hi > file)"`
- `echo `echo hi > file``
- `var=$(echo hi > file)`
- `var="$(echo hi > file)"`
- `var=`echo hi > file``
- `result=$(ls > file 2>&1)`
- `result="$(ls > file 2>&1)"`
- `echo $(echo hi > file) && echo ok` (compound)
- `if [ $(cat file) ]; then echo ok > out; fi` (conditional)
- `for f in $(ls); do echo $f > out; done` (loop)
- `echo $(echo $(echo nested > file))` (double nesting)
- `echo $((5 > 3))` (arithmetic expansion)
- `echo $((5 + 3 > file))` (arithmetic with file)
- `echo $(true)` (command substitution with builtin)
- `var=$(echo test)` (no redirection in substitution)
- `echo $(ls /) > file` (ls in substitution, redirect outside)
- `$(echo hi > file)` (standalone substitution)
**Results:** 20+ targeted tests across three environments (empty, env2 with basic allow rules, env3 with complex regex patterns). Found **3 confirmed bugs** in command substitution handling:

BUG #1: Substitution args not counted (env3)
COMMAND: cat $(echo files.txt)
TOOL OUTPUT: "REQUIRES-USER-APPROVAL"
EXPECTED: Should be approved since cat with args is allowed in env3 (pattern ^cat\s+.*). But substitution args are not counted when matching the pattern.

BUG #2: Standalone substitution with redirection (env2)
COMMAND: $(echo hello) > output.txt
TOOL OUTPUT: "REQUIRES-USER-APPROVAL"
EXPECTED: Should be approved since echo is allowed in env2. But the outer substitution wraps an allowed command but is treated as "$(...)" command.

BUG #3: Variable assignment with substitution (env2)
COMMAND: var=$(echo hello)
TOOL OUTPUT: "REQUIRES-USER-APPROVAL"
EXPECTED: Should be approved since echo is allowed in env2. But substitution in variable assignments isn't recognized as a separate command.

Correct behavior verified: cat <(ls) → approve ✓, ls | cat $(ls) → approve ✓, cat $(ls) → approve ✓.

Root cause: shfmt JSON treats command substitutions differently than literal arguments, and the segments extraction in segments.py doesn't recognize substitution-wrapped allowed commands.

**Deliverable:** All tests run, results documented, bugs reported

### Phase 5: Here-Docs
**Status:** complete
**Objective:** Test << and <<- here-documents
**Results:** Ran 30 targeted heredoc tests across all 3 environments (empty, env2, env3). All tests behaved correctly — heredocs were properly detected and processed. No bugs found.
**Test Families:**
- `cat << EOF`
- `cat <<EOF`
- `cat <<EOF > file`
- `cat <<- EOF`
- `cat <<-EOF`
- `cat <<-EOF > file`
- `grep pattern << EOF`
- `grep pattern <<EOF > file`
- `ls | grep pattern << EOF`
- `cat > file << EOF` (redirect before heredoc)
- `cat > file <<EOF` (redirect before heredoc)
- `cat >> file << EOF` (append with heredoc)
- `tee file << EOF` (tee with heredoc)
- `sort << EOF` (utility with heredoc)
- `awk '{print}' << EOF` (awk with heredoc)
- `sed 's/a/b/' << EOF` (sed with heredoc)
- `cat <<EOF > file1 && cat <<EOF2 > file2` (multiple heredocs)
- `cat <<EOF > file1; cat <<EOF2 > file2` (separate heredocs)
- `cat <<'EOF' > file` (quoted delimiter - no expansion)
- `cat <<"EOF" > file` (double-quoted delimiter)
- `cat <<END > file` (non-standard delimiter)
- `cat << EOF > file1 && cat << EOF2 > file2` (different delimiters)
- `if true; then cat << EOF > file; fi` (heredoc in if)
- `for x in 1; do cat << EOF > file; done` (heredoc in loop)
**Deliverable:** All tests run, results documented, bugs reported

### Phase 6: Quoting Edge Cases
**Status:** complete
**Objective:** Test single, double, escape, mixed quoting
**Test Families:**
- `echo 'hi' > file`
- `echo "hi" > file`
- `echo 'hi > file'`
- `echo "hi > file"`
- `echo hi\ >\ file`
- `echo "hi" > file`
- `echo 'hi' > file && echo "ok"`
- `var="hi > file"`
- `var='hi > file'`
- `cmd=$(echo "hi > file")`
- `echo 'test > file' > file2` (nested redirects)
- `echo "test > file" > file2`
- `echo "test 'inner' > file"` (mixed quotes)
- `echo "test \"escaped\" > file"` (escaped quotes)
- `echo "test \'single\' > file"` (escaped single)
- `echo 'test "double" > file'` (quotes inside single)
- `echo "test '$' > file"` (dollar in quotes)
- `echo "test `$'\t'` > file"` (ANSI-C quoting)
- `echo "test $(pwd) > file"` (subst in quotes)
- `echo 'test $(pwd) > file'` (literal subst in single)
- `echo $var > file` (variable in redirect)
- `echo "$var" > file` (quoted variable)
- `echo ${var:-default} > file` (param expansion)
- `echo ${var?message} > file` (param expansion)
- `echo ${var#pattern} > file` (pattern removal)
**Results:** 29 targeted tests across three environments (empty, minimal, complex). All tests passed. **0 bugs found.**

The tool correctly handles: single quotes, double quotes, mixed quotes, nested quotes, escaped quotes, heredocs with quotes, heredocs with variable/command substitution, backtick substitution, indented heredocs, empty strings, multiple redirections with quotes, variable in redirects, param expansion, pattern removal.

**Deliverable:** All tests run, results documented, bugs reported

### Phase 7: Variables and Expansion
**Status:** partially complete
**Objective:** Test variable assignment and expansion
**Bugs Fixed (Manual Investigation):**

BUG #8: LetClause was skipped (produced no segments), treated as empty command
COMMAND: let x=5 > file
TOOL OUTPUT: "REQUIRES-USER-APPROVAL" <empty command> produced no parseable segments — defaulting to wildcard policy (ask)."
EXPECTED: Should produce a variable assignment segment with expression captured as arg, and properly handle the > file redirect.
EVIDENCE: shfmt parses as: LetClause { exprs: [BinaryArithm{x: Word(x), op: "=", y: Word(5)}] }
FIX: Added LetClause handling in _extract_segments() to produce variable assignment segment with proper redirect inheritance. Also fixed has_cmdsubst detection for DblQuoted values in variable assignments.

**Remaining:** Variable assignment, parameter expansion, shell builtins with redirects (still to test)
**Test Families:**
- `VAR=value`
- `VAR="value" > file`
- `VAR='value' > file`
- `export VAR=value > file`
- `readonly VAR=value > file`
- `declare VAR=value > file`
- `echo $VAR > file`
- `echo "${VAR}" > file`
- `echo ${VAR:-default} > file`
- `cmd="true" && echo hi > file`
- `VAR=value cmd > file` (env var inline)
- `VAR="value with spaces" cmd > file`
- `VAR=$(echo hi > file) cmd` (subst in inline var)
- `VAR=value; cmd > file` (assignment then command)
- `VAR=value && cmd > file`
- `export VAR=value; echo hi > file`
- `local VAR=value > file` (inside function context)
- `let x=5 > file` (let with redirect)
- `let "x = 5" > file` (quoted let)
- `typeset VAR=value > file`
- `shopt -s extglob > file` (shopt with redirect)
- `set -o pipefail > file` (set with redirect)
- `unset VAR > file`
- `echo ${VAR:+value} > file` (param expansion)
- `echo ${VAR#prefix} > file`
- `echo ${VAR%suffix} > file`
- `echo ${VAR/pattern/replacement} > file`
- `echo ${VAR,,} > file` (case conversion)
**Deliverable:** All tests run, results documented, bugs reported

### Phase 8: Subshells and Grouping
**Status:** not started
**Objective:** Test () and {} grouping
**Test Families:**
- `(echo hi > file)`
- `{ echo hi > file; }`
- `(echo hi > file && echo ok)`
- `{ echo hi > file; } && echo ok`
- `(cat file1 > file2) && (cat file2 > file3)`
- `(echo hi > file1) | (cat > file2)`
- `(echo hi > file1) | (cat > file2) | (cat > file3)` (3 subshells)
- `(true) && (false) && (echo hi > file)` (chained subshells)
- `(echo hi > file) & (echo ok > file2)` (backgrounded)
- `(echo hi > file) | { cat > file2; }` (mixed grouping)
- `{ echo hi > file1; echo ok > file2; }` (multiple in brace)
- `{ cat file1; cat file2; } > output` (combined output)
- `(cat file1 | cat file2) > output` (pipe in subshell)
- `for f in *; do (echo "$f" > "output_$f"); done` (loop with subshell)
**Deliverable:** All tests run, results documented, bugs reported

### Phase 9: Special Builtins
**Status:** not started
**Objective:** Test cd, test, [, [[, true, false
**Test Families:**
- `cd / > file`
- `test -f file > file2`
- `[ -f file ] > file2`
- `[[ -f file ]] > file2`
- `true > file`
- `false > file`
- `type cd > file`
- `which cd > file`
- `[ -f file ] && echo hi > out`
- `[[ -f file ]] || echo hi > out`
- `test "x" = "x" > file`
- `[ "x" != "y" ] > file`
- `[[ "$var" == "val" ]] > file`
- `[ -d / ] && [ -f file ] > out`
- `test -r file && test -w file > out`
- `[ -e file ] && cat file > out`
- `true | false > file` (pipe through builtin)
- `false && true > file`
- `true || true > file`
- `[ -z "$var" ] > file`
- `[ -n "$var" ] > file`
- `[ "$var" -eq 0 ] > file` (numeric comparison)
- `[[ $var =~ pattern ]] > file` (regex)
- `[ -f file ] && { cat file > out; }` (compound test)
- `if [ -f file ]; then cat file > out; fi` (if with redirect)
- `case $(test -f file && echo yes) in yes) echo ok > out;; esac`
- `eval "echo hi > file"` (eval with redirect)
- `exec > file` (exec redirect)
- `exec 3> file` (fd exec)
- `command ls > file` (command builtin)
- `builtin echo > file` (builtin cmd)
- `[ 1 -lt 2 ] && echo ok > out` (chained compare)
**Deliverable:** All tests run, results documented, bugs reported

### Phase 10: Tricky Patterns
**Status:** not started
**Objective:** Test uncommon or ambiguous bash syntax
**Test Families:**
- `echo hi > file < file`
- `cmd > /dev/null`
- `cmd < /dev/null`
- `cmd > /dev/null 2>&1`
- `cmd < /dev/null > /dev/null`
- `echo hi > file 2> /dev/null`
- `cat < file > /dev/null`
- `ls > /dev/null 2> /dev/null`
- `true > file 2>&1 > file2` (triple redirect)
- `true > file 2> file2 > file3` (three distinct)
- `true > file 2>&1 &` (background with redirect)
- `true > file &` (simple background)
- `true > file1 2>&1 & true > file2` (bg + fg)
- `true > file </dev/null` (redirect order)
- `true </dev/null > file` (other order)
- `true >file` (no spaces)
- `true> file` (partial space)
- `true>file` (no spaces at all)
- `true > file < file2 < file3` (multiple input)
- `true > file 2> file2 < file3` (mixed directions)
- `true > /dev/null 2>&1 > /dev/null` (devnull chain)
- `true 3>&1 > /dev/null` (save fd)
- `true > /dev/null 3>&1` (save after)
**Deliverable:** All tests run, results documented, bugs reported

### Phase 11: Nested Constructs and Compound Expressions
**Status:** not started
**Objective:** Test deeply nested and compound expressions
**Test Families:**
- Nested substitution: `echo $(echo $(echo $(echo hi))) > file`
- Nested substitution with redirect: `echo $(echo $(cat <<< "hi") > file)`
- Mixed pipes and substitution: `echo $(echo hi | tr 'a' 'b') > file`
- Pipe chains: `echo hi | grep hi | grep h | cat > file`
- Complex pipeline: `ls | grep text | xargs cat > file`
- Nested conditionals: `if [ x ]; then if [ y ]; then echo hi > file; fi; fi`
- Compound logical: `[ x ] && ([ y ] || [ z ]) > file`
- Brace expansion with redirect: `echo {a,b,c} > file`
- Brace expansion nested: `echo {a,b}{c,d} > file`
- Here-doc in substitution: `cat <<< $(echo hi) > file`
- Here-doc in condition: `if $(cat <<< "yes" | grep yes); then echo ok > file; fi`
- Nested arithmetic: `let x=$(($((${y:-5}) + 3)) + 2) > file`
- Multi-level nesting: `(( $(($(1+1)+1) > 2)) ) && echo ok > file`
**Deliverable:** All tests run, results documented, bugs reported

### Phase 12: Complex Nested Constructs
**Status:** not started
**Objective:** Test deeply nested and compound expressions
**Test Families:**
- Nested substitution: `echo $(echo $(echo $(echo hi))) > file`
- Nested substitution with redirect: `echo $(echo $(cat <<< "hi") > file)`
- Mixed pipes and substitution: `echo $(echo hi | tr 'a' 'b') > file`
- Pipe chains: `echo hi | grep hi | grep h | cat > file`
- Complex pipeline: `ls | grep text | xargs cat > file`
- Nested conditionals: `if [ x ]; then if [ y ]; then echo hi > file; fi; fi`
- Compound logical: `[ x ] && ([ y ] || [ z ]) > file`
- Brace expansion with redirect: `echo {a,b,c} > file`
- Brace expansion nested: `echo {a,b}{c,d} > file`
- Here-doc in substitution: `cat <<< $(echo hi) > file`
- Here-doc in condition: `if $(cat <<< "yes" | grep yes); then echo ok > file; fi`
- Nested arithmetic: `let x=$(($((${y:-5}) + 3)) + 2) > file`
- Multi-level nesting: `(( $(($(1+1)+1) > 2)) ) && echo ok > file`
**Deliverable:** All tests run, results documented, bugs reported

### Phase 13: Advanced Bash Constructs
**Status:** not started
**Objective:** Test process substitution, coproc, traps, functions
**Test Families:**
- Process substitution: `cat <(echo hi) > file`
- Process substitution: `diff <(ls file1) <(ls file2)`
- Process substitution redirect: `cat <(echo hi) > file2`
- Coproc: `coproc myproc { echo hi; }`
- Coproc with redirect: `coproc myproc { echo hi > file; }`
- Trap with redirect: `trap "echo trap > file" EXIT`
- Function with redirect: `fn() { echo hi > file; }`
- Function call with redirect: `fn > out`
- Export with complex: `export PATH="$PATH:/usr/local/bin" > file`
- Export with substitution: `export VAR=$(echo hi) > file`
- Unset with array: `unset arr[@] > file`
- declare with type: `declare -A map > file`
**Deliverable:** All tests run, results documented, bugs reported

### Phase 14: Combined and Edge Cases
**Status:** not started
**Objective:** Test all features combined and unusual bash patterns
**Test Families:**
- Multi-feature: `if [ $(echo hi) ]; then cat <<< "x" | grep x > file; fi`
- Mixed: `while read line; do echo $line > file; done <(echo hi)`
- Complex pipeline with heredocs: `cat << EOF | grep pattern > file`
- Nested everything: `if $(test -f <(echo hi)); then cat <<< $(echo ok) > file; fi`
- Multi-line compound: long commands with multiple features
- Empty command: just whitespace
- Single-quote edge: `'single > file'` vs `"double > file"`
- Escaped redirect: `echo hi \> file`
- Comment redirect: `# redirect > file`
- Here-doc with escape: `cat <<EOF\n` (edge)
- Here-doc with tab: `cat <<-	EOF` (edge)
- Substitution in here-doc: `cat <<EOF \n$var\nEOF`
**Deliverable:** All tests run, results documented, bugs reported

## Results

### Phase 0

**Architecture Overview:**
lovely-bash-permissions parses bash commands into structured AST using shfmt-py, extracts command segments, and evaluates them against configurable rules.

**Core Components:**
1. **Parser** (parser.py, converter.py): Uses shfmt-py's --to-json to parse bash, converts to typed Python dataclass AST nodes.
2. **AST Types** (ast.py): 45 dataclass types: CallExpr, Word, Lit, Redir, BinaryCmd (pipes/&&/||), Block, Subshell, IfClause, ForClause, WhileClause, CmdSubst, ProcSubst, etc.
3. **Segment Extraction** (segments.py): parse_segments() splits complex commands into individual segments. Each segment: command (name), arguments (strings), redirections (dicts).
4. **Rules Engine** (rules.py): check_allowed_patterns(), check_blocked_patterns(), check_output_redirection(), check_input_redirection(), check_background_execution()
5. **Evaluator** (evaluate.py): evaluate_bash_command() - parses, extracts segments, evaluates each, aggregates (all allowed → allow, any denied → deny, any asks → ask)
6. **Config System** (config/): loader.py (3-location deep merge), manager.py (PermissionsManager), schema.py (Pydantic models), jsonc.py (json5), devin.py (Exec patterns to regex)
7. **Hook Interface** (hook.py): process_hook_event(), generate_hook_response()
8. **CLI** (cli.py, devin_cli.py): --test, --show-config, --setup

**Config System Details:**
- **Lovely Permissions Config** (lovely-permissions.jsonc): 3 load locations (global → project → local), deep merged (objects merge, arrays concatenate, scalars override). Key: bash with ToolConfig schema (* wildcard, allowed_cmds_regex, blocked_paths_regex, output_redirection, input_redirection, background_execution, subshell, variable_assignment)
- **Devin Config** (config.json): 3 locations, permissions.allow Exec(prefix) patterns converted to anchored regex (Exec(git log) → ^git log(\s|$))
- **Effective Config** (effective_bash.py): Combines lovely config bash section with Devin exec regexes, always adds hook label regex

**Current Environment Config (Phase 0):**
- **Global lovely config** (~/.config/devin/lovely-permissions.jsonc): 47 allowed_cmds_regex patterns, *: "ask", subshell: "allow", output_redirection: object (*: ask, stderr_to_dev_null: allow, stderr_to_stdout: allow), blocked_paths_regex: ["\/etc", "\.env$", "\.envrc$"]
- **Global devin config** (~/.config/devin/config.json): permissions.allow: ["Exec(: '[♡ perms:)"]
- **Project/local configs**: Don't exist (.devin/ is empty)

**Effective Config for Current Environment:**
- allowed_cmds_regex: 47 patterns from global lovely + 1 from devin (hook label)
- blocked_paths_regex: ["\/etc", "\.env$", "\.envrc$"]
- Wildcard: "ask"
- Subshell: "allow"
- Output redirection: object (ask default, allow stderr_to_dev_null, allow stderr_to_stdout)
- Input redirection: "ask"
- Background execution: "ask"
- Variable assignment: "ask"


## Bug Counter

Total bugs documented: **7 / 50**

Phases completed: 0, 1, 2, 3, 4, 5, 6
Phases remaining: 7, 8, 9, 10, 11, 12, 13, 14

Next: Phase 7 - Variables and Expansion (variable assignment, parameter expansion, shell builtins with redirects).

