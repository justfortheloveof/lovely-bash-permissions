# Plan

## Objective

We are working on our python devin_cli functionality.

For each ISSUE documented below, you MUST orchestrate the implementation by ALWAYS spawning a research agent to investigate implementation options. You then pick the proper implementation and spawn an agent for implementation of the chosen solution.

Test Examples:

```
uv run lovely-devin-permissions --test 'cmd'
node /home/alx/repos/jftlo/lovely-devin-permissions/dist/hook.js --test 'cmd'
```

## ISSUES

### Number 1

Run the following test or any other nested subshell should result in ALL nested commands being tested against our rules AND should print each matching pattern for each matching command.

The test case below does NOT pass currently as it should be printing the matching `ls` pattern from our global config AND print the echo pattern twice as there are 2 echo cmds  

```
❯ uv run lovely-devin-permissions -t 'echo $(ls $(echo hi))'
{
  "decision": "approve",
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "updatedInput": {
      "command": ": '[♡ perms: 💚 auto-approved] command matches allowed pattern ^echo(\\s+.*)?$.' ; echo $(ls $(echo hi))"
    }
  }
}
```


> [!NOTE]
> We have another CLI, `uv run lovely-bash-inspection` that seemingly has better logic to detect subshells and nested subshells:

```
❯ uv run lovely-bash-inspection --string 'echo $(ls $(echo hi))'
statement 1 `echo $(ls $(echo hi))`:
  cmd: echo
  args: $(...)
    cmd: ls
    args: $(...)
      cmd: echo
      args: hi

Variables: yes
Pipes:     no
```
