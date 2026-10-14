# 01: Add a policy-backed Copilot Bash hook

**What to build:** A runnable `lovely-copilot-permissions` hook evaluates Copilot `preToolUse` Bash calls using the existing Lovely decision engine and the global Copilot Lovely policy. Users can register it manually for local Copilot CLI sessions and receive Copilot-native decisions with explanations.

**Blocked by:** None (can start immediately).

**Status:** resolved

- [x] The hook accepts Copilot's native camelCase payload, handles `toolArgs` as either an object or a JSON-encoded object, and evaluates only the Bash tool for `preToolUse`; other tools produce no decision.
- [x] Malformed input and missing or non-string commands produce a denial, while an empty string is evaluated by the configured error policy.
- [x] Allow, ask, and deny policy verdicts map to Copilot's matching decision; ask and deny include their reason, and allow omits the decision reason.
- [x] Each handled verdict emits one progress JSON line before exactly one final decision JSON object, with no unrelated stdout output.
- [x] The global policy follows `COPILOT_HOME` or Copilot's default home. A missing policy defaults to ask; a present unreadable, malformed, or invalid policy denies.
- [x] Valid allow, ask, and deny decisions exit successfully; failures that produce no verdict exit nonzero.
- [x] The executable is registered as a console command and can be called directly by a user-level hook without a setup command.
- [x] In-process tests cover supported payload forms, non-Bash handling, malformed input, all verdicts, output framing, and process status.
- [x] The project overview, architecture guide, and Copilot integration guide describe the implemented local Linux/macOS hook, manual registration, and the lack of cloud-agent or automatic-setup support.
