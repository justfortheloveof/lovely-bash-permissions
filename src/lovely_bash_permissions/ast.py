"""
AST node types for bash commands.
"""

from dataclasses import dataclass
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
    type: str
    pos: Position
    end: Position


@dataclass
class Word(Node):
    """A word with parts (could be literal, variable, expansion)."""
    parts: List['Part']


@dataclass
class Part:
    """A part of a word."""
    type: str
    pos: Position
    end: Position
    value: Optional[str] = None


@dataclass
class CallExpr(Node):
    """A call expression (command with arguments)."""
    args: List['Word']


@dataclass
class BinaryCmd(Node):
    """Binary command (pipe)."""
    op: str
    x: 'Node'
    y: 'Node'


@dataclass
class Stmt:
    """A statement."""
    cmd: 'Node'
    position: Position
    pos: Position
    end: Position


@dataclass
class File(Node):
    """Top-level file node."""
    stmts: List['Stmt']


# Type mapping from shfmt's JSON to our dataclasses
NODE_TYPES = {
    "File": File,
    "CallExpr": CallExpr,
    "BinaryCmd": BinaryCmd,
    "Word": Word,
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
        return BinaryCmd(
            type=node_type,
            pos=_parse_position(data.get("Pos")),
            end=_parse_position(data.get("End")),
            op=data.get("Op", ""),
            x=node_from_json(data.get("X")),
            y=node_from_json(data.get("Y")),
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
    return Stmt(
        cmd=cmd,
        position=_parse_position(data.get("Position")),
        pos=_parse_position(data.get("Pos")),
        end=_parse_position(data.get("End")),
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
    return Part(
        type=data.get("Type", ""),
        pos=_parse_position(data.get("Pos")),
        end=_parse_position(data.get("End")),
        value=data.get("Value"),
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
