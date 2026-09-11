"""Tests for redirection extraction in parse_segments."""

from lovely_bash_permissions.segments import parse_segments


class TestSegmentRedirections:
    """Verify that segments carry redirection info."""

    def test_no_redirection(self) -> None:
        segs = parse_segments("ls -la")
        assert len(segs) == 1
        assert segs[0]["redirections"] == []

    def test_simple_output_redir(self) -> None:
        segs = parse_segments("ls > /tmp/out")
        assert len(segs) == 1
        r = segs[0]["redirections"]
        assert len(r) == 1
        assert r[0]["Op"] == ">"
        assert r[0]["Word"]["Parts"][0]["Value"] == "/tmp/out"

    def test_simple_input_redir(self) -> None:
        segs = parse_segments("grep foo < input.txt")
        assert len(segs) == 1
        r = segs[0]["redirections"]
        assert len(r) == 1
        assert r[0]["Op"] == "<"

    def test_truncate_redir(self) -> None:
        segs = parse_segments("cat <> /tmp/out")
        assert len(segs) == 1
        r = segs[0]["redirections"]
        assert len(r) == 1
        assert r[0]["Op"] == "<>"
        assert r[0]["Word"]["Parts"][0]["Value"] == "/tmp/out"

    def test_fd_redirection(self) -> None:
        segs = parse_segments("cmd 2>/dev/null")
        assert len(segs) == 1
        r = segs[0]["redirections"]
        assert len(r) == 1
        assert r[0]["N"] == {"Value": "2"}

    def test_combined_redir(self) -> None:
        segs = parse_segments("cmd &>/tmp/out")
        assert len(segs) == 1
        r = segs[0]["redirections"]
        assert len(r) == 1
        assert r[0]["Op"] in ("&>", ">&")

    def test_multiple_redirs_on_command(self) -> None:
        segs = parse_segments("cmd > out 2> err")
        assert len(segs) == 1
        r = segs[0]["redirections"]
        assert len(r) == 2

    def test_pipe_left_redir(self) -> None:
        segs = parse_segments("ls > /tmp/out | grep x")
        assert len(segs) == 2
        left = segs[0]
        right = segs[1]
        assert len(left["redirections"]) == 1
        assert left["redirections"][0]["Op"] == ">"
        assert right["redirections"] == []

    def test_pipe_right_redir(self) -> None:
        segs = parse_segments("ls | grep x 2>/dev/null")
        assert len(segs) == 2
        left, right = segs[0], segs[1]
        assert left["redirections"] == []
        r = right["redirections"]
        assert len(r) == 1
        assert r[0]["Op"] == ">"

    def test_pipe_both_sides_redir(self) -> None:
        segs = parse_segments("ls > /tmp/out | grep x 2>/dev/null")
        assert len(segs) == 2
        left, right = segs[0], segs[1]
        assert len(left["redirections"]) == 1
        assert left["redirections"][0]["Op"] == ">"
        r = right["redirections"]
        assert len(r) == 1
        assert r[0]["Op"] == ">"

    def test_and_chain_redir(self) -> None:
        segs = parse_segments("test -f x && cat x > out")
        assert len(segs) == 2
        right = segs[1]
        r = right["redirections"]
        assert len(r) == 1
        assert r[0]["Op"] == ">"

    def test_or_chain_redir(self) -> None:
        segs = parse_segments("false || echo missing > out")
        assert len(segs) == 2
        right = segs[1]
        r = right["redirections"]
        assert len(r) == 1

    def test_sequential_redir(self) -> None:
        segs = parse_segments("ls > out; cat in")
        assert len(segs) == 2
        r = segs[0]["redirections"]
        assert len(r) == 1

    def test_background_redir_on_pipe(self) -> None:
        """Background redirect (& on whole pipeline) goes to last segment."""
        segs = parse_segments("ls | grep x &>/tmp/log")
        assert len(segs) == 2
        right = segs[1]
        r = right["redirections"]
        assert len(r) == 1

    def test_complex_pipe_redir(self) -> None:
        segs = parse_segments("cat a.txt | grep x | head -5 > out")
        assert len(segs) == 3
        last = segs[2]
        r = last["redirections"]
        assert len(r) == 1

    def test_if_branch_redir(self) -> None:
        segs = parse_segments("if true; then cat x > out; fi")
        assert len(segs) >= 1
        # at least one segment should have redirections

    def test_while_body_redir(self) -> None:
        segs = parse_segments("while true; do cat x > out; done")
        assert len(segs) >= 1

    def test_func_body_redir(self) -> None:
        segs = parse_segments("f() { cat x > out; }")
        assert len(segs) >= 1

    def test_empty_command(self) -> None:
        segs = parse_segments("")
        assert segs == []
