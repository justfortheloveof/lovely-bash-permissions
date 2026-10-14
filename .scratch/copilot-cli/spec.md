# GitHub Copilot CLI support

Status: resolved

## Problem Statement

Lovely Bash Permissions can evaluate Bash commands for Devin and for the Pi extension, but it cannot currently participate in GitHub Copilot CLI sessions. Copilot users therefore cannot apply Lovely’s Bash policy or its explanations to shell commands run by Copilot.

Copilot exposes a command-hook protocol that can make a policy decision before a tool executes. Its hook payload, saved command approvals, configuration locations, and user-facing status channel differ from Devin’s. A Copilot host is needed to connect those host-specific concepts to the existing Bash policy without changing the shared evaluator.

## Solution

Add a `lovely-copilot-permissions` CLI that runs as a local GitHub Copilot CLI command hook. It will evaluate Bash tool calls through the existing Lovely decision engine, account for Copilot’s saved command approvals, and return Copilot-native decisions and explanations.

The CLI will provide hook mode, `--test`, and `--show-config`. Users will register the executable manually in a user-level Copilot hook file. The initial integration targets Linux and macOS only and does not include a setup command or Copilot cloud-agent support.

## User Stories

1. As a Copilot CLI user, I want Bash tool calls evaluated by Lovely’s Bash policy, so that my existing command-safety rules apply during Copilot sessions.
2. As a Copilot CLI user, I want the integration to run only for the `preToolUse` event, so that it makes its decision immediately before a tool call executes.
3. As a Copilot CLI user, I want the hook to inspect only the `bash` tool, so that other Copilot tools remain outside this Bash-specific policy.
4. As a Copilot CLI user, I want native camelCase hook payloads accepted, so that the integration uses Copilot CLI’s own event format.
5. As a Copilot CLI user, I want `toolArgs` accepted both as an object and as a JSON-encoded string, so that payloads in either documented shape can be evaluated.
6. As a Copilot CLI user, I want malformed hook input or a missing/non-string command to produce a denial, so that incomplete requests cannot accidentally run unchecked.
7. As a Copilot CLI user, I want an empty command string evaluated by the policy rather than silently skipped, so that it receives the configured error-policy behavior.
8. As a Copilot CLI user, I want an `allow` verdict to return Copilot’s native allow decision, so that an approved command can proceed without a second permission prompt.
9. As a Copilot CLI user, I want an `ask` verdict to return Copilot’s native ask decision, so that interactive Copilot sessions can request approval and autopilot sessions follow Copilot’s documented ask behavior.
10. As a Copilot CLI user, I want a `deny` verdict to return Copilot’s native deny decision and its reason, so that a command rejected by policy cannot execute and Copilot can explain the refusal.
11. As a Copilot CLI user, I want the reason for every verdict shown in Copilot’s timeline, so that allowed, approval-requiring, and denied commands are all observable without rewriting the Bash command.
12. As a Copilot CLI user, I want timeline progress messages to remain separate from the hook’s final decision JSON, so that Copilot can display status while still parsing one valid decision response.
13. As a Copilot CLI user, I want ask and deny reasons included in the hook decision, so that Copilot’s agent can understand why approval is needed or a command was refused.
14. As a Copilot CLI user, I want Lovely’s explicit deny rules to take precedence over imported Copilot approvals, so that a saved approval cannot weaken a Lovely denial.
15. As a Copilot CLI user, I want matching saved Copilot command approvals imported into the effective allow patterns, so that commands I have already approved for this Copilot location are not needlessly asked about again.
16. As a Copilot CLI user, I want exact saved command identifiers to match exactly and trailing `:*` identifiers to match the command itself or that command followed by arguments, so that imported approvals preserve Copilot’s documented matching semantics.
17. As a Copilot CLI user, I want saved approvals selected by Copilot’s permission-location rules, so that repository, submodule, linked-worktree, and non-repository scopes behave consistently with Copilot.
18. As a Copilot CLI user, I want a missing saved-approval file treated as “no saved approvals,” so that a new Copilot installation does not produce a warning on every command.
19. As a Copilot CLI user, I want unreadable or malformed saved-approval data to produce a warning and contribute no approvals, so that an auxiliary host file cannot silently grant access.
20. As a Copilot CLI user, I want a missing Lovely policy to default to asking, so that commands are not automatically allowed when I have not created a policy.
21. As a Copilot CLI user, I want malformed or unusable Lovely policy configuration to deny, so that invalid policy cannot be treated as permission.
22. As a Copilot CLI user, I want global, shared project, and personal local Copilot policies to merge in that precedence order, so that I can set defaults, share repository rules, and privately override them.
23. As a Copilot CLI user, I want the project policy located from the active checkout root found from the event’s `cwd`, so that a hook process working directory cannot make Copilot evaluate the wrong repository’s policy.
24. As a Copilot CLI user, I want the personal local policy documented as a file to ignore in version control, so that private overrides are not accidentally shared.
25. As a Copilot CLI user, I want `--test COMMAND` to print the final Copilot decision JSON without timeline progress, so that I can inspect the exact response the hook would return.
26. As a Copilot CLI user, I want `--test` to use the same policy sources and saved approvals as hook mode, so that a local test reflects the configuration used by the running integration.
27. As a Copilot CLI user, I want `--show-config` to report the policy sources, Copilot saved-approval source and location, imported approvals, and effective Bash configuration, so that I can diagnose unexpected decisions.
28. As a Copilot CLI user, I want handled decisions in both hook and test modes to use the same successful process exit status, so that the JSON response—not a host-specific exit-code convention—carries the verdict.
29. As a Copilot CLI user, I want invocation failures to remain distinguishable from valid decisions, so that automation can detect when no verdict was produced.
30. As a Copilot CLI user, I want the executable available on `PATH` and callable directly from a user-level hook, so that the hook works across repositories without requiring each repository to add the package as a dependency.
31. As a Copilot CLI user, I want the user-level hook registration to apply across my local repositories, so that I can enable the integration once for local Copilot CLI sessions.
32. As a Copilot CLI user, I want the CLI to honor `COPILOT_HOME` and otherwise use Copilot’s default home, so that its global policy and saved-approval lookups follow my Copilot configuration directory.
33. As a Copilot CLI user using legacy `--config-dir`, I want the documentation to explain that the hook must also receive `COPILOT_HOME`, so that the subprocess can locate the same saved approvals.
34. As a Copilot CLI user, I want the integration documented as Linux/macOS-only initially, so that I know not to rely on it where the shared parser cannot reliably locate `shfmt`.
35. As a Copilot CLI user, I want cloud-agent support clearly excluded, so that I do not assume a user-level local hook is active in an ephemeral cloud job.
36. As a Copilot CLI user, I want no automatic setup command to mutate my Copilot configuration, so that I can register or remove the user-level hook manually.

## Implementation Decisions

- Add a Copilot host adapter and console entry point. The adapter owns Copilot’s hook input/output contract; it does not duplicate Bash parsing or policy evaluation.
- Reuse the host-agnostic Bash decision function and policy vocabulary. Do not route Copilot through Devin’s protocol adapter or Devin-specific effective-config wrapper.
- Use only the Copilot CLI `preToolUse` event in native camelCase form, matching the Bash tool name and leaving all other tools untouched.
- Normalize `toolArgs` from either a JSON object or a JSON-encoded object, then require a string command. Malformed hook requests produce an explicit deny response.
- Map policy verdicts directly to Copilot’s `permissionDecision` vocabulary. Return an explicit `ask` rather than falling through to Copilot’s default permission path.
- Emit one persistent Copilot progress message for every verdict as a one-line progress JSON object, followed by exactly one final decision JSON object. The progress message includes the verdict and policy reason and is display-only. Include `permissionDecisionReason` for ask and deny, but not allow.
- Add Copilot-specific policy discovery and saved-approval loading. Policy levels merge global, project, then local; reuse the existing Lovely validation and deep-merge semantics.
- Convert only saved `commands` approvals for the matching Copilot permission location into additional allowed-command patterns. Match each parsed command segment in its executed form, preserving Copilot’s exact-identifier and trailing `:*` prefix behavior; do not reuse Devin’s `Exec(...)` prefix converter. Deduplicate imported patterns and retain Lovely deny precedence.
- Resolve project policy from the active checkout root found from the event’s `cwd`, or the normalized event `cwd` outside a Git checkout. Do not substitute the hook process’s working directory when the event `cwd` is absent or invalid. Resolve saved approvals separately according to Copilot’s permission-location identity, including linked-worktree behavior.
- Missing Lovely policy files are ignored, and if all are missing the policy defaults to ask. Any present Lovely policy source that is unreadable, malformed, or invalid denies—even when another source is valid. Malformed hook input denies. Non-Bash tool calls produce no decision. A missing Copilot saved-approval file is normal; unreadable or malformed existing approval data warns and imports no approvals.
- `--test` prints the final Copilot decision JSON without progress output. It uses the current working directory as its policy context and evaluates an empty command through the configured `error` policy. Valid allow, ask, and deny verdicts exit successfully in both hook and test modes; invocation failures that produce no verdict exit nonzero.
- `--show-config` exposes candidate Lovely policy sources, the Copilot saved-approval file and selected location, imported approvals, and the effective Bash policy. For an invalid Lovely source, match Devin’s behavior: print an error to stderr and exit nonzero without partial JSON.
- Do not add `--setup`. Document manual user-level hook registration using Copilot’s direct `exec` form and the executable on `PATH`.
- Update the root project overview and architecture guide to identify Copilot as a planned third permission host, and provide a dedicated Copilot integration guide. Record the separate Copilot policy namespace in an ADR.
- The initial supported host platforms are Linux and macOS. Do not change shared `shfmt` discovery as part of this feature.

## Testing Decisions

- Tests should assert externally observable behavior: parsed hook payloads result in the correct Copilot decision JSON, progress output, stderr warning, and process status. Avoid pinning private helper structure unless a focused config test needs to isolate a matching rule.
- Keep CLI tests in-process, as requested. Call the CLI entry function with controlled stdin, stdout, stderr, environment, and working directory; do not launch the installed console script or a Copilot process.
- Test the Copilot adapter’s supported input forms, non-Bash skip behavior, malformed input denial, all three policy verdicts, progress/decision ordering, and `--test`/`--show-config` output.
- Test policy source discovery and precedence, `COPILOT_HOME` fallback, active checkout root selection, local override behavior, and invalid Lovely policy handling.
- Test that the event `cwd`, rather than the hook process directory, determines policy discovery; missing or invalid event `cwd` denies. Test `--test` from its current directory and an empty command.
- Test strict Lovely-source failure behavior, including one malformed source alongside another valid source, all sources missing, malformed merged policy, and `--show-config` error output.
- Test saved-approval lookup for the active Copilot location, exact and trailing `:*` identifiers against executed command segments, compound commands where only one segment is approved, irrelevant approval kinds, missing-file silence, malformed-file warning, and Lovely deny precedence over imported approvals.
- Test that hook and test modes use successful exit status for valid allow, ask, and deny decisions, and that no-verdict invocation errors remain nonzero.
- Assert progress lines use Copilot’s one-line progress JSON framing, are followed by exactly one final decision object, and that the final object contains the expected `permissionDecision` and optional reason.
- Test the existing shared decision engine only through its established public decision interface; do not add parser/evaluator tests unless implementation changes that shared behavior.
- Prior art includes the Devin CLI’s in-process mode tests and config-loader tests, plus the Pi CLI’s protocol contract tests. The Copilot feature intentionally uses the in-process seam rather than Pi’s real-subprocess protocol seam.

## Out of Scope

- Copilot `permissionRequest`, lifecycle hooks, or any hook event other than `preToolUse`.
- Tools other than Copilot’s Bash tool.
- Copilot cloud-agent support, repository-level hook deployment, or cloud sandbox packaging.
- Windows support or changes to shared `shfmt` discovery.
- An automatic `--setup` command or any mutation of Copilot settings/hook files.
- Importing transient Copilot command-line grants or arbitrary Copilot settings/policy rules; only persisted saved command approvals are imported.
- Changes to the shared Bash parser, evaluator, or policy vocabulary.

## Further Notes

The selected Copilot policy locations are `$COPILOT_HOME/lovely-permissions.jsonc` (defaulting to `~/.copilot/lovely-permissions.jsonc`), `.github/copilot/lovely-permissions.jsonc`, and `.github/copilot/lovely-permissions.local.jsonc`, merged in that order. The local project file should be added to `.gitignore`.

Saved approvals are read from `$COPILOT_HOME/permissions-config.json`, defaulting to `~/.copilot/permissions-config.json`. If users launch Copilot with legacy `--config-dir`, they must also set `COPILOT_HOME` for the hook subprocess to use the same directory.

The manual hook registration belongs in a dedicated JSON file under `$COPILOT_HOME/hooks/`; it should match `bash` and invoke `lovely-copilot-permissions` through direct `exec`. This is local Copilot CLI integration only.

The final hook response is one JSON object: allow returns `permissionDecision: "allow"`; ask and deny return their matching `permissionDecision` plus `permissionDecisionReason`. Before it, emit a single-line `{"type":"progress","message":"..."}` object. Copilot strips progress lines from hook output and displays them in the timeline; they do not enter the model’s context. Do not emit other stdout text or multiple final objects.

The Copilot hook timeout remains at its default of 30 seconds, as requested. Copilot treats any nonzero `preToolUse` command-hook exit as a denial, even if stdout says allow; a timeout is the exception and fails open to Copilot’s normal permission flow. The shared parser’s own `shfmt` timeout is also 30 seconds, so the equal timeout boundaries can race. This is an accepted, documented limitation.

Copilot’s managed permission controls remain Copilot-owned. Its managed rules use deny > ask > allow precedence, and a managed ask requires fresh approval that cannot be satisfied by a hook or a saved approval. The integration imports persisted command approvals only; it does not import transient flags or arbitrary Copilot settings.

For `--show-config`, invalid Lovely policy sources produce an error on stderr and a nonzero exit, with no partial JSON. `--test ""` is a command evaluation, not a usage error. Both modes use the same successful exit status for valid allow, ask, and deny responses; the JSON carries the verdict.
