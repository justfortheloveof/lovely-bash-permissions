"""
AST node types for bash commands.
"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Position:
    """Position information for AST nodes."""
    offset: int
    line: int
    col: int


@dataclass
class Range:
    """Range with start and end positions."""
    pos: Position
    end: Position


@dataclass
class Node:
    """Base AST node."""
    type: str = None
    pos: Position = None
    end: Position = None
    extra: Optional[dict] = None
    args: Optional[List['Word']] = None


@dataclass
class Word(Node):
    """A word with parts (could be literal, variable, expansion)."""
    parts: List['Part'] = None


@dataclass
class Part:
    """A part of a word."""
    type: str = None
    pos: Position = None
    end: Position = None
    value: Optional[str] = None
    parts: Optional[List['Part']] = None


@dataclass
class CallExpr(Node):
    """A call expression (command with arguments)."""
    args: List['Word'] = None


@dataclass
class BinaryCmd(Node):
    """Binary command (pipe)."""
    op: str = None
    x: 'Node' = None
    y: 'Node' = None
    redirs: Optional[List['Redir']] = None


@dataclass
class Redir:
    """Redirection."""
    op: str = None
    word: 'Word' = None
    pos: Position = None
    end: Position = None
    op_pos: Position = None

def redir_from_json(data: dict) -> Redir:
    """Convert shfmt JSON redirection to typed object."""
    return Redir(
        op=data.get("Op", ""),
        word=word_from_json(data.get("Word")),
        pos=_parse_position(data.get("Pos")),
        end=_parse_position(data.get("End")),
        op_pos=_parse_position(data.get("OpPos")),
    )

@dataclass
class Stmt:
    """A statement."""
    cmd: 'Node' = None
    position: Position = None
    pos: Position = None
    end: Position = None
    redirs: Optional[List['Redir']] = None


@dataclass
class File(Node):
    """Top-level file node."""
    stmts: List['Stmt'] = None


# Type mapping from shfmt's JSON to our dataclasses
NODE_TYPES = {
    "File": File,
    "CallExpr": CallExpr,
    "BinaryCmd": BinaryCmd,
    "Word": Word,
    "DeclClause": Node,
}


def node_from_json(data: dict) -> Node:
    """Convert shfmt JSON to typed AST node."""
    node_type = data.get("Type", "")
    
    # Handle nodes that have 'Cmd' but no 'Type' (wrapped statements)
    if not node_type and "Cmd" in data:
        return node_from_json(data["Cmd"])
    
    if node_type not in NODE_TYPES:
        return Node(
            type=node_type,
            pos=_parse_position(data.get("Pos")),
            end=_parse_position(data.get("End")),
        )
    
    cls = NODE_TYPES[node_type]
    
    if node_type == "File":
        return File(
            type=node_type,
            pos=_parse_position(data.get("Pos")),
            end=_parse_position(data.get("End")),
            stmts=[stmt_from_json(s) for s in data.get("Stmts", [])],
        )
    elif node_type == "Stmt":
        return stmt_from_json(data)
    elif node_type == "CallExpr":
        return CallExpr(
            type=node_type,
            pos=_parse_position(data.get("Pos")),
            end=_parse_position(data.get("End")),
            args=[word_from_json(a) for a in data.get("Args", [])],
        )
    elif node_type == "BinaryCmd":
        x = data.get("X")
        y = data.get("Y")
        x_node = node_from_json(x)
        y_node = node_from_json(y)
        redirs = []
        # Check if Y has redirs
        if isinstance(y, dict) and "Redirs" in y:
            redirs = [redir_from_json(r) for r in y["Redirs"]]
        return BinaryCmd(
            type=node_type,
            pos=_parse_position(data.get("Pos")),
            end=_parse_position(data.get("End")),
            op=data.get("Op", ""),
            x=x_node,
            y=y_node,
            redirs=redirs,
        )
    elif node_type == "DeclClause":
        # Export/declare/readonly: convert Arg objects (with name/value) to Words
        words = []
        for arg in data.get("Args", []):
            if isinstance(arg, dict):
                # Extract the value part as a Word-like structure
                val = arg.get("value", arg.get("Value", {}))
                # Build a minimal Word from the value
                if val:
                    w = Word(
                        type="Word",
                        pos=_parse_position(val.get("Pos")),
                        end=_parse_position(val.get("End")),
                        parts=[],
                    )
                    if "Parts" in val:
                        for p in val["Parts"]:
                            w.parts.append(part_from_json(p))
                    words.append(w)
        return Node(
            type=node_type,
            pos=_parse_position(data.get("Pos")),
            end=_parse_position(data.get("End")),
            args=words,
        )
    elif node_type == "Word":
        return word_from_json(data)
    elif node_type == "Lit":
        return part_from_json(data)
    
    return Node(
        type=node_type,
        pos=_parse_position(data.get("Pos")),
        end=_parse_position(data.get("End")),
    )


def stmt_from_json(data: dict) -> Stmt:
    """Convert a shfmt JSON statement to a typed Stmt object."""
    cmd = node_from_json(data.get("Cmd"))
    redirs = None
    if "Redirs" in data:
        redirs = [redir_from_json(r) for r in data.get("Redirs", [])]
    return Stmt(
        cmd=cmd,
        position=_parse_position(data.get("Position")),
        pos=_parse_position(data.get("Pos")),
        end=_parse_position(data.get("End")),
        redirs=redirs,
    )


def word_from_json(data: dict) -> Word:
    """Convert a shfmt JSON word to a typed Word object."""
    parts = [part_from_json(p) for p in data.get("Parts", [])]
    return Word(
        type="Word",
        pos=_parse_position(data.get("Pos")),
        end=_parse_position(data.get("End")),
        parts=parts,
    )


def part_from_json(data: dict) -> Part:
    """Convert a shfmt JSON part to a typed Part object."""
    parts = None
    if "Parts" in data:
        parts = [part_from_json(p) for p in data.get("Parts", [])]
    
    # For DblQuoted, the value is the concatenation of inner parts
    value = data.get("Value")
    if data.get("Type") == "DblQuoted" and parts:
        value = "".join(p.value for p in parts if p.value)
    
    return Part(
        type=data.get("Type", ""),
        pos=_parse_position(data.get("Pos")),
        end=_parse_position(data.get("End")),
        value=value,
        parts=parts,
    )


def _parse_position(data: dict) -> Position:
    """Parse position data from shfmt JSON."""
    return Position(
        offset=data.get("Offset", 0),
        line=data.get("Line", 0),
        col=data.get("Col", 0),
    )


def parse_ast(command: str) -> Node:
    """
    Parse a bash command and return a typed AST node.
    
    Args:
        command: Bash command to parse
    
    Returns:
        Typed AST node (File, Stmt, etc.)
    """
    from .parser import parse
    raw = parse(command)
    return node_from_json(raw)
