/**
 * Pure evaluator for AutoRefresh's `stopWhen` grammar.
 *
 * Extracted from AutoRefresh.tsx so it's testable without a React
 * runtime. AutoRefresh imports `evalStopWhen` and calls it from its
 * useEffect. The two are the same function; keep them in sync (there's
 * a Node smoke test at src/lib/__tests__/stopWhen.node.mjs that
 * exercises this module).
 *
 * Supported grammar (intentionally narrow — runs client-side, not FEEL):
 *
 *   "scan.status === 'completed'"           strict equality
 *   "scan.status == 'completed'"            loose equality
 *   "scan.status !== 'completed'"           strict inequality
 *   "scan.status IN ('completed','failed')" one-of check (SQL-ish)
 *   "scan.status IS NOT NULL"               truthy check
 *   "scan.status IS NULL"                   nullish check
 *   "!scan"                                 negation
 *
 * Anything else returns false (safer to keep polling than to falsely
 * stop on a mistyped expression). Full FEEL is out of scope.
 */

export function evalStopWhen(expr: string, data: Record<string, unknown>): boolean {
  const trimmed = expr.trim();
  if (!trimmed) return false;

  if (trimmed.startsWith("!")) {
    return !resolvePath(trimmed.slice(1).trim(), data);
  }

  const isNotNull = trimmed.match(/^([\w.]+)\s+IS\s+NOT\s+NULL$/i);
  if (isNotNull) {
    const v = resolvePath(isNotNull[1], data);
    return v != null && v !== "";
  }
  const isNull = trimmed.match(/^([\w.]+)\s+IS\s+NULL$/i);
  if (isNull) {
    const v = resolvePath(isNull[1], data);
    return v == null || v === "";
  }

  const inMatch = trimmed.match(/^([\w.]+)\s+IN\s+\(([^)]+)\)$/i);
  if (inMatch) {
    const v = resolvePath(inMatch[1], data);
    const options = inMatch[2]
      .split(",")
      .map(s => s.trim().replace(/^['"]|['"]$/g, ""));
    return v != null && options.includes(String(v));
  }

  const eqMatch = trimmed.match(/^([\w.]+)\s*(!==?|===?|==)\s*['"]?([^'"]*?)['"]?$/);
  if (eqMatch) {
    const v = resolvePath(eqMatch[1], data);
    const op = eqMatch[2];
    const target = eqMatch[3];
    const equal = v != null && String(v) === target;
    return op.startsWith("!") ? !equal : equal;
  }

  return false;
}

export function resolvePath(path: string, data: Record<string, unknown>): unknown {
  if (!path.includes(".")) return data[path];
  const parts = path.split(".");
  let cur: unknown = data[parts[0]];
  for (let i = 1; i < parts.length && cur != null; i++) {
    cur = (cur as Record<string, unknown>)[parts[i]];
  }
  return cur;
}
