# Lovely Permissions

This context describes the policy concepts used to decide whether a Bash command may run through a coding-agent host.

## Language

**Bash policy**:
Rules that determine whether a Bash command is allowed, requires approval, or is denied.

**Policy verdict**:
The `allow`, `ask`, or `deny` result produced when a Bash command is evaluated against a Bash policy.

**Verdict label**:
User-facing text and icon paired with a policy verdict for presentation. A verdict label does not change the underlying policy verdict.

**Copilot saved command approval**:
A GitHub Copilot CLI permission that automatically approves matching shell commands for a particular permission location. It is separate from a policy verdict.

**Copilot permission location**:
The repository or directory identity GitHub Copilot CLI uses to scope saved command approvals.
