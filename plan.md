# Plan: Bash Command Parser with shfmt-py

## Goal
Build a Python library that uses shfmt-py's `--to-json` flag to parse bash commands and expose the AST for inspection. This will be used to parse commands that AI agents want to run.

## Status: In Progress (Phase 1)

## Architecture

The system will have these components:

1. **Parser Core** (`src/lovely_bash_permissions/parser.py`)
   - Invoke shfmt's `--to-json` flag to parse bash commands
   - Parse the JSON output into a structured Python AST representation
   - Handle errors (syntax errors, etc.)

2. **AST Node Types** (`src/lovely_bash_permissions/ast.py`)
   - Define typed dataclasses or models for each node type
   - Enable type-safe inspection of the command tree

3. **Inspector/Traversal** (`src/lovely_bash_permissions/inspect.py`)
   - Utility functions to query the AST
   - Find commands, arguments, pipelines, redirections, etc.

4. **CLI** (future)
   - Command-line tool to inspect bash commands

## Implementation Plan

### Phase 1: Foundation (Current)
- [x] Initialize repo with uv
- [x] Add shfmt-py dependency
- [x] Explore shfmt-py's JSON output format
- [x] Create `parser.py` with core parse function
- [x] Define AST dataclasses in `ast.py`
- [x] Build inspector with traversal utilities
- [x] Implement get_commands(), get_arguments(), has_variable(), get_redirections()
- [x] Test with pipes, redirections, and variables
- [ ] Write comprehensive tests
- [ ] Write documentation (README)
- [ ] Commit and tag v0.1.0-alpha

### Phase 2: AST Inspection
- [ ] Build more comprehensive inspector
- [ ] Implement node visitor pattern
- [ ] Add helper methods: find_commands(), find_arguments(), has_pipe(), get_target_files()
- [ ] Write comprehensive tests
- [ ] Commit and tag v0.2.0-alpha

### Phase 3: Error Handling & Edge Cases
- [ ] Robust error handling
- [ ] Handle shell features: pipes, redirects, variables, subshells, conditionals
- [ ] Handle multi-line commands
- [ ] Write edge case tests
- [ ] Commit and tag v0.3.0-alpha

### Phase 4: Polish & Documentation
- [ ] Full documentation (README, docstrings)
- [ ] Examples in README
- [ ] Type hints and py.typed
- [ ] Publish to PyPI (optional)
- [ ] Commit and tag v0.4.0

## Research: shfmt-py Capabilities

shfmt v3.14.0 supports:
- `--to-json`: Print syntax tree as typed JSON
- `--from-json`: Read syntax tree from typed JSON
- Parser options: `--language-dialect bash/posix/mksh/bats/zsh`
- Simplify mode: `--simplify`
- Minify mode: `--minify`

## shfmt AST Node Types (Observed)

| Type | Description |
|------|-------------|
| `File` | Top level, has `Stmts` array |
| `Stmt` | Statement with `Cmd`, `Position`, `Redirs` |
| `CallExpr` | Simple command call with `Args` array |
| `BinaryCmd` | Pipe `|` with `X`, `Y`, `Op` |
| `Word` | Has `Parts` array |
| `Lit` | Literal value with `Value` field |
| `ParamExp` | Parameter expansion (e.g., $HOME) with `Param` |
| `Var` | Variable reference |
| `And/Or` | `&&` / `||` (to be tested) |
| `Subshell` | `(cmd)` (to be tested) |
| `If/For/While/Case` | Control flow (to be tested) |
| `Func` | Function definition (to be tested) |
| `Alias` | Alias definition (to be tested) |

## Key Decisions (To Be Made)
1. Use dataclasses vs pydantic vs attrs for AST nodes
2. Whether to validate JSON schema
3. How to handle unknown/shfmt-specific node types
4. Visitor pattern implementation
5. Include shell dialect detection or always use bash?

## Risks
- shfmt JSON format may be complex and unstructured
- Need to understand shfmt's AST node types thoroughly
- Performance: spawning shfmt binary per parse call
- Edge cases in bash syntax that shfmt may not handle

## Next Steps
1. Write comprehensive tests
2. Build more comprehensive inspector
3. Write documentation (README)
4. Commit and tag
