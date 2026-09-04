# Plan

## Objective

Make sure or output redirection permission work as expected, approval/prompting user/denying should have the exact same behavior as our TS version ../jftlo/lovely-devin-permissions/.

- Step 1: investigate why redirect stderr to devnull is asking the user in our python version, but allowed as expected in the TS version [DONE]

  Root cause: Python's `check_output_redirection` only reads the wildcard level (`policy.get("*")`) from object-form policies, but doesn't check per-kind levels like `stderr_to_dev_null` and `stderr_to_stdout`. The TS version's `resolveRedirectionLevel` correctly resolves per-kind policies. Config has `{"*": "ask", "stderr_to_dev_null": "allow", "stderr_to_stdout": "allow"}` so TS auto-approves `2> /dev/null` but Python asks.

Examples:

```
lovely-bash-permissions devin-cli  ❯ uv run lovely-devin-permissions --test 'echo hi 2> /dev/null'
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "updatedInput": {
      "command": ": '[♡ perms: 💛 REQUIRES-USER-APPROVAL] command matches allowed pattern ^echo(\\s+.*)?$; output redirection requires approval' ; echo hi 2> /dev/null"
    }
  }
}

lovely-bash-permissions devin-cli  ❯ uv run lovely-devin-permissions --test 'echo hi 2>&1'
{
  "decision": "approve",
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "updatedInput": {
      "command": ": '[♡ perms: 💚 auto-approved] command matches allowed pattern ^echo(\\s+.*)?$.' ; echo hi 2>&1"
    }
  }
}

lovely-bash-permissions devin-cli  ❯ node /home/alx/repos/jftlo/lovely-devin-permissions/dist/hook.js --test 'echo hi 2> /dev/null'
{
  "decision": "approve",
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "updatedInput": {
      "command": ": '[♡ perms: 💚 auto-approved] command matches allowed pattern ^echo(\\s+.*)?$' ; echo hi 2> /dev/null"
    }
  }
}

lovely-bash-permissions devin-cli  ❯ node /home/alx/repos/jftlo/lovely-devin-permissions/dist/hook.js --test 'echo hi 2>&1'
{
  "decision": "approve",
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "updatedInput": {
      "command": ": '[♡ perms: 💚 auto-approved] command matches allowed pattern ^echo(\\s+.*)?$' ; echo hi 2>&1"
    }
  }
}
```

- Step 2: Implement per-kind output redirection policy resolution [DONE]

  Completed: Added classify_output_redirection() and _resolve_output_level() in rules.py, modified check_output_redirection to accept per-kind object-form policies. Fixed operator string bugs (" >&" → "&>", "& >>" → "&>>"). N field read from redir level (not inside Word).

  Completed: Fixed ruff lint issues - unused Literal import, unused kind_keys variable, SIM108 ternary. All 498 tests pass.

- Step 3: validate that all other output_redirection permissions work as expected and document outcome of all different variations [DONE]

  Validation completed via tests/test_output_redirection_validation.py:

  **Default config** (output_redirection: `*`=ask, stderr variants=allow):
  - stdout>file → ask (correct: stdout_to_dev_null falls back to wildcard=ask)
  - append >> → ask (same reason)
  - &> both → ask (classified as other/redir, wildcard=ask)
  - >& bash combined → ask (same)
  - 2>&1 stderr-to-stdout → auto-approved ✓
  - 2>stderr/file → ask (classified as other, not stderr_to_dev_null)
  - pipe+redirect → ask

  **Key finding**: Only stderr_to_stdout kind auto-approves under default config. All other redirections fall back to wildcard=ask.

  **Per-kind deny tests**: All stderr variants auto-approve regardless of deny policies (since those kinds aren't denied). stdout_to_dev_null denies correctly.

  **TS comparison**: Both versions agree - stderr variants auto-approve, others ask. Earlier mismatches were config differences (allowed_cmds_regex matching), not logic bugs.
