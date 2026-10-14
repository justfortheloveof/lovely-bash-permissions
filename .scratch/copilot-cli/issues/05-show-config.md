# 05: Add `--show-config` diagnostics

**What to build:** Users can diagnose unexpected Copilot decisions by inspecting which Lovely policies and Copilot approvals are in effect and what effective Bash policy they produce.

**Blocked by:** 03: Import saved Copilot command approvals.

**Status:** resolved

- [x] `--show-config` reports candidate Lovely policy sources, the saved-approval source and selected permission location, imported approvals, and the effective Bash policy.
- [x] If a Lovely policy source is invalid, the command writes an error to stderr, exits nonzero, and emits no partial JSON.
- [x] In-process tests cover successful diagnostic output and invalid-policy failure behavior.
- [x] The Copilot integration guide documents how to inspect the effective configuration and troubleshoot invalid policies.
