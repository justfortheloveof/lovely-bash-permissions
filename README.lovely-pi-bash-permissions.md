# lovely-pi-bash-permissions

The bash permission engine behind [`lovely-pi-permissions`](https://github.com/jftlo/lovely-pi-permissions),
a Pi coding-agent extension. This CLI evaluates bash commands; the extension
gates its `bash` tool calls through this one.

The two names are distinct and are never used interchangeably:

| | Where | What it is |
| --- | --- | --- |
| **`lovely-pi-permissions`** | a separate repository, TypeScript | the Pi extension — the *client* |
| **`lovely-pi-bash-permissions`** | this repository, Python | this CLI — the *server* |

The extension owns config discovery, deep-merge, mode selection, the ask prompt,
doom-loop detection, and status-bar sync. This process owns exactly one thing:
given a bash command and a resolved policy, decide `allow` / `ask` / `deny` and
say why.

> [!WARNING]
> NO GUARANTEE OF SAFETY - USE AT YOUR OWN RISK

## Install

This package is **not published to PyPI**. Install it from source, and prefer
`pipx` over `pip`: the package depends on `pydantic` and `shfmt-py`, and a
global `pip install` of it into a user's environment is intrusive at best.

```bash
pipx install git+https://github.com/justfortheloveof/lovely-bash-permissions
```

Or, for development:

```bash
git clone https://github.com/justfortheloveof/lovely-bash-permissions
cd lovely-bash-permissions && pip install -e .
```

Verify:

```bash
lovely-pi-bash-permissions --help
```

> [!IMPORTANT]
> **If `lovely-bash-permissions` is already installed but `lovely-pi-bash-permissions` is not, you have an
> older version** — the Pi console script was added later, and there are no
> releases to be behind. Reinstall from source as above. The two failures look
> identical from the outside and have opposite fixes.

### POSIX only

This is a POSIX-only product, and that is a decision rather than an oversight.
`find_shfmt` looks for the shfmt binary in a venv's `bin/` and on `PATH`; a
Windows pipx venv puts it in `Scripts/`, which nothing here searches. Rather than
half-support it, `validate` probes for the binary and reports it — so on Windows an
unfindable shfmt **blocks all bash** (see [Failure modes](#failure-modes)) rather
than silently allowing everything. If Windows support is ever wanted it is a small
change: add `Scripts/` and a `.exe` suffix to the candidate lists, plus a re-run of
the e2e test on that platform.

## The wire protocol

One JSON object on stdin, one JSON object on stdout, then exit. The client
spawns this binary per call, so there is no stream and nothing to keep aligned:
the exchange is one request against one response by construction.

All of stdin is read, not one line. A client that somehow sent two requests gets
one honest parse error instead of an answer to the first and silence about the
second — which is the whole class of misalignment a stream allowed and one
process per call cannot.

`op` is a discriminator, not a leftover of the stream framing. There are two
operations, and the client has to say which: `evaluate` for a verdict, and
`validate` to ask whether a config is usable at all — which is also how the
extension probes for shfmt at `session_start`.

```jsonc
// request
{"op": "evaluate", "command": "git status", "config": { /* the bash block */ }, "top_level": "allow"}
{"op": "validate", "config": { /* the bash block */ }}

// response
{"protocol": 1, "action": "allow", "reason": "...", "reasons": ["...", "..."]}
{"protocol": 1, "valid": true}
{"protocol": 1, "valid": false, "error": "unknown bash config key 'x'; valid keys are ..."}
```

`protocol` is on **every** response, not just `validate`, so the client can
assert it on the first exchange it sees whichever op it sent. A missing or
non-`1` value is a handshake failure, reported at `session_start` — never a
per-command error.

Only protocol lines go to stdout. Diagnostics go to stderr, which carries one
thing: a crash before or during the handshake, where no protocol line was ever
written. A traceback never enters a block reason — that string goes into the
model's context on every blocked command and would leak absolute paths into the
conversation.

### `evaluate`

Required fields: `command` (string), `config` (a bash block), `top_level`.

`top_level` carries the **mode's** wildcard, and it is required for a reason
that is not obvious: a bash block that declares no `"*"` of its own cannot
express "this mode says allow" to a process that never saw the mode.

```jsonc
{"allowed_cmds_regex": ["^ls"]}  with top_level "allow"  ->  "ls" is not allowlisted, so the
                                                            wildcard decides: allow
{"allowed_cmds_regex": ["^ls"]}  with no top_level       ->  "ask"
```

The block is sent **verbatim, exactly as the file declares it**. Do not splice a
resolved `"*"` into it: that works numerically and is wrong in substance, because
`validate` would then check a config that differs from the one on disk and a user
reading its error would be chasing a key they never typed.

An invalid config answers `{"action": "deny", ...}` rather than an error object.
The client blocks either way, and a verdict shape it already understands is one
fewer thing to get wrong at the seam. An unvalidated policy is never evaluated.

### `validate`

`{"op": "validate", "config": {...}}` returns `{"protocol": 1, "valid": true}` or
`{"valid": false, "error": ...}`. It exists so config errors surface at
`session_start` — on the status bar — rather than on the first command.

`validate` covers **the bash block only**. The extension's non-bash tools
(`read`, `write`, `edit`, `grep`, `find`, `ls`, custom tools) and `doom_loop`
never reach this process, so the TypeScript-side level check is their *only*
validation. It is not redundant with `validate`, and dropping it because "the
server already covers it" would silently un-validate every non-bash level.

The error text is Python's, unmodified, and it is a contract: it names the key
that is wrong and lists the keys that are right. The extension prefixes the mode
and the file it came from, because this process has no idea which of five files
produced it.

## The bash config schema

A `bash` block, in full. It is exactly the same schema the Devin half uses, which
is the point — one vocabulary, one implementation, two hosts.

| Key | Meaning |
| --- | --- |
| `*` | default level for this tool; anything below inherits it |
| `error` | level applied when a command cannot be analysed at all (parse failure, missing shfmt) |
| `allowed_cmds_regex` | allow commands matching any of these regexes |
| `blocked_cmds_regex` | deny commands matching any of these regexes |
| `output_redirection` | a level, or an object keyed by redirection kind |
| `input_redirection` | level for `< f`, `<< heredoc` |
| `background_execution` | level for `cmd &` |
| `command_substitution` | level for `$(...)` and backticks |
| `process_substitution` | level for `<(...)` / `>(...)` |
| `subshell` | level for `( ... )` groups |
| `variable_assignment` | level for `FOO=bar cmd` |

Every level is one of `allow`, `ask`, `deny`.

`output_redirection` takes either a bare level or an object over `*`,
`stdout_to_dev_null`, `stderr_to_dev_null`, `stderr_to_stdout` and `other`. `other`
is a named kind, not another name for `*`: given `ls > /dev/null 2> /tmp/f`,
`{"stdout_to_dev_null": "allow", "other": "allow"}` permits both redirections
while `{"stdout_to_dev_null": "allow", "*": "deny"}` does not.

**Any other key is a hard error.** There is no back-compat and no warning path:

```jsonc
{"bash": {"permission": "allow"}}
```

```
unknown bash config key 'permission'; valid keys are '*', 'allowed_cmds_regex', ...
```

A key this process cannot read must not validate. `permission` was the one that
survived longest: it looked like it set the tool's default level, nothing
consulted it, and it changed no verdict — while the wildcard quietly decided the
real outcome. A key that reads as "configured" while governing nothing is worse
than a typo, because nothing about it looks wrong.

Note that `blocked_paths_regex` — which the extension documents for non-bash
tools — is **not** a bash key. Under `bash` it is rejected like any other unknown
key. Path blocking for bash is `blocked_cmds_regex`.

## The level fallback chain (D6)

A tool's level is resolved in this order, and each step is a real config key:

```
bash block's "*"  ->  the mode's "*"  ->  "ask"
```

The mode-level `"*"` supplies levels to already-active tools. It **never
activates a tool**: a tool absent from the mode is unreachable even when the mode
is `"*": "allow"`. That is the fail-closed direction, and it is what stops a
wildcard from silently re-enabling a tool that was deliberately left out.

`doom_loop` is not a tool — it is a config key with its own level, and it is
never "activated" because there is no tool of that name to activate.

## `--test`

Evaluate one command against one config and exit. A developer tool, not part of
the protocol.

```bash
lovely-pi-bash-permissions --test "git status" .pi/lovely-permissions.jsonc
lovely-pi-bash-permissions --test --mode strict "git status" ~/.pi/agent/lovely-permissions.jsonc
echo '{"*": "ask", "allowed_cmds_regex": ["^git\\s"]}' | lovely-pi-bash-permissions --test "git status"
```

`--test` is a flag and the command is positional, which is what lets
`--test --mode strict "cmd"` parse at all.

**A path is read as given.** It is never located, never discovered, never merged.
Config resolution belongs to the extension; resolving Pi's three locations here
would put a second resolver in the tree, and it could not reproduce what the
extension uses anyway — the extension concatenates arrays and selects a mode
before this process ever sees a block, so a merge here would be a *different*
config from the one in force. Debugging a rejection against a policy that was
never in force is worse than no merge at all.

The one thing `--test` does that the server does not is accept a **mode-wrapped**
file, because every real Pi config file is one. A bare block would not fail
loudly — the root schema is permissive, so `bash` would come back absent, the
evaluator would run on an empty policy, and every command would resolve to `ask`.
That is indistinguishable from a correct pessimistic policy, so a mode with no
`bash` block is a hard error instead.

| Flag | Meaning |
| --- | --- |
| `--mode NAME` | which mode of a mode-wrapped config to use; defaults to the first, whose name is printed to stderr |
| *(none)* | read the config from stdin instead of a path |

### Exit codes

| Code | Meaning | Cases |
| --- | --- | --- |
| `0` | a verdict, non-denying | `allow` or `ask` |
| `2` | a verdict, denying | `deny` |
| `1` | **no verdict at all** | usage with no input; unreadable file; a file that is neither shape; a mode with no `bash` block; unknown `--mode`; an invalid config |

Without that middle row a script cannot tell *"the policy denies this"* from
*"I handed you the wrong file"* — which is the distinction a CI check needs most.
`2` for deny and `1` for no verdict matches `lovely-devin-permissions`, so the
two CLIs in this package agree.

## Failure modes

Every failure below ends with the same sentence, in the extension's message:

> All bash commands are blocked until this is fixed.

It is not padding. Blocking all bash is the *designed* behaviour when this
process is unusable, and without that sentence the user's first instinct is to
go looking for a misconfigured policy — a bug hunt for a setup error.

| Failure | What the user sees |
| --- | --- |
| binary not found | names the `pipx install` command, and distinguishes "not installed" from "an older `lovely-bash-permissions` that predates the Pi CLI" |
| protocol version mismatch | names the resolved path that answered and the version it speaks, because a user with both a `PATH` binary and a configured one needs to know which one replied |
| shfmt missing | names **shfmt-py**, the package that provides the binary — shfmt is not a separate install |
| config invalid | the mode and file it came from, then Python's message verbatim |

The shfmt case is the one that matters most on POSIX, because it is the only one
where the server is running *fine* and every command would otherwise be allowed.
A missing binary is not a crash: the process spawns, the handshake passes, and
every command then routes through the `error` policy — which is `allow` under
`{"*": "allow"}`. Health checks cannot see it, because the process is healthy.
`validate` probes for the binary explicitly for that reason.

## How the client finds this process

In preference order:

1. an explicit path in the extension config, if present
2. `LOVELY_PI_BASH_PERMISSIONS_BIN` in the environment
3. `lovely-pi-bash-permissions` on `PATH`

A miss blocks all bash by design, so the failure is discovered and reported at
`session_start` rather than on the first command.

## Development

```bash
uv sync
uv run pytest                 # the suite, including tests/test_protocol_e2e.py
uv run pytest -m linting      # ruff + mypy --strict
```

`tests/test_protocol_e2e.py` drives this CLI as a real subprocess over a real
pipe, asserting the framing invariant across turns. It exists because every
other test calls a function directly, and the layer nobody was testing is the
one that kept breaking: a missing `top_level` field, an un-resolved `error` key,
and a golden gate that named the wrong section were all invisible from either
repository alone.

## See also

- [`lovely-pi-permissions`](https://github.com/jftlo/lovely-pi-permissions) — the Pi extension (client)
- [`README.lovely-devin-permissions.md`](README.lovely-devin-permissions.md) — the Devin hook, which speaks the same policy vocabulary over a different protocol
- [`README.md`](README.md) — the underlying bash-AST library
