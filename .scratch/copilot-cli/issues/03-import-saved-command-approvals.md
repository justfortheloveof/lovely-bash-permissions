# 03: Import saved Copilot command approvals

**What to build:** Commands already approved by the user in Copilot are not needlessly asked about again, while Lovely deny rules remain authoritative and malformed auxiliary approval data cannot grant access.

**Blocked by:** 02: Add repository and personal Copilot policies.

**Status:** resolved

- [x] Saved approvals are loaded from Copilot's configured home and selected for the active Copilot permission location, including repositories, submodules, linked worktrees, and directories outside a repository.
- [x] Only persisted command approvals for the matching location are imported; unrelated approval kinds and transient grants are ignored.
- [x] Exact command identifiers match exactly, and trailing `:*` identifiers match the command itself or that command followed by arguments.
- [x] Imported matchers are applied to each parsed command segment in its executed form, deduplicated, and cannot override an explicit Lovely deny.
- [x] A missing saved-approval file is silent; unreadable or malformed existing data warns and contributes no approvals.
- [x] In-process tests cover permission-location selection, exact and prefix matching, compound commands, irrelevant approval kinds, file errors, and deny precedence.
- [x] The Copilot integration guide explains saved approvals, their location-scoped matching behavior, and custom-home configuration.
