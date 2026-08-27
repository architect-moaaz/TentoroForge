"""FEEL-lite AST nodes — Python dataclass AST matching the TypeScript AST."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional


@dataclass
class ASTNode:
    """Base class for all AST nodes."""
    pass


@dataclass
class NumberLiteral(ASTNode):
    value: float


@dataclass
class StringLiteral(ASTNode):
    value: str


@dataclass
class BooleanLiteral(ASTNode):
    value: bool


@dataclass
class NullLiteral(ASTNode):
    pass


@dataclass
class Identifier(ASTNode):
    name: str


@dataclass
class UnaryExpr(ASTNode):
    operator: str  # "-", "+"
    operand: ASTNode


@dataclass
class BinaryExpr(ASTNode):
    operator: str  # "+", "-", "*", "/", "%", "^"
    left: ASTNode
    right: ASTNode


@dataclass
class ComparisonExpr(ASTNode):
    operator: str  # "=", "!=", "<", "<=", ">", ">="
    left: ASTNode
    right: ASTNode


@dataclass
class LogicalExpr(ASTNode):
    operator: str  # "and", "or"
    left: ASTNode
    right: ASTNode


@dataclass
class RangeExpr(ASTNode):
    """Range expression: [low..high] or (low..high) with inclusive/exclusive endpoints."""
    low: ASTNode
    high: ASTNode
    low_inclusive: bool = True
    high_inclusive: bool = True


@dataclass
class ListExpr(ASTNode):
    elements: List[ASTNode] = field(default_factory=list)


@dataclass
class InExpr(ASTNode):
    """'value in list/range' expression."""
    value: ASTNode
    target: ASTNode  # ListExpr or RangeExpr


@dataclass
class NotExpr(ASTNode):
    operand: ASTNode


@dataclass
class IfExpr(ASTNode):
    condition: ASTNode
    then_branch: ASTNode
    else_branch: Optional[ASTNode] = None


@dataclass
class FunctionCall(ASTNode):
    name: str
    arguments: List[ASTNode] = field(default_factory=list)


@dataclass
class MemberExpr(ASTNode):
    """Dot access: object.property."""
    object: ASTNode
    property: str


@dataclass
class WildcardExpr(ASTNode):
    """Represents '-' wildcard (matches anything)."""
    pass


@dataclass
class BetweenExpr(ASTNode):
    """'value between low and high' expression."""
    value: ASTNode
    low: ASTNode
    high: ASTNode
