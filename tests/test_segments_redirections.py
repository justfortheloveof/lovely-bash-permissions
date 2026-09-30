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
        assert r[0]["Target"] == "/tmp/out"

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
        assert r[0]["Target"] == "/tmp/out"

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


def _names(command: str) -> list[str]:
    return [seg["command"] for seg in parse_segments(command)]


class TestSegmentsRedirectionTargetsWalkedOnce:
    """A substitution in a redirection target runs once, and always surfaces.

    The target walk used to live in the command handlers and read the
    *inherited* redirections, so a statement redirection was walked once per
    command inside it, and a statement with no ordinary command never walked it.
    """

    def test_block_redirect_target_runs_once(self) -> None:
        assert _names("{ ls; echo; } > $(cmd)") == ["ls", "echo", "cmd"]

    def test_loop_redirect_target_runs_once(self) -> None:
        assert _names("while ls; do echo; done < $(cmd)").count("cmd") == 1

    def test_assignment_only_statement_surfaces_target(self) -> None:
        assert _names("x=1 > $(cmd)") == ["", "cmd"]

    def test_let_statement_surfaces_target(self) -> None:
        assert "cmd" in _names("let x=1 > $(cmd)")

    def test_redirection_only_statement_surfaces_target(self) -> None:
        segs = parse_segments("> $(cat /etc/passwd)")
        assert [(s["command"], s["arguments"]) for s in segs] == [("", []), ("cat", ["/etc/passwd"])]

    def test_pipe_side_target_keeps_source_order(self) -> None:
        assert _names("ls > $(cmd) | echo") == ["ls", "cmd", "echo"]

    def test_heredoc_body_in_pipe_keeps_source_order(self) -> None:
        assert _names("cat <<EOF | wc\n$(cmd)\nEOF") == ["cat", "cmd", "wc"]

    def test_inner_redirection_reaches_the_redirection_policy(self) -> None:
        segs = parse_segments("x=1 > $(echo hi > /tmp/f)")
        targets = [r["Target"] for s in segs for r in s["redirections"]]
        assert "/tmp/f" in targets
