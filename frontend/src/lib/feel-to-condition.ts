// ---------------------------------------------------------------------------
// FEEL-lite → visual condition tree (the inverse of condition-to-feel)
//
// A rule's condition has ONE record: the FEEL text in the Blueprint (`when`),
// which the app's engine runs and Smith reads. The visual builder edits a tree,
// so a rule written by the build or by Smith is read back into a tree here.
// It reads the subset the builder can show — comparisons, `in` lists, null
// tests, the four text functions, and/or/not groups — and answers `undefined`
// for anything else, so the editor can offer the expression as text instead of
// showing a tree that means something different.
// ---------------------------------------------------------------------------

import type {
  ConditionExpression,
  ConditionGroup,
  ConditionNode,
  ConditionOperator,
} from "@/types/rules";

type Tok =
  | { t: "ident"; v: string }
  | { t: "str"; v: string }
  | { t: "num"; v: string }
  | { t: "op"; v: string }
  | { t: "punc"; v: string };

class Unreadable extends Error {}

function tokenize(src: string): Tok[] {
  const out: Tok[] = [];
  let i = 0;
  while (i < src.length) {
    const c = src[i];
    if (/\s/.test(c)) { i++; continue; }
    if (c === '"') {
      let j = i + 1;
      let s = "";
      while (j < src.length && src[j] !== '"') {
        if (src[j] === "\\" && j + 1 < src.length) { s += src[j + 1]; j += 2; continue; }
        s += src[j++];
      }
      if (j >= src.length) throw new Unreadable("unterminated string");
      out.push({ t: "str", v: s });
      i = j + 1;
      continue;
    }
    if (/[0-9]/.test(c) || (c === "-" && /[0-9]/.test(src[i + 1] ?? "") && !lastIsValue(out))) {
      let j = i + 1;
      while (j < src.length && /[0-9.]/.test(src[j])) j++;
      out.push({ t: "num", v: src.slice(i, j) });
      i = j;
      continue;
    }
    if (/[A-Za-z_]/.test(c)) {
      let j = i + 1;
      while (j < src.length && /[A-Za-z0-9_.]/.test(src[j])) j++;
      out.push({ t: "ident", v: src.slice(i, j) });
      i = j;
      continue;
    }
    const two = src.slice(i, i + 2);
    if (two === "!=" || two === ">=" || two === "<=") { out.push({ t: "op", v: two }); i += 2; continue; }
    if (c === "=" || c === ">" || c === "<") { out.push({ t: "op", v: c }); i++; continue; }
    if ("()[],".includes(c)) { out.push({ t: "punc", v: c }); i++; continue; }
    throw new Unreadable(`unexpected ${c}`);
  }
  return out;
}

function lastIsValue(toks: Tok[]): boolean {
  const l = toks[toks.length - 1];
  return !!l && (l.t === "ident" || l.t === "num" || l.t === "str" || (l.t === "punc" && (l.v === ")" || l.v === "]")));
}

const OPS: Record<string, ConditionOperator> = {
  "=": "equals", "!=": "not_equals", ">": "gt", ">=": "gte", "<": "lt", "<=": "lte",
};
const FUNCS: Record<string, ConditionOperator> = {
  matches: "matches_regex", contains: "contains", starts_with: "starts_with", ends_with: "ends_with",
};
const WORDS = new Set(["and", "or", "not", "in", "true", "false", "null"]);

export function feelToCondition(feel: string | null | undefined): ConditionExpression | null | undefined {
  const text = (feel ?? "").trim();
  if (!text || text === "true") return null;
  let toks: Tok[];
  try {
    toks = tokenize(text);
  } catch {
    return undefined;
  }
  let p = 0;
  let n = 0;
  const id = () => `c_${++n}_${Math.random().toString(36).slice(2, 7)}`;
  const peek = () => toks[p];
  const isWord = (w: string) => peek()?.t === "ident" && (peek() as { v: string }).v === w;
  const expectPunc = (v: string) => {
    const t = toks[p++];
    if (!t || t.t !== "punc" || t.v !== v) throw new Unreadable(`expected ${v}`);
  };

  const value = (): string => {
    const t = toks[p++];
    if (!t) throw new Unreadable("missing value");
    if (t.t === "str" || t.t === "num") return t.v;
    if (t.t === "ident" && (t.v === "true" || t.v === "false")) return t.v;
    if (t.t === "ident" && /^user\.[A-Za-z_][A-Za-z0-9_]*$/.test(t.v)) return t.v;
    throw new Unreadable("not a value");
  };

  const field = (): string => {
    const t = toks[p++];
    if (!t || t.t !== "ident" || WORDS.has(t.v)) throw new Unreadable("not a field");
    return t.v;
  };

  const list = (): string => {
    expectPunc("[");
    const items: string[] = [];
    while (peek() && !(peek().t === "punc" && (peek() as { v: string }).v === "]")) {
      items.push(value());
      if (peek()?.t === "punc" && (peek() as { v: string }).v === ",") p++;
    }
    expectPunc("]");
    return items.join(", ");
  };

  const leaf = (): ConditionNode => {
    const t = peek();
    if (t?.t === "ident" && FUNCS[t.v] && toks[p + 1]?.t === "punc" && (toks[p + 1] as { v: string }).v === "(") {
      p += 2;
      const f = field();
      expectPunc(",");
      const v = value();
      expectPunc(")");
      return { id: id(), field: f, operator: FUNCS[t.v], value: v };
    }
    const f = field();
    if (isWord("in")) {
      p++;
      return { id: id(), field: f, operator: "in", value: list() };
    }
    const o = toks[p++];
    if (!o || o.t !== "op") throw new Unreadable("expected a comparison");
    if (isWord("null")) {
      p++;
      if (o.v === "=") return { id: id(), field: f, operator: "is_null", value: "" };
      if (o.v === "!=") return { id: id(), field: f, operator: "is_not_null", value: "" };
      throw new Unreadable("null compares by = or != only");
    }
    return { id: id(), field: f, operator: OPS[o.v], value: value() };
  };

  const unary = (): ConditionExpression => {
    if (isWord("not") && toks[p + 1]?.t === "punc" && (toks[p + 1] as { v: string }).v === "(") {
      p += 2;
      const save = p;
      // not(x in [..]) is the builder's "not in"
      try {
        const f = field();
        if (isWord("in")) {
          p++;
          const v = list();
          expectPunc(")");
          return { id: id(), field: f, operator: "not_in", value: v };
        }
      } catch { /* fall through to a NOT group */ }
      p = save;
      const inner = orExpr();
      expectPunc(")");
      return { id: id(), logic: "NOT", conditions: [inner] };
    }
    if (peek()?.t === "punc" && (peek() as { v: string }).v === "(") {
      p++;
      const inner = orExpr();
      expectPunc(")");
      return inner;
    }
    return leaf();
  };

  const join = (logic: "AND" | "OR", parts: ConditionExpression[]): ConditionExpression => {
    if (parts.length === 1) return parts[0];
    const flat: ConditionExpression[] = [];
    for (const part of parts) {
      if ("logic" in part && part.logic === logic) flat.push(...part.conditions);
      else flat.push(part);
    }
    return { id: id(), logic, conditions: flat } as ConditionGroup;
  };

  const andExpr = (): ConditionExpression => {
    const parts = [unary()];
    while (isWord("and")) { p++; parts.push(unary()); }
    return join("AND", parts);
  };

  const orExpr = (): ConditionExpression => {
    const parts = [andExpr()];
    while (isWord("or")) { p++; parts.push(andExpr()); }
    return join("OR", parts);
  };

  try {
    const tree = orExpr();
    if (p !== toks.length) return undefined;
    return tree;
  } catch {
    return undefined;
  }
}

/** Every field a condition tree reads. */
export function conditionFields(expr: ConditionExpression | null | undefined): string[] {
  if (!expr) return [];
  if ("logic" in expr) return expr.conditions.flatMap((c) => conditionFields(c));
  return [expr.field];
}
