# Copilot has a separate Bash policy namespace

**Status: accepted**

Copilot’s Bash policy files use Copilot-specific global, repository, and local locations rather than Devin’s `.devin` locations. A user may use Copilot without using Devin, so the Copilot integration must be independently configurable; aligning its files with Copilot’s own scopes supports that use. The tradeoff is that a user who runs both hosts may maintain policies that diverge, while both hosts continue to share the same policy schema and decision engine.
