# BUGZ

## TODO

Launch more agents to investigate parsing bugs, particularly with:
- input redir

## BUGZ-015: Here-string (`<<<`) bypasses the `input_redirection` policy

**Status:** open
**Area:** input redirection classification (`src/lovely_bash_permissions/rules.py`)

### Symptom

Input redirection via a here-string (`<<<`) is never classified as input
redirection, so the `input_redirection` policy (default `ask`) is not applied.
Other input-redirection forms — `< file`, `<<EOF`, `< <(...)`, `0< file`,
`(echo < a)` — all correctly trigger "input redirection requires approval".

Reproduction:

```console
$ uv run lovely-devin-permissions --test 'echo hello <<< "world"'
# 💚 auto-approved: command matches allowed pattern: ^echo(\s+.*)?$

$ uv run lovely-devin-permissions --test 'echo hello < file'
# 💛 REQUIRES-USER-APPROVAL: input redirection requires approval
```

### Root cause

shfmt emits here-strings as `Op: "<<<"` in its JSON AST, but both
input-redirection classifiers only check for `<` and `<<`:

- `_check_segments_input_redirs` — `src/lovely_bash_permissions/rules.py:543`
  (the path actually used by `evaluate_bash_command`):

  ```python
  if r.get("Op") in ("<", "<<"):
  ```

- `check_input_redirection` — `src/lovely_bash_permissions/rules.py:424`
  (same gap):

  ```python
  if op in ("<", "<<"):
  ```

A `<<<` redir is therefore dropped from `input_redirs`, the check returns
`matched: False` ("no input redirection"), and the command falls through to
allowed-pattern matching, where loose patterns like `^echo(\s+.*)?$` approve it.

### Consequences

- Any command containing a here-string is exempt from the
  `input_redirection` policy. In the default config (`subshell: ask`) a
  `$(…)` inside the here-string is still caught by the subshell walk, but with
  `subshell: allow` a nested command substitution in a `<<<` word (e.g.
  `echo <<< $(cmd)`) auto-approves where an equivalent `<`/`<<` redirection
  would require approval.
- The blocked-path check on redirection targets (`_find_blocked_path` over the
  collected `targets`) never sees here-string words, so a blocked path inside a
  `<<<` word is only caught incidentally by the whole-command string match,
  not by redirection-target policy.

### Fix

Include `<<<` in the operator sets in both places, e.g.:

```python
if r.get("Op") in ("<", "<<", "<<<"):   # _check_segments_input_redirs
if op in ("<", "<<", "<<<"):            # check_input_redirection
```

Nested input redirections such as `echo < <(cat a)` are already handled
correctly (outer op is `<` with a process-substitution word, whose contents are
walked separately); no change needed there.
