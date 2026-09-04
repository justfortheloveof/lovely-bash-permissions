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

- Step 2: Implement per-kind output redirection policy resolution [IN PROGRESS]

  Completed: Added classify_output_redirection() and _resolve_output_level() in rules.py, modified check_output_redirection to accept per-kind object-form policies. Fixed operator string bugs (" >&" → "&>", "& >>" → "&>>"). N field read from redir level (not inside Word).

  Remaining: 5 tests failing - need to verify evaluate.py passes config correctly to rules functions; fix ruff lint issues (unused Literal import, unused kind_keys variable, ternary SIM108). Then verify all other output_redirection patterns work (Step 3).

- Step 3: validate that all other output_redirection permissions work as expected and document outcome of all different variations
