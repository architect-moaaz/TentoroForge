declare module "@tentoroforge/feel-lite" {
  export type Context = Record<string, unknown>;
  export function evaluateExpression(expr: string, ctx?: Context): unknown;
}
