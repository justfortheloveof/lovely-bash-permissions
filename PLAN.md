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
- [x] 276 tests collected, all passing — baseline confirmed.

### Step 2 — Create `test_ast.py` with all node type tests
- [x] Created `tests/test_ast.py` from `test_parser.py` and `test_nodes.py`
- All node-type test classes preserved: TestLitNodes, TestSglQuotedNodes, TestParamExpNodes,
  TestDblQuotedNodes, TestCmdSubstNodes, TestArithmExpNodes, TestProcSubstNodes,
  TestExtGlobNodes, TestBlockNodes, TestFuncDeclNodes, TestBraceExpNode,
  TestSimpleCommands, TestPipes, TestRedirections, TestVariables, TestComplexCommands,
  TestEdgeCases, TestASTStructure

### Step 3 — Create `test_inspect.py` from phase2 tests
- [x] Created `tests/test_inspect.py` from `test_phase2.py`
- Test classes moved: TestVisitorPattern, TestFindCommands, TestFindArguments,
  TestHasPipe, TestGetTargetFiles, TestIntegration

### Step 4 — Create `test_features.py` from phase3 tests
- [x] Created `tests/test_features.py` from `test_phase3.py`
- Test classes moved: TestSubshells, TestIfStatements, TestForLoops, TestWhileLoops,
  TestAndOrOperators, TestMultiLineCommands, TestComplexNestedStructures,
  TestEdgeCases, TestCommandSubstitution, TestRedirectionComplex,
  TestVariablesComplex, TestErrorMessages, TestParseErrorAttributes

### Step 5 — Delete old files and verify
- [x] Removed `test_nodes.py`, `test_phase2.py`, `test_phase3.py`
- [x] Full suite rerun: 276 tests passing

### Step 6 — Add `tests/__init__.py` if missing
Ensure the tests directory is a proper package (for relative imports).

## Completion Criteria
- [x] All original test classes/functions preserved and passing (276 tests)
- [x] New file names match source module names (ast → ast, inspect → inspect)
- [x] Zero test duplication between files
