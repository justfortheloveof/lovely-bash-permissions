# Architecture

A short map of `lovely_bash_permissions` for someone who has not read it before.
Two independent halves ship in one package: a general-purpose bash parser, and a
Devin CLI permission hook built on top of it.

## Tests

`tests/` mirrors the package, so "where does the test for X go" has one answer.

| Location | Holds |
| --- | --- |
| `tests/test_<module>.py` | tests for `lovely_bash_permissions/<module>.py` |
| `tests/config/test_<module>.py` | tests for `lovely_bash_permissions/config/<module>.py` |
| `tests/scenarios/` | tests that span modules and exercise a whole decision |
| `tests/tooling/` | checks on the repository, not the package |

A module whose tests split by concern gets `test_<module>_<concern>.py` siblings
rather than one large file — `cli.py` has four, `rules.py` two, `segments.py`
four. Anything in `scenarios/` deliberately belongs to no single module: it is
about the product's behaviour, not one module's internals. If a test only
imports one module, it does not belong there.

All shared fixtures and helpers live in a single `tests/conftest.py`. The tree is
split by subject, not by audience, so one root conftest serves all of it and
there is nowhere else to look.

## The two halves

**Library half** — the parser and its inspection API, which is what `README.md`
documents. Its dependency order is strictly one-way:

```
errors.py            (leaf: ShfmtError)
parser.py            -> errors            (shfmt subprocess -> raw JSON)
ast.py               (leaf: the typed node dataclasses)
inspect.py           -> ast               (queries over a tree the caller holds)
converter.py         -> ast, parser       (raw JSON -> typed tree)
segments.py          -> ast, converter, errors, inspect, parser
rules.py             -> segments          (types only; policy on segment dicts)
evaluate.py          -> ast, converter, inspect, parser, rules, segments
cli.py               -> ast, converter, errors, inspect, segments
__init__.py          re-exports the public surface
```

`inspect.py` depends on `ast.py` alone on purpose: it answers questions about a
tree the caller already holds, so it never parses. `converter.py` imports
`parser.parse` lazily, inside `parse_ast`, to keep the graph acyclic.

**Devin half** — the permission hook: `config/` -> `hook.py` -> `devin_cli.py`.
It depends on the library half (`hook.py` calls `evaluate.evaluate_bash_command`)
and **nothing in the library half imports any of it**; `config/` imports nothing
from the library half at all. The parser can be vendored and used on its own, and
the hook can be deleted without touching it. Two console scripts sit at the
edges: `lovely-bash-inspection` (library half) and `lovely-devin-permissions`
(Devin half).

## One permission decision

`evaluate_bash_command(command, config)` is the whole flow, in order:

1. **`parse(command)`** — one `shfmt --to-json` subprocess. Any failure raises
   `ShfmtError`; the hook maps that to the `error` policy rather than letting the
   command through.
2. **`node_from_json(raw)`** — raw JSON becomes a typed `File`.
3. **`_segments_from_ast(tree)`** — the typed AST becomes the flat segment list.
4. **`rules.py` policy checks** over those segments, plus the per-segment
   allowed/blocked matchers in `evaluate.py`.
5. **Verdict** — a `_Verdict` accumulator folded through the steps, ending in
   `{"status", "reason", "segments"}`.

Steps 1-3 happen **exactly once per decision**, threaded through a single
`ParsedCommand` dataclass (`raw`, `tree`, `segments`) that every later pass
reads. This was a deliberate fix: building the three forms separately meant
spawning shfmt twice and re-running the JSON-to-AST conversion three times for one
decision. Do not "simplify" a call site back into calling `parse()` or
`parse_segments()` directly — undoing that is what `ParsedCommand` exists to
prevent.

## Two representations, on purpose

The typed dataclass AST and the raw shfmt JSON both stay in `ParsedCommand`.
Having both looks like leftover duplication; it is not. Two consumers need
fields the typed AST does not carry:

- **Heredoc-body scanning** (`evaluate._heredoc_body_texts`) walks the **raw**
  tree and identifies a heredoc by its `Op` (`<<` / `<<-`) plus its `Hdoc` key.
  shfmt's redirection dicts have no `Type` field to dispatch on, and the typed
  `Redir` carries the body as an ordinary `Word`, indistinguishable from a normal
  redirect target.
- **Background detection** (`rules._collect_background_command_names`) walks the
  **raw** tree and keys off a `Background` boolean on the statement dict. The
  typed `Stmt` has no such attribute at all.

Everything else — substitution detection, allowed-pattern matching, segment
extraction — uses the typed AST, which is cheaper to traverse and more complete
(it sees substitutions nested inside quoted strings, which a raw-dict visitor
misses). This split is deliberate: converting the raw tree away would cost a
walk and buy nothing for those two callers.

## The invariant that matters most

**Policy is decided on the *executed* form of a word, never the text as typed.**

`inspect._word_exec` renders a word the way bash would resolve it: quotes
removed, backslashes unescaped, expansions kept as visible placeholders. The
segment redirection field `Target` and the segment `normalized_arguments` list
are both built from it, and `rules._redir_target` reads `Target` as the *only*
field policy is decided on.

This is not cosmetic. Matching the raw text instead lets a user write
`/e"tc"/passwd` or `/etc\/passwd` and slip a blocked path past a `\/etc` pattern,
and lets `find /tmp -e"x"ec rm {} +` defeat a `^find(?!.*\s-exec\b)` guard
because the guard never sees the quote. Every `Target` and
`normalized_arguments` value is the string bash would actually open or execute.
If you add a matcher, match the executed form.

Two corollaries worth keeping: `DblQuoted` is rendered from its `parts`, never
from its `value` field, because `value` is lossy and would read `"pre${x}y"` as
`prey` - text the user never typed; and a bare `$(...)` stays a literal
placeholder, with `evaluate._opaque_match_unreliable` dropping any match whose
pattern would need a token only the expansion can produce, so the command is
escalated rather than approved.

## Things that look wrong but are not

Each of the following was considered, tested, and kept on purpose. Removing or
"simplifying" any of them reintroduces a bypass, so read this before changing
the code they point at.

- **`segments._extract_segments` has explicit no-op branches for `Lit` and
  `SglQuoted` word parts.** They emit no segment and look like dead code, but the
  function's final `else` arm logs an "Unhandled AST node type" warning, so
  removing them would start warning on every literal in every command. The
  branches are where a real decision is recorded: a bare literal reached as a
  *word part* is data — an argument, a glob, an operand under test — not a
  command.
- **The substitution arm at the tail of `evaluate._empty_segment_result` looks
  unreachable, and currently is:** no command in the harness corpus both yields
  zero segments and still carries a substitution flag, because
  `_extract_segments` recurses into every substitution container. Keep it
  anyway. It is the fail-closed path — if a future construct is not walked, a
  zero-segment command would otherwise fall straight through to the wildcard,
  and under `"*": "allow"` that is an auto-approval of a command nothing
  inspected. A redundant gate is not the same as a removable one.
- **`parse_segments` returning `[]` is ambiguous** — "no commands here" and
  "could not parse" look identical, because a parse failure is swallowed. No
  in-tree caller can observe the difference: `evaluate` parses with `parse()`
  (which raises) before it ever calls `parse_segments`, and the inspection CLI
  parses with `parse_ast` and exits non-zero. Direct callers should parse first
  and catch the exception.
- **The inspection CLI renders a declaration as one `assign: export FOO=bar`
  line while the permission path splits it into two segments** — one for the
  operands, one for the `export` keyword. The split is what lets
  `variable_assignment` reach the operands at all; before it, `export FOO=bar`
  was approved even under `"variable_assignment": "deny"`. Mirroring it in the
  display would print both forms, duplicating the keyword and losing the
  association between keyword and operand.
- **`rules._redir_target` reads only `Target`** and reconstructs nothing from the
  other redirection keys. That is the point, not an oversight: `Target` is the
  executed form, so a part-wise reconstruction could only ever be more lossy
  than the value already in hand.
