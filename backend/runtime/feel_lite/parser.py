"""FEEL-lite recursive descent parser.

Precedence (lowest to highest):
  if/then/else < or < and < not < in/comparisons < +/- < * / % < ^ < unary < member/function < primary
"""

from __future__ import annotations

from typing import List

from runtime.feel_lite.tokenizer import Token, TokenType
from runtime.feel_lite.ast_nodes import (
    ASTNode,
    BetweenExpr,
    BinaryExpr,
    BooleanLiteral,
    ComparisonExpr,
    FunctionCall,
    Identifier,
    IfExpr,
    InExpr,
    ListExpr,
    LogicalExpr,
    MemberExpr,
    NotExpr,
    NullLiteral,
    NumberLiteral,
    RangeExpr,
    StringLiteral,
    UnaryExpr,
    WildcardExpr,
)


class ParseError(Exception):
    """Raised when the parser encounters unexpected input."""

    def __init__(self, message: str, position: int = -1):
        self.position = position
        super().__init__(message)


class Parser:
    """Recursive descent parser for FEEL-lite expressions."""

    def __init__(self, tokens: List[Token]):
        self.tokens = tokens
        self.pos = 0

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def _current(self) -> Token:
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return Token(TokenType.EOF, "", -1)

    def _peek(self, offset: int = 0) -> Token:
        idx = self.pos + offset
        if idx < len(self.tokens):
            return self.tokens[idx]
        return Token(TokenType.EOF, "", -1)

    def _advance(self) -> Token:
        token = self._current()
        self.pos += 1
        return token

    def _expect(self, tt: TokenType) -> Token:
        token = self._current()
        if token.type != tt:
            raise ParseError(
                f"Expected {tt.name} but got {token.type.name} ({token.value!r})",
                token.position,
            )
        return self._advance()

    def _match(self, *types: TokenType) -> Token | None:
        if self._current().type in types:
            return self._advance()
        return None

    # -----------------------------------------------------------------------
    # Grammar rules (lowest precedence first)
    # -----------------------------------------------------------------------

    def parse(self) -> ASTNode:
        node = self._parse_if_expr()
        if self._current().type != TokenType.EOF:
            # Allow trailing tokens — just return what we parsed
            pass
        return node

    def _parse_if_expr(self) -> ASTNode:
        """if expr then expr [else expr]"""
        if self._current().type == TokenType.If:
            self._advance()
            condition = self._parse_or()
            self._expect(TokenType.Then)
            then_branch = self._parse_if_expr()
            else_branch = None
            if self._match(TokenType.Else):
                else_branch = self._parse_if_expr()
            return IfExpr(condition=condition, then_branch=then_branch, else_branch=else_branch)
        return self._parse_or()

    def _parse_or(self) -> ASTNode:
        left = self._parse_and()
        while self._current().type == TokenType.Or:
            self._advance()
            right = self._parse_and()
            left = LogicalExpr(operator="or", left=left, right=right)
        return left

    def _parse_and(self) -> ASTNode:
        left = self._parse_not()
        while self._current().type == TokenType.And:
            self._advance()
            right = self._parse_not()
            left = LogicalExpr(operator="and", left=left, right=right)
        return left

    def _parse_not(self) -> ASTNode:
        if self._current().type == TokenType.Not:
            self._advance()
            operand = self._parse_not()
            return NotExpr(operand=operand)
        return self._parse_in_comparison()

    def _parse_in_comparison(self) -> ASTNode:
        left = self._parse_addition()

        # between expr and expr
        if self._current().type == TokenType.Between:
            self._advance()
            low = self._parse_addition()
            self._expect(TokenType.And)
            high = self._parse_addition()
            return BetweenExpr(value=left, low=low, high=high)

        # in expr
        if self._current().type == TokenType.In:
            self._advance()
            target = self._parse_addition()
            return InExpr(value=left, target=target)

        # Comparisons: =, !=, <, <=, >, >=
        comp_types = (TokenType.Eq, TokenType.NotEq, TokenType.Lt, TokenType.LtEq, TokenType.Gt, TokenType.GtEq)
        if self._current().type in comp_types:
            op_token = self._advance()
            right = self._parse_addition()
            return ComparisonExpr(operator=op_token.value, left=left, right=right)

        return left

    def _parse_addition(self) -> ASTNode:
        left = self._parse_multiplication()
        while self._current().type in (TokenType.Plus, TokenType.Minus):
            op = self._advance()
            right = self._parse_multiplication()
            left = BinaryExpr(operator=op.value, left=left, right=right)
        return left

    def _parse_multiplication(self) -> ASTNode:
        left = self._parse_exponent()
        while self._current().type in (TokenType.Star, TokenType.Slash, TokenType.Percent):
            op = self._advance()
            right = self._parse_exponent()
            left = BinaryExpr(operator=op.value, left=left, right=right)
        return left

    def _parse_exponent(self) -> ASTNode:
        base = self._parse_unary()
        if self._current().type == TokenType.Caret:
            self._advance()
            exp = self._parse_unary()  # Right-associative
            return BinaryExpr(operator="^", left=base, right=exp)
        return base

    def _parse_unary(self) -> ASTNode:
        if self._current().type == TokenType.Minus:
            op = self._advance()
            operand = self._parse_unary()
            return UnaryExpr(operator="-", operand=operand)
        if self._current().type == TokenType.Plus:
            self._advance()
            return self._parse_unary()
        return self._parse_member_or_call()

    def _parse_member_or_call(self) -> ASTNode:
        node = self._parse_primary()

        # Multi-word FEEL builtins: `starts with` / `ends with` (the canonical
        # spaced spelling the function catalogue advertises). The tokenizer emits
        # two identifiers; join them so `starts with(x, "A")` parses to a
        # FunctionCall("starts with", …) instead of the bare Identifier("starts")
        # with the rest silently dropped → a wrong-branch at runtime.
        if (isinstance(node, Identifier) and node.name in ("starts", "ends")
                and self._current().type == TokenType.Identifier
                and self._current().value == "with"):
            self._advance()
            node = Identifier(name=f"{node.name} with")

        while True:
            if self._current().type == TokenType.Dot:
                self._advance()
                prop_token = self._expect(TokenType.Identifier)
                node = MemberExpr(object=node, property=prop_token.value)
            elif self._current().type == TokenType.LParen and isinstance(node, Identifier):
                # Function call
                self._advance()
                args: list[ASTNode] = []
                if self._current().type != TokenType.RParen:
                    args.append(self._parse_if_expr())
                    while self._match(TokenType.Comma):
                        args.append(self._parse_if_expr())
                self._expect(TokenType.RParen)
                node = FunctionCall(name=node.name, arguments=args)
            elif self._current().type == TokenType.LBracket:
                # Could be indexing — treat as member access with expression
                self._advance()
                idx_expr = self._parse_if_expr()
                self._expect(TokenType.RBracket)
                # For simplicity, treat bracket access as a function call "get"
                node = FunctionCall(name="get", arguments=[node, idx_expr])
            else:
                break

        return node

    def _parse_primary(self) -> ASTNode:
        token = self._current()

        # Wildcard
        if token.type == TokenType.Wildcard:
            self._advance()
            return WildcardExpr()

        # Number
        if token.type == TokenType.Number:
            self._advance()
            return NumberLiteral(value=float(token.value))

        # String
        if token.type == TokenType.String:
            self._advance()
            return StringLiteral(value=token.value)

        # Boolean
        if token.type == TokenType.Boolean:
            self._advance()
            return BooleanLiteral(value=token.value.lower() == "true")

        # Null
        if token.type == TokenType.Null:
            self._advance()
            return NullLiteral()

        # Parenthesized expression or range
        if token.type == TokenType.LParen:
            self._advance()
            # Check if this is a range: (low..high)
            expr = self._parse_if_expr()
            if self._current().type == TokenType.DotDot:
                self._advance()
                high = self._parse_if_expr()
                # Determine inclusivity: ( means exclusive
                low_inclusive = False
                if self._current().type == TokenType.RParen:
                    self._advance()
                    return RangeExpr(low=expr, high=high, low_inclusive=False, high_inclusive=False)
                elif self._current().type == TokenType.RBracket:
                    self._advance()
                    return RangeExpr(low=expr, high=high, low_inclusive=False, high_inclusive=True)
                else:
                    self._expect(TokenType.RParen)
            self._expect(TokenType.RParen)
            return expr

        # List or range with bracket
        if token.type == TokenType.LBracket:
            self._advance()
            # Check for empty list
            if self._current().type == TokenType.RBracket:
                self._advance()
                return ListExpr(elements=[])

            first = self._parse_if_expr()

            # Range: [low..high]
            if self._current().type == TokenType.DotDot:
                self._advance()
                high = self._parse_if_expr()
                high_inclusive = True
                if self._current().type == TokenType.RBracket:
                    self._advance()
                    return RangeExpr(low=first, high=high, low_inclusive=True, high_inclusive=True)
                elif self._current().type == TokenType.RParen:
                    self._advance()
                    return RangeExpr(low=first, high=high, low_inclusive=True, high_inclusive=False)
                else:
                    self._expect(TokenType.RBracket)

            # List
            elements = [first]
            while self._match(TokenType.Comma):
                elements.append(self._parse_if_expr())
            self._expect(TokenType.RBracket)
            return ListExpr(elements=elements)

        # Identifier
        if token.type == TokenType.Identifier:
            self._advance()
            return Identifier(name=token.value)

        # Comparison operators as prefix (for cell expressions like ">= 100")
        if token.type in (TokenType.Lt, TokenType.LtEq, TokenType.Gt, TokenType.GtEq, TokenType.NotEq):
            op = self._advance()
            operand = self._parse_addition()
            # Return as a ComparisonExpr with a placeholder left side
            # The evaluator will supply the input value as the left side
            return ComparisonExpr(operator=op.value, left=Identifier(name="?"), right=operand)

        # Not keyword prefix
        if token.type == TokenType.Not:
            self._advance()
            # Check for "not(" pattern
            if self._current().type == TokenType.LParen:
                self._advance()
                expr = self._parse_if_expr()
                self._expect(TokenType.RParen)
                return NotExpr(operand=expr)
            operand = self._parse_primary()
            return NotExpr(operand=operand)

        raise ParseError(
            f"Unexpected token: {token.type.name} ({token.value!r})",
            token.position,
        )


def parse(tokens: List[Token]) -> ASTNode:
    """Parse a list of tokens into an AST node."""
    parser = Parser(tokens)
    return parser.parse()
