# 01: Standardize Copilot verdict output

**What to build:** Copilot hook and test mode show the agreed branded verdict labels and readable reason bullets while preserving Copilot's native decision protocol.

**Blocked by:** None (can start immediately).

**Status:** resolved

- [x] Each handled verdict emits one progress message with the matching heart and verdict label, followed by one hyphen bullet per reason. When the reason list is empty, use the fallback reason as one bullet.
- [x] The progress event remains one physical JSON line, followed by exactly one final decision object.
- [x] Ask and deny final decision reasons contain the matching label and bullet list; allow omits `permissionDecisionReason`.
- [x] The final `permissionDecision` remains Copilot-native, and the Bash command is not rewritten.
- [x] `--test` stdout exactly matches hook-mode stdout for allow, ask, and deny.
- [x] In-process tests verify labels, bullet formatting, output ordering, reason-field behavior, and hook/test output parity.
- [x] The Copilot integration guide documents the labeled progress output and matching `--test` output.

## Comments

Implementation and automated tests are complete at commit `62d366b`.
