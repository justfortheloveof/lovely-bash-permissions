"""Tests for the word renderers."""

from lovely_bash_permissions.ast import CmdSubst, DblQuoted, Lit, ParamExp, SglQuoted, Word
from lovely_bash_permissions.words import word_exec


class TestWordExec:
    """Test word_exec() - the executed-form renderer (quotes removed,
    backslashes unescaped bash-style, expansion placeholders kept)."""

    def test_quote_split_path(self) -> None:
        word = Word(parts=[Lit(value="/e"), DblQuoted(parts=[Lit(value="tc")], value=None), Lit(value="/passwd")])
        assert word_exec(word) == "/etc/passwd"

    def test_backslash_escaped_flag(self) -> None:
        # shfmt parses `find /tmp -ex\ec` as a single Lit with a backslash
        # literal; unquoted backslash drops the next character.
        word = Word(parts=[Lit(value=r"-ex\ec")])
        assert word_exec(word) == "-exec"

    def test_double_quoted_backslash_t_stays(self) -> None:
        # Inside "..." bash only unescapes $ ` " \ and newline, so a
        # backslash-t keeps its backslash.
        word = Word(parts=[DblQuoted(parts=[Lit(value="/e\tc/passwd")], value=None)])
        assert word_exec(word) == "/e\tc/passwd"

    def test_single_quoted_verbatim(self) -> None:
        # Single quotes: content is verbatim, no unescaping.
        word = Word(parts=[SglQuoted(value='"a\b"')])
        assert word_exec(word) == '"a\b"'

    def test_param_exp_placeholder(self) -> None:
        word = Word(parts=[ParamExp(param="DIR"), Lit(value="/out.txt")])
        assert word_exec(word) == "$DIR/out.txt"

    def test_cmd_subst_placeholder(self) -> None:
        word = Word(parts=[CmdSubst(), Lit(value="/x")])
        assert word_exec(word) == "$(...)/x"

    def test_plain_literal(self) -> None:
        word = Word(parts=[Lit(value="hello")])
        assert word_exec(word) == "hello"

    def test_nested_double_quotes(self) -> None:
        # Adjacent double-quoted regions ("/dev""/null") render as the
        # concatenated content.
        word = Word(
            parts=[DblQuoted(parts=[Lit(value="/dev"), DblQuoted(parts=[Lit(value="/null")], value=None)], value=None)]
        )
        assert word_exec(word) == "/dev/null"

    def test_double_quoted_with_expansion(self) -> None:
        # "..." with a nested ParamExp: placeholder kept, backslash rules
        # applied to the nested Lit in double-quote context.
        word = Word(parts=[DblQuoted(parts=[ParamExp(param="DIR"), Lit(value="/out.txt")], value=None)])
        assert word_exec(word) == "$DIR/out.txt"
