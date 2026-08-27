/** FEEL-lite expression engine — barrel export. */

export { tokenize, TokenType, type Token } from './tokenizer';
export { parse, ParseError } from './parser';
export type { ASTNode } from './ast';
export { evaluate, matchValue, evaluateExpression, type Context } from './evaluator';
