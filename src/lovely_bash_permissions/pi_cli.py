"""``lovely-pi-bash-permissions`` - the bash permission server for the Pi extension.

The client is `lovely-pi-permissions <https://github.com/jftlo/lovely-pi-permissions>`_,
a TypeScript Pi extension. This CLI is the Python half. The two are never the
same thing and are never referred to interchangeably.

Two surfaces, and nothing else (D9):

- **server mode** (no flags): reads newline-delimited JSON requests on stdin and
  writes exactly one response line per request on stdout, until EOF. This is
  what the extension drives, for bash tool calls only.
- **``--test``**: evaluates one command against one config and exits. A
  developer tool, not part of the protocol.

**This process resolves nothing and loads nothing in server mode.** Config
discovery, deep-merge and mode selection belong to the extension (D1); the
extension sends a resolved bash block and this side validates and evaluates it.
The one exception is ``--test``, which may unwrap a mode container because a
developer pointing it at the extension's own config file needs to, and because
it is not the protocol - see :func:`_load_test_config`.

The wire protocol, version 1:

    -> {"op": "evaluate", "command": "...", "config": {...}, "top_level": "allow"}
    -> {"op": "validate", "config": {...}}
    <- {"protocol": 1, "action": "allow", "reason": "...", "reasons": [...]}
    <- {"protocol": 1, "valid": true}
    <- {"protocol": 1, "valid": false, "error": "..."}

``protocol`` is on *every* response, not just ``validate``, so the client can
assert it on the first exchange it sees whichever op it sent - which is the case
that matters when the extension and the installed binary come from different
install attempts.

``top_level`` is required on ``evaluate`` and carries the *mode's* wildcard. A
bash block that declares no ``*`` of its own is not a policy: it cannot express
"this mode says allow" to a process that never saw the mode, and without it the
D6 fallback chain breaks at the seam, in the permissive direction.

``validate`` covers the bash block only. The extension's non-bash tools and
``doom_loop`` never reach this process, so its TypeScript-side level check is
their *only* validation and must not be consolidated into this one.

POSIX-only. ``find_shfmt`` searches a venv's ``bin/`` and the bare name; a
Windows pipx venv puts the binary in ``Scripts/`` and nothing here looks
there. Rather than half-support it, the failure is made loud instead: ``validate``
probes for the binary and reports it, so an unfindable shfmt blocks all bash
(D8) instead of silently allowing everything.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, NoReturn

from . import decide
from .config.jsonc import parse_jsonc, read_jsonc_file
from .config.schema import VALID_BASH_CONFIG_KEYS, ToolConfig
from .parser import find_shfmt

#: Bumped only for a breaking wire change. The client asserts it during the
#: handshake and reports a mismatch at `session_start` - never per command.
PROTOCOL_VERSION = 1

#: Exit codes, matching `lovely-devin-permissions` so the two CLIs agree:
#: a verdict is 0 or 2, and "no verdict at all" is 1. A script must be able to
#: tell "the policy denies this" from "I handed you the wrong file".
EXIT_VERDICT = 0
EXIT_USAGE = 1
EXIT_DENY = 2

#: Every error this process returns names the fix, and stops there. The client
#: appends the same closing line to all four of its startup failures - "All bash
#: commands are blocked until this is fixed." - because D8 blocks all bash *by
#: design* and without it a blocked shell reads as a misconfigured policy
#: rather than a setup error. That line is the client's to print, not this
#: process's, so this side supplies only what failed and the one command that
#: fixes it.

#: The wire key that carries a block's default level. Read here, written by the
#: schema as an alias; never as the field name.
WILDCARD_KEY = "*"


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------


def _fail(message: str) -> NoReturn:
    """A no-verdict outcome: usage, unreadable input, or an unusable config.

    The block reason stays a short constant naming the category and the fix.
    A traceback in there would land in the model's context on every blocked
    command and leak absolute paths into the conversation; stderr carries that,
    for a human, once.
    """
    print(f"lovely-pi-bash-permissions: {message}", file=sys.stderr)
    sys.exit(EXIT_USAGE)


def _parse_bash_config(config: object) -> ToolConfig:
    """Validate a raw bash block, or exit(1) with the validator's own message.

    An unvalidated policy is never evaluated. The message is Python's verbatim:
    the extension prefixes it with the mode and file it came from, because
    Python has no idea which of five files produced it.
    """
    try:
        return ToolConfig.model_validate(config)
    except ValueError as exc:
        _fail(f"invalid bash config: {_pydantic_message(exc)}")


def _pydantic_message(exc: ValueError) -> str:
    """The human half of a pydantic error, without the type/URL noise.

    A pydantic `ValidationError` string carries `type=value_error` and a docs
    link per error, which are for a developer reading a traceback. The
    extension puts this string in front of a user, so it is trimmed to the
    message itself.
    """
    errors = getattr(exc, "errors", None)
    if not callable(errors):
        return str(exc)
    return "; ".join(str(error.get("msg", "")) for error in errors())


def _config_as_dict(config: ToolConfig) -> dict[str, Any]:
    """The validated block, in the spelling the evaluator reads and renders.

    Three things have to be right here, and each has a visible failure:

    - `by_alias`, or the block comes back keyed `wildcard` and the level is
      invisible to `resolve_bash_config`.
    - `mode="json"`, or every level stays a `PermissionLevel` member. It
      compares equal to its string value, so the policy still works, but the
      evaluator renders it into a reason string and the user reads
      `wildcard policy is PermissionLevel.deny`.
    - `exclude_none`, because a resolved dict carries only the keys that were
      set; an explicit `None` would read as a declared-but-empty level.
    """
    return config.model_dump(mode="json", by_alias=True, exclude_none=True)


# ---------------------------------------------------------------------------
# Ops
# ---------------------------------------------------------------------------


def op_validate(config: object) -> dict[str, Any]:
    """`{"op": "validate", "config": {...}}` -> is this bash block usable?

    Reports the validator's message verbatim, so the extension can prefix the
    *where* and leave the *what* to this side.
    """
    try:
        ToolConfig.model_validate(config)
    except ValueError as exc:
        return {"protocol": PROTOCOL_VERSION, "valid": False, "error": _pydantic_message(exc)}

    # The binary is probed here, not lazily, and that is the whole reason this
    # op exists separately. A missing shfmt is not a crash: the server spawns
    # fine, the handshake passes, and every command then routes through the
    # `error` policy instead - which under `{"*": "allow"}` is `allow`. The
    # process looks healthy while the shell is wide open, and the only clue is
    # a reason string mentioning a parse failure. Shfmt is a bare Go binary
    # that `shfmt-py` drops into the venv's `bin/`; there is no import that
    # could fail instead, so the probe has to be explicit.
    #
    # The message names the *providing package*, because "binary not found"
    # alone does not say what to do - shfmt is not a separate install.
    try:
        find_shfmt()
    except (OSError, ValueError) as exc:
        return {
            "protocol": PROTOCOL_VERSION,
            "valid": False,
            "error": (
                "the shfmt binary required to parse bash commands was not found. "
                "It is provided by the shfmt-py package that lovely-pi-bash-permissions "
                "depends on. Reinstall that package, or point the extension's binary path "
                f"at a working install. ({exc})"
            ),
        }
    return {"protocol": PROTOCOL_VERSION, "valid": True}


def op_evaluate(command: object, config: object, top_level: object) -> dict[str, Any]:
    """`{"op": "evaluate", ...}` -> the verdict and its reasons.

    An invalid config answers `deny` rather than an error object: the client
    blocks every call on this response either way, and a verdict shape it
    already understands is one fewer thing to get wrong at the seam.
    """
    try:
        validated = ToolConfig.model_validate(config)
    except ValueError as exc:
        return {
            "protocol": PROTOCOL_VERSION,
            "action": "deny",
            "reason": f"invalid bash config: {_pydantic_message(exc)}",
            "reasons": [f"invalid bash config: {_pydantic_message(exc)}"],
        }

    if not isinstance(command, str):
        return {
            "protocol": PROTOCOL_VERSION,
            "action": "deny",
            "reason": "evaluate: 'command' must be a string",
            "reasons": ["evaluate: 'command' must be a string"],
        }

    level = top_level if isinstance(top_level, str) and top_level else "ask"
    decision = decide.decide_bash_command(command, _config_as_dict(validated), level)
    return {
        "protocol": PROTOCOL_VERSION,
        "action": decision["action"],
        "reason": decision["reason"],
        "reasons": decision["reasons"],
    }


def handle_request(request: dict[str, Any]) -> dict[str, Any]:
    """One request dict -> one response dict. Never raises.

    The invariant is one response line per request line, always. A request this
    cannot answer gets an error response and the stream continues: a desync
    would silently misalign every verdict after it, and a crash would take the
    extension's shell down with the server.
    """
    op = request.get("op")
    if op == "evaluate":
        return op_evaluate(request.get("command"), request.get("config"), request.get("top_level"))
    if op == "validate":
        return op_validate(request.get("config"))
    return {
        "protocol": PROTOCOL_VERSION,
        "valid": False,
        "error": f"unknown op {op!r}; expected 'evaluate' or 'validate'",
    }


# ---------------------------------------------------------------------------
# Server mode
# ---------------------------------------------------------------------------


def serve(source: Any = None, sink: Any = None) -> int:  # noqa: ANN401 - any readable line source, any writable text sink
    """Read requests until EOF, writing one response line each.

    `print(..., flush=True)` on every response, because stdout is a pipe and
    therefore block-buffered: a long-lived server that does not flush looks
    hung from the client's side, and the client is holding a 10 s timeout.
    """
    lines = source if source is not None else sys.stdin
    out = sink if sink is not None else sys.stdout
    for line in lines:
        if not line.strip():
            continue
        try:
            request = json.loads(line)
        except ValueError as exc:
            response: dict[str, Any] = {
                "protocol": PROTOCOL_VERSION,
                "valid": False,
                "error": f"malformed request: {exc}",
            }
        else:
            if not isinstance(request, dict):
                response = {
                    "protocol": PROTOCOL_VERSION,
                    "valid": False,
                    "error": "malformed request: expected a JSON object",
                }
            else:
                try:
                    response = handle_request(request)
                except Exception as exc:  # noqa: BLE001 - one bad request must not end the session
                    print(f"lovely-pi-bash-permissions: {type(exc).__name__}: {exc}", file=sys.stderr)
                    response = {
                        "protocol": PROTOCOL_VERSION,
                        "valid": False,
                        "error": f"internal error: {type(exc).__name__}: {exc}",
                    }
        try:
            out.write(json.dumps(response, ensure_ascii=False) + "\n")
            out.flush()
        except BrokenPipeError:
            # The client went away mid-session - it timed out, or the user quit.
            # That is a normal end, not a crash: exiting quietly here matters
            # because the client is holding a 10 s timeout and a traceback on
            # stderr at this exact moment is the one thing it would report as a
            # server fault. Note that `flush` can raise on a *later* write, so
            # the interpreter's own shutdown flush has to be silenced too -
            # otherwise it prints "Exception ignored" and an error code after
            # this returns.
            _silence_interpreter_flush()
            return EXIT_VERDICT
    return EXIT_VERDICT


def _silence_interpreter_flush() -> None:
    """Point stdout at devnull so the interpreter's exit-time flush is quiet.

    Python flushes ``sys.stdout`` during shutdown even after the stream has
    failed, and prints ``BrokenPipeError ... Exception ignored in: <_io...>``
    plus a non-zero exit. Redirecting the real stdout to ``os.devnull`` is the
    documented way to avoid it; ``sys.stdout`` is a separate wrapper object, so
    it is reassigned too.
    """
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
    except (OSError, ValueError):  # pragma: no cover - a stdout with no fileno
        pass
    sys.stdout = open(os.devnull, "w")  # noqa: SIM115 - must live for the process


# ---------------------------------------------------------------------------
# --test
# ---------------------------------------------------------------------------


def _looks_like_mode_wrapped(data: dict[str, Any]) -> bool:
    """Is this a `{"<mode>": {"<tool>": {...}}}` file rather than a bash block?

    Detected structurally, not by asking the schema. `PermissionsConfig` is
    permissive at the root, so a mode container parses without complaint and
    `bash` comes back `None` - and the failure mode is silent and confident:
    the evaluator runs on an empty policy and reports `ask` for everything,
    which is indistinguishable from a correct pessimistic policy.

    The discriminator is that a Pi config's top-level values are *all* mode
    objects, and that none of its keys is a key a bash block may carry. The
    second clause is what keeps `{"output_redirection": {"other": "deny"}}` -
    one key, one dict value, a perfectly ordinary bash block - on the bash
    side of the line.
    """
    if not data or any(key in VALID_BASH_CONFIG_KEYS for key in data):
        return False
    return all(isinstance(value, dict) for value in data.values())


def _parse_config_text(text: str, source: str) -> dict[str, Any]:
    """Parse config text as JSONC, exactly as the file route does.

    The same parser for both routes is the point: a comment or a trailing
    comma is legal in a file the user wrote and illegal in one piped to
    ``--test``, and the difference would read as a bug in the tool.
    """
    try:
        data = parse_jsonc(text)
    except ValueError as exc:
        _fail(f"cannot parse config from {source}: {exc}")
    if not isinstance(data, dict):
        _fail(f"config from {source} is not a JSON object, so there is no bash block in it")
    return data


def _load_test_config(path: str | None, mode: str | None) -> tuple[dict[str, Any], str]:
    """Read a bash block and its top-level wildcard, for ``--test`` only.

    A path is read **as-is**: never located, never discovered, never merged.
    Two reasons, and they are the same reason. Config resolution belongs to the
    extension (D1), so resolving the three Pi locations here would put a second
    resolver in the tree - the exact seam the split exists to build. And it
    could not reproduce what the extension uses anyway: the extension
    concatenates arrays and selects a mode before Python sees a block, so a
    merge here would be a *different* config from the one under test. Debugging
    a rejection against a policy that was never in force is worse than no
    merge at all.

    Unwrapping a mode container is host-shape knowledge that brushes D1, which
    is why it lives here and not in the server. Teaching the server about
    modes would undo D1.

    Returns the bash block and the wildcard the mode supplies for it.
    """
    if path is None:
        source = "<stdin>"
        data = _parse_config_text(sys.stdin.read(), source)
    else:
        source = path
        result = read_jsonc_file(path)
        if result.error is not None or not isinstance(result.value, dict):
            _fail(f"cannot read config from {path}: {result.error or 'not a JSON object'}")
        data = result.value

    wildcard = data.get(WILDCARD_KEY)
    top_level = wildcard if isinstance(wildcard, str) and wildcard else "ask"

    if _looks_like_mode_wrapped(data):
        modes = [key for key, value in data.items() if isinstance(value, dict)]
        chosen = mode if mode is not None else (modes[0] if modes else "")
        if chosen not in data or not isinstance(data[chosen], dict):
            _fail(f"unknown mode {chosen!r} in {source}; available modes: {', '.join(repr(m) for m in modes)}")
        print(f"using mode {chosen!r} from {source}", file=sys.stderr)
        selected: dict[str, Any] = data[chosen]
        mode_block = selected.get("bash")
        if not isinstance(mode_block, dict):
            _fail(
                f"mode {chosen!r} in {source} has no 'bash' block. "
                f"This tool evaluates bash commands, and a mode without one is not a policy - "
                f"refusing to answer rather than reporting 'ask' for everything."
            )
        # A mode is {"<mode>": {"*": ..., "bash": {...}}}, and that mode-level
        # "*" is exactly the fallback a bash block's own missing "*" resolves
        # against. Omitting it here would make --test disagree with what the
        # live extension does: a mode of {"*": "allow", "bash": {...}} would
        # report ask while the extension reports allow.
        wildcard = selected.get(WILDCARD_KEY)
        return mode_block, (wildcard if isinstance(wildcard, str) and wildcard else "ask")

    if mode is not None:
        _fail(f"--mode {mode!r} was given, but {source} is a bare bash block, not a mode-wrapped file")
    if isinstance(data.get("bash"), dict):
        # A whole PermissionsConfig file, the shape a Devin user has. Taking
        # its bash block is unambiguous; a bare block has no "bash" key.
        return dict(data["bash"]), top_level
    return dict(data), top_level


def run_test(command: str, path: str | None, mode: str | None) -> int:
    """Evaluate one command against one config file (or stdin) and exit.

    Both routes land in the same validator and the same call into
    :func:`decide.decide_bash_command`; there is exactly one code path into the
    decision here, or `--test` would be testing something the server does not
    do.
    """
    if not command.strip():
        _fail("no command given")
    config, top_level = _load_test_config(path, mode)
    validated = _parse_bash_config(config)
    decision = decide.decide_bash_command(command, _config_as_dict(validated), top_level)
    for reason in decision["reasons"]:
        print(f"- {reason}")
    print(f"{decision['action']}: {decision['reason']}")
    return EXIT_DENY if decision["action"] == "deny" else EXIT_VERDICT


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="lovely-pi-bash-permissions",
        description=(
            "Bash permission decisions for the lovely-pi-permissions Pi extension. "
            "With no arguments, serves newline-delimited JSON on stdin/stdout. "
            "--test evaluates a single command and exits."
        ),
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help=(
            "Evaluate one COMMAND against a config and exit (0 allow/ask, 2 deny, 1 no verdict). "
            "A flag, not an option with a value, so that "
            '`--test --mode strict "git status"` parses - argparse refuses an '
            "option-looking token as another option's value, which silently ate the command."
        ),
    )
    parser.add_argument(
        "command",
        nargs="?",
        help="With --test: the bash command to evaluate.",
    )
    parser.add_argument(
        "config",
        nargs="?",
        help=(
            "With --test: a path to a config file, read exactly as given - never located, "
            "discovered or merged. Accepts a bare bash block, a whole PermissionsConfig, or a "
            "mode-wrapped Pi config. Read from stdin when omitted."
        ),
    )
    parser.add_argument(
        "--mode",
        metavar="NAME",
        help="With --test: which mode of a mode-wrapped config to use. Defaults to the first.",
    )
    args = parser.parse_args()

    if not args.test:
        if args.command is not None or args.config is not None or args.mode is not None:
            _fail("a command, a config path and --mode only apply to --test; run the server with no arguments")
        sys.exit(serve())

    if args.command is None:
        _fail("--test needs a command to evaluate")

    if not sys.stdin.isatty() or args.config is not None:
        sys.exit(run_test(args.command, args.config, args.mode))

    # No path and nothing on stdin: waiting on a terminal for a config would
    # look like a hang. Say what is needed and exit non-zero.
    _fail("no config given: pass a path, or pipe a config on stdin")


if __name__ == "__main__":
    main()
