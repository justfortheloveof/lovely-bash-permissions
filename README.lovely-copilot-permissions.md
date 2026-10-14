# lovely-copilot-permissions

> **Planned integration:** this guide documents the agreed interface; the Copilot CLI is not available until its implementation lands.

A local GitHub Copilot CLI hook that evaluates Bash tool calls with Lovely Bash Permissions. It uses the shared Bash decision engine, but Copilot has its own hook protocol, saved approvals, and Lovely policy locations.

## Install

This package is not published to PyPI. Install it from source with `pipx` so the `lovely-copilot-permissions` executable is available on `PATH` to a user-level hook:

```bash
pipx install git+https://github.com/jftlo/lovely-bash-permissions
```

Verify the command is available:

```bash
lovely-copilot-permissions --help
```

## Register the user-level hook

Create a JSON file under `~/.copilot/hooks/`. If `COPILOT_HOME` is set, use `$COPILOT_HOME/hooks/` instead. For example, save this as `lovely-bash-permissions.json`:

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

The direct `exec` form avoids shell parsing and expects the executable on `PATH`. This is a user-level hook, so it applies to local Copilot CLI sessions across repositories. Restart Copilot CLI after changing hook files. There is no `--setup` command; hook registration is manual.

The hook uses Copilot’s native camelCase `preToolUse` payload and matches only the `bash` tool. It accepts `toolArgs` as either an object or a JSON-encoded object, then requires a string `command`. Other tools are untouched.

## Decisions and output

The hook evaluates each Bash command using Lovely’s `allow`, `ask`, or `deny` policy verdict and returns Copilot’s matching `permissionDecision`. An `ask` is explicit: interactive Copilot can prompt, while Copilot autopilot treats it as a denial.

For every verdict, the hook first writes one persistent progress object to stdout, then one final decision object. Copilot strips progress objects from the hook result and displays them in the timeline; progress is display-only and does not enter the model’s context.

```json
{"type":"progress","message":"Lovely policy: deny — command matches a blocked rule"}
{"permissionDecision":"deny","permissionDecisionReason":"command matches a blocked rule"}
```

The final object is the decision. `permissionDecisionReason` is included for `ask` and `deny`, not `allow`. The hook does not rewrite the Bash command.

Every handled verdict exits with status `0`; inspect the JSON to distinguish allow, ask, and deny. Copilot treats a nonzero `preToolUse` command-hook exit as a denial, even if stdout contains an allow response. Hook timeouts are the exception: Copilot fails open to its normal permission flow.

The hook’s timeout is left at Copilot’s default of 30 seconds. The shared parser also has a 30-second `shfmt` timeout, so a slow parse can race Copilot’s outer timeout. This is a known limitation of the selected default.

## Lovely policy configuration

Copilot has a separate Lovely policy namespace, merged from global to project to local:

| Scope | Location |
| --- | --- |
| Global | `$COPILOT_HOME/lovely-permissions.jsonc` (default `~/.copilot/lovely-permissions.jsonc`) |
| Project | `.github/copilot/lovely-permissions.jsonc` at the active checkout root |
| Personal local override | `.github/copilot/lovely-permissions.local.jsonc` at the active checkout root |

Add `.github/copilot/lovely-permissions.local.jsonc` to the project’s `.gitignore` so personal rules are not committed. The project path is located from the event payload’s `cwd`, not the hook process’s current directory. Outside a Git checkout, that event directory is the project context.

These files use the same policy schema and deep-merge semantics as Devin’s Lovely policy files. See [the Devin guide](README.lovely-devin-permissions.md#configuration-files) for the Bash policy keys and regex guidance.

- If every Lovely policy file is missing, the safe default is `ask`.
- If any existing Lovely policy source is unreadable, malformed, or invalid, the command is denied—even if another source is valid.
- Malformed hook input or a missing/non-string command is denied. An empty command is evaluated through the policy’s `error` level.

## Copilot saved command approvals

The hook imports saved shell approvals from `$COPILOT_HOME/permissions-config.json` (default `~/.copilot/permissions-config.json`). For a custom `COPILOT_HOME`, the hook follows that directory. If Copilot is launched with the legacy `--config-dir`, also set `COPILOT_HOME` so the hook subprocess reads the same file.

Only `kind: "commands"` approvals from the location matching Copilot’s current permission location are imported. Copilot uses the Git root for repositories, the main repository root for linked worktrees, the submodule’s own location for submodules, and the normalized current directory outside Git.

Command identifiers follow Copilot’s literal and trailing-`:*` matching rules, but Lovely applies the imported matchers to each parsed command segment’s executed form:

- `git status` matches that exact segment, not `git status --short`.
- `git:*` matches `git` or a `git` segment followed by arguments.
- In `git status && rm -rf /tmp`, a saved approval for `git:*` can approve only the `git` segment; the `rm` segment is still evaluated by Lovely policy.

Imported approvals add allow patterns; Lovely deny rules still win. A missing saved-approval file is normal and silent. If an existing file is unreadable or malformed, the CLI warns on stderr and imports no approvals from it.

Copilot’s managed permission rules remain in force: deny takes precedence over ask, which takes precedence over allow, and a managed ask requires fresh approval that cannot be satisfied by a hook or saved approval. See [GitHub’s managed settings reference](https://docs.github.com/en/copilot/reference/enterprise-administrators/enterprise-managed-settings#permissions).

## CLI modes

Test a command without starting a Copilot session:

```bash
lovely-copilot-permissions --test "git status"
```

`--test` prints the final Copilot decision JSON and does not emit timeline progress. It uses the current working directory, the same Lovely policy sources, and the matching saved Copilot approvals. An empty command is evaluated by the policy. Valid allow, ask, and deny results all exit `0`; invocation failures that produce no verdict exit nonzero.

Inspect the candidate policy files, saved-approval source and location, imported approvals, and effective Bash configuration:

```bash
lovely-copilot-permissions --show-config
```

For an invalid Lovely policy source, `--show-config` writes an error to stderr and exits nonzero without partial JSON, matching Devin’s CLI behavior.

## Scope and limitations

- Linux and macOS only for the initial release. Windows support requires reliable Windows `shfmt` discovery.
- Local Copilot CLI only. User-level hooks and the installed executable are not available in Copilot cloud-agent jobs.
- Only `preToolUse` for `bash` is supported; `permissionRequest` and other hook events are out of scope.
- The integration imports persisted command approvals only, not transient command-line grants or arbitrary Copilot settings.
