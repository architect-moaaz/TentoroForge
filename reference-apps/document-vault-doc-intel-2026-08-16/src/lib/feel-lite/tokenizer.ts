/** FEEL-lite tokenizer — produces a token stream from an expression string. */

export enum TokenType {
  // Literals
  Number = "Number",
  String = "String",
  Boolean = "Boolean",
  Null = "Null",

  // Identifiers & keywords
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

  // Operators
  Plus = "Plus",
  Minus = "Minus",
  Star = "Star",
  Slash = "Slash",
  Percent = "Percent",
  Power = "Power",

  // Comparison
  Eq = "Eq",           // =
  Neq = "Neq",         // !=
  Lt = "Lt",           // <
  Lte = "Lte",         // <=
  Gt = "Gt",           // >
  Gte = "Gte",         // >=

  // Delimiters
  LParen = "LParen",
  RParen = "RParen",
  LBracket = "LBracket",
  RBracket = "RBracket",
  Comma = "Comma",
  Dot = "Dot",
  DotDot = "DotDot",   // ..
  Colon = "Colon",

  // Special
  Wildcard = "Wildcard", // -  (when used as cell value meaning "any")
  EOF = "EOF",
}

export interface Token {
  type: TokenType;
  value: string;
  start: number;
  end: number;
}

const KEYWORDS: Record<string, TokenType> = {
  if: TokenType.If,
  then: TokenType.Then,
  else: TokenType.Else,
  and: TokenType.And,
  or: TokenType.Or,
  not: TokenType.Not,
  in: TokenType.In,
  between: TokenType.Between,
  true: TokenType.True,
  false: TokenType.False,
  null: TokenType.Null,
};

// String function keywords are just identifiers
const STRING_FUNCTIONS = new Set([
  "starts", "ends", "contains", "matches", "with",
  "sum", "count", "min", "max", "avg",
  "string", "number", "date", "now", "duration",
  "abs", "floor", "ceiling", "round",
]);

export function tokenize(input: string): Token[] {
  const tokens: Token[] = [];
  let pos = 0;

  function peek(): string {
    return pos < input.length ? input[pos] : "";
  }

  function advance(): string {
    return input[pos++];
  }

  function addToken(type: TokenType, value: string, start: number) {
    tokens.push({ type, value, start, end: pos });
  }

  while (pos < input.length) {
    const start = pos;
    const ch = peek();

    // Whitespace
    if (/\s/.test(ch)) {
      advance();
      continue;
    }

    // Numbers
    if (/[0-9]/.test(ch)) {
      let num = "";
      while (pos < input.length && /[0-9.]/.test(input[pos])) {
        num += advance();
      }
      addToken(TokenType.Number, num, start);
      continue;
    }

    // Strings
    if (ch === '"' || ch === "'") {
      const quote = advance();
      let str = "";
      while (pos < input.length && input[pos] !== quote) {
        if (input[pos] === "\\") {
          advance();
          if (pos < input.length) str += advance();
        } else {
          str += advance();
        }
      }
      if (pos < input.length) advance(); // closing quote
      addToken(TokenType.String, str, start);
      continue;
    }

    // Identifiers & keywords
    if (/[a-zA-Z_$]/.test(ch)) {
      let id = "";
      while (pos < input.length && /[a-zA-Z0-9_$.]/.test(input[pos])) {
        // Handle dotted identifiers like customer.age but not ".."
        if (input[pos] === ".") {
          if (pos + 1 < input.length && input[pos + 1] === ".") break;
          if (pos + 1 < input.length && /[a-zA-Z_$]/.test(input[pos + 1])) {
            id += advance();
          } else {
            break;
          }
        } else {
          id += advance();
        }
      }

      const lower = id.toLowerCase();
      if (lower in KEYWORDS) {
        addToken(KEYWORDS[lower], id, start);
      } else {
        addToken(TokenType.Identifier, id, start);
      }
      continue;
    }

    // Multi-character operators
    if (ch === "." && pos + 1 < input.length && input[pos + 1] === ".") {
      advance(); advance();
      addToken(TokenType.DotDot, "..", start);
      continue;
    }
    if (ch === "!" && pos + 1 < input.length && input[pos + 1] === "=") {
      advance(); advance();
      addToken(TokenType.Neq, "!=", start);
      continue;
    }

    // Accept JS `==` as FEEL `=` (LLM-authored conditions emit `x == null`).
    if (ch === "=" && pos + 1 < input.length && input[pos + 1] === "=") {
      advance(); advance();
      addToken(TokenType.Eq, "==", start);
      continue;
    }
    if (ch === "<" && pos + 1 < input.length && input[pos + 1] === "=") {
      advance(); advance();
      addToken(TokenType.Lte, "<=", start);
      continue;
    }
    if (ch === ">" && pos + 1 < input.length && input[pos + 1] === "=") {
      advance(); advance();
      addToken(TokenType.Gte, ">=", start);
      continue;
    }

    // JS-style logical operators as aliases for the FEEL `and`/`or` keywords.
    // LLM-authored conditions (workflow branches, rules) commonly emit
    // `{{a}} != null && {{b}} != null`; accept `&&`/`||` so they tokenize as
    // And/Or and parse+evaluate instead of erroring with "Unexpected token".
    if (ch === "&" && pos + 1 < input.length && input[pos + 1] === "&") {
      advance(); advance();
      addToken(TokenType.And, "&&", start);
      continue;
    }
    if (ch === "|" && pos + 1 < input.length && input[pos + 1] === "|") {
      advance(); advance();
      addToken(TokenType.Or, "||", start);
      continue;
    }

    // Single-character operators
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
        // Wildcard: "-" is a wildcard if it's the only token or surrounded by structural tokens
        const prevToken = tokens.length > 0 ? tokens[tokens.length - 1] : null;
        const isWildcard =
          !prevToken ||
          prevToken.type === TokenType.Comma ||
          prevToken.type === TokenType.LParen ||
          prevToken.type === TokenType.LBracket;

        if (isWildcard && (pos >= input.length || /[\s,)\]]/.test(input[pos]))) {
          addToken(TokenType.Wildcard, "-", start);
        } else {
          addToken(TokenType.Minus, "-", start);
        }
        continue;
      }
    }

    // Skip unknown characters
    advance();
  }

  addToken(TokenType.EOF, "", pos);
  return tokens;
}
