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
    extra: Optional[dict] = None


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
class Subshell(Node):
    """Subshell (parenthesized command group)."""
    stmts: List['Stmt'] = None


@dataclass
class IfClause(Node):
    """If clause with condition, then, else branches."""
    cond: List['Stmt'] = None
    then: List['Stmt'] = None
    elif_branches: List[dict] = None
    else_branch: List['Stmt'] = None


@dataclass
class ForClause(Node):
    """For loop."""
    var: 'Word' = None
    words: List['Word'] = None
    body: List['Stmt'] = None


@dataclass
class WhileClause(Node):
    """While loop."""
    cond: List['Stmt'] = None
    body: List['Stmt'] = None


@dataclass
class AndCmd(Node):
    """Logical AND (&&)."""
    x: 'Node' = None
    y: 'Node' = None


@dataclass
class OrCmd(Node):
    """Logical OR (||)."""
    x: 'Node' = None
    y: 'Node' = None


@dataclass
class CaseClause(Node):
    """Case statement."""
    expr: 'Word' = None
    branches: List[dict] = None
    default: List['Stmt'] = None


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
    "Subshell": Subshell,
    "IfClause": IfClause,
    "ForClause": ForClause,
    "WhileClause": WhileClause,
    "AndCmd": AndCmd,
    "OrCmd": OrCmd,
    "CaseClause": CaseClause,
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
        # Capture Assigns separately (variable assignments like files=$(...))
        assigns_raw = data.get("Assigns")
        extra = None
        if assigns_raw:
            extra = {"assigns": assigns_raw}
        return CallExpr(
            type=node_type,
            pos=_parse_position(data.get("Pos")),
            end=_parse_position(data.get("End")),
            args=[word_from_json(a) for a in data.get("Args", [])],
            extra=extra,
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
    elif node_type == "Subshell":
        return Subshell(
            type=node_type,
            pos=_parse_position(data.get("Pos")),
            end=_parse_position(data.get("End")),
            stmts=[stmt_from_json(s) for s in data.get("Stmts", [])],
        )
    elif node_type == "IfClause":
        # Cond/Then/Else may be a string field name (e.g. "Pos") or dict/list
        cond_raw = data.get("Cond", [])
        then_raw = data.get("Then", [])
        else_raw = data.get("Else")
        
        cond = []
        if isinstance(cond_raw, list):
            for item in cond_raw:
                if isinstance(item, dict) and "Cmd" in item:
                    cond.append(stmt_from_json(item))
        
        then = []
        if isinstance(then_raw, list):
            for item in then_raw:
                if isinstance(item, dict) and "Cmd" in item:
                    then.append(stmt_from_json(item))
        
        elif_branches = []
        for b in data.get("Elif", []):
            if isinstance(b, dict):
                b_cond = []
                b_body = []
                c_raw = b.get("Cond", [])
                if isinstance(c_raw, list):
                    for item in c_raw:
                        if isinstance(item, dict) and "Cmd" in item:
                            b_cond.append(stmt_from_json(item))
                body_raw = b.get("Then", b.get("Body", []))
                if isinstance(body_raw, list):
                    for item in body_raw:
                        if isinstance(item, dict) and "Cmd" in item:
                            b_body.append(stmt_from_json(item))
                elif_branches.append({"cond": b_cond, "body": b_body})
        
        else_branch = []
        if isinstance(else_raw, dict):
            # Check if it's an elif (nested if) or a plain else body
            # shfmt represents elif as a nested structure in Else without a Type field,
            # but with a Cond field indicating an elif condition.
            if "Cond" in else_raw:
                # elif branch: has Cond, Then, and possibly nested Else
                nested_cond_raw = else_raw.get("Cond", [])
                nested_then_raw = else_raw.get("Then", [])
                nested_else_raw = else_raw.get("Else")
                
                nested_cond = []
                if isinstance(nested_cond_raw, list):
                    for item in nested_cond_raw:
                        if isinstance(item, dict) and "Cmd" in item:
                            nested_cond.append(stmt_from_json(item))
                
                nested_then = []
                if isinstance(nested_then_raw, list):
                    for item in nested_then_raw:
                        if isinstance(item, dict) and "Cmd" in item:
                            nested_then.append(stmt_from_json(item))
                
                elif_branches.append({"cond": nested_cond, "body": nested_then})
                
                # Process nested else recursively
                if isinstance(nested_else_raw, dict):
                    if "Cond" in nested_else_raw:
                        # Another elif - convert recursively
                        nested_nested = node_from_json(nested_else_raw)
                        elif_branches.extend(nested_nested.elif_branches)
                        else_branch = nested_nested.else_branch
                    else:
                        # Plain else body
                        nested_nested_then = nested_else_raw.get("Then", [])
                        if isinstance(nested_nested_then, list):
                            for item in nested_nested_then:
                                if isinstance(item, dict) and "Cmd" in item:
                                    else_branch.append(stmt_from_json(item))
                elif isinstance(nested_else_raw, list):
                    for item in nested_else_raw:
                        if isinstance(item, dict) and "Cmd" in item:
                            else_branch.append(stmt_from_json(item))
            else:
                # Plain else body
                nested_then = else_raw.get("Then", [])
                if isinstance(nested_then, list):
                    for item in nested_then:
                        if isinstance(item, dict) and "Cmd" in item:
                            else_branch.append(stmt_from_json(item))
        elif isinstance(else_raw, list):
            for item in else_raw:
                if isinstance(item, dict) and "Cmd" in item:
                    else_branch.append(stmt_from_json(item))
        
        return IfClause(
            type=node_type,
            pos=_parse_position(data.get("Pos")),
            end=_parse_position(data.get("End")),
            cond=cond,
            then=then,
            elif_branches=elif_branches,
            else_branch=else_branch,
        )
    elif node_type == "ForClause":
        # ForClause has "Loop" field with "Type": "WordIter"
        # Name is a simple value dict with "Value"
        loop = data.get("Loop", {})
        var_name = None
        if isinstance(loop, dict):
            name_info = loop.get("Name", {})
            if isinstance(name_info, dict):
                var_name = name_info.get("Value")
        
        items = []
        if isinstance(loop, dict):
            for w in loop.get("Items", []):
                if isinstance(w, dict):
                    items.append(word_from_json(w))
        
        body = []
        do_raw = data.get("Do", [])
        if isinstance(do_raw, list):
            for s in do_raw:
                if isinstance(s, dict) and "Cmd" in s:
                    body.append(stmt_from_json(s))
        
        return ForClause(
            type=node_type,
            pos=_parse_position(data.get("Pos")),
            end=_parse_position(data.get("End")),
            var=None if var_name is None else Word(
                type="Word",
                parts=[Part(type="Lit", value=var_name)],
            ),
            words=items,
            body=body,
        )
    elif node_type == "WhileClause":
        return WhileClause(
            type=node_type,
            pos=_parse_position(data.get("Pos")),
            end=_parse_position(data.get("End")),
            cond=[stmt_from_json(s) for s in data.get("Cond", [])],
            body=[stmt_from_json(s) for s in data.get("Do", [])],
        )
    elif node_type == "AndCmd":
        return AndCmd(
            type=node_type,
            pos=_parse_position(data.get("Pos")),
            end=_parse_position(data.get("End")),
            x=node_from_json(data.get("X")),
            y=node_from_json(data.get("Y")),
        )
    elif node_type == "OrCmd":
        return OrCmd(
            type=node_type,
            pos=_parse_position(data.get("Pos")),
            end=_parse_position(data.get("End")),
            x=node_from_json(data.get("X")),
            y=node_from_json(data.get("Y")),
        )
    elif node_type == "CaseClause":
        return CaseClause(
            type=node_type,
            pos=_parse_position(data.get("Pos")),
            end=_parse_position(data.get("End")),
            expr=word_from_json(data.get("Expr")),
            branches=[
                {
                    "patterns": [word_from_json(w) for w in b.get("Patterns", [])],
                    "body": [stmt_from_json(s) for s in b.get("Body", [])],
                }
                for b in data.get("Branches", [])
            ],
            default=[stmt_from_json(s) for s in data.get("Default", [])],
        )
    
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
        extra=data.get("Stmts") if data.get("Type") == "CmdSubst" else None,
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
