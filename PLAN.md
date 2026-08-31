# Test Refactoring Plan

## Current State

**Source modules (4 files):**
- `src/lovely_bash_permissions/__init__.py` — package exports
- `src/lovely_bash_permissions/parser.py` — core parser (`parse`, `ParseError`)
- `src/lovely_bash_permissions/ast.py` — AST node types and parsing logic
- `src/lovely_bash_permissions/inspect.py` — inspection/traversal utilities

**Test files (4 files):**
- `tests/test_parser.py` — parser tests ✅ matches source correctly
- `tests/test_nodes.py` — only **BraceExp** node type (1 class, 6 tests)
- `tests/test_phase2.py` — visitor pattern + inspection helpers (find_commands, find_arguments, has_pipe, get_target_files)
- `tests/test_phase3.py` — edge cases, error handling, shell features (subshells, if/else, loops, pipes)

**Problem:** Most node-type tests (Lit, SglQuoted, ParamExp, DblQuoted, CmdSubst, ArithmExp, ProcSubst, ExtGlob, Block, FuncDecl) live inside `test_parser.py` — a file that should test only the parser module. Test files don't match source file names, and coverage is scattered rather than organized by module.

## Target Structure

```
tests/
├── test_parser.py       — parser module tests (parse, ParseError)  [already correct]
├── test_ast.py          — all node type tests (from test_parser.py + test_nodes.py)
├── test_inspect.py      — inspection/traversal tests (from test_phase2.py)
└── test_features.py     — shell features, edge cases (from test_phase3.py)
```

## Steps

### Step 1 — Verify current tests pass
Run the full test suite and confirm baseline passes before any changes.

### Step 2 — Create `test_ast.py` with all node type tests
Move every test class that tests AST node types from `test_parser.py` and `test_nodes.py` into this new file. Includes:
- TestLitNodes, TestSglQuotedNodes, TestParamExpNodes, TestDblQuotedNodes
- TestCmdSubstNodes, TestArithmExpNodes, TestProcSubstNodes, TestExtGlobNodes
- TestBlockNodes, TestFuncDeclNodes (from `test_parser.py`)
- TestBraceExpNode (from `test_nodes.py`, rename class to match naming convention)
- TestSimpleCommands, TestPipes, TestRedirections, TestVariables, TestComplexCommands,
  TestEdgeCases, TestASTStructure (from `test_parser.py` — these test parsed AST structure)

### Step 3 — Create `test_inspect.py` from phase2 tests
Move inspection helper tests from `test_phase2.py`:
- TestVisitorPattern, TestFindCommands, TestFindArguments, TestHasPipe,
  TestGetTargetFiles, TestIntegration

### Step 4 — Create `test_features.py` from phase3 tests
Move shell features and edge-case tests from `test_phase3.py`:
- TestSubshells, TestIfStatements, TestForLoops, TestWhileLoops,
  TestAndOrOperators, TestMultiLineCommands, TestComplexNestedStructures,
  TestEdgeCases, TestCommandSubstitution, TestRedirectionComplex,
  TestVariablesComplex, TestErrorMessages, TestParseErrorAttributes

### Step 5 — Delete old files and verify
Remove `test_nodes.py`, `test_phase2.py`, `test_phase3.py`. Run full suite: all tests must pass.

### Step 6 — Add `tests/__init__.py` if missing
Ensure the tests directory is a proper package (for relative imports).

## Completion Criteria
- All original test classes/functions preserved and passing
- New file names match source module names (ast → ast, inspect → inspect)
- Zero test duplication between files
