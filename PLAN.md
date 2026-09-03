# Plan:

## Objective

We MUST fix this issue, where what gets added to the config file has an escaped unicode char instead of the char itself.

This is how I reproduced the issue:

```
❯ rm ~/.config/devin/config.json

❯ cat ~/.config/devin/config.json
cat: /home/alx/.config/devin/config.json: No such file or directory

✗ uv run lovely-devin-permissions -s
Added "Exec(: '[♡ perms:)" to /home/alx/.config/devin/config.json so Devin auto-approves the hook's ":" no-op label

❯ cat ~/.config/devin/config.json
{
  "permissions": {
    "allow": [
      "Exec(: '[\u2661 perms:)"
    ]
  }
}
```
```
```
