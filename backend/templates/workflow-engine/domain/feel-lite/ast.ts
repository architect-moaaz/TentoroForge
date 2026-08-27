/** FEEL-lite AST node types. */

export type ASTNode =
  | NumberLiteral | StringLiteral | BooleanLiteral | NullLiteral
  | Identifier | UnaryExpression | BinaryExpression | ComparisonExpression
  | LogicalExpression | RangeExpression | ListExpression | InExpression
  | NotExpression | IfExpression | FunctionCall | MemberExpression
  | WildcardExpression | BetweenExpression;

export interface NumberLiteral { type: "NumberLiteral"; value: number; }
export interface StringLiteral { type: "StringLiteral"; value: string; }
export interface BooleanLiteral { type: "BooleanLiteral"; value: boolean; }
export interface NullLiteral { type: "NullLiteral"; }
export interface Identifier { type: "Identifier"; name: string; }
export interface UnaryExpression { type: "UnaryExpression"; operator: "-" | "+"; operand: ASTNode; }
export interface BinaryExpression { type: "BinaryExpression"; operator: "+" | "-" | "*" | "/" | "%" | "^"; left: ASTNode; right: ASTNode; }
export interface ComparisonExpression { type: "ComparisonExpression"; operator: "=" | "!=" | "<" | "<=" | ">" | ">="; left: ASTNode; right: ASTNode; }
export interface LogicalExpression { type: "LogicalExpression"; operator: "and" | "or"; left: ASTNode; right: ASTNode; }
export interface RangeExpression { type: "RangeExpression"; startInclusive: boolean; endInclusive: boolean; start: ASTNode; end: ASTNode; }
export interface ListExpression { type: "ListExpression"; elements: ASTNode[]; }
export interface InExpression { type: "InExpression"; value: ASTNode; list: ASTNode; }
export interface NotExpression { type: "NotExpression"; operand: ASTNode; }
export interface IfExpression { type: "IfExpression"; condition: ASTNode; thenBranch: ASTNode; elseBranch: ASTNode; }
export interface FunctionCall { type: "FunctionCall"; name: string; args: ASTNode[]; }
export interface MemberExpression { type: "MemberExpression"; object: ASTNode; property: string; }
export interface WildcardExpression { type: "WildcardExpression"; }
export interface BetweenExpression { type: "BetweenExpression"; value: ASTNode; low: ASTNode; high: ASTNode; }
