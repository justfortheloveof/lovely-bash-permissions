"""The policy vocabulary, declared once.

Every bash construct the permission evaluator can gate, and every output
redirection kind it can classify, is named here and nowhere else. The schema
validates against these tuples, the effective-config builder resolves from them,
and the evaluator builds its rules from them, so a key cannot be added to one
place and forgotten in the others.

That forgetting is not hypothetical. ``ToolConfig.permission`` was a declared
config field with no reader anywhere in the product: it validated cleanly,
changed no verdict, and nobody noticed. The cause was structural - the key
list was written out three times, by hand, in three modules, with nothing
tying the copies together. One declaration removes the possibility rather than
testing for it.

This module holds data (plus one trivial accessor) and imports nothing from
the package, so the library half and the Devin half can both depend on it
without a cycle.

``error`` is deliberately absent. It is a level-bearing key and the docs group
it with the others, but it is not gated per construct: it is read by the hook
when a command cannot be analysed *at all*, before any of the constructs below
are considered. :data:`NON_CONSTRUCT_KEYS` names the keys that are resolved
here but read elsewhere.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final, Literal

#: A permission level, in this product's vocabulary. ``block`` is Devin's wire
#: word and is deliberately not one of these.
Level = Literal["allow", "ask", "deny"]

#: The level every unset wildcard falls back to.
DEFAULT_LEVEL: Final[Level] = "ask"

#: The wire key that carries a block's default level.
WILDCARD_KEY: Final = "*"


def wildcard_level(block: Mapping[str, Any]) -> Any:  # noqa: ANN401 - config values are unvalidated
    """The block's ``*`` level, or :data:`DEFAULT_LEVEL` when the key is absent.

    ``.get`` semantics, not ``or``: an explicitly empty wildcard is returned as
    written, exactly as every call site this replaced behaved.
    """
    return block.get(WILDCARD_KEY, DEFAULT_LEVEL)


#: Constructs the evaluator gates individually, each overridable by a config
#: key of the same name. Order is alphabetical.
POLICY_KEYS: Final[tuple[str, ...]] = (
    "background_execution",
    "command_substitution",
    "input_redirection",
    "output_redirection",
    "process_substitution",
    "subshell",
    "variable_assignment",
)

#: Level-bearing config keys that are resolved alongside :data:`POLICY_KEYS` but
#: are not per-construct policies.
NON_CONSTRUCT_KEYS: Final[tuple[str, ...]] = ("error",)

#: Kinds :func:`lovely_bash_permissions.rules.classify_output_redirection` sorts
#: an output redirection into. ``other`` is the catch-all - every write that is
#: neither a dev-null discard nor an fd duplication - and is configurable in
#: its own right, which is what makes it distinct from the ``*`` wildcard:
#: ``{"stdout_to_dev_null": "allow", "other": "allow"}`` permits a command that
#: mixes both, where ``{"stdout_to_dev_null": "allow", "*": "deny"}` does not.
OUTPUT_REDIRECTION_KINDS: Final[tuple[str, ...]] = (
    "other",
    "stderr_to_dev_null",
    "stderr_to_stdout",
    "stdout_to_dev_null",
)

#: Config keys that are not level-bearing policies, spelled **as they appear in a
#: config file** - ``*``, not the ``wildcard`` field name.
#:
#: The wire spelling is what a ``mode="before"`` validator sees when it checks a raw
#: dict for unknown keys, so the wire spelling is what must be declared here. The
#: field name (``wildcard``) is only the *alias* for ``*``; every consumer in this
#: package compares against aliases, never against field names. See D11.
WIRE_NON_POLICY_CONFIG_KEYS: Final[frozenset[str]] = frozenset({"allowed_cmds_regex", "blocked_cmds_regex", "*"})
