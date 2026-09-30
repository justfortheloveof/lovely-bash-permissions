"""``lovely-pi-bash-permissions`` - bash permission decisions for the Pi extension.

The client is `lovely-pi-permissions <https://github.com/jftlo/lovely-pi-permissions>`_,
a TypeScript Pi extension. This CLI is the Python half. The two are never the
same thing and are never referred to interchangeably.

Two surfaces, plus one developer flag (D9):

- **the protocol path** (no flags): reads one JSON request from stdin, writes
  one JSON response to stdout, and exits. This is what the extension drives,
  for bash tool calls only.
- **``--test``**: evaluates one command against one config and exits. A
  developer tool, not part of the protocol.
- **``--print-schema``**: prints the JSON Schema of a bash block and exits. It
  is what the extension's contract test reads, so the two repositories'
  config vocabularies cannot drift apart silently. Not part of the protocol.

**One process, one request, one response.** There is no long-lived server and
no stream to keep aligned: the extension spawns this binary per call and reads
the single response object it produces. That is why ``op`` still exists (there
are two operations, and the client must say which) while a *sequence* of
requests has no meaning here at all.

**This process resolves nothing and loads nothing in the protocol path.** Config
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
from .policy import WILDCARD_KEY

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

# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------


def _response(**fields: Any) -> dict[str, Any]:  # noqa: ANN401 - any JSON value
    """A response object: ``protocol`` first, then *fields*, in order."""
    return {"protocol": PROTOCOL_VERSION, **fields}


def _error(message: str) -> dict[str, Any]:
    """A response for a request this process could not answer."""
    return _response(valid=False, error=message)


def _deny(reason: str) -> dict[str, Any]:
    """An ``evaluate`` response that denies, with one reason."""
    return _response(action="deny", reason=reason, reasons=[reason])


def _level_or_ask(value: object) -> str:
    """*value* when it is a non-empty string, else ``"ask"``.

    Used for the wildcards this side reads before any validation. Only the
    type is checked here: the value itself is validated where it is used.
    """
    return value if isinstance(value, str) and value else "ask"


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
        return _error(_pydantic_message(exc))

    # The binary is probed here, not lazily, and that is the whole reason this
    # op exists separately. A missing shfmt is not a crash: this process starts
    # fine and every `evaluate` then asks (see `decide.error_action`), so the
    # user is prompted for every command with no hint why until the reason is
    # read. Reporting it once, at session start, is what makes it visible. Shfmt is a bare Go binary
    # that `shfmt-py` drops into the venv's `bin/`; there is no import that
    # could fail instead, so the probe has to be explicit.
    #
    # The message names the *providing package*, because "binary not found"
    # alone does not say what to do - shfmt is not a separate install.
    try:
        find_shfmt()
    except (OSError, ValueError) as exc:
        return _error(
            "the shfmt binary required to parse bash commands was not found. "
            "It is provided by the shfmt-py package that lovely-pi-bash-permissions "
            "depends on. Reinstall that package, or point the extension's binary path "
            f"at a working install. ({exc})"
        )
    return _response(valid=True)


def op_evaluate(command: object, config: object, top_level: object) -> dict[str, Any]:
    """`{"op": "evaluate", ...}` -> the verdict and its reasons.

    An invalid config answers `deny` rather than an error object: the client
    blocks every call on this response either way, and a verdict shape it
    already understands is one fewer thing to get wrong at the seam.
    """
    try:
        validated = ToolConfig.model_validate(config)
    except ValueError as exc:
        return _deny(f"invalid bash config: {_pydantic_message(exc)}")

    if not isinstance(command, str):
        return _deny("evaluate: 'command' must be a string")

    decision = decide.decide_bash_command(command, _config_as_dict(validated), _level_or_ask(top_level))
    return _response(action=decision["action"], reason=decision["reason"], reasons=decision["reasons"])


def handle_request(request: dict[str, Any]) -> dict[str, Any]:
    """One request dict -> one response dict. Never raises.

    A request this cannot answer gets an error response rather than an
    exception. There is no stream to protect any more, but the reason the
    invariant survives is unchanged in spirit: a crash here would produce no
    response at all, and the client has to distinguish "I asked something
    unanswerable" from "the engine died", which it can only do if this never
    raises.
    """
    op = request.get("op")
    if op == "evaluate":
        return op_evaluate(request.get("command"), request.get("config"), request.get("top_level"))
    if op == "validate":
        return op_validate(request.get("config"))
    return _error(f"unknown op {op!r}; expected 'evaluate' or 'validate'")


# ---------------------------------------------------------------------------
# The protocol path
# ---------------------------------------------------------------------------


def run_once(source: Any = None, sink: Any = None) -> int:  # noqa: ANN401 - any readable text source, any writable text sink
    """Read one request, write one response, and return the exit code.

    All of stdin is read, not one line, and that is deliberate. A client that
    sent two requests would have its whole payload fail to parse and get one
    honest error, rather than have this process silently answer the first and
    discard the second - which is the whole class of misalignment a stream used
    to allow and no longer can.

    The verdict is in the response body, never in the exit code. The exit code
    answers a different question - did this process manage to produce a
    response object at all - so a ``deny`` verdict is 0 (a decision was
    produced) and only an internal failure is 1.
    """
    inp = source if source is not None else sys.stdin
    out = sink if sink is not None else sys.stdout

    response, exit_code = _answer(inp.read())
    # One small object into a pipe buffer that will not be read until this
    # returns, so there is nothing to flush for - but the read end may already
    # be gone anyway. The client kills this process on a request timeout and on
    # `session_shutdown`, and either can land during the write. That used to be
    # a narrow window in a long-lived server answering on a timer; it is narrower
    # now, but not closed, and an unhandled EPIPE would turn a missing response
    # into a traceback and a non-zero exit - which the client reads as an
    # engine failure and routes through the `error` policy. A reader that has
    # already gone away is not a policy event, so it exits 0 and says nothing.
    try:
        out.write(json.dumps(response, ensure_ascii=False) + "\n")
        out.flush()
    except BrokenPipeError:
        # `flush` can raise on a *later* write, so the interpreter's own
        # shutdown flush has to be silenced too - otherwise it prints
        # "Exception ignored" and an error code after this returns.
        _silence_interpreter_flush()
        return EXIT_VERDICT
    return exit_code


def _answer(raw: str) -> tuple[dict[str, Any], int]:
    """The response to one raw request, and the exit code that goes with it."""
    if not raw.strip():
        # A hook with no input is normal and exits quietly; this is not a hook.
        # An empty request means the caller failed to write one, so say so
        # rather than answering "ask" for a command nobody sent.
        return _error(
            "no request on stdin: this process reads exactly one JSON request and answers it with one JSON response"
        ), EXIT_USAGE
    try:
        request = json.loads(raw)
    except ValueError as exc:
        return _error(f"malformed request: {exc}"), EXIT_USAGE
    if not isinstance(request, dict):
        return _error("malformed request: expected a JSON object"), EXIT_USAGE
    try:
        return handle_request(request), EXIT_VERDICT
    except Exception as exc:  # noqa: BLE001 - no response at all is worse than an error response
        print(f"lovely-pi-bash-permissions: {type(exc).__name__}: {exc}", file=sys.stderr)
        return _error(f"internal error: {type(exc).__name__}: {exc}"), EXIT_USAGE


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
    is why it lives here and not in the protocol path. Teaching the protocol
    path about modes would undo D1.

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

    top_level = _level_or_ask(data.get(WILDCARD_KEY))

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
        return mode_block, _level_or_ask(selected.get(WILDCARD_KEY))

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
    decision here, or `--test` would be testing something the protocol path
    does not do.
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
# --print-schema
# ---------------------------------------------------------------------------


def bash_config_schema() -> dict[str, Any]:
    """The JSON Schema of a bash block, keyed by wire names (``*``, not ``wildcard``).

    This is the vocabulary the extension's ``BashConfig`` type must match: a
    key the extension declares and this schema does not is rejected by
    ``validate``, and a key this schema accepts and the extension does not
    declare cannot be written without a type error.
    """
    return ToolConfig.model_json_schema(by_alias=True)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="lovely-pi-bash-permissions",
        description=(
            "Bash permission decisions for the lovely-pi-permissions Pi extension. "
            "With no arguments, reads one JSON request on stdin, writes one JSON response "
            "on stdout, and exits. --test evaluates a single command and exits."
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
    parser.add_argument(
        "--print-schema",
        action="store_true",
        help="Print the JSON Schema of a bash config block and exit. For the extension's contract test.",
    )
    args = parser.parse_args()

    if args.print_schema:
        if args.test or args.command is not None or args.config is not None or args.mode is not None:
            _fail("--print-schema takes no other arguments")
        print(json.dumps(bash_config_schema(), indent=2, ensure_ascii=False))
        sys.exit(EXIT_VERDICT)

    if not args.test:
        if args.command is not None or args.config is not None or args.mode is not None:
            _fail(
                "a command, a config path and --mode only apply to --test; run with no arguments to read one request on stdin"
            )
        sys.exit(run_once())

    if args.command is None:
        _fail("--test needs a command to evaluate")

    if not sys.stdin.isatty() or args.config is not None:
        sys.exit(run_test(args.command, args.config, args.mode))

    # No path and nothing on stdin: waiting on a terminal for a config would
    # look like a hang. Say what is needed and exit non-zero.
    _fail("no config given: pass a path, or pipe a config on stdin")


if __name__ == "__main__":
    main()
