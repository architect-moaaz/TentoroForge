/** FEEL-lite recursive descent parser. */

import { TokenType, type Token } from './tokenizer';
import type { ASTNode } from './ast';

export class ParseError extends Error {
  constructor(message: string, public position: number) {
    super(message);
    this.name = 'ParseError';
  }
}

export function parse(tokens: Token[]): ASTNode {
  let pos = 0;

  function peek(): Token { return tokens[pos]; }
  function advance(): Token { return tokens[pos++]; }
  function expect(type: TokenType): Token {
    const tok = peek();
    if (tok.type !== type) throw new ParseError(`Expected ${type} but got ${tok.type}`, tok.start);
    return advance();
  }

  function parseExpression(): ASTNode {
    if (peek().type === TokenType.If) return parseIf();
    return parseOr();
  }

  function parseIf(): ASTNode {
    expect(TokenType.If);
    const condition = parseExpression();
    expect(TokenType.Then);
    const thenBranch = parseExpression();
    expect(TokenType.Else);
    const elseBranch = parseExpression();
    return { type: 'IfExpression', condition, thenBranch, elseBranch };
  }

  function parseOr(): ASTNode {
    let left = parseAnd();
    while (peek().type === TokenType.Or) { advance(); left = { type: 'LogicalExpression', operator: 'or', left, right: parseAnd() }; }
    return left;
  }

  function parseAnd(): ASTNode {
    let left = parseNot();
    while (peek().type === TokenType.And) { advance(); left = { type: 'LogicalExpression', operator: 'and', left, right: parseNot() }; }
    return left;
  }

  function parseNot(): ASTNode {
    if (peek().type === TokenType.Not) {
      advance();
      if (peek().type === TokenType.LParen) { expect(TokenType.LParen); const op = parseExpression(); expect(TokenType.RParen); return { type: 'NotExpression', operand: op }; }
      return { type: 'NotExpression', operand: parseNot() };
    }
    return parseComparison();
  }

  function parseComparison(): ASTNode {
    let left = parseAddSub();
    if (peek().type === TokenType.In) { advance(); return { type: 'InExpression', value: left, list: parseRangeOrList() }; }
    if (peek().type === TokenType.Between) { advance(); const low = parseAddSub(); expect(TokenType.And); const high = parseAddSub(); return { type: 'BetweenExpression', value: left, low, high }; }
    const ops: Record<string, '=' | '!=' | '<' | '<=' | '>' | '>='> = { [TokenType.Eq]: '=', [TokenType.Neq]: '!=', [TokenType.Lt]: '<', [TokenType.Lte]: '<=', [TokenType.Gt]: '>', [TokenType.Gte]: '>=' };
    if (peek().type in ops) { const op = advance(); return { type: 'ComparisonExpression', operator: ops[op.type], left, right: parseAddSub() }; }
    return left;
  }

  function parseAddSub(): ASTNode {
    let left = parseMulDiv();
    while (peek().type === TokenType.Plus || peek().type === TokenType.Minus) {
      const op = advance();
      left = { type: 'BinaryExpression', operator: op.type === TokenType.Plus ? '+' : '-', left, right: parseMulDiv() };
    }
    return left;
  }

  function parseMulDiv(): ASTNode {
    let left = parsePower();
    while (peek().type === TokenType.Star || peek().type === TokenType.Slash || peek().type === TokenType.Percent) {
      const op = advance();
      left = { type: 'BinaryExpression', operator: op.type === TokenType.Star ? '*' : op.type === TokenType.Slash ? '/' : '%', left, right: parsePower() };
    }
    return left;
  }

  function parsePower(): ASTNode {
    let left = parseUnary();
    while (peek().type === TokenType.Power) { advance(); left = { type: 'BinaryExpression', operator: '^', left, right: parseUnary() }; }
    return left;
  }

  function parseUnary(): ASTNode {
    if (peek().type === TokenType.Minus) { advance(); return { type: 'UnaryExpression', operator: '-', operand: parseUnary() }; }
    if (peek().type === TokenType.Plus) { advance(); return parseUnary(); }
    return parsePostfix();
  }

  function parsePostfix(): ASTNode {
    let node = parsePrimary();
    while (peek().type === TokenType.Dot) { advance(); const p = expect(TokenType.Identifier); node = { type: 'MemberExpression', object: node, property: p.value }; }
    return node;
  }

  function parsePrimary(): ASTNode {
    const tok = peek();
    if (tok.type === TokenType.Wildcard) { advance(); return { type: 'WildcardExpression' }; }
    if (tok.type === TokenType.Number) { advance(); return { type: 'NumberLiteral', value: parseFloat(tok.value) }; }
    if (tok.type === TokenType.String) { advance(); return { type: 'StringLiteral', value: tok.value }; }
    if (tok.type === TokenType.True) { advance(); return { type: 'BooleanLiteral', value: true }; }
    if (tok.type === TokenType.False) { advance(); return { type: 'BooleanLiteral', value: false }; }
    if (tok.type === TokenType.Null) { advance(); return { type: 'NullLiteral' }; }

    if (tok.type === TokenType.Identifier) {
      const id = advance();
      if ((id.value === 'starts' || id.value === 'ends') && peek().type === TokenType.Identifier && peek().value === 'with') {
        advance(); const name = id.value + ' with'; expect(TokenType.LParen); const args = parseArgList(); expect(TokenType.RParen);
        return { type: 'FunctionCall', name, args };
      }
      if (peek().type === TokenType.LParen) { advance(); const args = parseArgList(); expect(TokenType.RParen); return { type: 'FunctionCall', name: id.value, args }; }
      return { type: 'Identifier', name: id.value };
    }

    if (tok.type === TokenType.LParen) {
      advance(); const expr = parseExpression();
      if (peek().type === TokenType.DotDot) {
        advance(); const end = parseExpression();
        const endInc = peek().type === TokenType.RBracket;
        if (peek().type === TokenType.RParen) { advance(); return { type: 'RangeExpression', startInclusive: false, endInclusive: false, start: expr, end }; }
        if (peek().type === TokenType.RBracket) { advance(); return { type: 'RangeExpression', startInclusive: false, endInclusive: true, start: expr, end }; }
      }
      expect(TokenType.RParen); return expr;
    }

    if (tok.type === TokenType.LBracket) {
      advance();
      if (peek().type === TokenType.RBracket) { advance(); return { type: 'ListExpression', elements: [] }; }
      const first = parseExpression();
      if (peek().type === TokenType.DotDot) {
        advance(); const end = parseExpression();
        if (peek().type === TokenType.RBracket) { advance(); return { type: 'RangeExpression', startInclusive: true, endInclusive: true, start: first, end }; }
        if (peek().type === TokenType.RParen) { advance(); return { type: 'RangeExpression', startInclusive: true, endInclusive: false, start: first, end }; }
        throw new ParseError('Expected ] or ) to close range', peek().start);
      }
      const elements: ASTNode[] = [first];
      while (peek().type === TokenType.Comma) { advance(); elements.push(parseExpression()); }
      expect(TokenType.RBracket);
      return { type: 'ListExpression', elements };
    }

    if (tok.type === TokenType.Not) {
      advance();
      if (peek().type === TokenType.LParen) { expect(TokenType.LParen); const op = parseExpression(); expect(TokenType.RParen); return { type: 'NotExpression', operand: op }; }
      return { type: 'NotExpression', operand: parsePrimary() };
    }

    throw new ParseError(`Unexpected token: ${tok.type}`, tok.start);
  }

  function parseArgList(): ASTNode[] {
    const args: ASTNode[] = [];
    if (peek().type === TokenType.RParen) return args;
    args.push(parseExpression());
    while (peek().type === TokenType.Comma) { advance(); args.push(parseExpression()); }
    return args;
  }

  function parseRangeOrList(): ASTNode {
    if (peek().type === TokenType.LBracket || peek().type === TokenType.LParen) return parsePrimary();
    return parseAddSub();
  }

  const result = parseExpression();
  if (peek().type !== TokenType.EOF) throw new ParseError(`Unexpected token after expression: ${peek().type}`, peek().start);
  return result;
}
