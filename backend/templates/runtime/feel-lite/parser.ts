/** FEEL-lite recursive descent parser.
 *
 * Precedence (lowest → highest):
 *   if/then/else
 *   or
 *   and
 *   not
 *   in / comparisons
 *   + / -
 *   * / / / %
 *   ^ (power)
 *   unary (- +)
 *   member / function call
 *   primary (literals, identifiers, grouped expressions, ranges, lists)
 */

import { TokenType, type Token } from "./tokenizer";
import type { ASTNode } from "./ast";

export class ParseError extends Error {
  constructor(
    message: string,
    public position: number,
  ) {
    super(message);
    this.name = "ParseError";
  }
}

export function parse(tokens: Token[]): ASTNode {
  let pos = 0;

  function peek(): Token {
    return tokens[pos];
  }

  function advance(): Token {
    return tokens[pos++];
  }

  function expect(type: TokenType): Token {
    const tok = peek();
    if (tok.type !== type) {
      throw new ParseError(
        `Expected ${type} but got ${tok.type} ("${tok.value}")`,
        tok.start,
      );
    }
    return advance();
  }

  function match(...types: TokenType[]): Token | null {
    if (types.includes(peek().type)) {
      return advance();
    }
    return null;
  }

  // ── if/then/else ──────────────────────────────────────
  function parseExpression(): ASTNode {
    if (peek().type === TokenType.If) {
      return parseIfExpression();
    }
    return parseOr();
  }

  function parseIfExpression(): ASTNode {
    expect(TokenType.If);
    const condition = parseExpression();
    expect(TokenType.Then);
    const thenBranch = parseExpression();
    expect(TokenType.Else);
    const elseBranch = parseExpression();
    return { type: "IfExpression", condition, thenBranch, elseBranch };
  }

  // ── or ────────────────────────────────────────────────
  function parseOr(): ASTNode {
    let left = parseAnd();
    while (peek().type === TokenType.Or) {
      advance();
      const right = parseAnd();
      left = { type: "LogicalExpression", operator: "or", left, right };
    }
    return left;
  }

  // ── and ───────────────────────────────────────────────
  function parseAnd(): ASTNode {
    let left = parseNot();
    while (peek().type === TokenType.And) {
      advance();
      const right = parseNot();
      left = { type: "LogicalExpression", operator: "and", left, right };
    }
    return left;
  }

  // ── not ───────────────────────────────────────────────
  function parseNot(): ASTNode {
    if (peek().type === TokenType.Not) {
      advance();
      // not(...) is a function-like call
      if (peek().type === TokenType.LParen) {
        expect(TokenType.LParen);
        const operand = parseExpression();
        expect(TokenType.RParen);
        return { type: "NotExpression", operand };
      }
      const operand = parseNot();
      return { type: "NotExpression", operand };
    }
    return parseComparison();
  }

  // ── comparison / in / between ─────────────────────────
  function parseComparison(): ASTNode {
    let left = parseAddSub();

    // Handle "in" expression
    if (peek().type === TokenType.In) {
      advance();
      const list = parseRangeOrList();
      return { type: "InExpression", value: left, list };
    }

    // Handle "between X and Y"
    if (peek().type === TokenType.Between) {
      advance();
      const low = parseAddSub();
      expect(TokenType.And);
      const high = parseAddSub();
      return { type: "BetweenExpression", value: left, low, high };
    }

    // Comparison operators
    const compOps: Record<string, "=" | "!=" | "<" | "<=" | ">" | ">="> = {
      [TokenType.Eq]: "=",
      [TokenType.Neq]: "!=",
      [TokenType.Lt]: "<",
      [TokenType.Lte]: "<=",
      [TokenType.Gt]: ">",
      [TokenType.Gte]: ">=",
    };

    const tok = peek();
    if (tok.type in compOps) {
      advance();
      const right = parseAddSub();
      return {
        type: "ComparisonExpression",
        operator: compOps[tok.type],
        left,
        right,
      };
    }

    return left;
  }

  // ── addition / subtraction ────────────────────────────
  function parseAddSub(): ASTNode {
    let left = parseMulDiv();
    while (peek().type === TokenType.Plus || peek().type === TokenType.Minus) {
      const op = advance();
      const right = parseMulDiv();
      left = {
        type: "BinaryExpression",
        operator: op.type === TokenType.Plus ? "+" : "-",
        left,
        right,
      };
    }
    return left;
  }

  // ── multiplication / division / modulo ────────────────
  function parseMulDiv(): ASTNode {
    let left = parsePower();
    while (
      peek().type === TokenType.Star ||
      peek().type === TokenType.Slash ||
      peek().type === TokenType.Percent
    ) {
      const op = advance();
      const right = parsePower();
      left = {
        type: "BinaryExpression",
        operator:
          op.type === TokenType.Star
            ? "*"
            : op.type === TokenType.Slash
              ? "/"
              : "%",
        left,
        right,
      };
    }
    return left;
  }

  // ── power ─────────────────────────────────────────────
  function parsePower(): ASTNode {
    let left = parseUnary();
    while (peek().type === TokenType.Power) {
      advance();
      const right = parseUnary();
      left = { type: "BinaryExpression", operator: "^", left, right };
    }
    return left;
  }

  // ── unary ─────────────────────────────────────────────
  function parseUnary(): ASTNode {
    if (peek().type === TokenType.Minus) {
      const op = advance();
      const operand = parseUnary();
      return { type: "UnaryExpression", operator: "-", operand };
    }
    if (peek().type === TokenType.Plus) {
      advance();
      return parseUnary();
    }
    return parsePostfix();
  }

  // ── member access / function call ─────────────────────
  function parsePostfix(): ASTNode {
    let node = parsePrimary();

    while (true) {
      if (peek().type === TokenType.Dot) {
        advance();
        const propTok = expect(TokenType.Identifier);
        node = { type: "MemberExpression", object: node, property: propTok.value };
      } else {
        break;
      }
    }

    return node;
  }

  // ── primary ───────────────────────────────────────────
  function parsePrimary(): ASTNode {
    const tok = peek();

    // Wildcard
    if (tok.type === TokenType.Wildcard) {
      advance();
      return { type: "WildcardExpression" };
    }

    // Number
    if (tok.type === TokenType.Number) {
      advance();
      return { type: "NumberLiteral", value: parseFloat(tok.value) };
    }

    // String
    if (tok.type === TokenType.String) {
      advance();
      return { type: "StringLiteral", value: tok.value };
    }

    // Boolean
    if (tok.type === TokenType.True) {
      advance();
      return { type: "BooleanLiteral", value: true };
    }
    if (tok.type === TokenType.False) {
      advance();
      return { type: "BooleanLiteral", value: false };
    }

    // Null
    if (tok.type === TokenType.Null) {
      advance();
      return { type: "NullLiteral" };
    }

    // Identifier (may be a function call)
    if (tok.type === TokenType.Identifier) {
      const idTok = advance();

      // Multi-word function names: "starts with", "ends with"
      if (
        (idTok.value === "starts" || idTok.value === "ends") &&
        peek().type === TokenType.Identifier &&
        peek().value === "with"
      ) {
        advance(); // consume "with"
        const funcName = idTok.value + " with";
        expect(TokenType.LParen);
        const args = parseArgList();
        expect(TokenType.RParen);
        return { type: "FunctionCall", name: funcName, args };
      }

      // Regular function call
      if (peek().type === TokenType.LParen) {
        advance(); // consume (
        const args = parseArgList();
        expect(TokenType.RParen);
        return { type: "FunctionCall", name: idTok.value, args };
      }

      // Dotted identifier already handled by tokenizer (customer.age → single Identifier token)
      return { type: "Identifier", name: idTok.value };
    }

    // Grouped expression or range with parentheses
    if (tok.type === TokenType.LParen) {
      advance();
      // Check for range: (start..end)  or  (start..end]
      const expr = parseExpression();
      if (peek().type === TokenType.DotDot) {
        advance();
        const end = parseExpression();
        const endInclusive = peek().type === TokenType.RBracket;
        if (peek().type === TokenType.RParen) {
          advance();
          return {
            type: "RangeExpression",
            startInclusive: false,
            endInclusive: false,
            start: expr,
            end,
          };
        }
        if (peek().type === TokenType.RBracket) {
          advance();
          return {
            type: "RangeExpression",
            startInclusive: false,
            endInclusive: true,
            start: expr,
            end,
          };
        }
      }
      expect(TokenType.RParen);
      return expr;
    }

    // Range or list with brackets: [start..end] or [a, b, c]
    if (tok.type === TokenType.LBracket) {
      advance();

      // Empty list
      if (peek().type === TokenType.RBracket) {
        advance();
        return { type: "ListExpression", elements: [] };
      }

      const first = parseExpression();

      // Range: [start..end]  or  [start..end)
      if (peek().type === TokenType.DotDot) {
        advance();
        const end = parseExpression();
        const endInclusive = peek().type === TokenType.RBracket;
        if (peek().type === TokenType.RBracket) {
          advance();
          return {
            type: "RangeExpression",
            startInclusive: true,
            endInclusive: true,
            start: first,
            end,
          };
        }
        if (peek().type === TokenType.RParen) {
          advance();
          return {
            type: "RangeExpression",
            startInclusive: true,
            endInclusive: false,
            start: first,
            end,
          };
        }
        throw new ParseError("Expected ] or ) to close range", peek().start);
      }

      // List: [a, b, c]
      const elements: ASTNode[] = [first];
      while (peek().type === TokenType.Comma) {
        advance();
        elements.push(parseExpression());
      }
      expect(TokenType.RBracket);
      return { type: "ListExpression", elements };
    }

    // Not keyword at primary level (not handled above) — e.g. "not(x)"
    if (tok.type === TokenType.Not) {
      advance();
      if (peek().type === TokenType.LParen) {
        expect(TokenType.LParen);
        const operand = parseExpression();
        expect(TokenType.RParen);
        return { type: "NotExpression", operand };
      }
      const operand = parsePrimary();
      return { type: "NotExpression", operand };
    }

    throw new ParseError(
      `Unexpected token: ${tok.type} ("${tok.value}")`,
      tok.start,
    );
  }

  function parseArgList(): ASTNode[] {
    const args: ASTNode[] = [];
    if (peek().type === TokenType.RParen) return args;

    args.push(parseExpression());
    while (peek().type === TokenType.Comma) {
      advance();
      args.push(parseExpression());
    }
    return args;
  }

  function parseRangeOrList(): ASTNode {
    // Could be a range [a..b], (a..b], a list [a,b,c], or a single expression
    if (peek().type === TokenType.LBracket || peek().type === TokenType.LParen) {
      return parsePrimary();
    }
    // Single value — wrap in a list for uniform handling
    return parseAddSub();
  }

  const result = parseExpression();

  if (peek().type !== TokenType.EOF) {
    throw new ParseError(
      `Unexpected token after expression: ${peek().type} ("${peek().value}")`,
      peek().start,
    );
  }

  return result;
}
