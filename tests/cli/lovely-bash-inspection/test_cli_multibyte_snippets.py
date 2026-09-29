"""Statement snippets must survive non-ASCII source text.

shfmt reports positions as **byte** offsets into the UTF-8 source, while the
snippet is sliced out of a ``str`` indexed by code point.  Before the fix the
``str`` was sliced with a byte offset, so a single non-ASCII character
anywhere earlier in the command shifted (and truncated) every later
statement's snippet - ``echo ✓; ls`` reported statement 2 as an empty string,
and ``echo "héllo"; ls # 日本語`` reported it as a single stray character.

These tests pin the snippets, not the rendering in general; see
``test_cli.py`` for redirection placement and ``test_words_output.py`` for
value-word output.
"""

import pytest

from lovely_bash_permissions.cli import main

# Deliberately not ASCII letters, so a byte/character offset mismatch is
# visible: 'e' is 1 byte, '✓' is 3, 'é' is 2, '日' is 3.
_MULTIBYTE = "✓"
_ACCENTED = "héllo wörld"
_CJK = "日本語"


def _snippets(capsys: pytest.CaptureFixture[str]) -> list[str]:
    """Return the ``statement N `...` `` headers, in order."""
    return [line for line in capsys.readouterr().out.splitlines() if line.startswith("statement ")]


def _snippet_texts(capsys: pytest.CaptureFixture[str]) -> list[str]:
    """Return just the quoted source text of each statement header."""
    out = []
    for line in _snippets(capsys):
        start = line.find("`") + 1
        end = line.rfind("`")
        out.append(line[start:end] if start and end > start else "")
    return out


class TestStatementSnippetsWithMultibyteSource:
    """A non-ASCII character must not shift later statements' snippets."""

    def test_ascii_source_is_unchanged(self, capsys: pytest.CaptureFixture[str]) -> None:
        main(["--string", "echo hi; ls"])
        assert _snippet_texts(capsys) == ["echo hi;", "ls"]

    def test_multibyte_before_a_later_statement(self, capsys: pytest.CaptureFixture[str]) -> None:
        # The slice must start at the real character index, not three bytes
        # past it, or the second snippet comes back empty.
        main(["--string", f"echo {_MULTIBYTE}; ls"])
        assert _snippet_texts(capsys) == [f"echo {_MULTIBYTE};", "ls"]

    def test_accented_and_cjk_source(self, capsys: pytest.CaptureFixture[str]) -> None:
        main(["--string", f'echo "{_ACCENTED} {_MULTIBYTE}"; ls # {_CJK}'])
        assert _snippet_texts(capsys) == [f'echo "{_ACCENTED} {_MULTIBYTE}";', "ls"]

    def test_many_statements_after_multibyte(self, capsys: pytest.CaptureFixture[str]) -> None:
        main(["--string", f"echo {_MULTIBYTE}; ls; pwd; date"])
        assert _snippet_texts(capsys) == [f"echo {_MULTIBYTE};", "ls;", "pwd;", "date"]

    def test_multibyte_in_a_single_statement(self, capsys: pytest.CaptureFixture[str]) -> None:
        main(["--string", f'echo "{_MULTIBYTE}{_CJK}"'])
        assert _snippet_texts(capsys) == [f'echo "{_MULTIBYTE}{_CJK}"']

    def test_multibyte_does_not_disturb_command_rendering(self, capsys: pytest.CaptureFixture[str]) -> None:
        # The command/args lines were always correct (they come from the AST,
        # not from source offsets) - assert they stay correct alongside.
        main(["--string", f'echo "{_ACCENTED}"; ls'])
        lines = capsys.readouterr().out.splitlines()
        assert "  cmd: echo" in lines
        assert f"  args: {_ACCENTED}" in lines
        assert "  cmd: ls" in lines
