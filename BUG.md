lovely-bash-permissions devin-cli ❯ uv run lovely-devin-permissions -t 'export TEST=1 hi -l'
{
  "decision": "approve",
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "updatedInput": {
      "command": ": '[♡ perms: 💚 auto-approved] command matches allowed pattern' ; export TEST=1 hi -l"
    }
  }
}
