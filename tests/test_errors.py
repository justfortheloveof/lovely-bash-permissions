"""``user_message`` is what a user reads when a config will not validate.

The string it produces is a prompt bullet on the Devin side and an error field on
the Pi side, so it lands in a model's context. The developer's half of a pydantic
error - the docs URL, the ``type=``/``input_value=``/``input_type=`` block - is
for whoever is debugging the validator, and it used to arrive there whole.

The inputs are the product's own schemas rather than a toy model: the messages
under assertion are the ones a user with a real config file will read, and a toy
would only prove the helper works on pydantic.
"""

from typing import Any

from pydantic import ValidationError

from lovely_bash_permissions.config.schema import PermissionsConfig, ToolConfig
from lovely_bash_permissions.errors import ShfmtError, user_message

#: What the Devin half validates: a whole config file, so every location is
#: prefixed with ``bash.``. What Pi validates is a bare block, so its locations are
#: not - which is why the two hosts' prefixes differ and only their pydantic half
#: is comparable.
WHOLE_FILE = PermissionsConfig

#: A pattern that will not compile, which is the error a user is most likely to
#: hit and the one that used to carry the whole allow list into the message.
BAD_PATTERN: dict[str, Any] = {"bash": {"allowed_cmds_regex": ["["]}}

#: A misspelled level. pydantic's message names the three valid options and not
#: what the user wrote, which was only ever in the half being stripped.
BAD_LEVEL: dict[str, Any] = {"bash": {"*": "alow"}}


def _whole_file_error(config: dict[str, Any]) -> ValidationError:
    try:
        WHOLE_FILE.model_validate(config)
    except ValidationError as exc:
        return exc
    raise AssertionError("expected a ValidationError")


class TestTheStructuredRoute:
    """An object that has ``errors()`` is rendered from it, not from ``str()``."""

    def test_the_message_keeps_the_location(self) -> None:
        """Which key is wrong is the question the user has.

        The old Pi rendering kept only ``msg``, so a bad pattern in a file with
        eleven keys in it said what was wrong and not where.
        """
        message = user_message(_whole_file_error(BAD_PATTERN))
        assert "bash.allowed_cmds_regex" in message
        assert "unterminated character set" in message

    def test_the_documentation_noise_is_gone(self) -> None:
        """No docs URL, no type block, no count header."""
        message = user_message(_whole_file_error({"bash": {"allowed_cmds_regex": ["["], "*": "alow"}}))
        for noise in ("errors.pydantic.dev", "type=", "input_value", "input_type", "validation error"):
            assert noise not in message, noise

    def test_a_short_scalar_the_user_typed_is_echoed_back(self) -> None:
        """pydantic's enum message names the options but not what you wrote."""
        assert "alow" in user_message(_whole_file_error(BAD_LEVEL))

    def test_a_collection_is_not_echoed_back(self) -> None:
        """The leak itself: every pattern in the file, to report one bad one.

        ``input_value=['\\\\/etc', '\\\\.env$', '[']`` is the whole allow list,
        dumped into a prompt, for a single unterminated character set.
        """
        message = user_message(_whole_file_error({"bash": {"allowed_cmds_regex": ["\\/etc", "\\.env$", "["]}}))
        assert "\\/etc" not in message
        assert "\\.env$" not in message
        assert "unterminated character set" in message

    def test_a_bare_block_locates_its_keys_without_the_prefix(self) -> None:
        """Pi validates a block, so its locations are not ``bash.``-prefixed."""
        try:
            ToolConfig.model_validate({"allowed_cmds_regex": ["["]})
        except ValidationError as exc:
            message = user_message(exc)
        else:
            raise AssertionError("expected a ValidationError")
        assert message.startswith("allowed_cmds_regex: ")

    def test_several_errors_are_one_line(self) -> None:
        """A reason is a reason, not a document."""
        message = user_message(_whole_file_error({"bash": {"*": "alow", "allowed_cmds_regex": ["["]}}))
        assert "\n" not in message
        assert ";" in message


class TestTheTextRoute:
    """An exception that has already been through ``str()`` is cleaned as text.

    This is the shape the Devin half actually receives: ``config.manager``
    re-raises the loader's messages as a plain ``ValueError``, so there is no
    ``ValidationError`` left to ask for ``.errors()``. Asking only for the
    structured route no-ops on it, which is how the raw rendering reached a
    reason.
    """

    RAW = (
        "2 validation errors for PermissionsConfig\n"
        "bash.allowed_cmds_regex\n"
        '  Value error, pattern "[": invalid regex: unterminated character set at position 0'
        " [type=value_error, input_value=['\\\\/etc', '['], input_type=list]\n"
        "    For further information visit https://errors.pydantic.dev/2.13/v/value_error\n"
        "bash.star\n"
        "  Input should be 'allow', 'deny' or 'ask' [type=enum, input_value='alow', input_type=str]"
    )

    def test_the_noise_is_removed(self) -> None:
        message = user_message(ValueError(self.RAW))
        for noise in ("errors.pydantic.dev", "type=", "input_value", "input_type", "validation errors for"):
            assert noise not in message, noise
        assert "\\/etc" not in message

    def test_the_finding_and_its_location_survive(self) -> None:
        message = user_message(ValueError(self.RAW))
        assert "bash.allowed_cmds_regex: Value error, pattern" in message
        assert "unterminated character set" in message

    def test_it_is_one_line(self) -> None:
        assert "\n" not in user_message(ValueError(self.RAW))

    def test_it_is_idempotent(self) -> None:
        """A host that trims twice must not change the text the second time.

        The message is built trimmed in ``config.loader`` and then travels out
        through ``manager``'s plain ``ValueError``, where a host trims it again.
        Two passes have to be the same as one.
        """
        once = user_message(ValueError(self.RAW))
        assert user_message(ValueError(once)) == once

    def test_a_message_with_nothing_to_trim_is_untouched(self) -> None:
        assert user_message(ValueError("plain")) == "plain"


class TestOtherExceptions:
    """The function is total: anything renderable renders."""

    def test_a_parse_failure_keeps_its_message(self) -> None:
        exc = ShfmtError("shfmt timed out after 5s")
        assert user_message(exc) == "shfmt timed out after 5s"

    def test_an_empty_message_is_empty(self) -> None:
        assert user_message(ValueError("")) == ""
