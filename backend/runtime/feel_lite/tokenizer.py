"""FEEL-lite tokenizer — Python mirror of the TypeScript tokenizer.

Supports: numbers, strings, booleans, null, identifiers, keywords,
arithmetic/comparison/logical operators, delimiters, wildcard, EOF.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum, auto
from typing import List


class TokenType(Enum):
    # Literals
    Number = auto()
    String = auto()
    Boolean = auto()
    Null = auto()

    # Identifiers & keywords
    Identifier = auto()
    If = auto()
    Then = auto()
    Else = auto()
    And = auto()
    Or = auto()
    Not = auto()
    In = auto()
    Between = auto()
    True_ = auto()
    False_ = auto()

    # Arithmetic operators
    Plus = auto()        # +
    Minus = auto()       # -
    Star = auto()        # *
    Slash = auto()       # /
    Percent = auto()     # %
    Caret = auto()       # ^

    # Comparison operators
    Eq = auto()          # =
    NotEq = auto()       # !=
    Lt = auto()          # <
    LtEq = auto()        # <=
    Gt = auto()          # >
    GtEq = auto()        # >=

    # Delimiters
    LParen = auto()      # (
    RParen = auto()      # )
    LBracket = auto()    # [
    RBracket = auto()    # ]
    Comma = auto()       # ,
    Dot = auto()         # .
    DotDot = auto()      # ..
    Colon = auto()       # :

    # Special
    Wildcard = auto()    # -  (contextual)
    EOF = auto()


# Keywords mapping
KEYWORDS = {
    "if": TokenType.If,
    "then": TokenType.Then,
    "else": TokenType.Else,
    "and": TokenType.And,
    "or": TokenType.Or,
    "not": TokenType.Not,
    "in": TokenType.In,
    "between": TokenType.Between,
    "true": TokenType.True_,
    "false": TokenType.False_,
    "null": TokenType.Null,
}


@dataclass
class Token:
    type: TokenType
    value: str
    position: int

    def __repr__(self) -> str:
        return f"Token({self.type.name}, {self.value!r}, pos={self.position})"


def tokenize(input_str: str) -> List[Token]:
    """Tokenize a FEEL-lite expression string into a list of Tokens."""
    tokens: List[Token] = []
    pos = 0
    length = len(input_str)

    while pos < length:
        ch = input_str[pos]

        # Skip whitespace
        if ch in (" ", "\t", "\n", "\r"):
            pos += 1
            continue

        # Two-character operators first
        if pos + 1 < length:
            two = input_str[pos : pos + 2]
            # Accept the JS-style operators the generation pipeline emits
            # (`==`, `&&`, `||`) as aliases for FEEL's `=`, `and`, `or`.
            # LLM-authored conditions use both spellings interchangeably
            # (see the vet-app definitions: `{{a}} == 'X' && {{b}} != null`).
            # `==` MUST carry the value "=" so ComparisonExpr's operator
            # (parser reads op_token.value) normalizes to the `=` branch in
            # _eval_comparison; a raw "==" value would miss every equality.
            if two == "==":
                tokens.append(Token(TokenType.Eq, "=", pos))
                pos += 2
                continue
            if two == "&&":
                tokens.append(Token(TokenType.And, "&&", pos))
                pos += 2
                continue
            if two == "||":
                tokens.append(Token(TokenType.Or, "||", pos))
                pos += 2
                continue
            if two == "!=":
                tokens.append(Token(TokenType.NotEq, "!=", pos))
                pos += 2
                continue
            if two == "<=":
                tokens.append(Token(TokenType.LtEq, "<=", pos))
                pos += 2
                continue
            if two == ">=":
                tokens.append(Token(TokenType.GtEq, ">=", pos))
                pos += 2
                continue
            if two == "..":
                tokens.append(Token(TokenType.DotDot, "..", pos))
                pos += 2
                continue

        # Single-character operators and delimiters
        if ch == "+":
            tokens.append(Token(TokenType.Plus, "+", pos))
            pos += 1
            continue
        if ch == "*":
            tokens.append(Token(TokenType.Star, "*", pos))
            pos += 1
            continue
        if ch == "/":
            tokens.append(Token(TokenType.Slash, "/", pos))
            pos += 1
            continue
        if ch == "%":
            tokens.append(Token(TokenType.Percent, "%", pos))
            pos += 1
            continue
        if ch == "^":
            tokens.append(Token(TokenType.Caret, "^", pos))
            pos += 1
            continue
        if ch == "=":
            tokens.append(Token(TokenType.Eq, "=", pos))
            pos += 1
            continue
        if ch == "<":
            tokens.append(Token(TokenType.Lt, "<", pos))
            pos += 1
            continue
        if ch == ">":
            tokens.append(Token(TokenType.Gt, ">", pos))
            pos += 1
            continue
        if ch == "(":
            tokens.append(Token(TokenType.LParen, "(", pos))
            pos += 1
            continue
        if ch == ")":
            tokens.append(Token(TokenType.RParen, ")", pos))
            pos += 1
            continue
        if ch == "[":
            tokens.append(Token(TokenType.LBracket, "[", pos))
            pos += 1
            continue
        if ch == "]":
            tokens.append(Token(TokenType.RBracket, "]", pos))
            pos += 1
            continue
        if ch == ",":
            tokens.append(Token(TokenType.Comma, ",", pos))
            pos += 1
            continue
        if ch == ":":
            tokens.append(Token(TokenType.Colon, ":", pos))
            pos += 1
            continue

        # Dot (not ..)
        if ch == ".":
            tokens.append(Token(TokenType.Dot, ".", pos))
            pos += 1
            continue

        # Minus / Wildcard: context-dependent
        # Minus is a wildcard if it appears as the sole token or after certain tokens
        if ch == "-":
            # Determine if this is a unary minus, binary minus, or wildcard
            # Wildcard: "-" is the entire cell expression, typically at start or after comma/bracket
            # We'll emit Minus and let the parser decide context
            if _is_wildcard_context(tokens):
                tokens.append(Token(TokenType.Wildcard, "-", pos))
            else:
                tokens.append(Token(TokenType.Minus, "-", pos))
            pos += 1
            continue

        # Numbers: integer or decimal
        if ch.isdigit() or (ch == "." and pos + 1 < length and input_str[pos + 1].isdigit()):
            start = pos
            has_dot = False
            while pos < length and (input_str[pos].isdigit() or (input_str[pos] == "." and not has_dot)):
                if input_str[pos] == ".":
                    # Check if next char is also a dot (..) — don't consume
                    if pos + 1 < length and input_str[pos + 1] == ".":
                        break
                    has_dot = True
                pos += 1
            tokens.append(Token(TokenType.Number, input_str[start:pos], start))
            continue

        # Strings: single or double-quoted
        if ch in ('"', "'"):
            start = pos
            quote = ch
            pos += 1
            while pos < length and input_str[pos] != quote:
                if input_str[pos] == "\\":
                    pos += 1  # skip escaped char
                pos += 1
            if pos < length:
                pos += 1  # consume closing quote
            raw = input_str[start + 1 : pos - 1]
            tokens.append(Token(TokenType.String, raw, start))
            continue

        # Identifiers and keywords
        if ch.isalpha() or ch == "_":
            start = pos
            while pos < length and (input_str[pos].isalnum() or input_str[pos] in ("_", ".")):
                # Allow dots in identifiers for nested access like "person.age"
                # But stop if it's a ".." range operator
                if input_str[pos] == ".":
                    if pos + 1 < length and input_str[pos + 1] == ".":
                        break
                    # Also break if next char is not alphanumeric (end of identifier)
                    if pos + 1 >= length or not (input_str[pos + 1].isalnum() or input_str[pos + 1] == "_"):
                        break
                pos += 1

            word = input_str[start:pos]
            lower = word.lower()

            if lower in KEYWORDS:
                tt = KEYWORDS[lower]
                # Map true/false to Boolean token type as well
                if tt == TokenType.True_:
                    tokens.append(Token(TokenType.Boolean, "true", start))
                elif tt == TokenType.False_:
                    tokens.append(Token(TokenType.Boolean, "false", start))
                elif tt == TokenType.Null:
                    tokens.append(Token(TokenType.Null, "null", start))
                else:
                    tokens.append(Token(tt, word, start))
            else:
                tokens.append(Token(TokenType.Identifier, word, start))
            continue

        # Unknown character — skip
        pos += 1

    tokens.append(Token(TokenType.EOF, "", pos))
    return tokens


def _is_wildcard_context(tokens: List[Token]) -> bool:
    """Determine if a '-' should be treated as a wildcard based on preceding tokens.

    A '-' is a wildcard when:
    - It's the first token (standalone wildcard cell)
    - It follows a comma, open bracket, or open paren (list/range context)
    """
    if not tokens:
        return True
    last = tokens[-1]
    return last.type in (TokenType.Comma, TokenType.LBracket, TokenType.LParen)
