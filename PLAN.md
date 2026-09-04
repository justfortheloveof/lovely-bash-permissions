# Plan

## Objective

Make sure or output redirection permission work as expected, approval/prompting user/denying should have the exact same behavior as our TS version ../jftlo/lovely-devin-permissions/.

- Step 1: investigate why redirect stderr to devnull is asking the user in our python version, but allowed as expected in the TS version

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

- Step 2: Implement proper fix

- Step 3: validate that all other output_redirection permissions work as expected and document outcome of all different variations
