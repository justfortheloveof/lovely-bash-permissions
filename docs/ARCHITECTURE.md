# Architecture

A short map of `lovely_bash_permissions` for someone who has not read it before.
Three surfaces ship in one package: a general-purpose bash parser, and two
permission clients built on top of it — one for Devin's hook protocol, one that
serves the Pi coding agent's extension over a pipe.

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

A **contract** test — one that pins a property spanning two modules, usually
across the two halves — lives with the side it is about rather than in
`scenarios/`, and does not need to import only one module to earn its place. The
"every declared policy key is enforced" tests in `tests/config/test_schema.py`
are the example: their subject is the config surface, and they reach into
`evaluate` only to check that what the schema accepts is acted on.

Test classes carry the module they cover: `TestSegmentsEdgeCases`,
`TestParserSimpleCommands`, `TestEvaluateEdgeCases`. The same input is often
asserted at several layers - `""` raises from `parse_ast`, yields `[]` from
`parse_segments`, and raises again from `evaluate_bash_command` - and those
three tests were once all `TestEdgeCases::test_empty_command`, so a name
matched three different tests and `pytest -k` could not tell them apart. The
prefix makes `Class::test` unique across the suite and makes
`pytest -k TestSegments` select one module's tests. The five files that had a
collision were renamed in full so no file mixes the two conventions; the
twenty-three files that never collided keep their bare class names.

All shared fixtures and helpers live in a single `tests/conftest.py`. The tree is
split by subject, not by audience, so one root conftest serves all of it and
there is nowhere else to look.

## The three surfaces

**Library half** — the parser and its inspection API, which is what `README.md`
documents. Its dependency order is strictly one-way:

```
errors.py            (leaf: ShfmtError, and user_message)
policy.py            (leaf: the policy vocabulary and the Level type)
matching.py          (leaf: the one regex matcher for allow and block lists)
parser.py            -> errors            (shfmt subprocess -> raw JSON)
ast.py               (leaf: the typed node dataclasses)
words.py             -> ast               (a word as value / raw / executed text)
inspect.py           -> ast, words        (queries over a tree the caller holds)
converter.py         -> ast, parser       (raw JSON -> typed tree)
segments.py          -> ast, converter, errors, parser, words
rules.py             -> matching, policy, segments (types only; policy on segment dicts)
evaluate.py          -> ast, converter, inspect, matching, parser, policy, rules, segments, words
cli.py               -> ast, converter, errors, inspect, segments, words
__init__.py          re-exports the public surface
```

`errors.py` holds `user_message` as well as the exceptions, and it is a leaf for
the same reason they are: both hosts render a verdict to a user — and, through
it, to a model — and a config that will not validate has to produce that text
without the developer half of a pydantic error in it. It lives there rather than
in either host because the two reach the same message by different routes and a
message rendered twice renders twice. It imports nothing, duck-types `errors()`
rather than importing pydantic, and keeps working when the error has already been
through `str()` — which is the shape the Devin half actually receives, since
`config.manager` re-raises the loader's messages as a plain `ValueError`.

`inspect.py` and `words.py` depend on `ast.py` alone on purpose: they answer
questions about a tree the caller already holds, so they never parse. `converter.py` imports
`parser` at module level; `parser.py` imports only `errors.py`, so the edge
cannot cycle.

**Devin half** — the permission hook: `config/` -> `hook.py` -> `devin_cli.py`.
**Nothing in the library half imports any of it**, which is what makes the parser
vendored-and-usable-on-its-own and the hook deletable-without-trace. The
dependency runs one way only, and `config/` now takes part in it too:
`config/schema.py` and `config/effective_bash.py` import `policy.py`, which holds
the policy vocabulary both halves resolve from. `policy.py` is data and imports
nothing, so the edge cannot cycle.

**Pi half** — `decide.py` -> `pi_cli.py`, the server the Pi coding agent's
extension `lovely-pi-permissions` drives over a pipe. It is a *host*, not a
third copy of the policy: it calls the same `decide.decide_bash_command` the
Devin hook calls, and owns no decision logic of its own.

Three console scripts sit at the edges: `lovely-bash-inspection` (library half),
`lovely-devin-permissions` (Devin half), and `lovely-pi-bash-permissions` (Pi
half).

**`policy.py` declares the vocabulary once.** Every construct the evaluator gates
and every output-redirection kind it classifies is named there; the schema
validates against it, the effective-config builder resolves from it, and the
evaluator builds its rules from it. This exists because the list used to be
written out by hand in three modules, which is how `ToolConfig.permission` came to
be a declared config key with no reader anywhere — it validated, it was
documented as though it did something, and it changed no verdict. A key declared
in one copy and forgotten in the others is now not expressible.

The vocabulary declares **wire** keys, not field names. The one place the two
namespaces differ is the wildcard — the field is `wildcard`, the config key is
`*` — and a `mode="before"` validator sees raw dict keys, i.e. the wire
spelling. `WIRE_NON_POLICY_CONFIG_KEYS` therefore holds `"*"`, and the schema's
own field-vs-vocabulary check compares *aliases* so the two agree. Do not
"simplify" either back to field names: a vocabulary that mixed the two rejects
every bash block that sets a level, which is a total failure of the primary
feature and is invisible on review because the vocabulary looks right where it is
read.

## The two seams, and why they exist

Both exist to stop host-specific code from reaching into shared code, which is
what makes a second host possible at all. Neither is a stylistic preference, and
neither should be inlined back into its caller.

**`resolve_bash_config` / `get_effective_bash_config`.** `get_effective_bash_config`
calls `load_devin_exec_regexes(project_dir)` — a host that has no `Exec()`
concept cannot call it without reading a Devin config file it has no opinion
about. The host-agnostic resolution is the first function; the Devin merge is a
thin wrapper over it.

`resolve_bash_config` branches on `if not raw_bash:`, **not**
`if raw_bash is None:`. An empty block and `None` take the same branch today, so
`{}` never gets the `{**bash}` spread, never has its keys resolved, and returns
the bare four-key default. The natural-looking `is None` would spread `{}`,
resolve every policy key against the wildcard, and change the output for a config
that is a documented no-op — drift introduced by the very refactor meant to
prevent it. That is why the parameter is typed `object`: a `dict` signature
invites narrowing the truthiness test away. The `{**bash}` spread itself is
equally load-bearing — the function is still called directly with unvalidated
dicts by `--show-config` and by the golden harness.

**`decide_bash_command`.** The decision logic used to live inside `hook.py`,
interleaved with Devin's wire protocol. It is now one host-agnostic function that
both hosts call, so a policy change cannot land in one and miss the other.

Two things about it are load-bearing and previously implicit:

- It **resolves the config before evaluating**. `error` is a
  `NON_CONSTRUCT_KEYS` key: the evaluator's own level resolution never touches
  it, only `resolve_bash_config` populates it. Skip the resolution and a shfmt
  failure on `{"*": "allow"}` falls through the chain to the wildcard and
  reports `ask` — silent, and in the permissive direction.
- It **speaks `deny`, never `block`.** `deny` is this product's policy
  vocabulary; `block` is Devin's wire vocabulary, produced only by `hook.py`'s
  `_DEVIN_ACTION` at the seam. Forwarding a `deny` where `block` is expected
  misses both `elif action == "block"` branches in `generate_hook_response`, so
  the response is `None`, the CLI never reaches `sys.exit(2)`, and the denied
  command runs. Translate once, at the seam, and nowhere else. The word must not
  appear in `decide.py` as a value, which `tests/test_decide.py` asserts by
  walking its AST.

## The two halves, by full name

- `lovely-pi-bash-permissions` — this repo, Python, the engine. Reads one JSON
  request on stdin, evaluates bash commands, writes one JSON response on
  stdout, exits.
- `lovely-pi-permissions` — a separate repository, TypeScript, the client. A Pi
  coding-agent extension that spawns the engine once per *bash tool call* — plus
  once at `session_start` to probe it — and gates bash through it. It owns config
  discovery, deep-merge, mode selection, the ask prompt, doom-loop detection, and
  status-bar sync; none of that lives here.

Nothing is resident between calls, so the client keeps no child to restart, no
buffered line reader, and no queue of in-flight requests.

They are never the same thing, and they are never referred to interchangeably.
A reader who found this file via either project needs to know which half they
are looking at, and a "server unavailable" message that names the wrong project
sends them to the wrong repository. The wire protocol is documented in
`README.lovely-pi-bash-permissions.md`, and it is stable once both sides have
shipped.

## One permission decision

`evaluate_bash_command(command, config)` is the whole flow, in order:

1. **`parse(command)`** — one `shfmt --to-json` subprocess. Any failure raises
   `ShfmtError`; the hook maps that to the `error` policy rather than letting the
   command through.
2. **`node_from_json(raw)`** — raw JSON becomes a typed `File`.
3. **`segments_from_ast(tree)`** — the typed AST becomes the flat segment list.
4. **`rules.py` policy checks** over those segments, plus the per-segment
   allowed/blocked matchers in `evaluate.py`. Every regex match, in either
   module, goes through `matching.match_texts`.
5. **Verdict** — a `_Verdict` accumulator folded through the steps, ending in
   `{"status", "reason", "reasons", "segments"}`.

`reasons` is the same information as `reason`, as a list, de-duplicated in append
order. A consumer must **not** re-split `reason` on `"; "` to recover it: most
reasons contain a semicolon themselves, and the single largest class of reason
the evaluator produces is a one-element list like
`['"ls" command is not allowlisted; wildcard policy is ask']`, which a naive split
tears into two bullets. The list is empty only when the verdict is an `allow` with
nothing to explain — a matched pattern, or the wildcard — and never for an `ask`
or a `deny`. Both facts are load-bearing for the Pi prompt, which renders one
bullet per entry.

### Why a reason carries its level

`_Verdict.reasons` is `list[tuple[level, text]]`, and `_finalize_reasons` emits
only the pairs whose level is the final verdict. One rule, applied once, at the
end — because a reason is an *argument* for a verdict, and most steps do not know
the verdict when they record it.

The check used to live in each step, against the status as of that step, and that
placement is what made it wrong: `_apply_redirection_policies` runs before
`_apply_wildcard_resolution`, so an approval recorded at step four survived a
downgrade at step five. The user was told part of a command had been approved in
the middle of the prompt asking them about the rest — the two things the same
reason string was never supposed to do at once. Each step that needed the rule had
to remember it, and two of them did not.

What the pairing buys is that all three of these hold **by construction** rather
than by every future step checking: a `deny` names only why it was refused; an
`ask` names only what approval is being requested for; an `allow` names every
rule that permitted it. The last one is why a construct that resolves to `allow`
has to say so rather than stay silent — the reason list is how a user finds out
which of their own rules permitted a command, and a rule that permits silently
answers nothing.

Recording the level a reason *argues for* is not the level its step goes on to
produce. `_apply_substitution_policies` decides first, then records once, because
one nested-non-match sentence argues for a `deny` under a `deny` policy, an `ask`
under an `allow` one, and a `deny` under a command already refused for something
else. The fourth return path holds a `_Verdict` for the same reason: with
`{"*": "deny", "command_substitution": "allow"}` the wildcard refuses the command
while the substitution policy permits the construct, and a plain list of strings
puts both sentences in the refusal.

`tests/scenarios/test_verdict_reporting.py` pins the three properties, and
`test_verdict_fail_closed.py` pins the safety half — that a verdict is never more
permissive than the reasons it carries.

### A fourth return path

`evaluate_bash_command` has a second exit for commands that parse to **zero
segments** — `_empty_segment_result`, reached via `if not segments`. It carries
`reasons` on every branch, and for the same reason: over the golden corpus 120 of
its rows are `ask`, and a host asked to explain a verdict it has no reasons for
either shows an empty prompt or invents one.

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

`words.word_exec` renders a word the way bash would resolve it: quotes
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
placeholder, with `matching.opaque_match_unreliable` dropping any match whose
pattern would need a token only the expansion can produce, so the command is
escalated rather than approved.

## Things that look wrong but are not

Each of the following was considered, tested, and kept on purpose. Removing or
"simplifying" any of them reintroduces a bypass, so read this before changing
the code they point at.

- **`error` inherits the wildcard, so `{"*": "allow"}` auto-approves a command
  the parser could not read.** Deliberate, and chosen over defaulting `error` to
  `ask`: a user who wrote `{"*": "allow", "error": "allow"}` and a user who wrote
  `{"*": "allow"}` get the same answer, and one key means one thing. The cost is
  that `blocked_cmds_regex` offers no protection for input shfmt rejects — it is
  never reached, because the command is never analysed. `error: "ask"` is the
  documented answer for anyone who wants malformed-but-bash-accepted syntax to
  prompt. Note this is an *inheritance*, not a default: `policy.DEFAULT_LEVEL` is
  `ask`, and an absent key under an asking wildcard asks.
- **A command that produces zero segments inherits the wildcard too**, so
  `(( 1+2 ))`, `[[ -f x ]]` and `case $x in esac` are auto-approved under
  `{"*": "allow"}`. Same reasoning and the same escape hatch, and the reasoning
  differs from the substitution arm of `_empty_segment_result` only in that the
  substitution arm fails closed for an *inherited* allow and this one does not.
  What makes it safe is that the reason names the level: `<empty command>
  produced no parseable segments - defaulting to wildcard policy (allow)`, so an
  approval resting on "we could not analyse this" is visible rather than silent.
- **`rules._resolve_output_level` returns `deny` for a level it does not
  recognise**, while the three sibling resolvers return `deny` for the same
  input and this one used to return `allow`. The asymmetry is the point: `"block"`
  is Devin's own wire word for a refusal, so it is the level a config author is
  most likely to reach for from the wrong vocabulary, and it must not approve a
  redirection. The no-kinds case still returns `allow` — that reads no level at
  all, so it is "nothing to govern" rather than "a level I did not recognise" —
  and `check_output_redirections` cannot reach it anyway.
- **`segments._HANDLERS` maps `Lit`, `SglQuoted` and `ExtGlob` to the no-op
  `_nothing`.** The entries emit no segment and look like dead code, but a type
  missing from the table logs an "Unhandled AST node type" warning, so removing
  them would start warning on every literal in every command. The entries are
  where a real decision is recorded: a bare literal reached as a *word part* is
  data — an argument, a glob, an operand under test — not a command.
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
