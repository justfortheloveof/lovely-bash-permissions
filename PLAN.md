# Plan: `lovely-pi-bash-permissions`

A second CLI in this repo, `lovely-pi-bash-permissions`, that evaluates bash commands
for the Pi coding agent's `lovely-pi-permissions` extension using this package's engine.

The two names are deliberately distinct: the **CLI** is `lovely-pi-bash-permissions`
(this repo, Python), the **extension** is `lovely-pi-permissions`
(`../jftlo/lovely-pi-permissions`, TypeScript). They are never the same thing and are
never referred to interchangeably below.

The Pi extension stays TypeScript. It keeps owning config discovery, deep-merge, and
mode selection, and calls the new CLI over a persistent JSONL pipe for **bash tool
calls only**. Everything else the extension does (non-bash tool permissions, doom-loop
detection, the ask prompt, answer caching, status-bar sync) is untouched.

Two repos are involved:

| Repo | Path | Work |
| --- | --- | --- |
| `lovely-bash-permissions` (Python, this repo) | `.` | Phases 1-4 |
| `lovely-pi-permissions` (TS extension) | `../jftlo/lovely-pi-permissions` | Phase 5 |

Phases 1-4 are one reviewable change in this repo. Phase 5 is a separate repo and lands
once the wire protocol is stable.

**All work in both repos lands on a branch named `migrate-bash-to-python`, created off the
current tip of the checked-out branch in each.** See §9 step 0 for the commands and the two
rules that are easy to get wrong.

---

## 1. Current state

### 1.1 This repo

`src/lovely_bash_permissions/` is two halves, documented in `docs/ARCHITECTURE.md`:

**Library half** (host-agnostic, no knowledge of any agent):

```
errors.py            (leaf: ShfmtError)
parser.py            -> errors            (shfmt subprocess -> raw JSON)
ast.py               (leaf: the typed node dataclasses)
inspect.py           -> ast               (queries over a tree the caller holds)
converter.py         -> ast, parser       (raw JSON -> typed tree)
segments.py          -> ast, converter, errors, inspect, parser
rules.py             -> segments          (policy on segment dicts)
evaluate.py          -> ast, converter, inspect, parser, rules, segments
cli.py               -> ast, converter, errors, inspect, segments
policy.py            (leaf: the policy vocabulary, imports nothing)
```

**Devin half** (the permission hook):

```
config/schema.py         -> policy
config/jsonc.py          (leaf)
config/devin.py          -> jsonc              (Devin config paths, Exec(...) -> regex)
config/loader.py         -> devin, jsonc, schema
config/effective_bash.py -> devin, policy
config/manager.py        -> devin, loader
hook.py                  -> config/*, evaluate
devin_cli.py             -> config/*, hook
```

Console scripts (`pyproject.toml`):

```toml
lovely-bash-inspection = "lovely_bash_permissions.cli:main"
lovely-devin-permissions = "lovely_bash_permissions.devin_cli:main"
```

`policy.py` declares the policy vocabulary **once**; `config/schema.py`,
`config/effective_bash.py`, and `evaluate.py` all resolve from it, so a key cannot be
added to one and forgotten in the others. That module is the precedent this plan
follows.

One wrinkle matters for Phase 1 and is called out in 4.0: the tuples there serve **two
namespaces**. `POLICY_KEYS` / `NON_CONSTRUCT_KEYS` are wire keys, read as
`config.get(key)`. `NON_POLICY_CONFIG_KEYS` is currently a *field name*
(`"wildcard"`) because its only consumer compares against `model_fields`. Exactly one
key differs between the two spellings. Phase 1 makes the vocabulary declare wire keys
throughout (D11) and switches the field-name check to compare aliases.

Current test state: **1657 passing**, 93% coverage. Gates are `pytest` plus the
`linting` marker (`ruff check`, `ruff format --check`, `mypy --strict .`).

**This file is itself inside the format gate.** `ruff format --check` covers `**/*.md`
and reformats the Python fenced blocks inside it, so `tests/tooling/test_lint_gates.py`
fails on any code block in this plan that is not already `ruff format` output. When
editing a snippet here, run `ruff format --diff PLAN.md` — a block that reads correctly
but wraps differently from what ruff produces will fail the suite. (Line-length 120,
double quotes, per `[tool.ruff.format]` in `pyproject.toml`.)

Neither repo has CI (no `.github/` in either). "Gate" throughout this plan means the
local commands above, and `vp run build` for the extension — not a green check on a
remote.

**This repo has no git remote, and is not on PyPI.** Both matter for Phase 5, which
tells users to install a binary from here: see 8.9b for the install story and the
prerequisite the missing remote creates.

### 1.2 The Pi extension

`../jftlo/lovely-pi-permissions` does substantially more than bash:

- gates `read`/`write`/`edit`/`grep`/`find`/`ls` and custom tools via `permission` +
  `blocked_paths_regex`
- **modes**: config is `{ "default": {...}, "strict": {...} }`, switchable at runtime
  via `/lovely-permissions-cfg`
- 4-option ask prompt (Allow / Reject / Reject and end turn / Reject with reason)
- `doom_loop` detection (deny-by-default, 3 identical calls in a row), with a rejection
  memo keyed by tool + serialized input so repeat offenders are not re-prompted
- `pi.setActiveTools()` sync so only configured tools are live
- `/lovely-permissions-view`, status-bar mode indicator, per-decision notifications

Bash today goes through the **old TypeScript** `@justfortheloveof/lovely-bash-permissions@0.1.15`
(shell-quote based). `src/permissions/bash-evaluation.ts` is its only consumer of
`BashPermissions`; `src/settings/index.ts` also uses its zod schemas.

### 1.3 The schema gap

**Correction to an earlier draft of this table, which overstated it.** The draft claimed Pi's
bash base level is `permission` and that path blocking is a bash capability. Neither is
true of the *code*; both are true of the *README*, and that is where the real problem is.
`tool-evaluator.ts:21` already reads `['*']` for bash
(`(toolConfig as BashPermissionsConfig)['*']`), and `blocked_paths_regex` is already gated
behind `!isBash` at `tool-evaluator.ts:29`. So the rename in 8.3 is real only for the
non-bash tools and `doom_loop`, and `blocked_paths_regex` is already non-bash-only.

The README nonetheless tells users to write `"bash": { "permission": "ask" }`
(`README.md:37`), and `bashPermissionsConfigSchema` is a `z.core.$strip` object - so that
key is **silently dropped**, leaving the bash block with no `'*'`, which
`tool-evaluator.ts:22` treats as `permission === undefined` and blocks. A user following the
Quick Start gets a shell that refuses to run, with no diagnostic. The npm zod schema has no
`permission` key at all. Treat the README as the defect, not the evaluator.

What actually differs, per row:

| | Pi (TS, today) | Devin (Python, now) |
| --- | --- | --- |
| base level | `'*'` (code) / `permission` (README only) | `"*"` |
| path blocking | `blocked_paths_regex`, non-bash only | `blocked_cmds_regex` (bash) |
| parse/shfmt failure | always ask (raw-string heuristic) | `error` policy |
| substitutions | always ask, not configurable | `command_substitution`, `process_substitution` |
| subshells | always ask, not configurable | `subshell` |
| assignments | not gated | `variable_assignment` |
| redirection kinds | 3 | 4 (adds `other`) |

The five capability rows below the first two are the real gap. Moving to the Devin schema
is a strict gain, and it is a breaking *documentation* change far more than a code one: the
5 rows of new gating plus `other`. Still 0 users (the author), no back-compat, hard errors.

---

## 2. Decisions

These are settled. Do not relitigate them without cause.

| # | Decision | Choice |
| --- | --- | --- |
| D1 | Who loads/merges config | **TS resolves, Python evaluates.** One config loader, one schema. `--test` may unwrap a mode container (6.4b) because it is a developer tool, not the protocol; the server must not. |
| D2 | Transport | **Persistent server process**, newline-delimited JSON over stdin/stdout. |
| D3 | Back-compat | **None.** Hard errors, loud messages. |
| D4 | Old TS npm dep | **Dropped** from the extension. |
| D5 | Unknown key under `bash` | **Hard error** (`extra: "forbid"` on `ToolConfig`). |
| D6 | Missing level | Tool `*` -> mode `*` -> `"ask"`. |
| D7 | Mode `*` | A **level** wildcard. Supplies levels to already-active tools. **Never activates a tool.** |
| D8 | CLI unreachable | **Fail closed.** Block every bash call, sticky for the session. |
| D9 | CLI surface | Server mode + `--test`. Show-config stays in TS. |
| D10 | Naming | The CLI is `lovely-pi-bash-permissions`; the extension is `lovely-pi-permissions`. Never interchanged. |
| D11 | Vocabulary namespaces | **The vocabulary declares wire keys, not field names.** The one `*`/`wildcard` divergence is resolved in `policy.py`, not at each use site. See 4.0. |
| D12 | Policy vocabulary | `allow` / `ask` / `deny`, everywhere, in both repos. `block` is Devin-wire-only and is produced by the seam, never returned by `decide.py`. See 5.2. |
| D13 | Stale responses | **A timeout kills and respawns the child.** No request ids, no response matching. See 8.1. |

### 2.1 On D7 (tool activation)

Activation is unchanged and is **not** affected by a mode-level `"*"`:

```ts
const configured = new Set(Object.keys(mgr.getConfig()));   // the mode's tool keys
const active = pi.getAllTools().map(t => t.name).filter(n => configured.has(n));
pi.setActiveTools(active);
```

A tool absent from the mode is unreachable even when the mode is `"*": "allow"`. That is
the fail-closed direction and it is what stops `*` from silently re-enabling a tool that
was deliberately left out.

`doom_loop` is **not** a tool: `SessionRuntime` reads it out of the config map and
`pi.getAllTools()` never contains it, so it is never activated. It is a config key with
its own level.

### 2.2 Rationale for the two seams this plan creates

Both exist to stop host-specific code from reaching into shared code, which is what
makes adding a second host possible at all.

- `resolve_bash_config` / `get_effective_bash_config` - today
  `get_effective_bash_config` calls `load_devin_exec_regexes(project_dir)` as its first
  statement (`config/effective_bash.py:30`). A host that has no `Exec()` concept cannot
  call it without reading a Devin config file.
- `decide_bash_command` - today the decision logic lives inside `hook.py`, mixed with
  the Devin wire protocol.

---

## 3. Phase 0 - Capture two behaviour baselines

`tools/golden.py` is a behaviour-fingerprint harness that excludes itself from lint
(`pyproject.toml` `[tool.ruff] extend-exclude`). It captures `evaluate_bash_command`
verdicts, `parse_segments`, `parse_ast` fingerprints, the inspection API, rendered CLI
output, and the config/effective-config layer across a large command corpus, plus a
`ground_truth` section that cross-checks extracted segment command names against shfmt's
own output (§9 step 1). Its top-level sections are `commands`, `configs`, `dialects`,
`cli`, `ast`, `ground_truth`, and `config_layer` - the last holding `effective`, `schema`,
`load`, `jsonc`, `hook`, and `hook_label`. Note that the `load`, `hook` and `hook_label`
sections are easy to forget when enumerating a phase's expected diff, and `load` does carry
validation errors that Phase 1 changes.

```bash
.venv/bin/python tools/golden.py capture /tmp/baseline-A-pre-phase1.json
```

(`compare` prints `IDENTICAL` when clean. `capture` emits benign JSONC parse warnings to
stderr - that is expected.)

**Baselines live in `/tmp`, and that is fine.** Capture is deterministic and takes ~28 s
(verified: two independent captures compare `IDENTICAL`), so a lost baseline is regenerated
by re-running one command rather than reconstructed by hand. The lifetimes line up with
`/tmp`'s fragility: A is only compared during Phase 1, B only during Phase 2, and C is
long-lived but also regenerable. Nothing depends on a baseline surviving a reboot.

**But the fingerprint is tied to the shfmt version, and that is the real caveat.**
`pyproject.toml` declares `shfmt-py>=4.1.0` - a floor, not a pin. shfmt is a Go binary that
ships inside that wheel, so a dependency bump can change how commands are parsed, and every
`compare` against an older baseline then shows a large diff that is **not** a code
regression. `ground_truth` is the most exposed section, because it reads shfmt's raw JSON
shape directly - finding 21 is precisely that failure, one version apart.

So `capture` prints the resolved shfmt version to **stderr** on every run. Not into the
JSON: adding a key would itself change the fingerprint and invalidate the baseline it is
meant to label. When a diff appears that spans many commands, check the shfmt version on
the two captures before investigating the code.

### 3.1 Baselines and their gates

**This is not one baseline compared at the end. Each phase has its own, with a different
gate.** `evaluate_bash_command`'s return shape is part of the fingerprint, so phases that
change it produce real, expected diffs.

| Baseline | Captured | Gate for the phase that follows |
| --- | --- | --- |
| **A** | Before Phase 1 | Phase 1 must differ in **exactly** the two rows in 3.2 |
| **B** | End of Phase 1 | Phase 2: `commands` gains a `reasons` key on every entry (5.3); every other section `IDENTICAL` |
| **C** | End of Phase 2 | Phases 3+ must be `IDENTICAL` |

**Which section `reasons` lands in.** `evaluate_bash_command`'s return dict is recorded by
`tools/golden.py:173` into the top-level **`commands`** section, and `effective` is
`get_effective_bash_config`'s output (`golden.py:294`) - a config dict that gains nothing in
Phase 2. So the Phase 2 diff is: `commands` gains `reasons`, `config_layer.effective` is
byte-identical. An earlier draft of this table stated the reverse, which made rows B and
§5.3 mutually unsatisfiable: an implementer following it literally would halt on exactly the
diff §5.3 mandates. The section assignments above are verified against `capture()`.

Phases 3 and 4 add new modules and do not touch the library, so Baseline C is expected to
be stable for the rest of the project. Keep it for any future change to
`evaluate_bash_command`.

**Baseline C's limits, stated plainly.** The harness fingerprints `evaluate_bash_command`,
`parse_segments`, `parse_ast`, the inspection API, CLI output, and the config layer. It
does **not** import `decide.py` or `pi_cli.py` — neither exists when C is captured. So
Phase 3's "IDENTICAL vs C" gate is *vacuously* true: it cannot detect a Phase 3
regression, only confirm that Phase 3 left the library alone. That is a real and useful
check (Phase 3 must not perturb the evaluator), but it is not a test of the server.

Phase 3's actual gate is Phase 4's unit tests — `tests/test_pi_cli.py` and
`tests/test_decide.py`, which §7 adds. Do not read a green Phase 3 golden diff as
evidence the protocol works.

If a future change makes the server's behaviour observable through the harness, extend
`capture_config_layer` with a `decide` section and capture a Baseline D at that point
rather than reasoning about it per-change.

If a `compare` shows a difference **not** listed for that phase, stop and diagnose it
before proceeding. Do not refresh the baseline to make a diff disappear.

### 3.2 Phase 1's diff is expected, and here is exactly what it is

`tools/golden.py:283` deliberately includes `{"permission": "allow"}` in
`raw_bash_variants`, and `:287` includes `{"unknown_key": 1}`. Both are affected by
Phase 1, so **Phase 1 will not be `IDENTICAL` against Baseline A**, and should not be:

| Fingerprint key | Before | After | Why |
| --- | --- | --- | --- |
| `config_layer.schema` / `bash\|18` | `ValidationError: ... config key 'permission' is not supported - use * instead` | `unknown bash config key 'permission'; valid keys are ...` | The `_REPLACED_KEYS` message is deleted |
| `config_layer.schema` / `bash\|22` | `{"ok": "<PermissionsConfig>"}` | `ValidationError: unknown bash config key 'unknown_key'; ...` | `extra: "forbid"` |

**Any other difference in the `schema` section is a bug.** Review the full diff rather
than eyeballing these two rows, but these two must change and nothing else may.

Every other section must be `IDENTICAL` across Phase 1 - Phase 1 touches only the schema, so
a change in `commands`, `dialects`, `configs`, `ast`, `cli`, `ground_truth`,
`config_layer.effective`, `config_layer.load`, `config_layer.jsonc`, `config_layer.hook` or
`config_layer.hook_label` would be a defect. (`config_layer.schema` is the one section
allowed to differ, in exactly the two rows above.)

### 3.3 `get_effective_bash_config` passes unknown keys through - preserve that

`effective_bash.py:56` spreads `{**bash, ...}`. Today an unvalidated dict with junk keys
flows straight through: fingerprint `effective|18|ask` contains `"permission": "allow"`,
and `effective|22|ask` contains `"unknown_key": 1`.

After Phase 1 this is unreachable from the validated path, but
`get_effective_bash_config` is still called **directly** with unvalidated dicts by
`handle_show_config` (`devin_cli.py:170`) and by the golden harness itself.

**The Phase 2 split must preserve the `{**bash}` spread byte for byte.** If the
`effective` section of the fingerprint churns during Phase 2, the split changed
observable behaviour and must be reworked - it is not acceptable drift to write off.

---

## 4. Phase 1 - Enforce the config vocabulary; delete `_REPLACED_KEYS`

### 4.0 First: the vocabulary declares *wire* keys, not field names

**This is a prerequisite, not a detail of the rewrite below, and getting it wrong
silently rejects the most common key in the product.**

`policy.py`'s tuples are consumed in two places that need *different* namespaces:

| Consumer | Needs | `NON_POLICY_CONFIG_KEYS` today |
| --- | --- | --- |
| `evaluate.py:121`, `effective_bash.py:61` - `config.get(key)` against a user dict | **wire key** | n/a — these use `POLICY_KEYS` / `NON_CONSTRUCT_KEYS`, which are wire-shaped already |
| `schema.py:111` — `set(type(self).model_fields)` | **field name** | `"wildcard"` |

Exactly one key diverges: the Python field is `wildcard`, the config key is `*`.
Every other key is spelled identically in both namespaces, so the divergence is
invisible until it matters.

The trap: §4's instruction to build the unknown-key set "from the same `policy.py`
vocabulary that `_fields_match_the_policy_vocabulary` already checks against" is
**wrong as written**. A `mode="before"` validator sees raw dict keys, and
`NON_POLICY_CONFIG_KEYS` contains `"wildcard"`, never `"*"`. Verified against
pydantic 2.13:

```
{'*': 'ask'}        -> REJECT: unknown bash config key '*'; valid keys are ['allowed_cmds_regex', ...
{'error': 'deny'}   -> OK
```

That rejects **every bash block that sets a level** - D6, D7, and the extension's
own `default` mode. It is a total failure of the primary feature, and it is
invisible in review because the vocabulary looks right where it is read.

**The fix, in `policy.py`:** the constant's *meaning* changes — it stops holding a
field name and starts holding the wire key — so it is renamed, because a name that
still reads as a field list is exactly what would cause the next person to reintroduce
the bug.

```python
#: Config keys that are not level-bearing policies, spelled **as they appear in a
#: config file** - ``*``, not the ``wildcard`` field name.
#:
#: The wire spelling is what a ``mode="before"`` validator sees when it checks a raw
#: dict for unknown keys, so the wire spelling is what must be declared here. The
#: field name (``wildcard``) is only the *alias* for ``*``; every consumer in this
#: package compares against aliases, never against field names. See D11.
WIRE_NON_POLICY_CONFIG_KEYS: Final[frozenset[str]] = frozenset({"allowed_cmds_regex", "blocked_cmds_regex", "*"})
```

The rename touches four sites, all in this repo:
`policy.py:61` (the declaration), `config/schema.py:9` (the import),
`config/schema.py:110-112` (the vocabulary check), and `tests/config/test_schema.py:420`
(the hand-written copy that must go anyway — see 4.2).

Then the two consumers derive what they each need, and neither re-derives the other's
spelling:

- **Wire set** (the new before-validator):
  `set(POLICY_KEYS) | set(NON_CONSTRUCT_KEYS) | WIRE_NON_POLICY_CONFIG_KEYS` —
  now correct by construction.
- **Field-name check** (`_fields_match_the_policy_vocabulary`, unchanged in intent):
  compare **aliases**, not field names, so it agrees with the wire set:

```python
declared = {f.alias or name for name, f in type(self).model_fields.items()}
```

Verified end to end against pydantic 2.13: `{"*": "ask"}`, `{"error": "deny"}` and
a multi-key policy block all validate; `{"permission": "allow"}` and
`{"unknown_key": 1}` are rejected.

**Why fix it here rather than patch the validator.** The alternative - special-casing
`"*" -> "wildcard"` inside the new validator - leaves two spellings of the same
vocabulary in the tree, which is the exact failure `policy.py` was written to
remove (see its module docstring: the key list was written out three times by hand
and nothing tied the copies together). D11 records the choice so the next person
does not "simplify" the constant back.

**Test this first, in isolation, before touching `_REPLACED_KEYS`.** It is a
one-line round trip: `ToolConfig.model_validate({"*": "ask"})` must succeed.

### 4.1 The rewrite itself

**File: `src/lovely_bash_permissions/config/schema.py`** (currently lines 69-100).

Delete `_REPLACED_KEYS` and `_warn_extra_fields`. Replace with:

- `ToolConfig.model_config = {"extra": "forbid"}`
- a `mode="before"` validator that raises
  `unknown bash config key 'X'; valid keys are '<comma-joined>'`, with the valid set
  built from the **wire** vocabulary established in 4.0.

The error message must list `'*'` and must not contain the substring `wildcard` -
a user reading `valid keys are 'wildcard'` would look for a `wildcard` key in their
config and find none.

**Why this shape.** `_REPLACED_KEYS` enumerates mistakes we happen to have heard of. Its
own docstring states the principle: a key that reads as "configured" while changing
nothing is worse than a typo, because the wildcard quietly decides the real outcome. One
rule over a declared vocabulary enforces that; a per-key table does not, and grows a
new entry every time someone guesses a name.

**Scope.** `ToolConfig` is only ever instantiated as a **bash** block
(`KNOWN_TOOLS = frozenset({"bash"})`, and `PermissionsConfig.bash` is its sole use), so
making it strict is safe.

The root `PermissionsConfig` **stays permissive** (`extra: "allow"` + warn): a Pi mode
legitimately carries `read`/`write`/`edit` blocks that Python never sees, and
`tests/config/test_loader.py` merges exactly those.

Keys this subsumes: `allow`, `deny`, `permission`, `blocked_paths_regex`.

### 4.2 Tests to rewrite

| Test | Why |
| --- | --- |
| `tests/config/test_schema.py:235` `test_allow_deny_shorthand_rejected` | Now the generic unknown-key error. |
| `tests/config/test_schema.py:243` `test_permission_key_rejected` | Asserts a specific message that no longer exists. |
| `tests/config/test_schema.py:258` `test_permission_key_rejected_at_every_level` | Same. |
| `tests/config/test_schema.py:265` `test_permission_key_rejection_precedes_unknown_key_warning` | Same; the distinction is gone since one path remains. |
| `tests/config/test_schema.py:272` `test_wildcard_is_not_rejected` | **Keep, and promote.** It is the only existing test that would have caught 4.0. Rename to make the wire spelling explicit (`test_star_key_is_not_rejected`). |
| `tests/config/test_schema.py:307` `test_renamed_blocked_key_ignored_with_warning` | **Assertion inverts.** It currently asserts `blocked_paths_regex` warns and is ignored - the exact fail-open being closed. Rewrite as a rejection test and say so in its docstring. |
| `tests/config/test_loader.py:443-450` | Asserts the removed message text. |

Add:

1. **The 4.0 regression test** - `{"*": "ask"}` validates, at `ToolConfig` level and
   through `PermissionsConfig.model_validate({"bash": {"*": "ask"}})`.
2. The error message lists the valid keys, **every key named in that message is
   actually accepted** (parametrised over the message's contents, so the message
   cannot drift from the validator), and the message contains `*` but not `wildcard`.
3. `_fields_match_the_policy_vocabulary` still fires when a field is added or renamed -
   its whole point is surviving 4.0, so it needs a test that fails if the alias
   comparison is reverted to field names.

Unchanged and still passing: `test_unknown_key_logs_warning` and
`test_typo_key_logs_warning` (both root-level, root stays permissive);
`tests/test_evaluate.py:300 test_old_key_ignored` (calls the evaluator directly with a
raw dict, never touches the schema).

Note `tests/config/test_schema.py:420` hardcodes its own copy of the key list
(`NON_POLICY_KEYS`, including `"wildcard"`). It must be updated in the same commit and
should import from `policy.py` rather than restate it - a third hand-written copy is the
bug this phase exists to remove.

### 4.3 Phase 1 exit criteria

1. All tests pass, `mypy --strict` and `ruff` clean.
2. `golden.py compare` against **Baseline B** is `IDENTICAL` (i.e. capture B, change
   nothing, confirm the harness is stable).
3. `golden.py compare` against **Baseline A** differs in **exactly** the two rows in
   3.2 and nowhere else. Inspect the whole diff; do not spot-check.
4. Commit, then start Phase 2.

---

## 5. Phase 2 - Extract the host-agnostic core

Pure refactor. No behaviour change. **Gate: `compare` against Baseline B is
`IDENTICAL`** (see 3.1 - it is not Baseline A).

### 5.1 `config/effective_bash.py` - split host concerns

Extract:

```python
def resolve_bash_config(raw_bash: object, top_level_wildcard: str = "ask") -> dict[str, Any]:
    """Resolve every policy key against the wildcards. Host-agnostic.

    NOTE: the branch is ``if raw_bash:``, not ``if raw_bash is not None:``. See below.
    """
```

`get_effective_bash_config(raw_bash, project_dir, top_level_wildcard)` stays as a thin
Devin wrapper: call `resolve_bash_config`, then append
`load_devin_exec_regexes(project_dir)` to `allowed_cmds_regex` and dedupe. Both keep
deriving from `POLICY_KEYS` / `NON_CONSTRUCT_KEYS` - the vocabulary stays declared once.

**Preserve the truthiness test exactly. `if raw_bash:` is load-bearing.** The existing
code branches on truthiness (`effective_bash.py:33`), so `{}` and `None` take the **same**
branch and `{}` never gets the `{**bash}` spread, never has its keys resolved, and returns
the bare 4-key default dict. Verified:

```
resolve({},     "ask") -> {'*': 'ask', 'error': 'ask', 'allowed_cmds_regex': [...], 'blocked_cmds_regex': []}
resolve(None,   "ask") -> (identical)
```

Writing the natural `if raw_bash is not None:` instead would spread `{}`, resolve every
policy key against the wildcard, and change the output for golden variant `1|ask` - which
is the drift 5.4 forbids, introduced by the very refactor meant to prevent it. The
signature above says `object` precisely so the truthiness test stays honest. If a future
change needs to distinguish "absent" from "empty", that is a behaviour change and belongs
in its own phase with its own baseline, not in this split.

### 5.2 New `src/lovely_bash_permissions/decide.py`

Move out of `hook.py`:

- `_LEVEL_TO_ACTION`
- `_error_action` (routes every failure through the configured `error` policy)

Add:

```python
def decide_bash_command(command: str, config: dict[str, Any], top_level_wildcard: str = "ask") -> dict[str, Any]:
    """Evaluate a command against a config, resolving it first.

    ``config`` is a *raw* bash block; this resolves it via ``resolve_bash_config``
    (5.1) before evaluating, so ``error`` is populated. See "the `error` policy is
    unreachable" below - omitting that step is silent and wrong.

    Returns {"action": "allow"|"ask"|"deny", "reason": str, "reasons": list[str]}.
    """
```

`hook.process_hook_event` calls it; the Pi server calls it. One decision
implementation, two hosts.

**`decide.py` speaks `deny`. The `deny` -> `block` rename happens in the seam, and
only in the seam.** This is D12, and it is load-bearing.

`hook.py` today ends at `action = _LEVEL_TO_ACTION[status]` (`hook.py:215`), where
`_LEVEL_TO_ACTION` maps `{"allow": "allow", "ask": "ask", "deny": "block"}` (`hook.py:139`;
`_error_action` uses a `.get` form of the same table at `hook.py:150`). `block` is
**Devin's wire vocabulary**, not this product's: `generate_hook_response` branches on
`action == "block"` (`hook.py:109` and `:131`), and `devin_cli.py:246` keys exit code 2 off
`response.get("decision") == "block"` (`:247` is the `sys.exit(2)` itself).

The naive shape - return `deny` from `decide.py` and forward `decision["action"]`
verbatim from `process_hook_event` - therefore **fails open**. A forwarded `"deny"`:

- misses both `elif action == "block"` branches in `generate_hook_response`, so the
  function falls off the end and returns `None`;
- `devin_cli.handle_hook_event` returns `None` for a `None` response;
- `main` therefore never reaches the `sys.exit(2)` branch;

and the denied command **runs**. A `deny` verdict becomes a no-op, silently, on the
host that has a human in the loop.

So `process_hook_event` performs the translation explicitly:

```python
decision = decide_bash_command(command, config)
# `deny` is this product's policy vocabulary; `block` is Devin's wire
# vocabulary. Translated here, at the seam, and nowhere else - see D12.
action = _DEVIN_ACTION[decision["action"]]
return {"action": action, "reason": decision["reason"]}
```

where `_DEVIN_ACTION = {"allow": "allow", "ask": "ask", "deny": "block"}` stays in
`hook.py`. `decide.py` must never contain the string `block`, and `hook.py` must never
call anything a `deny` - so the vocabulary does not leak across the seam in either
direction.

**The `error` policy path gets the same treatment.** `_error_action` is the one place
a failure becomes a verdict, and it used `_LEVEL_TO_ACTION` internally. It moves into
`decide.py` and returns `deny`; `process_hook_event` translates it like any other
decision. `tests/test_hook.py:27` asserts
`_error_action({"*": "deny"}, ValueError("x"))["action"] == "block"` and must be
rewritten to expect `deny` at the `decide.py` level plus a `block` assertion at the
`process_hook_event` level - **both**, so the translation is pinned from each side.

**`decide_bash_command` must resolve the config before it can honour `error`.** This is a
prerequisite of the signature above, and getting it wrong is silent. `_error_action` reads
`config.get("error") or config.get("*") or "ask"` (`hook.py:149`) - and `error` is
populated by `get_effective_bash_config`, **not** by the evaluator's own `_resolve_level`,
which only walks `POLICY_KEYS` and never touches `NON_CONSTRUCT_KEYS`. So a raw block
handed straight to `decide_bash_command` routes every shfmt failure on `{"*": "allow"}` to
**`ask`**, because `error` is absent and the fallback chain reaches `*` = `allow` only if
that key survives - which it does not, once the block is un-resolved.

The fix is that `decide_bash_command` takes the **top-level wildcard** and resolves before
evaluating:

```python
def decide_bash_command(command: str, config: dict[str, Any], top_level_wildcard: str = "ask") -> dict[str, Any]:
```

which calls `resolve_bash_config(config, top_level_wildcard)` (5.1) first. `hook.py` already
has that wildcard in hand as `raw_config.get("*", "ask")` (`hook.py:198`); the Pi server
must supply it too - see 6.3. With resolution first, `error` is populated and
`_error_action` behaves identically on both hosts. Pin it with a test:
`decide_bash_command(<unparseable>, {"*": "allow"})` must NOT be `ask`.

**`process_hook_event` must also keep returning exactly `{"action", "reason"}` - it
must NOT forward `reasons`.** `tests/test_hook.py:194` asserts the whole returned dict with
`==` (`assert process_hook_event(event) == {"action": "skip"}`), which is what actually
breaks. One supporting claim in an earlier draft was wrong and is corrected here:
`tests/scenarios/test_hook_ux_format.py:85` does **not** read the result positionally - it
binds a single name and passes the dict to `generate_hook_response`, which reads it with
`.get("action")` / `.get("reason")` (`hook.py:88-89`). No positional unpacking exists
anywhere in `tests/`, so that file would survive a third key. The rule stands on
`test_hook.py:194` and on the Devin wire contract; it is simply pinned by one test, not two.
The function drops the extra key rather than passing it through.

The richer shape is for the Pi protocol only. The Devin half's contract is unchanged.

`hook.py` **keeps** the Devin protocol and nothing else moves out of it:
`PreToolUse` / `PermissionRequest`, the `exec` / `write_to_process` tool names, the
`:` label wrapper (`_hook_command` / `_strip_hook_wrappers`), `HOOK_LABEL_PREFIX`,
`HOOK_STATUS`, and the exit-code-2 contract. The Pi extension builds its own messages
and does not rewrite commands, so none of that transfers.

### 5.3 `evaluate.py` - expose the reason list

`_finalize_reason` already builds a deduped list before joining on `"; "`. Return it:

```python
{"status": ..., "reason": "; ".join(reasons), "reasons": [...], "segments": [...]}
```

Additive, so `hook.py` and all 1657 existing tests are unaffected.

**Why.** The Pi prompt renders one `- ` bullet per reason. Splitting the joined string on
`"; "` in TS would corrupt any reason containing a semicolon - and most do. Measured across
the golden corpus, 2280 of 3636 emitted reason lists (63%) contain a `"; "` *inside a
single element*, and 1219 of those are **one-element lists** that a naive split would tear
into two bullets, e.g.
`['"ls" command is not allowlisted; wildcard policy is ask']`. This is the single largest
class of reason the evaluator produces.

This changes `evaluate_bash_command`'s return shape, which `tools/golden.py:173` records
verbatim across the whole command corpus. So the `commands` section of the fingerprint
**will** gain a `reasons` key on every entry. That is an expected, mechanical Phase 2 diff.
Capture Baseline C afterwards for Phases 3+.

**The verification is "the list is empty only on the two fallback paths", not "`join`
equals `reason`".** `_finalize_reason` (`evaluate.py:862-882`) has four return paths, and
only the first two build a list:

| Path | Line | `reason` | `reasons` | Corpus |
| --- | --- | --- | --- | --- |
| allow + matched patterns | 868-871 | built from the list | non-empty | 253 |
| `verdict.reasons` | 872-877 | `"; ".join(seen)` | non-empty | 3383 |
| matched patterns, no reasons | 878-880 | `"command matches allowed pattern: ..."` | **empty** | part of 303 |
| nothing to say | 881-882 | `"allowed"` / `"allowed by wildcard policy (allow)"` | **empty** | part of 303 |

Measured over the corpus - 133 commands x 32 configs = 4256 evaluations, of which 4032
succeed and 224 raise `ParseError` - the empty list occurs on **303 entries, every one of
them `allow`**. An earlier draft of this section asked to "confirm every added value is a
list whose `"; ".join(...)` equals the pre-existing `reason` field"; that check **fails on
correct output**, and would have sent the implementer to add a synthetic reason to the two
fallback paths - changing `reason` and breaking the fingerprint those paths exist to
protect.

The correct gate, each clause verified against the corpus:

1. `reasons` is a list on every entry; `status` and `segments` are untouched.
2. `"; ".join(reasons) == reason` **whenever `reasons` is non-empty** - holds on all 3636
   such entries.
3. When `reasons` is empty, `reason` is one of the two fallback shapes and nothing else
   (303 entries; 11 distinct strings, all `"command matches allowed ..."` /
   `"allowed by wildcard policy (allow)"`).
4. **No `ask` and no `deny` entry has an empty list** (0 of 3476). This is the clause that
   actually protects the feature: it is what guarantees the ask prompt always has bullets.
   Note that a bare "`reasons` is non-empty iff `status != allow`" is *not* the rule either
   - 253 `allow` entries legitimately carry a non-empty list (path 1), so that phrasing
   over-constrains and would fail the other way.

The 224 error rows gain no `reasons` key at all: `evaluate_bash_command` raised, so there
is no return dict - `_safe` records `{"err": "ParseError: ..."}`. The gate is scoped to the
4032 `ok` rows.

### 5.4 Preserve the `{**bash}` spread

See 3.3. The Devin wrapper adds `Exec()` regexes to `allowed_cmds_regex`; everything else
about the returned dict - **including unknown keys** - must be byte-identical to today.
If the `effective` section churns during Phase 2 beyond the `reasons` addition, the split
changed observable behaviour and must be reworked.

---

## 6. Phase 3 - The `lovely-pi-bash-permissions` server

### 6.1 Entry point

`pyproject.toml`:

```toml
lovely-pi-bash-permissions = "lovely_bash_permissions.pi_cli:main"
```

(`keywords` already lists `pi`.)

### 6.2 New `src/lovely_bash_permissions/pi_cli.py`

No file loading, no mode logic, no `Exec()` merge. The extension sends a resolved
config; Python validates it and evaluates it.

### 6.3 Wire protocol

Newline-delimited JSON, stdin to stdout, **exactly one response line per request,
always**. A malformed request must yield an error response and continue, never a crash
and never a desync.

```jsonc
// ->
{"op": "evaluate", "command": "git status", "config": { /* the bash block */ }, "top_level": "allow"}
{"op": "validate", "config": { /* the bash block */ }}

// <-
{"protocol": 1, "action": "allow", "reason": "...", "reasons": ["...", "..."]}
{"protocol": 1, "valid": true}
{"protocol": 1, "valid": false, "error": "unknown bash config key 'x'; valid keys are ..."}
{"protocol": 1, "valid": false, "error": "shfmt binary not found: <detail>"}
```

On `evaluate`, an invalid config returns `{"action": "deny", ...}` - fail closed, never
evaluate an unvalidated policy.

`validate` exists so config errors surface at `session_start` (status bar) rather than on
the first command.

**`validate` must also resolve `shfmt`, or a missing binary is invisible until the first
command.** This is the one failure D8's sticky `unhealthy` flag does **not** catch, and
the reason is structural: `find_shfmt()` raises `FileNotFoundError` -> `ShfmtError` ->
`_error_action`, which is a *per-command* path. The server spawned fine, the process is
healthy, the handshake passes - so nothing marks it unhealthy, and every command quietly
routes through the `error` policy instead. Measured:

```
find_shfmt() raises -> evaluate("anything", {"*": "allow"})  ->  action "allow", per command, forever
```

That is a silent fail-open with a live-looking status bar: the user's shell behaves as if
configured, and the only clue is a reason string mentioning a parse failure. So `validate`
calls `find_shfmt()` once and reports the failure as a validation error, which the client
already surfaces at `session_start`. Verify the positive path too - it is not enough for
`validate` to pass when shfmt is present, it must fail when it is absent (and the test
must control for that, e.g. by running with a `PATH` and `VIRTUAL_ENV` that cannot resolve
it).

The message names the **providing package**, because "binary not found" alone does not
tell a user what to do - the binary is not a separate install, it ships inside `shfmt-py`:

```
lovely-pi-permissions: the shfmt binary required to parse bash commands was not
found. It is provided by the shfmt-py package that lovely-pi-bash-permissions
depends on. Reinstall that package, or point the extension's binary path at a
working install.
All bash commands are blocked until this is fixed.
```

This is the message that matters most on POSIX, because it is the one case where the
server is running fine and every command would otherwise be allowed.

`shfmt` is not a Python module, so there is no import to fail - it is a bare 3.5 MB static
Go binary that `shfmt-py` drops into the venv's `bin/`. That makes it a packaging fact
rather than an import, which is exactly why an explicit probe is required.

**Windows: decided - POSIX-only, declared unsupported.** `find_shfmt` (`parser.py:98-137`)
has no Windows handling. Candidates 1-3 all hardcode `bin/` and the bare name `shfmt`,
never `Scripts/` or `shfmt.exe`; only the final `shutil.which("shfmt")` fallback has any
chance of resolving, and a pipx venv on Windows puts the binary in `Scripts/`, which
nothing here looks in. Per the `validate` probe above, that is not a clean failure on
Windows - it is a silent `allow`-everything, which is the worst of the two outcomes.

Rather than half-support it, the decision is: **this product is POSIX-only**, stated as
such in `README.lovely-pi-bash-permissions.md` and in the extension's README. Two
consequences to carry out rather than leave implied:

- The `validate` shfmt probe is what keeps the failure *loud* on POSIX. On Windows the
  probe is the only thing standing between an unfindable binary and a silent
  `allow`-everything, so the README must not merely omit Windows - it must say that an
  unfindable shfmt will block all bash, which is the state a Windows user lands in.
- The risk table keeps this row as an accepted, documented limitation rather than a
  finding, and it is no longer an open question (§11).

If Windows support is ever wanted, it is one small change - add `Scripts/` and a `.exe`
suffix to the three candidate lists - plus a re-run of the e2e test (§7) on that platform.
Leaving it unimplemented is a choice; leaving it undeclared was the defect.

**`top_level` is required, not optional.** Without it the D6 chain breaks at the seam, and
breaks *openly enough to be trusted*. TS resolves `tool['*'] ?? mode['*'] ?? 'ask'` (8.3),
but a bash block that declares no `'*'` of its own cannot express "this mode says allow"
to a process that never saw the mode. Verified against the real resolver:

```
resolve({"allowed_cmds_regex": ["^ls"]}, "allow")  ->  "*": "allow"  ->  verdict: allow
same block, no top_level                             ->  "*": "ask"    ->  verdict: ask
```

So the block alone is not a policy. `top_level` carries the mode's `'*'` (default `"ask"`),
and `decide_bash_command` feeds it to `resolve_bash_config` - which is also what makes the
`error` policy reachable (5.2). The alternative - TS injecting a synthesised `'*'` into the
block - is rejected: it makes the resolved level indistinguishable from a user-written one,
and `validate` would then be checking a config that never existed in the file.

**`protocol` is on every response line, not just `validate`.** The client asserts it
during the handshake so a version-skewed pair fails clearly instead of mysteriously, and
putting it on every line means the client can assert on the first response it sees
regardless of which op it sent — which is the case that matters when the extension and
the installed binary come from different install attempts (8.10). A missing or
non-`1` value is a handshake failure, reported at `session_start` under the D8 posture,
never a per-command error.

The message names the **resolved path**, which is the part 8.10's resolution order makes
necessary — a user with both a `PATH` binary and an explicitly configured one needs to know
which one answered:

```
lovely-pi-permissions: the lovely-pi-bash-permissions binary at <resolved path>
speaks protocol version <n>, but this extension requires version 1.
This usually means a stale install. Reinstall from source:
    pipx install git+https://github.com/justfortheloveof/lovely-bash-permissions
All bash commands are blocked until this is fixed.
```

Server mode reads until EOF.

### 6.4 `--test`

```bash
lovely-pi-bash-permissions --test "git status" .pi/lovely-permissions.jsonc
lovely-pi-bash-permissions --test --mode strict "git status" ~/.pi/agent/lovely-permissions.jsonc
echo '{"*": "ask", "allowed_cmds_regex": ["^git\\s"]}' \
  | lovely-pi-bash-permissions --test "git status"
```

Takes an optional **path to a config file**, falling back to stdin. Both routes land in
the same loader and the same call into the evaluator - there is exactly one code path
into `decide_bash_command`.

**A path is read as-is. It is never located, discovered, or merged.** This is
deliberate and it contradicts nothing else in the plan; an earlier draft of this
section said to "accept the three Pi locations", and that was wrong:

- §6.2 states the server does **no file loading**, and D1 puts config resolution in
  TypeScript. Resolving `~/.pi/agent/` + `.pi/` + `.pi/*.local.jsonc` in Python would
  put a second config resolver in the tree - exactly the seam this plan exists to
  build (2.2).
- It could not reproduce what the extension actually uses anyway. TS `mergeDeep`
  concatenates arrays and applies mode selection before Python ever sees a bash block
  (8.3). A Python-side merge of the same three files would be a *different* config from
  the one under test, which is worse than no merge at all: a developer debugging a
  rejection would be reading a policy that was never in force.

So: one explicit path, read as the bash block it is, `--help` says so. If someone
wants the merged result, the extension's `/lovely-permissions-view` (8.9) is where it
comes from - that stays in TS per D9.

### 6.4b `--mode` - because a Pi config file is not a bash block

**The single most useful thing a developer can point `--test` at is the extension's own
config file, and that file is mode-wrapped.** Reading it as a bare `ToolConfig` does
not fail loudly - it fails *confidently*:

```
$ echo '{"default":{"bash":{"allowed_cmds_regex":["^vp"]}}}' > /tmp/pi.jsonc
$ lovely-pi-bash-permissions --test "vp run build" /tmp/pi.jsonc
# bash block parsed from mode-wrapped file -> None
```

`PermissionsConfig` is permissive at the root, so `default` is an unknown tool name and
only warns. `bash` comes back `None`, the evaluator runs with an **empty policy**, and
every command resolves to `ask` under the fallback wildcard. The tool reports a verdict,
the verdict is confidently wrong, and `ask`-for-everything is indistinguishable from a
correct pessimistic policy. An earlier draft of this section used exactly this command
as its worked example.

So the path form accepts two shapes:

- a **bare bash block** — `{"*": "ask", "allowed_cmds_regex": [...]}`
- a **mode-wrapped file** — `{"<mode>": {"bash": {...}, ...}}`, which is what every Pi
  config file actually is

Rules:

1. `--mode <name>` selects that mode. Without it, the **first** mode is used and its
   name is printed to stderr, so the answer is never ambiguous about which policy it
   came from.
2. An unknown `--mode` name is an error naming the modes that exist.
3. **A mode with no `bash` block is a hard error, never an empty policy.** So is a file
   that is neither shape. This is the whole point of the subsection: the one outcome
   that must never happen is a verdict computed from nothing.
4. This is `--test`-only. The server path (6.2) still takes a bare bash block. Unwrapping a
   mode container is host-shape knowledge that brushes D1, so it stays in the developer tool
   and out of the protocol - a note worth making, because the obvious "improvement" of
   teaching the server about modes would undo D1.
5. **The unwrapped mode's own `'*'` becomes the `top_level` wildcard** (6.3). A mode is
   `{"<mode>": {"*": "...", "bash": {...}}}`, and that mode-level `'*'` is exactly the
   value D6 says feeds the bash block's missing `'*'`. Passing it is what makes `--test`
   agree with what the extension does. Omitting it reproduces the seam bug in 6.3: a mode
   of `{"*": "allow", "bash": {"allowed_cmds_regex": ["^vp"]}}` would report `ask` while
   the live extension reports `allow`.

The path form is the one a developer actually uses, but for the opposite reason to the
one originally given: a developer who can name the file has the file the extension
loaded, and passes it explicitly.

Prints the verdict; exits `0` (allow/ask) or `2` (deny). With a TTY, no path, and no
stdin, print usage and exit non-zero rather than hanging.

**Exit codes distinguish a verdict from a broken invocation.** Without this, a script
cannot tell *"the policy denies this"* from *"I handed you the wrong file"*, which is the
distinction a CI check most needs:

| Code | Meaning | Cases |
| --- | --- | --- |
| **0** | a verdict, non-denying | `allow` or `ask` |
| **2** | a verdict, denying | `deny` |
| **1** | **no verdict at all** | usage with no input; unreadable file; a file that is neither shape; a mode with no `bash` block; unknown `--mode`; an invalid config |

`2` for deny and `1` for error is not arbitrary: it matches `lovely-devin-permissions`,
which already keys exit 2 off a denied decision (`devin_cli.py:246-247`) and uses `1` for
everything that produced no verdict. The two CLIs therefore agree, which is worth more
than any independent scheme.

### 6.5 Output discipline

The server writes **only** protocol lines to stdout. Diagnostics, warnings, and tracebacks
go to stderr - and stderr has a **narrower job than it looks**, because §6.3 and 8.4 give
most failures a better channel.

**Two channels, split by whether the server can speak the protocol yet.**

| Channel | Carries | Consumer |
| --- | --- | --- |
| **protocol** (primary) | anything the server can report: config errors on `validate`'s `error`, verdicts and their `reason` on `evaluate` | the extension, as the block/ask reason |
| **stderr** (fallback) | only what has no protocol line: a crash *before or during* handshake, or a traceback escaping the loop | a bounded tail in the `session_start` notification |

The protocol is primary because it is structured and knows what it is talking about. The
missing-shfmt case is the proof: it is reported as `{"valid": false, "error": ...}` by the
`validate` probe, so it never needs stderr at all. stderr exists for the one window where
no protocol line was ever written.

**The stderr tail never goes into the block reason.** `toToolCallEventResult`
(`mapping.ts:21`) puts `reason` straight into the model-facing tool result, so a traceback
there would burn context on every blocked command and leak absolute paths into the
conversation. It goes to the **`session_start` notification**, where the human sees it once,
at the moment it matters. The block reason stays a concise fixed string naming the category
and the fix - which is what D8 actually asks for, and what a fixed constant does better
than a traceback does.

Bound it: keep roughly the last 20 lines / 4 KB, so a chatty startup cannot produce an
unbounded notification. `--test` needs none of this - stderr lands on the terminal
directly, which is the other reason the two channels are not redundant.

This makes 6.5 a **requirement on the client**, not a description: without a bounded tail
in `server.ts`, a pre-handshake crash produces a block message with no explanation, which
is the exact failure D8 exists to prevent.

**Flush after every response line.** `print()` to a pipe is block-buffered; a
long-lived server that does not flush will appear to hang from the client's side, and a
`--test` that exits immediately after a `print` without a flush can truncate its last
line. Use `print(json.dumps(...), flush=True)` on the response path, and flush
explicitly before any `sys.exit`.

---

## 7. Phase 4 - Python tests and docs

Follows the conventions `docs/ARCHITECTURE.md` already states: tests mirror the package,
test classes carry the module they cover, all shared fixtures live in `tests/conftest.py`.

| File | Covers |
| --- | --- |
| `tests/test_pi_cli.py` | Protocol framing, one-response-per-request, malformed input, unknown op, `--test` |
| `tests/test_decide.py` | The shared decision, including every `error` policy path. **Asserts `decide_bash_command` returns `deny`, never `block`** (D12) |
| `tests/test_hook.py` (extend) | The `deny` -> `block` translation at the seam, asserted from *both* sides: `decide` yields `deny`, `process_hook_event` yields `block`. Rewrites `test_hook.py:27` accordingly |
| `tests/config/test_effective_bash.py` (extend) | `resolve_bash_config` in isolation; **pin that `get_effective_bash_config` output is unchanged across the split** |
| `tests/config/test_schema.py` (extend) | Strict-vocabulary rejection, message content, no over-rejection. **Includes the 4.0 regression test: `{"*": "ask"}` validates**, the message lists `*` and not `wildcard`, and every key named in the message is accepted. Update `test_schema.py:420`'s hand-written key list to import from `policy.py` |
| `tests/test_evaluate.py` (extend) | `reasons` per the **four-path** rule in 5.3 - especially that no `ask`/`deny` entry has an empty list |
| `tests/test_pi_cli.py` (extend) | `top_level` round-trip: `{"allowed_cmds_regex":["^ls"]}` + `top_level="allow"` is `allow`; the same block without it is `ask` |
| `tests/test_protocol_e2e.py` (new) | **The real wire, over a real pipe.** Spawns the installed `lovely-pi-bash-permissions` as a subprocess and drives actual JSONL |

Docs:

- `docs/ARCHITECTURE.md` - "two independent halves" becomes three surfaces. Document
  both seams and **why** they exist, so the next person does not re-inline them. Add a
  section naming the Pi client/server pair by their full names, since a reader who finds
  this file via either project needs to know which half they are looking at.
- New `README.lovely-pi-bash-permissions.md` - install, protocol, schema table, the D6
  fallback chain, failure modes. Cross-link the TS extension by name so the pairing is
  discoverable from either side.
- `README.md` - related-project section.

**Why `test_protocol_e2e.py` exists.** Every other test in this plan calls a function
directly. None of them cross the repo boundary, and that boundary is where the expensive
defects live: of the nine in §11.1 and the four in §11.2, **#10, #12 and #13 were all seam
defects** - a missing `top_level` field, an un-resolved `error` key, a gate that named the
wrong golden section. None was visible from either repo alone, and none would be caught by
`tests/test_pi_cli.py` (which tests the handler) or by §8.8's fake server (which tests the
TS client against a stub). The one layer nobody was testing is the one that kept breaking.

So the e2e is deliberately small and protocol-level rather than a second unit suite:

1. Spawn the console script as a real subprocess (`sys.executable -m` or the installed
   entry point), `stdin=PIPE, stdout=PIPE, text=True`.
2. Send an `evaluate` request, read exactly one line, parse it, assert `protocol == 1` and
   the expected `action`.
3. Repeat on the **same** process, so one-response-per-request is exercised across turns
   rather than in a fresh process each time.
4. Assert a malformed line gets an error response and the stream **desynchronises by
   exactly one line** - then that a subsequent good request still gets its own answer.
5. Assert the `validate` op's `shfmt` probe reports missing when `shfmt` cannot be resolved
   (6.3) - a negative-path test, because the positive one passes by accident today.

Skip with a clear message (not a silent pass) when the console script is not on `PATH`, so
a broken install does not masquerade as a green suite. The TS side gets the mirror of this
in Phase 5, but it is *not* a duplicate: 8.8's fake server proves the client is correct
against a stub, and only this proves the stub was faithful.

**Gate:** `pytest` green (1657 + new) and `-m linting` clean.

---

## 8. Phase 5 - The TS extension

Repo: `../jftlo/lovely-pi-permissions`. Per its toolchain constraint, use
`vp run build` for all lint/format/test/build - nothing else. That is the full gate:
`package.json:23` defines `build` as `vp fmt && vp check && vp test && vp build`, and
`vp run build` invokes the script rather than the built-in `vp build` (they are distinct:
`vp build` alone skips fmt, check, and test). `vp check` runs Oxfmt + Oxlint + tsgolint in
one pass with `typeAware` and `typeCheck` on (`vite.config.ts:16-21`), which is why
`noUnusedLocals` is a build error rather than a suggestion (8.8).

### 8.1 New `src/perms/server.ts`

Process lifecycle:

- spawn at `session_start` (which fires with reason `startup | reload | new | resume | fork`)
- **kill the child on `session_shutdown`** (reason `quit | reload | new | resume | fork`).
  Without this, `/reload` orphans a Python process every time - and the extension's
  README documents `/reload` as the way to re-read config.
- the `session_shutdown` handler is **idempotent**. `docs/extensions.md:220-224`
  requires it explicitly ("Register an idempotent `session_shutdown` handler"), and
  `docs/extensions.md:1251` warns that code in `withSession` must assume anything a
  shutdown handler invalidates is already gone. Kill, drop the handle, clear
  `unhealthy` in that order, and tolerate being called twice.
- newline-delimited JSON framing over stdin/stdout
- **per-request timeout: 10 s.** Not arbitrary - the two bounds it sits between are
  measured. A warm `evaluate` is **2.2 ms** (one shfmt subprocess per call, ~456/sec),
  while `parser.py:69` allows shfmt **30 s**. 10 s is roughly four orders of magnitude
  above normal operation and three times below the worst legitimate case, so it never
  fires spuriously (a cold shfmt on first call is the only slow path) while capping a
  genuine hang at a tenth of the time the user would otherwise wait.
- **This makes the 30 s shfmt timeout unreachable from the Pi path.** The client kills at
  10 s, so `parser.py:69`'s ceiling only ever applies to the Devin half. The risk row in
  §10 is restated accordingly - do not "fix" the client timeout upward to accommodate it.
- restart on crash
- sticky `unhealthy` flag: once set, **every** bash call blocks with a reason naming the
  fix (D8). There is no fallback local evaluator, ever.

**Every `docs/extensions.md` line citation in this section is pinned to
`@earendil-works/pi-coding-agent@0.84.3`, and they rot fast.** Re-verify before relying on
any of them. Measured across the versions present on this machine:

| pi version | `extensions.md` lines | `:766` is |
| --- | --- | --- |
| **0.84.3** (pinned here) | 3002 | the parallel-execution sentence quoted below |
| 0.84.4 (sibling repo) | ~3000 | `pi.on("thinking_level_select", ...)` - already drifted |
| 0.85.1 / 0.86.0 (mise) | 3023 / 3037 | drifted further |
| 0.87.1 (mise) | **215** | reorganised into many files |

The rule is: **cite pi docs by heading text and version, never by bare line number.** The
content this plan depends on is durable; the line numbers are not. The 0.87.x split moved
`extensions.md` into `cli.md` / `rpc.md` / `sdk.md` / `how-pi-works.md` / `security.md` and
others, so a `:766` reference is meaningless two minor versions out.

Spawning belongs in `session_start`, not the extension factory:
`docs/extensions.md:220-222` — "Do not start background resources such as processes ...
from the factory." `main.ts:17-19` already constructs `SettingsManager` /
`SessionRuntime` at factory scope, so the spawn must not be added there.

**Timeout handling: a timeout kills and respawns the child (D13).**

The client cannot simply give up on a slow request. A "give up" leaves an
unanswered request in flight, and the child will eventually write a response line for
it - which the *next* request reads as its own answer. The failure is silent and
adversarial: a command that was never actually evaluated gets a verdict from a
different command. The server stays correct (one response per request, 6.3); it is the
client that stops counting, and the invariant becomes meaningless.

Since the plan deliberately carries no request ids, respawn is the mechanism that
restores the pairing:

```
on timeout -> kill child -> await 'exit' -> clear buffered stdout -> spawn fresh child
            -> mark the in-flight request failed and return the fail-closed result
```

Killing is what makes this safe: the abandoned request's response can never be
written, because the process that would have written it is gone. This is distinct from
the `unhealthy` flag (D8), which is about *spawn* failure - a binary that is missing or
will not start - and stays sticky. A timeout is a latency event, not a health event,
and must not permanently disable bash.

Rejected alternatives, for the record: request ids / response matching adds correlation
state to both sides for a case that respawn solves by construction; draining "one stale
line" assumes exactly one response is pending, which is true today and is precisely
the assumption that has just been shown to be fragile.

**Serialization (corrected).** An earlier draft of this plan cited
`docs/extensions.md:766` —

> sibling tool calls from the same assistant message are preflighted sequentially, then
> executed concurrently

— and concluded that `tool_call` handlers for one assistant message can overlap. **That
reading is wrong**, and the shipped source settles it: `agent-loop.js:342` awaits
`prepareToolCall` in a `for` loop, and only reaches `Promise.all` at `:365` *after* the
last preflight completes. The CHANGELOG agrees (`CHANGELOG.md:2506`): "sequential
`tool_call` preflight preserved for extension interception". Sequential preflight;
concurrent *execution* afterwards.

Two consequences, and the second is the one that matters:

1. A promise queue in the client is **cheap insurance, not a correctness requirement.**
   Keep it — `tool_execution` is a runtime option (`agent.js:134`, default `parallel`),
   so the guarantee is a property of the shipped default rather than of the contract, and
   the queue costs nothing at ~2 ms warm. But do not describe it as protecting against an
   overlap that the shipped code does not produce.
2. **`SessionRuntime`'s mutable state is currently safe only because preflight is
   serial.** `callHistory` (`session.ts:20`) is appended to in `recordCall` (`:109`) and
   `answerCache` (`:23`) is read-then-written in the `loopBlock` branch (`:55-57`, `:72`),
   with no mutex anywhere. Both are read-modify-write across an `await`. This is correct
   today only because no two `tool_call` handlers interleave.

   That is a sharper statement of the constraint §8.7 already half-makes: the doom-loop
   streak and the answer cache are both *position-dependent* state, and the property that
   keeps them correct is pi's sequential preflight, not anything in this extension. Phase
   5 puts a subprocess round-trip on that path for the first time, so **document the
   invariant next to the state that depends on it** — on `callHistory` and `answerCache`,
   not only on the cache's mode-switch invalidation. If the queue in (1) is ever removed
   because it "looked unnecessary", this comment is what makes that decision visible.

   `ctx.signal` exists during `tool_call` (the `ExtensionContext` type declares
   `signal: AbortSignal | undefined`) and is currently not forwarded - the `tool_call`
   handler at `main.ts:103-119` passes only `mgr.getConfig()`, the ask callback, and a
   notify function. `contextToUI` (`prompter.ts:21-35`) forwards only `hasUI`, `select`,
   `input`, and `theme`, so the signal never reaches the prompt either. Forward it: a turn
   aborted mid-evaluation should cancel the request rather than hold the serialized queue
   open until timeout.

### 8.2 `src/permissions/bash-evaluation.ts`

`new BashPermissions(bashConfig).evaluate(command)` becomes `server.evaluate(command, cfg)`.
The call is two statements, not the chained form - `bash-evaluation.ts:20-22` - and the
result is read as `decision.status` / `decision.triggers` (`:24`, `:36`, `:49`).

The `decision.triggers` walk and both hand-rolled reason builders (`allowReasons`,
`askReasons`) are deleted. Python's `reasons[]` is the single source.

### 8.2b `describe.ts` - keep prose here, not policy

`describeToolCall` renders the *description* shown above the bullets in the ask prompt
("The agent is trying to run a SHELL cmd: ..."). It stays in TypeScript and is **not**
moved to Python: it is agent-UI prose, not a policy decision, and the Python side has no
opinion about how Pi should word a prompt.

The split must stay crisp so the two do not drift:

- **TypeScript owns** how the prompt reads - description text, bullet glyphs, colours,
  ordering, the `♡` branding.
- **Python owns** why the decision was reached - the `reasons[]` strings, in order.

If a reason arrives from Python already formatted as a bullet, TS must not add a second
one. Bullet assembly stays in `prompter.ts`.

### 8.3 Config schema

`bash` becomes exactly the Devin `ToolConfig`:

`*`, `error`, `allowed_cmds_regex`, `blocked_cmds_regex`, `output_redirection`
(string, or an object over `*` / `stdout_to_dev_null` / `stderr_to_dev_null` /
`stderr_to_stdout` / `other`), `input_redirection`, `background_execution`,
`command_substitution`, `process_substitution`, `subshell`, `variable_assignment`.

- `permission` -> `*` on **all** tools. Note bash **already** reads `['*']` today
  (`tool-evaluator.ts:21`), so this rename is real only for the non-bash tools and
  `doom_loop`; see 1.4.
- `blocked_paths_regex` survives **only** on non-bash tools
- level resolution (D6): `tool['*'] ?? mode['*'] ?? 'ask'`
- mode-level `*` never affects `setActiveTools` (see 2.1)

**Send the resolved wildcard as `top_level`; do not splice it into the block.** The
`evaluate` request carries the bash block verbatim plus `top_level: mode['*'] ?? 'ask'`
(6.3), and Python resolves the two together. Writing the resolved level into the block
before sending would work numerically and be wrong in substance: `validate` would then
check a config that differs from the file on disk, and a user reading the `validate` error
would be chasing a key they never typed. Keep the block exactly as the file declares it.

`src/runtime/session.ts` reads the `doom_loop` level in two places, and both are part of
this rename: line 49 `doomLoopConfig?.permission === 'allow'` and line 69
`(doomLoopConfig?.permission ?? 'deny') === 'ask'`. They become `doomLoopConfig?.['*']`.
Nothing else about doom-loop handling changes.

**The rename also invalidates `doom_loop`'s level validation - see 8.4.** The check in
`validateModes` reads `cfg.permission`, and 8.4 drops the schema it uses. A rename that
only edits the three read sites leaves `doom_loop` levels unvalidated, which is a silent
no-op rather than a loud break. This is the one place where a "mechanical rename" is not
mechanical, and it is worth doing in the same commit as the rename rather than leaving to
whoever hits the type error.

**The `answerCache` stays.** It is a doom-loop rejection memo, not an evaluation cache:
every read and write is inside the `if (loopBlock)` branch (`session.ts:54-74`), and the
`evaluateToolCall` path at lines 76-87 never touches it. It exists so that after a user
rejects a doom-looping call once, repetitions 4, 5, 6 do not re-prompt the same person.
A faster server does not make that redundant - the thing being preserved is the human's
answer, not a policy evaluation. Only `result?.block` is cached (line 72), so an "Allow"
answer is not remembered; that is correct and must not change.

### 8.4 `src/settings/index.ts`

Drop the `@justfortheloveof/lovely-bash-permissions` import. Bash validation becomes the
`validate` op (one round trip at `session_start` and on every mode switch, replacing
`bashPermissionsConfigSchema.parse` + the `findInvalidRegexes` walk). Non-bash tools keep
TS-side checks: a `PermissionLevel` check and a regex-compile check for
`blocked_paths_regex`.

**The non-bash `PermissionLevel` check needs a new home, and this is the part 8.3's rename
silently breaks.** `validateModes` currently does
(`settings/index.ts:53-56`):

```ts
for (const [toolName, cfg] of Object.entries(mode)) {
  if (!cfg) continue;
  if ('permission' in cfg && cfg.permission !== undefined) {
    permissionLevelSchema.parse(cfg.permission);
  }
```

That is the **only** validation a `doom_loop` level ever gets, and 8.4 removes
`permissionLevelSchema` (it is imported from the package being dropped) while 8.3 renames
the key it reads. Nothing in either section says what replaces it, so the check evaporates
and `{"doom_loop": {"*": "typo"}}` becomes a silent no-op - **the same defect this entire
plan exists to eliminate**, reintroduced one phase later, in the one key the golden
fingerprints never see (Python has no `doom_loop`; it appears nowhere in `src/`).

`PermissionLevel` is a three-value union, so the replacement is three lines and needs no
dependency:

```ts
const PERMISSION_LEVELS = ['allow', 'ask', 'deny'];
// in the loop, for every non-bash tool block including doom_loop:
const level = (cfg as BaseToolConfig)['*'];
if (level !== undefined && !PERMISSION_LEVELS.includes(level)) {
  problems.push(`mode "${modeName}", tool "${toolName}": invalid level "${level}" - expected one of ${PERMISSION_LEVELS.join(', ')}`);
}
```

Three things follow, and all three are testable:

- The check must cover `doom_loop` and the mode-level `*`, not just the six named tools -
  the current `Object.entries(mode)` loop already does, and the replacement must keep it.
- The loop must be `for (const [toolName, cfg] of Object.entries(mode))` over the **whole
  mode**, not a hardcoded list, for the same reason 8.4b's index signature is preserved.
- A typo'd level must still mark the manager invalid via the existing `problems` path
  (`reload` catches and sets invalid), so the status bar shows it at `session_start`
  rather than the user's shell quietly misbehaving later.

**`validate` covers the bash block only; say so in the op's contract.** It takes
`{ "config": { <bash block> } }` and validates exactly that. The six non-bash tools, the
mode-level `*`, and `doom_loop` never reach Python, so this TS-side check is their *only*
validation - it is not redundant with `validate`, and dropping it as "already covered by
the server" would be wrong. State that in the `pi_cli.py` docstring and in
`README.lovely-pi-bash-permissions.md`, so a later reader does not consolidate the two
into one and lose the checks.

**The invalid-config message needs context Python cannot supply.** `validate` returns
Python's error verbatim - `unknown bash config key 'x'; valid keys are ...` - and Python
has no idea which file or mode produced it. On its own that message is unactionable: a
user with three config files and five modes cannot tell which one to open. So TS prefixes
the mode name and the path it resolved that mode from:

```
lovely-pi-permissions: config is invalid in mode "strict" (.pi/lovely-permissions.jsonc):
unknown bash config key 'x'; valid keys are 'allowed_cmds_regex', 'blocked_cmds_regex', ..., '*'
Fix the config to re-enable permissions.
All bash commands are blocked until this is fixed.
```

The error text is Python's, unmodified - do not reword it, because Phase 1's message
content is pinned by tests (§4.2) and by the D5 contract. TS supplies only the *where*,
Python owns the *what*. That split is the same one 8.2b draws for reasons and bullets.

### 8.4b Four more files import the dropped package

**8.6 removes a dependency that 8.4 alone does not clear.** Five source files import
`@justfortheloveof/lovely-bash-permissions` today, and only one of them is the
`settings/index.ts` above. Removing the `package.json` entry without touching the other
four is a build failure at the first step of Phase 5, and `vp check` reports it as a
wall of unrelated "cannot find module" errors rather than as the real cause.

| File | What it imports | What replaces it |
| --- | --- | --- |
| `src/permissions/bash-evaluation.ts:2-6` | `BashPermissions`, `type BashPermissionsConfig`, `type PolicyViolation` | 8.2 - the whole `evaluate` call is replaced by `server.evaluate` |
| `src/settings/index.ts:1-6` | `bashPermissionsConfigSchema`, `findInvalidRegexes`, `permissionLevelSchema`, `type BashPermissionsConfig` | 8.4 - validation moves to the `validate` op |
| `src/settings/types.ts:1` | `type BashPermissionsConfig, PermissionLevel` | **Define locally** |
| `src/settings/types.ts:3` | `export type { PermissionLevel }` | **Define locally**, and keep the re-export so callers are unchanged |
| `src/permissions/tool-evaluator.ts:2` | `type BashPermissionsConfig` | import from `settings/types.ts` |
| `src/permissions/tool-evaluator.test.ts:11` | `type BashPermissionsConfig` | import from `settings/types.ts` |

Two corrections to an earlier draft of this table, both verified against the tree. It
omitted `bash-evaluation.ts` - the **only** file that constructs `BashPermissions`, and so
the one whose removal 8.2 actually performs. And it listed `PermissionLevel` among
`settings/index.ts`'s imports; it is not imported there (`grep -n PermissionLevel
src/settings/index.ts` returns nothing). The name in that file is `permissionLevelSchema`,
the zod schema, which 8.4 drops along with the rest.

The two types are small and they are now *this project's* schema, not somebody else's:

```ts
export type PermissionLevel = 'allow' | 'ask' | 'deny';
export interface BashConfig {
  '*'?: PermissionLevel;
  error?: PermissionLevel;
  allowed_cmds_regex?: string[];
  blocked_cmds_regex?: string[];
  output_redirection?: PermissionLevel | { '*'?: PermissionLevel; /* + the 4 kinds */ };
  input_redirection?: PermissionLevel;
  background_execution?: PermissionLevel;
  command_substitution?: PermissionLevel;
  process_substitution?: PermissionLevel;
  subshell?: PermissionLevel;
  variable_assignment?: PermissionLevel;
}
```

The key list must match §8.3 exactly, and Python's `validate` op is what proves it at
runtime rather than at compile time.

**`BaseToolConfig` loses its `Pick<>`.** Today:

```ts
export type BaseToolConfig = Pick<BashPermissionsConfig, 'blocked_paths_regex'> & {
  permission?: PermissionLevel;
};
```

That structural overlap exists only because the type was imported from another package,
and it is why `tool-evaluator.ts:21` needs casts. With a locally defined
`BashConfig`, the two shapes are genuinely disjoint and the casts go away:

```ts
export interface BaseToolConfig {
  '*'?: PermissionLevel;
  blocked_paths_regex?: string[];
}
```

**The second cast is in `settings/index.ts:60`, not `tool-evaluator.ts:60`.** An earlier
draft cited `tool-evaluator.ts:21,60`; line 60 there is `backgroundHint: false,` a
literal. The only other `as BashPermissionsConfig` in `src/` is
`settings/index.ts:60` (`const bash = cfg as BashPermissionsConfig;`), and it disappears
with 8.4. So two cast sites in two files, not two in one.

Two things must survive the rewrite:

- **The index signature** on `LovelyPermissionsConfig`
  (`[toolName: string]: BaseToolConfig | BashConfig | undefined`) is what makes
  `syncActiveTools` (`main.ts:57-58`) and the "unconfigured → block" guard
  (`tool-evaluator.ts:13-18`) work over arbitrary tool names. Do not "tidy" it into a
  fixed list of the seven tools.
- **`PermissionLevel` must still be exported from `settings/types.ts`.** Nothing else
  in `src/` imports it directly today, but it is a public type of the settings module
  and 8.4's "a `PermissionLevel` check" refers to it. It has to be *defined* here after
  8.6, not merely referenced.

### 8.5 Delete four dead fields

`outputRedirectHint`, `inputRedirectHint`, `backgroundHint`, `subshellHint` on
`EvalResult`. They are assigned in `bash-evaluation.ts`, `tool-evaluator.ts`, and
`session.ts` and **read nowhere** outside tests. `reasons[]` carries the information now.

### 8.6 `package.json`

Remove `@justfortheloveof/lovely-bash-permissions`. This makes the extension the last
consumer of the old shell-quote library.

### 8.7 Document the implicit couplings while we are in the file

**`SessionRuntime.cacheKey`** is `toolName + serializeToolInput(input)`
(`session.ts:105-107`) - it carries no mode and no policy. Its correctness across a mode
switch depends entirely on `main.ts:79` calling `session.clearAnswers()` by hand.

That coupling is implicit and undocumented: add a new config-change path and the cache
silently serves an answer from the previous mode. Since Phase 5 already edits
`session.ts`, add a comment on `answerCache` naming its invalidation points
(`onSessionStart`, `onInput`, `clearAnswers` on mode switch) so the next person does not
miss one. A comment, not a refactor.

**The same applies to the serial-preflight dependency**, which is broader than this
cache and documented in 8.1: `callHistory` and `answerCache` are both unsynchronised
read-modify-write state that is correct only because pi preflights `tool_call`
sequentially. Comment that next to both fields, so the next person to "parallelise the
server client" learns what they would be breaking.

### 8.8 Tests

Mirror `src/`, plus a fake-server harness covering: crash mid-session, request timeout
(kill-and-respawn, and the guarantee that **no stale response is ever read as a
later request's answer**), restart, the sticky-unhealthy path, and
`session_shutdown` idempotency (called twice, and called without a matching
`session_start`).

Three tests belong here that the fake server cannot express, because they are about
*config* rather than about the transport:

- **A typo'd non-bash level is rejected** - `{"doom_loop": {"*": "nope"}}` and
  `{"read": {"*": "typo"}}` must both mark the manager invalid, via the `problems` path in
  8.4. This is the regression guard for the finding in 8.3/8.4: the check that the rename
  would otherwise delete has to have a test or the deletion is invisible.
- **The mode-level `*` is validated too**, not just the six named tools - a config of
  `{"default": {"*": "nope", "bash": {...}}}` must be rejected. Keeps the
  `Object.entries(mode)` loop from being "tidied" into a hardcoded list.
- **`validate` failing for a missing shfmt sets the sticky-unhealthy state** (6.3), so the
  failure is visible at `session_start` rather than as silent per-command routing.

Note the layout reality: there is **no `src/permissions/bash-evaluation.test.ts`** today.
Bash behaviour is tested through `src/permissions/tool-evaluator.test.ts`, which holds 86
of the extension's 181 tests. The Phase 5 rewrite therefore lands mostly there, not in a
new file — "mirror `src/`" should not be read as "create a new test per source file".

Two build details that will otherwise surface as confusing failures:

- `node:child_process` is already covered by the `external` pattern `/^node:/`
  (`vite.config.ts:13`), so the child is spawned from the real Node API with no build
  config change. `server.ts` is reached from `main.ts`, so `build.lib.entry` stays a
  single string — no second rollup input needed.
- `tsconfig.json` sets `exactOptionalPropertyTypes: true` and
  `noUncheckedIndexedAccess: true`, and `noUnusedLocals: true` makes an unused import a
  **build error** (`vp check` runs type-aware lint, `vite.config.ts:16`). Spawn options
  carrying `signal: AbortSignal | undefined` will need `?:` or an explicit branch.

Also: `extensions/lovely-pi-permissions.js` is a **committed 137 kB build artifact**
(`.gitignore` covers `/dist`, not `extensions/`), and the old npm package is bundled
into it rather than external. Phase 5's final commit must include the rebuilt bundle,
and dropping `@justfortheloveof/lovely-bash-permissions` (8.6) should shrink it
noticeably — a good sanity check that the dep really is gone.

### 8.9 The extension's own config and docs

**`../jftlo/lovely-pi-permissions/.pi/lovely-permissions.jsonc`** must be updated. It is
currently:

```jsonc
{ "default": { "bash": { "allowed_cmds_regex": ["^vp\\s+run\\s+(build|check|checkfix|test)$", ...] } } }
```

With no `*` anywhere, the current evaluator hits `permission === undefined` in
`tool-evaluator.ts:22` and **blocks every bash call**. Under D6 the same file resolves
to `"ask"`, which is the intended behaviour - so the file needs an explicit `"*"` to
express what it means rather than relying on the fallback. Check it against the new
schema as part of Phase 5; it is the first real config anyone will run through this.

**The extension's `README.md`** documents the old schema throughout and cannot be
patched incrementally - the `permission` / `blocked_paths_regex` / 3-redirection-kind
model is described across the Quick Start, Bash Command Control, and Configuration
sections. Rewrite it against the new schema and the `vp run build` gate, and state the
**two-repo install** (see 8.9b). Include what to do when the binary is missing, since
that path blocks all bash by design (D8).

### 8.9b There is no PyPI release - the install is a git URL

**`lovely-bash-permissions` is not published.** `https://pypi.org/pypi/lovely-bash-permissions/json`
returns 404, the repo is at `0.1.0` with **no git remote**, and there is no CI in either
repo. An earlier draft of this section told the README to say "install the
`lovely-bash-permissions` PyPI package", which is an instruction to `pip install` a
package that does not exist.

This is worse than a broken link, because of D8: a user who follows the documented
install and fails lands on the fail-closed path, where **all bash is blocked by design**.
A missing binary therefore presents as a permissions bug rather than a setup bug, and
the reader's first instinct will be to go looking for a misconfigured policy. The
failure message has to name the install command, or the two get conflated.

**The install, as documented:**

```bash
pipx install git+https://github.com/justfortheloveof/lovely-bash-permissions
# or, for development:
git clone https://github.com/justfortheloveof/lovely-bash-permissions
cd lovely-bash-permissions && pip install -e .
```

`pipx` is the right tool rather than `pip`: the package's `dependencies` include
`pydantic` and `shfmt-py`, and a global `pip install` of it into a user's environment is
both intrusive and, on a managed machine, likely to fail.

**Prerequisite, outside the phases:** the repository needs a remote for the URL above to
resolve. Until one exists, the documented install is aspirational. Either add the remote
before Phase 5's README is written, or state in the README that it is installed from a
clone. Do not ship a URL that 404s — that is the same defect as the PyPI line, one
layer out.

Two consequences for the rest of Phase 5:

- **A version floor is unnecessary, a *binary* floor is not.** There are no releases to
  be behind, but a user can easily have a *pre-Phase-3* install of
  `lovely-bash-permissions` on their `PATH` that has no `lovely-pi-bash-permissions`
  console script at all (it is added in 6.1). That is a missing binary, which 8.10
  already handles — but the message must say "an older `lovely-bash-permissions` without
  the Pi CLI is installed" rather than a generic "not found", because the two look
  identical to the user and have opposite fixes.
- **`protocol: 1` (6.3) is what catches a mismatched pair**, and because it is on every
  response line the client can check it on the first exchange regardless of op.

### 8.10 How the extension locates the binary

Resolution order, in preference:

1. an explicit path in the extension config, if present
2. `LOVELY_PI_BASH_PERMISSIONS_BIN` in the environment
3. `lovely-pi-bash-permissions` on `PATH`

Because a miss blocks all bash, the failure message must be actionable - name what is
missing and give the install command, not just "server unavailable". The `session_start`
handshake is where this is discovered, so surface it there rather than on the first
command.

**Distinguish "not installed" from "an old version is installed".** There is no PyPI
release to be behind (8.9b), so the realistic miss is a user who has a pre-Phase-3
`lovely-bash-permissions` on their `PATH` that simply never had the
`lovely-pi-bash-permissions` console script. Those two failures look identical from the
outside and have opposite fixes, so the message names the distinction and gives the
command from 8.9b:

```
lovely-pi-permissions: the lovely-pi-bash-permissions binary was not found.
If lovely-bash-permissions is already installed, it is an older version that
predates the Pi CLI. Install or upgrade from source:
    pipx install git+https://github.com/justfortheloveof/lovely-bash-permissions
All bash commands are blocked until this is fixed.
```

The last line is not padding. D8 blocks every bash call by design, so the user needs to
know that a blocked shell is the *expected* consequence of a missing binary and not a
misconfiguration they should go hunting for in their policy.

The name matters here: the extension is `lovely-pi-permissions` and the binary it spawns
is `lovely-pi-bash-permissions`. Keep them distinct in every message, log line, and
comment - a "server unavailable" notice that names the wrong project sends the reader to
the wrong repo.

**All four startup failures now have specified wording**, so none is left to invention at
implementation time. They are written in the section that owns each failure rather than
collected in one table, which keeps them next to the behaviour they describe:

| Failure | Owner | Where specified |
| --- | --- | --- |
| binary not found | 8.10 | 8.10 |
| protocol version mismatch | 6.3 | 6.3 |
| shfmt missing | 6.3 | 6.3 |
| config invalid | 8.4 | 8.4 |

All four set sticky `unhealthy` and block all bash, and all four end with the same closing
line - `All bash commands are blocked until this is fixed.` - because that sentence is what
stops a user hunting for a policy bug that does not exist (D8). What differs is the middle:
what failed, and the one command that fixes it.

---

## 9. Order of work

0. **Branch first, in both repos, before any further work.** Every change in Phases 0-5
   MUST land on a branch named exactly `migrate-bash-to-python`, created off the current
   tip of whichever branch is checked out at the time:

   ```bash
   # this repo
   git switch -c migrate-bash-to-python
   # the extension
   cd ../jftlo/lovely-pi-permissions
   git switch -c migrate-bash-to-python
   ```

   The name is fixed and shared across both repos on purpose: it is the handle that ties the
   Python work and the TypeScript work to one migration, and it is what a reviewer greps for.
   Note the asymmetry the plan already has - Phases 1-4 are one reviewable change here,
   Phase 5 is a separate repo - so the two branches are reviewed independently and merged
   independently. The shared name is the only thing that keeps them identifiable as one
   piece of work.

   Two rules that are easy to get wrong:

   - **Branch off the checked-out tip, do not branch off `main`.** The repos are not on
     `main` and have no remote (§1.1), so "off the current tip" is the only well-defined
     instruction. Branching off a named branch would either fail or silently fork from
     something the author is not working on. This repo's line of work is `devin-cli`.
   - **Re-check the tip in the extension repo at the time you branch.** It is a separate
     working tree that moves independently; `0916254` is its tip as of this writing, and
     `PLAN.md` elsewhere in this document cites that revision's line numbers.

   Everything below happens on that branch. Do not commit plan work to the pre-existing
   branches, and do not merge either branch until Phase 4 (this repo) and Phase 5 (the
   extension) are both green - the wire protocol is only stable once §6 has shipped on one
   side and been consumed on the other.

1. **Phase 0** - retire the local fuzz harness, then capture Baseline A.
   - **Done during planning:** the untracked `.fuzz/` directory (a stale fuzz harness, two
     corpora, two result files) is deleted and its `.gitignore` entry removed. Its one
     capability that `tools/golden.py` lacked - cross-checking extracted segment command
     names against shfmt's own output - is **ported** into `capture()` as the
     `ground_truth` section. The `bash -n` pre-validation is deliberately not ported: it
     would add a shell dependency the harness does not have.
   - `ground_truth` records `{"missing": [...], "empty": <count>}` per command. It is a
     **fingerprint, not an assertion** - a variable assignment legitimately yields an
     empty-command segment (`x=1` -> command `''`), so a pass/fail check would be red on a
     correct run. Its value is that a regression in extraction moves the numbers even when
     every other section is untouched.
   - The comparison is a **multiset** (`Counter`), not a set: `echo a; echo b` is two
     `echo` commands, and dropping one is a real extraction bug a set comparison cannot see.
   - **The port needed a correction, and that is the instructive part.** Copied verbatim,
     the old harness read a literal with `p["Lit"]`; shfmt v3.14 encodes the text under
     `"Value"` (`"Lit"` is the node *Type*). The result was a function returning `[]` for
     every command - a section that is silently vacuous, reporting "0 missing" while
     checking nothing. It is in the tree because it was never run. So the port is only
     trustworthy once it has been **proved to fire**: injecting a one-line regression into
     `parse_segments` must make `missing` non-empty. It does - dropping the last segment
     reports `missing: ['grep']` for `ls -la | grep txt` and `missing: ['echo']` for
     `echo a; echo b`. Against unmodified code the result is `missing: []` across all 126
     parseable commands, which is a real finding: extraction is complete against shfmt's
     own view.
   - **Ordering is load-bearing: this lands before Baseline A is captured.** 3.2's rule is
     that any difference not enumerated for a phase is a bug, so a new fingerprint key
     appearing *after* A would show up in every later compare as an unauthorised diff and
     trip "stop and diagnose" on Phase 1 for a change that was intended.
   - Accepted loss, recorded so it is not read as an oversight: the two command corpora
     (`corpus2.txt`, `corpus3.txt`, ~10 kB) went with the directory and are **not** folded
     into `COMMANDS`. Re-adding coverage from them is a follow-up, not a prerequisite.
2. **Phase 1** - delete `_REPLACED_KEYS`, enforce the vocabulary. Self-contained. Gate:
   diff vs A is exactly 3.2; capture Baseline B. **Start with 4.0** - the namespace fix
   is a prerequisite and is a one-line round trip to verify.
3. **Phase 2** - extract `resolve_bash_config` and `decide_bash_command`, with the
   `deny`/`block` translation at the seam (5.2, D12) and the truthiness test preserved
   (5.1). Gate vs B is 3.1; capture Baseline C.
4. **Phase 3** - the server + `--test`, including `--mode` (6.4b) and the `shfmt` probe in
   `validate` (6.3). Gate vs C is `IDENTICAL`, which per 3.1 only proves the library was not
   perturbed; the real gate is Phase 4's tests.
5. **Phase 4** - Python tests and docs, **including `tests/test_protocol_e2e.py`** (§7) -
   the only layer the other two passes found was untested. Full gate green. **This is where
   Phase 3 is actually verified.**
6. **Phase 5** - the TS extension, once the protocol is stable. See 8.1 for the timeout
   policy (D13) and the corrected concurrency premise before writing `server.ts`. **Do the
   `doom_loop` / non-bash level validation in 8.4 in the same commit as the 8.3 rename** -
   the rename is what deletes it, so splitting them is how it gets lost.

**Before Phase 5's README is written:** the repository needs a git remote, or the
install URL in 8.9b does not resolve. This is not a code task and it is easy to
forget precisely because everything else in Phase 5 is a code task.

Phases 1-4 are one repo and one reviewable change. Every pre-existing test stays green
throughout.

---

## 10. Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| The `effective_bash` split silently changes a verdict | Baselines A/B/C with per-phase gates (3.1); a pinning unit test; 5.4 requires the `{**bash}` spread be preserved; 5.1 pins the truthiness test so the split cannot widen `{}`'s branch |
| Phase 1's expected diff masks an unintended one | The two allowed rows are enumerated (3.2); review the whole diff, not a spot check |
| **The vocabulary rejects `"*"`** | 4.0 resolves the `wildcard`/`*` namespace split in `policy.py`; dedicated round-trip test in 4.2 item 1; message asserted to list `*` and not `wildcard` |
| **A `deny` forwarded to Devin becomes a `None` and the command runs** | D12: `decide.py` returns `deny`, `hook.py` translates at the seam; both sides of the translation pinned by tests (5.2) |
| A `reasons` key in `decide_bash_command` breaks Devin's contract | `process_hook_event` drops it (5.2) rather than forwarding; pinned by `test_hook.py:194`, which is the one test that actually breaks |
| **The `reasons` gate rejects correct output** | 5.3 uses the four-path rule (`join` must equal `reason` only when the list is non-empty; no `ask`/`deny` may be empty), not "`join` always equals `reason`"; the naive form fails on 303 correct `allow` entries |
| **The `error` policy is unreachable when the config is un-resolved** | 5.2 gives `decide_bash_command` a `top_level_wildcard` and resolves before evaluating; pinned by an "unparseable command on `{"*": "allow"}` is not `ask`" test |
| **D6's mode-level `*` cannot cross the wire** | 6.3 adds `top_level` to the `evaluate` request; 8.3 forbids splicing the resolved level into the block; round-trip test in §7 |
| **A timed-out request's response is read as the next request's answer** | D13: a timeout kills and respawns the child, so the stale line can never be written; explicitly tested in 8.8 |
| Protocol skew between the two repos | `protocol: 1` in the `validate` response, asserted at handshake |
| A concurrent sibling call corrupts the JSONL stream | Promise queue in the TS client (8.1); one-response-per-request tested server-side |
| **`callHistory`/`answerCache` are only safe because pi preflights serially** | Documented next to the state in 8.1 and 8.7; the queue is kept as insurance |
| Block-buffered stdout makes the server look hung | Explicit `flush=True` on every response, and before `sys.exit` (6.5) |
| `/reload` orphans Python processes | `session_shutdown` handler, registered idempotent (8.1) |
| A spawn left in the extension factory violates the pi contract | pi docs, "Long-lived resources and shutdown" (`docs/extensions.md:220-222` at 0.84.3); spawn in `session_start` only (8.1) |
| **Pi doc line numbers rot across versions** | 8.1 cites by heading + version, never by bare line; `extensions.md:766` is already wrong at 0.84.4 and the file is 215 lines at 0.87.1 |
| **Dropping the npm dep breaks 4 more files than `package.json`** | 8.4b names all five importers and defines the two types locally |
| **`--test` on a mode-wrapped file evaluates an empty policy** | 6.4b adds `--mode`; a mode with no `bash` block is a hard error, never an empty policy |
| **A missing `protocol` field silently disables skew detection** | 6.3 puts it on every response line; asserted at handshake, tested |
| **The documented install does not exist** (no PyPI, no remote) | 8.9b: `pipx install git+<url>`, remote added as a stated prerequisite, actionable failure message in 8.10 |
| **A failed install looks like a permissions bug** (D8 blocks all bash) | 8.10's message names the install command and states that blocking is the expected consequence |
| TS and Python disagree on who formats a bullet | Ownership split stated in 8.2b |
| A strict `ToolConfig` rejects a working config | 0 users; the accepted cost of D3/D5 |
| **A missing `shfmt` silently allows everything** | 6.3: `validate` probes `find_shfmt()` at `session_start` and reports it, so it lands in the D8 sticky-unhealthy path. It is **not** caught by process health - the server runs fine and only the per-command `error` policy responds |
| A hung shfmt holds the serialized queue | Bounded at **10 s** by the client timeout (8.1), which kills and respawns; `parser.py:69`'s 30 s ceiling is therefore **unreachable** from the Pi path and applies only to the Devin half. `ctx.signal` cancels earlier on a turn abort |
| `shfmt` unfindable under pipx | `shfmt-py` drops a bare Go binary in the venv's `bin/`, and `find_shfmt` checks `sys.executable`'s parent - which *is* that `bin/`. Verify the positive case in the e2e test (§7) |
| **Windows is unsupported, and an unfindable shfmt there is silent** | **Decided: POSIX-only, declared as such in both READMEs** (6.3). `find_shfmt` searches only `bin/` and the bare name (`parser.py:120-125`), so a Windows pipx venv's `Scripts/` is invisible. The `validate` probe makes the failure loud rather than an `allow`-everything, and the README says so explicitly - an omitted platform is the defect, not an absent one |
| Windows spawn | TS owns all paths, so Python needs no `%APPDATA%` handling (unlike the Devin half). Confirm the spawn path works without a POSIX shell. |
| A typo'd non-bash / `doom_loop` level is unvalidated | 8.4 replaces `permissionLevelSchema` with a local three-value check over the whole mode; 8.3 flags that the rename deletes it; 8.8 tests it. Without this, a "mechanical" rename reintroduces the exact `permission` defect Phase 1 eliminates |
| A seam defect slips through because nothing tests the boundary | `tests/test_protocol_e2e.py` (§7) drives the real subprocess over a real pipe - the layer where #10, #12 and #13 all lived |

---

## 11. Open questions

**None outstanding.** Every question raised during planning has been resolved and folded
into the phases above:

- the answer cache - settled in 8.3 (it stays; the `permission` -> `*` rename is the only
  change), 8.7 and 8.1 (its invalidation points, and the serial-preflight dependency)
- `--test` ergonomics - settled in 6.4: a bare path read as-is, stdin as fallback
- binary resolution - settled in 8.10: config, then `LOVELY_PI_BASH_PERMISSIONS_BIN`, then
  `PATH`, with an actionable failure message
- config ownership, transport, back-compat, the npm dependency, the unknown-key rule, the
  level fallback chain, mode-wildcard semantics, failure posture, and CLI surface - all
  settled in section 2
- the vocabulary's namespace (`*` vs `wildcard`) - settled in 4.0 / D11
- the `deny` vs `block` vocabulary split across the seam - settled in 5.2 / D12
- stale responses after a client timeout - settled in 8.1 / D13
- `{}` vs `None` in the effective-config split - settled in 5.1 (truthiness, not `is not None`)
- a missing `shfmt` binary - settled in 6.3 (`validate` probes it; D8 covers the process, not the binary)
- validation of non-bash / `doom_loop` levels - settled in 8.4 / 8.8, since the Python `validate` op covers bash only
- Windows `find_shfmt` - **decided: POSIX-only**, declared as unsupported in both READMEs (6.3)
- the client's per-request timeout - **decided: 10 s**, from measured bounds rather than taste (8.1)
- where baselines live - **decided: `/tmp`**, regenerable in ~28 s; the shfmt-version label is printed at capture (3)
- `--test` exit codes - **decided: 0 verdict / 2 deny / 1 no verdict**, matching `devin_cli.py` (6.4)
- which channel carries a server failure - **decided: protocol primary, bounded stderr tail only for pre-handshake crashes, tail to the `session_start` notification** (6.5)
- startup failure wording - **decided: all four specified** in the section owning each failure (6.3, 8.4, 8.10)

### 11.1 Corrections from the two-repo re-assessment

Five defects were found by re-reading both repos against this plan and are now folded in.
Recorded here because each one was a *silent* failure - none would have surfaced as a
loud error:

| # | Was | Now | Severity |
| --- | --- | --- | --- |
| 1 | Phase 1 built its valid-key set from the field-name vocabulary, rejecting `"*"` | 4.0 fixes the namespace in `policy.py`; D11 | Total feature failure: every level-setting block rejected |
| 2 | `decide_bash_command` returns `deny`, forwarded verbatim to Devin | 5.2 translates at the seam; D12 | Fail-open: a denied command runs |
| 3 | "per-request timeout" with no request ids | 8.1 kills and respawns; D13 | Silent misattribution: a command evaluated against another's verdict |
| 4 | `--test` accepted the three Pi config locations | 6.4 reads a path as-is | Contradicted 6.2/D1; would have debugged a config never in force |
| 5 | Concurrency justified by a misreading of `docs/extensions.md:766` | 8.1 corrected; the real invariant is now documented | Wrong reasoning hid a real latent coupling |
| 6 | `package.json` dep dropped, but 4 other files still import it | 8.4b defines the types locally; `BaseToolConfig` loses its `Pick<>` | Build failure at step 1 of Phase 5 |
| 7 | `--test` example pointed at a mode-wrapped Pi config | 6.4b adds `--mode`; absent `bash` block is an error | Confident wrong answer: `ask` for everything |
| 8 | `protocol: 1` required in prose, absent from the example | 6.3 puts it on every response line | Skew detection silently dropped |
| 9 | README told to document a PyPI install that 404s | 8.9b: `pipx install git+<url>`, remote as prerequisite | Fail-closed design makes a setup error look like a policy bug |

Findings 1-3, 6 and 9 were all reachable only by cross-checking the plan against the
code; a review of the plan alone would not have caught any of them.

### 11.2 Corrections from the execution-based re-assessment

A second pass, which **ran** the code the plan describes rather than reading it, found four
more. They are recorded separately because the method is the point: every one of these was
invisible to reading, and three of them were only found by executing a §12-style check that
the plan itself mandates.

| # | Was | Now | Severity |
| --- | --- | --- | --- |
| 10 | 3.1's row B required `commands` to be `IDENTICAL` while 5.3 required it to gain `reasons` | 3.1 now names the correct section; the two gates are compatible | Self-blocking: the implementer halts on the diff the plan mandates |
| 11 | 5.3's gate said `"; ".join(reasons) == reason` | 5.3 uses the four-path rule: the equality holds only when the list is non-empty | Rejects correct output on 303 `allow` entries, sending the implementer to mutate `reason` |
| 12 | `decide_bash_command(command, config)` with no top-level wildcard | 5.2 adds `top_level_wildcard` and resolves before evaluating | `error` policy unreachable: shfmt failure on `{"*": "allow"}` becomes `ask` |
| 13 | 6.3's request carried no top-level wildcard | 6.3 adds `top_level`; 8.3 forbids splicing it into the block | D6 broken at the seam: a mode-level `allow` arrives as `ask` |

### 11.3 Corrections from the third pass (packaging, validation and the boundary)

A third pass looked where the first two had not: what the install actually puts on disk, what
validation the rename would delete, and which layer of the system had no test at all.

| # | Was | Now | Severity |
| --- | --- | --- | --- |
| 14 | 8.3 renames `permission` -> `'*'`; 8.4 drops `permissionLevelSchema` | 8.3 flags the coupling, 8.4 names the replacement check, 8.8 tests it | **Reintroduces the plan's own founding defect**: a `doom_loop` level typo becomes a silent no-op, in the one key no fingerprint sees |
| 15 | A missing `shfmt` treated as a `verify during Phase 3` footnote | 6.3 has `validate` probe `find_shfmt()` at `session_start` | **Silent fail-open**: the process is healthy, so D8 never fires; every command routes to the `error` policy, i.e. `allow` under `{"*": "allow"}` |
| 16 | 5.1 gave a signature with no body | 5.1 pins the truthiness test | `if raw_bash is not None:` would spread `{}` and change golden variant `1\|ask` - drift caused by the refactor meant to prevent it |
| 17 | No test anywhere crossed the repo boundary | `tests/test_protocol_e2e.py` (§7) | 3 of 4 defects in §11.2 were seam defects; the one untested layer is the one that keeps breaking |

Two further defects were found in the code itself, while retiring an untracked local fuzz
harness, and are numbered here so the plan's own list stays contiguous:

| # | Was | Now | Severity |
| --- | --- | --- | --- |
| 21 | `.fuzz/harness.py` read a shfmt literal as `p["Lit"]`; v3.14 uses `"Value"` | `ground_truth` in `capture()` uses `"Value"`, and the port is required to be proved to fire (§9 step 1) | The check returned `[]` for every command and reported a confident `missing: []` while checking nothing - a vacuous oracle, in the tree only because it was never run |
| 22 | `.fuzz/security_results.json` recorded 3 of 42 probes as `expected != got` | All three re-run against current code: all were probe-expectation errors, **zero real bypasses** | Not a product defect, but a stale harness reporting phantom mismatches sends the next person chasing three non-bugs |

On 22, the one that looked alarming - `(( x[$(rm -rf x)] ))` recorded as `allow` - is in
fact gated: the evaluator classifies the construct correctly and applies
`command_substitution`, not `subshell`. The probe asserted the wrong governing key. That
distinction is the reason `.fuzz/` was deleted rather than kept: an unmaintained harness
whose recorded failures are all wrong is worse than no harness, because the failures look
actionable.

Finding 14 is the one worth dwelling on, because it is the plan's own thesis turned against
it. `policy.py`'s docstring records that "`ToolConfig.permission` was a declared config field
with no reader anywhere in the product: it validated cleanly, changed no verdict, and nobody
noticed." A typo'd `doom_loop` level is that same defect, one phase later, reintroduced by
the very rename Phase 5 performs - and it is *harder* to notice, because Python has no
`doom_loop` at all, so no fingerprint in this repo can ever catch it. The validation is
TS-side, three lines long, and about to be deleted by a dependency removal. The check that
existed only as a side effect of an import.

Findings 14 and 15 share a shape worth naming: **both are cases where removing something
that was accidentally load-bearing creates a silent hole.** 14 removes a validator that
arrived via a dropped import; 15 is the absence of a check that D8's health model does not
cover, because a missing binary is not a crash. Neither would raise a type error or a
failing test - the compiler is silent and the suite is green.

**A fourth instance, found while porting rather than planning, and the purest one.** The
fuzz harness that `.fuzz/` deletion retired had a ground-truth check for segment
extraction - the one capability `golden.py` lacked. Ported *verbatim* into `capture()`, it
read a shfmt literal with `p["Lit"]`; shfmt v3.14 puts the text under `"Value"` (`"Lit"` is
the node `Type`, mapped in `converter.py:831`). So the ported function returned `[]` for
every command and the new `ground_truth` section reported a clean, confident
`missing: []` - **while checking nothing at all**. It is in the tree because nobody ran it:
it was untracked, gitignored, and ten days stale, and its own recorded "mismatches" were
probe-expectation errors (finding 21 below) rather than product bugs.

Nothing about that failure is subtle once described, and nothing would have caught it. It
is not a type error - the file is outside the lint and mypy gates (`tools/` is in
`extend-exclude`) - not a test failure, because there was no test - and not a diff, because
the section was new. The only thing that catches it is **deliberately breaking the thing
and watching the check go red**, which is why the port is now specified that way in §9
step 1 and must stay that way. A check that has never been seen to fail is not evidence.

**The pattern across all three passes.** Twelve defects in the plan, plus finding 21 in the
code it was ported from, and the ones that were most expensive were consistently the ones
that produced *no* error. What separates the sections that came out right from the ones
that came out wrong is whether the claim was executed: 4.0, 3.2 and 6.4b reproduced exactly
as predicted; 10, 11, 13, 15 and 16 did not. The conclusion is not "write more carefully" -
it is that **any sentence in this plan asserting a runtime behaviour is a test that has not
been written yet**, which is what §12 says and why §7 now has a file whose only job is to
cross the boundary. Finding 21 sharpens it further: a *test* asserting a runtime behaviour
is not enough either, if nobody has watched it fail.

Plus corrections of fact rather than design: §1.3's table overstated the schema gap (bash
already reads `['*']`; `blocked_paths_regex` is already `!isBash`-gated - the README is the
defect, and it is worse than the table said, because zod's `$strip` drops `"permission"`
silently and locks the user out); §8.4b omitted `bash-evaluation.ts` and listed a
`PermissionLevel` import that does not exist; six line citations were off by 1-2, and
`test_hook_ux_format.py:85` was wrongly credited with positional reads; pi's
`docs/extensions.md` line numbers are now cited by heading, since `:766` is already wrong
one minor version out.

**The pattern held on the second pass too.** Defects 10-13 are not worked examples this
time - they are *specifications*. 11 is a verification step that fails on correct code; 12
and 13 are two halves of the same omission, in different files, that neither mentions. Both
halves are invisible to a review that reads each section on its own.

If implementation surfaces a genuine fork, it goes here rather than being decided
silently mid-phase.

---

## 12. Completion criteria

A step is complete when:

- the change is implemented
- all tests pass (new and existing)
- the phase's golden gate from 3.1 is met, and the baseline for the next phase is captured
- `mypy --strict` and `ruff` are clean
- `docs/ARCHITECTURE.md` and the relevant README are updated in the same commit
- **every example, command, and quoted output in this plan that names a path, a key, a
  message, or a URL has been executed and its output checked against the claim beside
  it.** Three of the nine defects in 11.1 were exactly this failure — prose that read
  correctly and produced a confident wrong answer when run. "Document the install as a
  PyPI package" is such a sentence; `pip index` is not.
- **the plan is updated to match what was built.** Where implementation turned out
  differently, the reason is recorded here or in the phase that changed — otherwise the
  next reader inherits a plan that is confidently wrong in a new way.
