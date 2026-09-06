/** FEEL-lite tokenizer — produces a token stream from an expression string. */

export enum TokenType {
  Number = "Number",
  String = "String",
  Boolean = "Boolean",
  Null = "Null",
  Identifier = "Identifier",
  If = "If",
  Then = "Then",
  Else = "Else",
  And = "And",
  Or = "Or",
  Not = "Not",
  In = "In",
  Between = "Between",
  True = "True",
  False = "False",
  Plus = "Plus",
  Minus = "Minus",
  Star = "Star",
  Slash = "Slash",
  Percent = "Percent",
  Power = "Power",
  Eq = "Eq",
  Neq = "Neq",
  Lt = "Lt",
  Lte = "Lte",
  Gt = "Gt",
  Gte = "Gte",
  LParen = "LParen",
  RParen = "RParen",
  LBracket = "LBracket",
  RBracket = "RBracket",
  Comma = "Comma",
  Dot = "Dot",
  DotDot = "DotDot",
  Colon = "Colon",
  Wildcard = "Wildcard",
  EOF = "EOF",
}

export interface Token {
  type: TokenType;
  value: string;
  start: number;
  end: number;
}

const KEYWORDS: Record<string, TokenType> = {
  if: TokenType.If, then: TokenType.Then, else: TokenType.Else,
  and: TokenType.And, or: TokenType.Or, not: TokenType.Not,
  in: TokenType.In, between: TokenType.Between,
  true: TokenType.True, false: TokenType.False, null: TokenType.Null,
};

export function tokenize(input: string): Token[] {
  const tokens: Token[] = [];
  let pos = 0;

  function peek(): string { return pos < input.length ? input[pos] : ""; }
  function advance(): string { return input[pos++]; }
  function addToken(type: TokenType, value: string, start: number) {
    tokens.push({ type, value, start, end: pos });
  }

  while (pos < input.length) {
    const start = pos;
    const ch = peek();

    if (/\s/.test(ch)) { advance(); continue; }

    if (/[0-9]/.test(ch)) {
      let num = "";
      while (pos < input.length && /[0-9.]/.test(input[pos])) num += advance();
      addToken(TokenType.Number, num, start);
      continue;
    }

    if (ch === '"' || ch === "'") {
      const quote = advance();
      let str = "";
      while (pos < input.length && input[pos] !== quote) {
        if (input[pos] === "\\") { advance(); if (pos < input.length) str += advance(); }
        else str += advance();
      }
      if (pos < input.length) advance();
      addToken(TokenType.String, str, start);
      continue;
    }

    if (/[a-zA-Z_$]/.test(ch)) {
      let id = "";
      while (pos < input.length && /[a-zA-Z0-9_$.]/.test(input[pos])) {
        if (input[pos] === ".") {
          if (pos + 1 < input.length && input[pos + 1] === ".") break;
          if (pos + 1 < input.length && /[a-zA-Z_$]/.test(input[pos + 1])) id += advance();
          else break;
        } else id += advance();
      }
      const lower = id.toLowerCase();
      addToken(lower in KEYWORDS ? KEYWORDS[lower] : TokenType.Identifier, id, start);
      continue;
    }

    if (ch === "." && pos + 1 < input.length && input[pos + 1] === ".") { advance(); advance(); addToken(TokenType.DotDot, "..", start); continue; }
    if (ch === "!" && pos + 1 < input.length && input[pos + 1] === "=") { advance(); advance(); addToken(TokenType.Neq, "!=", start); continue; }
    if (ch === "<" && pos + 1 < input.length && input[pos + 1] === "=") { advance(); advance(); addToken(TokenType.Lte, "<=", start); continue; }
    if (ch === ">" && pos + 1 < input.length && input[pos + 1] === "=") { advance(); advance(); addToken(TokenType.Gte, ">=", start); continue; }

    switch (ch) {
      case "+": advance(); addToken(TokenType.Plus, "+", start); continue;
      case "*": advance(); addToken(TokenType.Star, "*", start); continue;
      case "/": advance(); addToken(TokenType.Slash, "/", start); continue;
      case "%": advance(); addToken(TokenType.Percent, "%", start); continue;
      case "^": advance(); addToken(TokenType.Power, "^", start); continue;
      case "=": advance(); addToken(TokenType.Eq, "=", start); continue;
      case "<": advance(); addToken(TokenType.Lt, "<", start); continue;
      case ">": advance(); addToken(TokenType.Gt, ">", start); continue;
      case "(": advance(); addToken(TokenType.LParen, "(", start); continue;
      case ")": advance(); addToken(TokenType.RParen, ")", start); continue;
      case "[": advance(); addToken(TokenType.LBracket, "[", start); continue;
      case "]": advance(); addToken(TokenType.RBracket, "]", start); continue;
      case ",": advance(); addToken(TokenType.Comma, ",", start); continue;
      case ".": advance(); addToken(TokenType.Dot, ".", start); continue;
      case ":": advance(); addToken(TokenType.Colon, ":", start); continue;
      case "-": {
        advance();
        const prev = tokens.length > 0 ? tokens[tokens.length - 1] : null;
        const isWC = !prev || prev.type === TokenType.Comma || prev.type === TokenType.LParen || prev.type === TokenType.LBracket;
        if (isWC && (pos >= input.length || /[\s,)\]]/.test(input[pos]))) addToken(TokenType.Wildcard, "-", start);
        else addToken(TokenType.Minus, "-", start);
        continue;
      }
    }
    advance();
  }

  addToken(TokenType.EOF, "", pos);
  return tokens;
}
