# 04: Add `--test` parity with hook mode

**What to build:** Users can preview the exact Copilot decision for a command without starting a Copilot session, using the same policy and saved-approval inputs as the live hook.

**Blocked by:** 03: Import saved Copilot command approvals.

**Status:** resolved

- [x] `--test COMMAND` prints the final Copilot decision JSON and does not emit timeline progress.
- [x] Test mode uses the current working directory as policy context and loads the same policy sources and saved approvals as hook mode.
- [x] An empty command is evaluated through the configured error policy rather than treated as a usage error.
- [x] Valid allow, ask, and deny decisions exit successfully; invocation failures that produce no verdict exit nonzero.
- [x] In-process tests cover configuration parity, empty commands, output, and process status without launching the installed command or Copilot.
- [x] The Copilot integration guide documents how to preview decisions with test mode.

## Comments

The follow-up in ticket 06 changes test-mode stdout to mirror hook mode, including its progress JSON line.
