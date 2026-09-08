"""Tests for JSONC parser."""

import os
import tempfile

import pytest

from lovely_bash_permissions.config.jsonc import (
    JSONCDecodeError,
    is_record,
    parse_jsonc,
    read_jsonc_file,
)


def _write_temp_file(content: str, suffix: str = ".jsonc") -> str:
    """Write content to a temporary file and return its path."""
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "w") as f:
        f.write(content)
    return path


def _clean_temp_file(path: str) -> None:
    """Remove a temporary file."""
    if os.path.exists(path):
        os.remove(path)


class TestParseJsonc:
    """Tests for parse_jsonc function."""

    def test_parse_valid_jsonc(self) -> None:
        """Valid JSONC with comments and trailing commas parses correctly."""
        result = parse_jsonc("""{
            // header comment
            "a": 1,
            /* block */
            "b": [2, 3,],
        }""")
        assert result == {"a": 1, "b": [2, 3]}

    def test_parse_invalid_jsonc(self) -> None:
        """Malformed JSONC raises JSONCDecodeError with line/column info."""

        def _try_parse(text: str) -> None:
            parse_jsonc(text)

        for bad in ("{invalid}", '{"a": }', "trailing, comma}"):
            err = pytest.raises(JSONCDecodeError, _try_parse, bad)
            assert err.value.line > 0
            assert err.value.column > 0

    def test_parse_with_bom(self) -> None:
        """File starting with BOM parses correctly."""
        result = parse_jsonc('\ufeff{"a": 1}')
        assert result == {"a": 1}

    def test_valid_json_object(self) -> None:
        result = parse_jsonc('{"a": 1, "b": 2}')
        assert result == {"a": 1, "b": 2}

    def test_valid_json_array(self) -> None:
        result = parse_jsonc("[1, 2, 3]")
        assert result == [1, 2, 3]

    def test_line_comments(self) -> None:
        result = parse_jsonc("""{
            // This is a comment
            "a": 1
        }""")
        assert result == {"a": 1}

    def test_block_comments(self) -> None:
        result = parse_jsonc("""{
            /* Block comment */
            "a": 1
        }""")
        assert result == {"a": 1}

    def test_inline_block_comments(self) -> None:
        result = parse_jsonc('{"a": 1 /* inline */ }')
        assert result == {"a": 1}

    def test_multiline_block_comments(self) -> None:
        result = parse_jsonc("""{
            /*
            Multi-line
            comment
            */
            "a": 1
        }""")
        assert result == {"a": 1}

    def test_trailing_commas(self) -> None:
        """Trailing commas in objects, arrays, and nested structures parse correctly."""
        result = parse_jsonc("""{
            "a": 1,
            "b": [2, 3,],
            "c": {
                "d": 4,
            },
        }""")
        assert result == {"a": 1, "b": [2, 3], "c": {"d": 4}}

    def test_bom_prefix(self) -> None:
        result = parse_jsonc('\ufeff{"a": 1}')
        assert result == {"a": 1}

    def test_empty_string(self) -> None:
        with pytest.raises(JSONCDecodeError):
            parse_jsonc("")

    def test_whitespace_only(self) -> None:
        with pytest.raises(JSONCDecodeError):
            parse_jsonc("   \n\t  ")

    def test_invalid_json(self) -> None:
        with pytest.raises(JSONCDecodeError):
            parse_jsonc("{invalid}")

    def test_error_messages_enriched_with_position(self) -> None:
        """Parse errors from json5 carry line/column position info."""
        err = pytest.raises(JSONCDecodeError, lambda: parse_jsonc("{bad}"))
        assert err.value.line > 0
        assert err.value.column > 0
        # repr includes position details from json5
        msg = str(err.value)
        assert "column" in msg.lower()

    def test_nested_objects(self) -> None:
        result = parse_jsonc('{"outer": {"inner": "value"}}')
        assert result == {"outer": {"inner": "value"}}

    def test_mixed_comments_and_trailing_commas(self) -> None:
        result = parse_jsonc("""{
            /* block */
            // line
            "a": 1,
            // another line
            "b": 2,
            /* trailing */
        }""")
        assert result == {"a": 1, "b": 2}

    def test_primitives(self) -> None:
        # These parse as valid JSON but aren't objects
        assert parse_jsonc("42") == 42
        assert parse_jsonc('"hello"') == "hello"
        assert parse_jsonc("true") is True
        assert parse_jsonc("false") is False
        assert parse_jsonc("null") is None


class TestReadJsoncFile:
    """Tests for read_jsonc_file function."""

    def test_valid_file(self) -> None:
        path = _write_temp_file('{"key": "value"}')
        try:
            result = read_jsonc_file(path)
            assert result.value == {"key": "value"}
        finally:
            _clean_temp_file(path)

    def test_missing_file(self) -> None:
        result = read_jsonc_file("/nonexistent/path.jsonc")
        assert result.value is None

    def test_empty_file(self) -> None:
        path = _write_temp_file("")
        try:
            result = read_jsonc_file(path)
            assert result.value is None
        finally:
            _clean_temp_file(path)

    def test_whitespace_only_file(self) -> None:
        path = _write_temp_file("   \n\t  ")
        try:
            result = read_jsonc_file(path)
            assert result.value is None
        finally:
            _clean_temp_file(path)

    def test_invalid_json_file(self) -> None:
        path = _write_temp_file("{invalid}")
        try:
            result = read_jsonc_file(path)
            assert result.value is None
        finally:
            _clean_temp_file(path)

    def test_file_with_comments(self) -> None:
        path = _write_temp_file("""// header comment
{
    // inline comment
    "key": "value" /* block comment */
}
// footer comment
""")
        try:
            result = read_jsonc_file(path)
            assert result.value == {"key": "value"}
        finally:
            _clean_temp_file(path)

    def test_file_with_trailing_commas(self) -> None:
        path = _write_temp_file('{"key": "value",}')
        try:
            result = read_jsonc_file(path)
            assert result.value == {"key": "value"}
        finally:
            _clean_temp_file(path)

    def test_regular_json_file(self) -> None:
        path = _write_temp_file('{"valid": "json"}', suffix=".json")
        try:
            result = read_jsonc_file(path)
            assert result.value == {"valid": "json"}
        finally:
            _clean_temp_file(path)

    def test_invalid_json_prints_error_to_stderr(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Invalid JSONC file prints filename and 'error parsing' to stderr."""
        path = _write_temp_file("{invalid json here}")
        try:
            result = read_jsonc_file(path)
            assert result.value is None
        finally:
            _clean_temp_file(path)
        outerr = capsys.readouterr()
        assert "error parsing" in outerr.err
        assert path in outerr.err

    def test_non_object_value_prints_error_to_stderr(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Valid JSON but non-object value (array) prints 'expected object' to stderr."""
        path = _write_temp_file("[1, 2, 3]")
        try:
            result = read_jsonc_file(path)
            assert result.value is None
        finally:
            _clean_temp_file(path)
        outerr = capsys.readouterr()
        assert "expected object" in outerr.err
        assert path in outerr.err

    def test_non_object_string_prints_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Valid JSON string value prints 'expected object, got str' to stderr."""
        path = _write_temp_file('"hello world"')
        try:
            result = read_jsonc_file(path)
            assert result.value is None
        finally:
            _clean_temp_file(path)
        outerr = capsys.readouterr()
        assert "expected object" in outerr.err
        assert "str" in outerr.err.lower()

    def test_non_object_int_prints_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Valid JSON int value prints 'expected object, got int' to stderr."""
        path = _write_temp_file("42")
        try:
            result = read_jsonc_file(path)
            assert result.value is None
        finally:
            _clean_temp_file(path)
        outerr = capsys.readouterr()
        assert "expected object" in outerr.err
        assert "int" in outerr.err.lower()

    def test_non_object_bool_prints_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Valid JSON bool value prints 'expected object, got bool' to stderr."""
        path = _write_temp_file("true")
        try:
            result = read_jsonc_file(path)
            assert result.value is None
        finally:
            _clean_temp_file(path)
        outerr = capsys.readouterr()
        assert "expected object" in outerr.err
        assert "bool" in outerr.err.lower()

    def test_null_value_treated_as_invalid(self) -> None:
        """Valid JSON null value is treated as invalid (empty/falsy), same as empty string."""
        result = parse_jsonc("null")
        assert result is None  # null parses as valid JSON, returns literal None

    def test_encoding_error_prints_to_stderr(self, capsys: pytest.CaptureFixture[str]) -> None:
        """File with invalid UTF-8 bytes prints 'error reading' to stderr."""
        fd, path = tempfile.mkstemp(suffix=".jsonc")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(b"{\xff\xfe invalid utf-8}")
            result = read_jsonc_file(path)
            assert result.value is None
        finally:
            _clean_temp_file(path)
        outerr = capsys.readouterr()
        assert "error reading" in outerr.err
        assert path in outerr.err


class TestIsRecord:
    """Tests for is_record function."""

    def test_plain_object(self) -> None:
        assert is_record({}) is True
        assert is_record({"a": 1}) is True

    def test_not_record(self) -> None:
        assert is_record([]) is False
        assert is_record("string") is False
        assert is_record(42) is False
        assert is_record(None) is False
        assert is_record(True) is False
