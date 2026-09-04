# Plan: [x] Fix unicode escaping in JSON output (ensure_ascii=False)

## Objective

Fix lovely-bash-permissions' block path regex detection, it should behave the same as lovely-devin-permissions

```
lovely-bash-permissions devin-cli  ❯ node /home/alx/repos/jftlo/lovely-devin-permissions/dist/hook.js --test 'ls /etc/'
{
  "decision": "block",
  "reason": "[♡ perms: ❤️ auto-rejected] Blocked by bash permissions: Argument \"/etc/\" matches blocked path pattern /\\/etc/. The tool has not been run.",
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "updatedInput": {
      "command": ": '[♡ perms: ❤️ auto-rejected]' ; ls /etc/"
    }
  }
}

lovely-bash-permissions devin-cli  ✗ uv run lovely-devin-permissions --test 'ls /etc/'
{
  "decision": "approve",
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "updatedInput": {
      "command": ": '[♡ perms: 💚 auto-approved] command matches allowed pattern ^ls(\\s+.*)?$' ; ls /etc/"
    }
  }
}
```
