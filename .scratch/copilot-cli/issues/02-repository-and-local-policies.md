# 02: Add repository and personal Copilot policies

**What to build:** Copilot users can layer shared repository rules and private local overrides on top of their global Lovely policy, with project context determined by the event Copilot actually sent.

**Blocked by:** 01: Add a policy-backed Copilot Bash hook.

**Status:** resolved

- [x] Shared project and personal local policies are discovered from the active checkout root found from the event's `cwd`, or from the normalized event directory outside a Git checkout.
- [x] A missing or invalid event `cwd` does not fall back to the hook process's working directory and instead fails closed.
- [x] Global, shared project, and personal local policies merge in that precedence order using Lovely's existing validation and merge behavior.
- [x] Missing policy sources are ignored and all-missing sources default to ask; any present unreadable, malformed, or invalid source denies, even if another source is valid.
- [x] The personal local policy is documented as a file to ignore in version control.
- [x] In-process tests cover policy precedence, active checkout selection, outside-repository behavior, missing/invalid event `cwd`, all-missing sources, and strict invalid-source handling.
