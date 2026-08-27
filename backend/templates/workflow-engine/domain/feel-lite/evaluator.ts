/** FEEL-lite AST evaluator. */

import type { ASTNode } from './ast';
import { tokenize } from './tokenizer';
import { parse } from './parser';

export type Context = Record<string, unknown>;

const BUILT_IN: Record<string, (...a: unknown[]) => unknown> = {
  sum: (...a) => flat(a).reduce((s, n) => s + n, 0),
  count: (...a) => (a.length === 1 && Array.isArray(a[0]) ? a[0] : a).length,
  min: (...a) => { const n = flat(a); return n.length ? Math.min(...n) : null; },
  max: (...a) => { const n = flat(a); return n.length ? Math.max(...n) : null; },
  avg: (...a) => { const n = flat(a); return n.length ? n.reduce((s, v) => s + v, 0) / n.length : null; },
  abs: (x) => Math.abs(num(x)),
  floor: (x) => Math.floor(num(x)),
  ceiling: (x) => Math.ceil(num(x)),
  round: (x, s?) => { const f = Math.pow(10, s !== undefined ? num(s) : 0); return Math.round(num(x) * f) / f; },
  contains: (s, sub) => String(s).includes(String(sub)),
  'starts with': (s, p) => String(s).startsWith(String(p)),
  'ends with': (s, p) => String(s).endsWith(String(p)),
  matches: (s, p) => { try { return new RegExp(String(p)).test(String(s)); } catch { return false; } },
  string: (x) => String(x ?? ''),
  number: (x) => { const n = Number(x); return isNaN(n) ? null : n; },
  date: (x) => { const d = new Date(String(x)); return isNaN(d.getTime()) ? null : d.toISOString().slice(0, 10); },
  now: () => new Date().toISOString(),
  duration: (x) => { const m = String(x).match(/^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$/i); if (!m) return null; return ((+m[1]||0)*86400+(+m[2]||0)*3600+(+m[3]||0)*60+(+m[4]||0))*1000; },
};

function flat(a: unknown[]): number[] {
  const r: number[] = [];
  for (const v of a) { if (Array.isArray(v)) r.push(...flat(v)); else { const n = Number(v); if (!isNaN(n)) r.push(n); } }
  return r;
}

function num(x: unknown): number { const n = Number(x); return isNaN(n) ? 0 : n; }

function resolve(name: string, ctx: Context): unknown {
  const parts = name.split('.'); let cur: unknown = ctx;
  for (const p of parts) { if (cur == null || typeof cur !== 'object') return undefined; cur = (cur as Record<string, unknown>)[p]; }
  return cur;
}

export function evaluate(node: ASTNode, ctx: Context): unknown {
  switch (node.type) {
    case 'NumberLiteral': return node.value;
    case 'StringLiteral': return node.value;
    case 'BooleanLiteral': return node.value;
    case 'NullLiteral': return null;
    case 'WildcardExpression': return Symbol.for('FEEL_WILDCARD');
    case 'Identifier': return resolve(node.name, ctx);
    case 'MemberExpression': { const o = evaluate(node.object, ctx); if (o == null || typeof o !== 'object') return undefined; return (o as Record<string, unknown>)[node.property]; }
    case 'UnaryExpression': return node.operator === '-' ? -num(evaluate(node.operand, ctx)) : num(evaluate(node.operand, ctx));
    case 'BinaryExpression': {
      const l = evaluate(node.left, ctx), r = evaluate(node.right, ctx);
      if (node.operator === '+' && (typeof l === 'string' || typeof r === 'string')) return String(l??'')+String(r??'');
      const ln = num(l), rn = num(r);
      switch (node.operator) { case '+': return ln+rn; case '-': return ln-rn; case '*': return ln*rn; case '/': return rn===0?null:ln/rn; case '%': return rn===0?null:ln%rn; case '^': return Math.pow(ln,rn); }
      break;
    }
    case 'ComparisonExpression': {
      const l = evaluate(node.left, ctx), r = evaluate(node.right, ctx);
      if (l === null || r === null) { if (node.operator === '=') return l===r; if (node.operator === '!=') return l!==r; return false; }
      if (typeof l === 'number' && typeof r === 'number') { switch(node.operator) { case '=': return l===r; case '!=': return l!==r; case '<': return l<r; case '<=': return l<=r; case '>': return l>r; case '>=': return l>=r; } }
      const ls = String(l), rs = String(r);
      switch(node.operator) { case '=': return ls===rs; case '!=': return ls!==rs; case '<': return ls<rs; case '<=': return ls<=rs; case '>': return ls>rs; case '>=': return ls>=rs; }
      break;
    }
    case 'LogicalExpression': { const l = evaluate(node.left, ctx); return node.operator === 'or' ? Boolean(l)||Boolean(evaluate(node.right, ctx)) : Boolean(l)&&Boolean(evaluate(node.right, ctx)); }
    case 'NotExpression': return !Boolean(evaluate(node.operand, ctx));
    case 'IfExpression': return Boolean(evaluate(node.condition, ctx)) ? evaluate(node.thenBranch, ctx) : evaluate(node.elseBranch, ctx);
    case 'InExpression': return matchValue(evaluate(node.value, ctx), node.list, ctx);
    case 'BetweenExpression': { const v = num(evaluate(node.value, ctx)); return v >= num(evaluate(node.low, ctx)) && v <= num(evaluate(node.high, ctx)); }
    case 'RangeExpression': return { __range: true, startInclusive: node.startInclusive, endInclusive: node.endInclusive, start: evaluate(node.start, ctx), end: evaluate(node.end, ctx) };
    case 'ListExpression': return node.elements.map(el => evaluate(el, ctx));
    case 'FunctionCall': { const fn = BUILT_IN[node.name]; if (!fn) throw new Error(`Unknown function: ${node.name}`); return fn(...node.args.map(a => evaluate(a, ctx))); }
  }
  return null;
}

export function matchValue(value: unknown, pattern: ASTNode, ctx: Context): boolean {
  if (pattern.type === 'WildcardExpression') return true;
  if (pattern.type === 'RangeExpression') {
    const v = num(value), s = num(evaluate(pattern.start, ctx)), e = num(evaluate(pattern.end, ctx));
    return (pattern.startInclusive ? v >= s : v > s) && (pattern.endInclusive ? v <= e : v < e);
  }
  if (pattern.type === 'ListExpression') return pattern.elements.some(el => el.type === 'RangeExpression' ? matchValue(value, el, ctx) : { r: (() => { const ev = evaluate(el, ctx); return value === ev || String(value) === String(ev); })() }.r);
  if (pattern.type === 'NotExpression') return !matchValue(value, pattern.operand, ctx);
  const pv = evaluate(pattern, ctx);
  return value === pv || String(value) === String(pv);
}

export function evaluateExpression(expr: string, ctx: Context = {}): unknown {
  if (!expr?.trim()) return null;
  return evaluate(parse(tokenize(expr)), ctx);
}
