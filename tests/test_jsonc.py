"""Tests for JSONC parser."""

import os
import tempfile

from lovely_bash_permissions.config.jsonc import (
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


def _clean_temp_file(path: str):
    """Remove a temporary file."""
    if os.path.exists(path):
        os.remove(path)


class TestParseJsonc:
    """Tests for parse_jsonc function."""

    def test_valid_json_object(self):
        result = parse_jsonc('{"a": 1, "b": 2}')
        assert result == {"a": 1, "b": 2}

    def test_valid_json_array(self):
        result = parse_jsonc("[1, 2, 3]")
        assert result == [1, 2, 3]

    def test_line_comments(self):
        result = parse_jsonc("""{
            // This is a comment
            "a": 1
        }""")
        assert result == {"a": 1}

    def test_block_comments(self):
        result = parse_jsonc("""{
            /* Block comment */
            "a": 1
        }""")
        assert result == {"a": 1}

    def test_inline_block_comments(self):
        result = parse_jsonc('{"a": 1 /* inline */ }')
        assert result == {"a": 1}

    def test_multiline_block_comments(self):
        result = parse_jsonc("""{
            /*
            Multi-line
            comment
            */
            "a": 1
        }""")
        assert result == {"a": 1}

    def test_trailing_commas_objects(self):
        result = parse_jsonc('{"a": 1, "b": 2,}')
        assert result == {"a": 1, "b": 2}

    def test_trailing_commas_arrays(self):
        result = parse_jsonc("[1, 2, 3,]")
        assert result == [1, 2, 3]

    def test_bom_prefix(self):
        result = parse_jsonc('\ufeff{"a": 1}')
        assert result == {"a": 1}

    def test_empty_string(self):
        result = parse_jsonc("")
        assert result is None

    def test_whitespace_only(self):
        result = parse_jsonc("   \n\t  ")
        assert result is None

    def test_invalid_json(self):
        result = parse_jsonc("{invalid}")
        assert result is None

    def test_nested_objects(self):
        result = parse_jsonc('{"outer": {"inner": "value"}}')
        assert result == {"outer": {"inner": "value"}}

    def test_mixed_comments_and_trailing_commas(self):
        result = parse_jsonc("""{
            /* block */
            // line
            "a": 1,
            // another line
            "b": 2,
            /* trailing */
        }""")
        assert result == {"a": 1, "b": 2}

    def test_primitives(self):
        # These parse as valid JSON but aren't objects
        assert parse_jsonc("42") == 42
        assert parse_jsonc('"hello"') == "hello"
        assert parse_jsonc("true") is True
        assert parse_jsonc("false") is False
        assert parse_jsonc("null") is None


class TestReadJsoncFile:
    """Tests for read_jsonc_file function."""

    def test_valid_file(self):
        path = _write_temp_file('{"key": "value"}')
        try:
            result = read_jsonc_file(path)
            assert result == {"key": "value"}
        finally:
            _clean_temp_file(path)

    def test_missing_file(self):
        result = read_jsonc_file("/nonexistent/path.jsonc")
        assert result is None

    def test_empty_file(self):
        path = _write_temp_file("")
        try:
            result = read_jsonc_file(path)
            assert result is None
        finally:
            _clean_temp_file(path)

    def test_whitespace_only_file(self):
        path = _write_temp_file("   \n\t  ")
        try:
            result = read_jsonc_file(path)
            assert result is None
        finally:
            _clean_temp_file(path)

    def test_invalid_json_file(self):
        path = _write_temp_file("{invalid}")
        try:
            result = read_jsonc_file(path)
            assert result is None
        finally:
            _clean_temp_file(path)

    def test_file_with_comments(self):
        path = _write_temp_file("""// header comment
{
    // inline comment
    "key": "value" /* block comment */
}
// footer comment
""")
        try:
            result = read_jsonc_file(path)
            assert result == {"key": "value"}
        finally:
            _clean_temp_file(path)

    def test_file_with_trailing_commas(self):
        path = _write_temp_file('{"key": "value",}')
        try:
            result = read_jsonc_file(path)
            assert result == {"key": "value"}
        finally:
            _clean_temp_file(path)

    def test_regular_json_file(self):
        path = _write_temp_file('{"valid": "json"}', suffix=".json")
        try:
            result = read_jsonc_file(path)
            assert result == {"valid": "json"}
        finally:
            _clean_temp_file(path)


class TestIsRecord:
    """Tests for is_record function."""

    def test_plain_object(self):
        assert is_record({}) is True
        assert is_record({"a": 1}) is True

    def test_not_record(self):
        assert is_record([]) is False
        assert is_record("string") is False
        assert is_record(42) is False
        assert is_record(None) is False
        assert is_record(True) is False
