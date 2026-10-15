# 06: Make `--test` mirror hook output

**What to build:** Users can inspect the complete stdout that Copilot receives for a command without starting a Copilot session.

**Blocked by:** 04: Add `--test` parity with hook mode.

**Status:** resolved

- [x] `--test COMMAND` prints the same progress JSON line followed by the final decision JSON object as hook mode.
- [x] In-process tests verify exact stdout parity for allow, ask, and deny verdicts.
- [x] The Copilot guide and spec document the complete test-mode output.
