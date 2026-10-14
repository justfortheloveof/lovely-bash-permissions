# lovely-copilot-permissions

A local GitHub Copilot CLI hook for evaluating Bash tool calls with Lovely Bash
Permissions. The initial integration supports the global Lovely policy only;
repository and personal-local policy layers and saved Copilot approvals are not
imported yet.

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

## Global Lovely policy

The initial integration reads one policy file:

| Scope | Location |
| --- | --- |
| Global | `$COPILOT_HOME/lovely-permissions.jsonc` (default `~/.copilot/lovely-permissions.jsonc`) |

The file uses Lovely's standard policy schema. For example:

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

If the global policy is missing, Lovely asks by default. A present policy that
is unreadable, malformed, or invalid denies the command rather than being
ignored. Repository and personal-local policy layers are not supported by this
initial version.

## Scope and limitations

- Initial support is for local Copilot CLI sessions on Linux and macOS.
- Copilot cloud-agent support is not included; a local user hook and executable
  are not deployed to cloud-agent jobs.
- Only the `preToolUse` Bash tool is handled. Other tools and hook events are
  outside this integration.
- Copilot's saved command approvals are not imported in this initial version.
- There is no `--setup`, `--test`, or `--show-config` mode; configure the hook
  manually as shown above.
- The hook uses Copilot's default 30-second timeout. The shared parser also has
  a 30-second `shfmt` timeout, so a slow parse can race Copilot's outer timeout.
  Copilot treats nonzero hook exits as denial, while a hook timeout fails open
  to its normal permission flow.
