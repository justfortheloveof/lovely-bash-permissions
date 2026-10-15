# Copilot verdict presentation

Status: resolved

## Problem Statement

Copilot currently receives a generic progress message, while the other permission-host output uses the recognizable `♡ perms` brand and action-specific verdict labels. The progress message also collapses multiple reasons into one line. Users want Copilot's timeline to clearly identify the product, action, and each reason, while preserving Copilot's native decision protocol.

The same presentation must be inspectable with `--test`. Repository-authored files also need consistent product terminology and regular hyphens instead of em dashes.

## Solution

Use the established `♡ perms` labels for Copilot verdicts, with a colored heart and status text for each action. Show the label first and list each reason as a hyphen bullet in a multiline progress message. Keep the progress event as one valid, physical-line JSON object, then emit the final Copilot decision object.

Ask and deny decisions retain a matching `permissionDecisionReason` containing the label and bullet reasons. Allow decisions continue to omit that field; their label and reason appear in the progress message. `--test` prints exactly the same progress and decision JSON as hook mode. Clean repository-authored files of the former brand phrase and em dashes without adding an automated check for either prohibition.

## User Stories

1. As a Copilot CLI user, I want every handled verdict identified with the `♡ perms` brand, so that I can recognize the permission host's output.
2. As a Copilot CLI user, I want an allow verdict labeled `💚 auto-approved`, so that approved commands are visually distinct.
3. As a Copilot CLI user, I want an ask verdict labeled `💛 REQUIRES-USER-APPROVAL`, so that commands needing my approval are clear.
4. As a Copilot CLI user, I want a deny verdict labeled `❤️ auto-rejected`, so that blocked commands are unmistakable.
5. As a Copilot CLI user, I want the verdict label followed by every reason as its own hyphen bullet, so that multiple explanations are easy to scan.
6. As a Copilot CLI user, I want an allow verdict with no detailed reasons to show its fallback reason as one bullet, so that every progress message remains explanatory.
7. As a Copilot CLI user, I want the final `permissionDecision` to remain Copilot's native `allow`, `ask`, or `deny` value, so that Copilot can process the decision.
8. As a Copilot CLI user, I want ask and deny decision reasons to carry the same label and bullet list as the progress message, so that the agent receives the rationale.
9. As a Copilot CLI user, I want allow decisions to omit `permissionDecisionReason`, so that allow behavior remains consistent with the agreed Copilot contract.
10. As a Copilot CLI user, I want the progress event to remain a single valid JSON object on one physical output line, so that Copilot can parse it and display its multiline message.
11. As a Copilot CLI user, I want progress output to remain separate from the final decision object, so that Copilot can display the status without confusing it with the decision.
12. As a Copilot CLI user, I want `--test COMMAND` to print the same progress and decision JSON as hook mode, so that I can inspect the complete Copilot-facing output without starting a session.
13. As a Copilot CLI user, I want the test output to show raw protocol JSON rather than a simulated timeline, so that I can compare it directly with hook output.
14. As a user of the repository, I want the disallowed former brand phrase removed from repository-authored files, so that branding is consistent.
15. As a user of the repository, I want product references to use Lovely Permissions where the product name is needed and neutral terms such as Copilot policy or Bash policy for policy concepts, so that branding and domain language are distinct.
16. As a reader of repository-authored files, I want em dashes replaced with regular hyphens, so that the repository follows one punctuation convention.

## Implementation Decisions

- Use the same action labels as the Devin hook: allow maps to `💚 auto-approved`, ask maps to `💛 REQUIRES-USER-APPROVAL`, and deny maps to `❤️ auto-rejected`.
- Format a progress message with the bracketed `♡ perms` verdict label on its first line and one `- ` bullet per reason on following lines. If the evaluator has no reason list, use its fallback reason as the single bullet.
- Emit exactly one progress event for each handled verdict. JSON serialization must keep the outer progress event on one physical stdout line while preserving newline characters in its message value.
- Emit exactly one final decision object after the progress event. Keep `permissionDecision` as Copilot's native action value. Include the matching labeled bullet text in `permissionDecisionReason` for ask and deny; omit that field for allow.
- Do not rewrite the Bash command or route Copilot through the Devin protocol adapter.
- Keep `--test` on the same output path as hook mode so its stdout is identical for the same command and context.
- Replace the disallowed former brand phrase throughout repository-authored files. Use Lovely Permissions for the product name where needed, and Copilot policy or Bash policy for descriptive policy references.
- Replace U+2014 em dashes with U+002D hyphens in repository-authored files, including code, comments, documentation, tests, plans, and local issue files. Exclude Git internals, generated files, vendored content, and environments.
- Do not add an automated lint or test gate for the wording or punctuation prohibitions.

## Testing Decisions

- Test externally observable behavior at the existing in-process CLI entry point. Control stdin, stdout, stderr, environment, arguments, and working directory; do not launch the installed command in automated tests.
- For allow, ask, and deny, assert the progress event's action label, heart, bullet reasons, and order before the final decision object.
- Use a command and policy that yield multiple reasons to verify that each reason becomes a separate bullet. Also cover the fallback when the evaluator provides no reason list.
- Assert that ask and deny final decision objects include the same labeled bullet text and that allow omits `permissionDecisionReason`.
- Assert that `--test` stdout exactly matches hook-mode stdout for allow, ask, and deny. Assert that the final decision values remain Copilot-native.
- Keep the progress event as one physical JSON line and verify its decoded message contains the intended newlines. This checks protocol framing, not Copilot's visual rendering.
- Perform a one-time repository-wide search for the prohibited former brand phrase and em dash after cleanup. Do not add a permanent automated check, as requested.
- Prior art includes the Devin hook label and contract tests, the Pi CLI's reason-list behavior, and the existing Copilot CLI in-process contract tests.

## Out of Scope

- Changing policy evaluation, parser behavior, verdict precedence, or the `allow`, `ask`, and `deny` decision semantics.
- Changing Copilot's native `permissionDecision` values or adding `permissionDecisionReason` to allow decisions.
- Rewriting the Bash command to carry a verdict label.
- Adding a permanent lint or test gate for the phrase or punctuation prohibitions.
- Adding Copilot setup automation, new hook events, or new supported platforms.

## Further Notes

- Copilot progress messages are shown to the user in the CLI timeline and are not sent to the LLM. Ask and deny `permissionDecisionReason` fields carry the agent-facing rationale.
- The heart and verdict label are presentation. The underlying policy verdict remains `allow`, `ask`, or `deny`.
- The current repository search found 116 matching lines containing em dashes across eight files. The cleanup includes prior documentation and issue material, not only the Copilot adapter.
- `--test` already mirrors hook-mode stdout. This spec preserves that behavior while changing the shared verdict presentation.
