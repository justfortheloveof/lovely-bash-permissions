# lovely-copilot-permissions

A local GitHub Copilot CLI hook for evaluating Bash tool calls with Lovely Bash
Permissions. Lovely policies can be layered globally, per repository, and in a
private local override. Saved Copilot approvals are not imported yet.

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

## Scope and limitations

- Initial support is for local Copilot CLI sessions on Linux and macOS.
- Copilot cloud-agent support is not included; a local user hook and executable
  are not deployed to cloud-agent jobs.
- Only the `preToolUse` Bash tool is handled. Other tools and hook events are
  outside this integration.
- Copilot's saved command approvals are not imported in this version.
- There is no `--setup`, `--test`, or `--show-config` mode; configure the hook
  manually as shown above.
- The hook uses Copilot's default 30-second timeout. The shared parser also has
  a 30-second `shfmt` timeout, so a slow parse can race Copilot's outer timeout.
  Copilot treats nonzero hook exits as denial, while a hook timeout fails open
  to its normal permission flow.
