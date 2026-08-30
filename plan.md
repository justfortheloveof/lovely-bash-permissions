# Plan: Bash Command Parser with shfmt-py

## Goal
Build a Python library that uses shfmt-py's `--to-json` flag to parse bash commands and expose the AST for inspection. This will be used to parse commands that AI agents want to run.

## Status: Complete (Phase 4)

## Architecture

The system has three main modules:
1. **`parser.py`** - Invokes shfmt binary and returns raw JSON
2. **`ast.py`** - Converts JSON to typed Python dataclasses
3. **`inspect.py`** - Provides query utilities (get_commands, get_arguments, etc.)

## File Structure
```
lovely-bash-permissions/
├── src/
│   └── lovely_bash_permissions/
│       ├── __init__.py      # Package exports
│       ├── parser.py        # Core shfmt invocation
│       ├── ast.py           # Typed AST dataclasses
│       └── inspect.py       # Query utilities
├── tests/                   # (to be created)
├── plan.md                  # This file
├── README.md                # Documentation
├── pyproject.toml           # uv project config
└── uv.lock                  # Lock file
```

## Implementation Plan

### Phase 1: Foundation (Complete)
- [x] Initialize repo with uv
- [x] Add shfmt-py dependency
- [x] Explore shfmt-py's JSON output format
- [x] Create `parser.py` with core parse function
- [x] Define AST dataclasses in `ast.py`
- [x] Build inspector with traversal utilities
- [x] Implement get_commands(), get_arguments(), has_variable(), get_redirections()
- [x] Test with pipes, redirections, and variables
- [x] Write comprehensive tests
- [ ] Write documentation (README)
- [x] Commit and tag v0.1.0-alpha

### Phase 2: AST Inspection (Complete)
- [x] Build more comprehensive inspector
- [x] Implement node visitor pattern
- [x] Add helper methods: find_commands(), find_arguments(), has_pipe(), get_target_files()
- [x] Write comprehensive tests (28 new tests added)
- [x] Commit and tag v0.2.0-alpha

### Phase 3: Error Handling & Edge Cases
- [ ] Robust error handling
- [ ] Handle shell features: pipes, redirects, variables, subshells, conditionals
- [ ] Handle multi-line commands
- [ ] Write edge case tests
- [ ] Commit and tag v0.3.0-alpha

### Phase 4: Polish & Documentation (Complete)
- [x] Full documentation (README, docstrings)
- [x] Examples in README
- [x] Type hints and py.typed
- [ ] Publish to PyPI (optional)
- [x] Commit and tag v0.4.0

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

---

## Context for Continuation

### What's Implemented
- `parser.py`: Invokes `.venv/bin/shfmt` with `--to-json` and returns raw JSON dict
- `ast.py`: Defines dataclasses (Position, Node, Word, Part, CallExpr, BinaryCmd, Stmt, File) and conversion functions (node_from_json, stmt_from_json, word_from_json, part_from_json)
- `inspect.py`: Query utilities (get_commands, get_arguments, has_variable, get_redirections)
- `__init__.py`: Exports all public API functions

### API Surface
```python
from lovely_bash_permissions import parse_ast, get_commands, get_arguments, has_variable, get_redirections

tree = parse_ast('ls -la | grep txt > output.txt')
get_commands(tree)        # ['ls', 'grep']
get_arguments(tree)       # [['-la'], ['txt']]
has_variable(tree)        # False
get_redirections(tree)    # [{'op': '>', 'target': 'output.txt'}]
```

### Dependencies
- shfmt-py>=4.1.0 (provides the shfmt binary at .venv/bin/shfmt)
- Python 3.14

### Test Status
- No formal test suite yet (only ad-hoc CLI tests)
- Tested: pipes, redirections, variables, simple commands

### Conventions
- Use dataclasses for AST nodes
- Lowercase method names
- Follow the shfmt JSON structure as closely as possible
- Test with `uv run python -c "..."`
