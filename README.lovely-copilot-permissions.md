# lovely-copilot-permissions

A local GitHub Copilot CLI hook for evaluating Bash tool calls with Lovely Bash
Permissions. Lovely policies can be layered globally, per repository, and in a
private local override. Persisted Copilot command approvals are imported only
for the active Copilot permission location.

## Install

This package is not published to PyPI. Install it from source with `pipx` so the
`lovely-copilot-permissions` executable is available on `PATH` to Copilot's
user-level hook:

```bash
pipx install git+https://github.com/jftlo/lovely-bash-permissions
```

Check that the command is available:

```bash
lovely-copilot-permissions --help
```

## Register the user-level hook

Create a JSON file under `~/.copilot/hooks/`. If `COPILOT_HOME` is set, use
`$COPILOT_HOME/hooks/` instead. For example, save this as
`lovely-bash-permissions.json`:

```json
{
  "version": 1,
  "hooks": {
    "preToolUse": [
      {
        "type": "command",
        "matcher": "^bash$",
        "exec": "lovely-copilot-permissions"
      }
    ]
  }
}
```

This direct `exec` form calls the executable on `PATH` without shell parsing.
The user-level registration applies across local repositories. Restart Copilot
CLI after changing hook files. Registration is manual: there is no setup command
and the hook does not modify Copilot configuration.

The hook accepts Copilot's camelCase `preToolUse` payload. It handles only
`toolName: "bash"` and accepts `toolArgs` either as an object or as a
JSON-encoded object. Other tools are left to Copilot without a decision.

## Decisions and output

Each Bash command is evaluated by Lovely's shared Bash decision engine. The
`allow`, `ask`, and `deny` policy verdicts map to Copilot's matching
`permissionDecision`; `ask` is explicit. For every verdict the hook writes one
progress JSON line and then exactly one final decision JSON object:

```json
{"type":"progress","message":"Lovely policy: deny — command matches a blocked rule"}
{"permissionDecision":"deny","permissionDecisionReason":"command matches a blocked rule"}
```

Copilot displays the progress message in the timeline and strips it from the
hook result. The final response includes `permissionDecisionReason` for `ask`
and `deny`, but not for `allow`; Lovely does not rewrite the Bash command.

Every handled verdict exits successfully, including `deny`. The JSON carries
the policy result. An invocation failure that produces no verdict exits
nonzero. Malformed input and missing or non-string commands produce an explicit
denial. An empty command is evaluated through the configured `error` policy.

## Preview a decision

Run `--test COMMAND` to print the final Copilot decision JSON without starting a
Copilot session or emitting timeline progress:

```bash
lovely-copilot-permissions --test 'git status'
```

Test mode uses the current working directory as its policy context and loads the
same Lovely policy files and saved Copilot command approvals as hook mode. For
example, to preview the policy for a repository, run the command from that
checkout. An empty command is still evaluated by Lovely's configured `error`
policy:

```bash
lovely-copilot-permissions --test ''
```

Allow, ask, and deny decisions all exit with status 0; the JSON contains the
verdict. Invalid invocations that produce no decision, such as omitting the
command, exit nonzero.

## Lovely policy files

Copilot policies use a separate namespace from Devin's policies. The CLI merges
these files from lowest to highest precedence:

| Scope | Location |
| --- | --- |
| Global | `$COPILOT_HOME/lovely-permissions.jsonc` (default `~/.copilot/lovely-permissions.jsonc`) |
| Shared project | `<checkout>/.github/copilot/lovely-permissions.jsonc` |
| Personal local | `<checkout>/.github/copilot/lovely-permissions.local.jsonc` |

For hook events, the project is selected using Copilot's event `cwd`, not the
hook process's current directory. In a Git checkout, Lovely uses the active
checkout root (including a linked worktree); outside a checkout, it uses the
normalized event directory. The event `cwd` must be an existing absolute
directory. A missing or invalid value produces a denial rather than silently
using the hook process's directory.

Policy objects merge recursively, arrays concatenate, and later scalar values
override earlier values. Every present file must be readable, valid JSONC, and
valid under Lovely's policy schema; one invalid source denies even if another
source is valid. Missing files are ignored. If all three are missing, Lovely
asks by default.

The local override is private and should be ignored by version control. For
example, add this to the repository's `.gitignore`:

```gitignore
.github/copilot/lovely-permissions.local.jsonc
```

Each file uses Lovely's standard policy schema. For example:

```jsonc
{
  "*": "ask",
  "bash": {
    "*": "ask",
    "error": "ask",
    "allowed_cmds_regex": ["^git status$"],
    "blocked_cmds_regex": ["\\.env$"]
  }
}
```

See the [Devin guide](README.lovely-devin-permissions.md#configuration-files)
for policy keys and regex guidance; Copilot uses the same Lovely schema and
decision engine, but not Devin's host protocol or configuration files.

## Copilot saved command approvals

The hook reads persisted approvals from
`$COPILOT_HOME/permissions-config.json` (default:
`~/.copilot/permissions-config.json`). If Copilot is launched with the legacy
`--config-dir` option, set `COPILOT_HOME` for the hook process to that same
directory so it reads Copilot's saved approvals.

Only `tool_approvals` entries with `kind: "commands"` are imported, and only
from the location matching the event's `cwd`. Repository approvals use the Git
checkout root; linked worktrees use their main repository root; submodules use
their own checkout root; and directories outside Git use the normalized event
directory. Other approval kinds and transient Copilot grants are ignored.

An identifier without a wildcard (for example, `git status`) matches the full
executed command exactly. An identifier ending in `:*` (for example, `git:*`)
matches that command itself or that command followed by arguments. Lovely
checks saved approvals against each parsed command segment, so a saved approval
for one part of a compound Bash command does not approve its other parts.
Lovely's explicit deny rules always take precedence over imported approvals.

If `permissions-config.json` is missing, no saved approvals are added and no
warning is emitted. If the existing file cannot be read or is malformed, the
hook writes a warning to stderr and imports no approvals from it.

## Scope and limitations

- Initial support is for local Copilot CLI sessions on Linux and macOS.
- Copilot cloud-agent support is not included; a local user hook and executable
  are not deployed to cloud-agent jobs.
- Only the `preToolUse` Bash tool is handled. Other tools and hook events are
  outside this integration.
- There is no `--setup` or `--show-config` mode; configure the hook manually as
  shown above.
- The hook uses Copilot's default 30-second timeout. The shared parser also has
  a 30-second `shfmt` timeout, so a slow parse can race Copilot's outer timeout.
  Copilot treats nonzero hook exits as denial, while a hook timeout fails open
  to its normal permission flow.
