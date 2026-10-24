/**
 * A small in-memory stand-in for the app's database and the parts of drizzle-orm the insights outbox uses, so
 * turns-store.ts, insights-outbox.ts and handoff-store.ts run in tests exactly as shipped, against rows kept in arrays.
 *
 * It understands only what those files ask of it: select / insert / update / delete with where, orderBy, limit and
 * returning, and the operators eq, ne, and, or, inArray, isNull, lt, gte, asc, desc, count and the one `sql` the outbox
 * uses to count attempts. Anything else throws, so a new kind of query cannot slip past a test unnoticed.
 */

export type Row = Record<string, any>;

/** A table: any property you read is a column of that name. */
function table(name: string, defaults: () => Row) {
  return new Proxy({ __table: name, __defaults: defaults } as any, {
    get(target, prop) {
      if (typeof prop !== "string" || prop in target) return target[prop];
      return { __col: prop, __table: name };
    },
  });
}

const time = (v: any) => (v instanceof Date ? v.getTime() : v);

export function createFakeDb() {
  const rows: Record<string, Row[]> = { turns: [], handoffs: [], conversations: [], messages: [] };
  const log: string[] = [];
  /** Test steering: make the next writes fail (e.g. a column that does not exist yet). */
  const faults = { insertThrows: null as null | (() => Error), updateThrows: null as null | (() => Error), selectThrows: null as null | (() => Error) };

  const turns = table("turns", () => ({}));
  const handoffs = table("handoffs", () => ({}));

  // ── operators: each builds a predicate over a row ──
  const col = (c: any) => c.__col as string;
  const ops = {
    eq: (c: any, v: any) => (r: Row) => time(r[col(c)]) === time(v),
    ne: (c: any, v: any) => (r: Row) => time(r[col(c)]) !== time(v),
    and: (...ps: any[]) => (r: Row) => ps.filter(Boolean).every((p) => p(r)),
    or: (...ps: any[]) => (r: Row) => ps.filter(Boolean).some((p) => p(r)),
    inArray: (c: any, vs: any[]) => (r: Row) => vs.includes(r[col(c)]),
    isNull: (c: any) => (r: Row) => r[col(c)] === null || r[col(c)] === undefined,
    lt: (c: any, v: any) => (r: Row) => r[col(c)] != null && time(r[col(c)]) < time(v),
    gte: (c: any, v: any) => (r: Row) => r[col(c)] != null && time(r[col(c)]) >= time(v),
    asc: (c: any) => ({ col: col(c), dir: 1 }),
    desc: (c: any) => ({ col: col(c), dir: -1 }),
    count: () => ({ __count: true }),
    sql: (strings: TemplateStringsArray, ...values: any[]) => {
      const text = strings.join("?");
      if (/coalesce\(\?, 0\) \+ 1/.test(text)) return { __increment: col(values[0]) };
      return { __rawsql: text };
    },
  };

  const tableRows = (t: any): Row[] => rows[t.__table];
  const applyCols = (r: Row, cols: any): Row => {
    if (!cols) return { ...r };
    const out: Row = {};
    for (const [k, c] of Object.entries<any>(cols)) {
      if (c?.__count) continue;
      out[k] = r[col(c)];
    }
    return out;
  };

  function setValues(r: Row, set: Row) {
    for (const [k, v] of Object.entries(set)) {
      if (v && typeof v === "object" && "__increment" in v) r[k] = (Number(r[v.__increment]) || 0) + 1;
      else r[k] = v;
    }
  }

  const db = {
    select(cols?: any) {
      let t: any;
      let pred: ((r: Row) => boolean) | null = null;
      let order: { col: string; dir: number } | null = null;
      let max = Infinity;
      const run = () => {
        if (faults.selectThrows) throw faults.selectThrows();
        let out = tableRows(t).filter((r) => (pred ? pred(r) : true));
        if (cols && Object.values<any>(cols).some((c) => c?.__count)) {
          return [{ n: out.length }];
        }
        if (order) out = [...out].sort((a, b) => (time(a[order!.col]) - time(b[order!.col]) || 0) * order!.dir);
        return out.slice(0, max).map((r) => applyCols(r, cols));
      };
      const q: any = {
        from(x: any) { t = x; return q; },
        where(p: any) { pred = p; return q; },
        orderBy(o: any) { order = o; return q; },
        limit(n: number) { max = n; return q; },
        then(res: any, rej: any) { try { return Promise.resolve(run()).then(res, rej); } catch (e) { return Promise.reject(e).then(res, rej); } },
      };
      return q;
    },
    insert(t: any) {
      return {
        values(v: Row | Row[]) {
          let ret = false;
          const run = () => {
            if (faults.insertThrows) throw faults.insertThrows();
            const made: Row[] = [];
            for (const one of Array.isArray(v) ? v : [v]) {
              const row: Row = { ...one };
              if (!row.id) row.id = `00000000-0000-4000-8000-${String(tableRows(t).length + 1).padStart(12, "0")}`;
              row.createdAt ??= new Date();
              if (t.__table === "turns") {
                row.shippedAt ??= null; row.shipAttempts ??= 0; row.shipError ??= null; row.rating ??= null; row.ratingAt ??= null;
              }
              log.push(`insert ${t.__table}`);
              tableRows(t).push(row);
              made.push({ ...row });
            }
            return ret ? made : undefined;
          };
          const q: any = {
            returning() { ret = true; return q; },
            then(res: any, rej: any) { try { return Promise.resolve(run()).then(res, rej); } catch (e) { return Promise.reject(e).then(res, rej); } },
          };
          return q;
        },
      };
    },
    update(t: any) {
      let set: Row = {};
      let pred: ((r: Row) => boolean) | null = null;
      let ret: any = null;
      const run = () => {
        if (faults.updateThrows) throw faults.updateThrows();
        const hit = tableRows(t).filter((r) => (pred ? pred(r) : true));
        for (const r of hit) setValues(r, set);
        log.push(`update ${t.__table} ${hit.length}`);
        return ret ? hit.map((r) => applyCols(r, ret)) : undefined;
      };
      const q: any = {
        set(v: Row) { set = v; return q; },
        where(p: any) { pred = p; return q; },
        returning(cols: any) { ret = cols; return q; },
        then(res: any, rej: any) { try { return Promise.resolve(run()).then(res, rej); } catch (e) { return Promise.reject(e).then(res, rej); } },
      };
      return q;
    },
    delete(t: any) {
      let pred: ((r: Row) => boolean) | null = null;
      const q: any = {
        where(p: any) { pred = p; return q; },
        then(res: any, rej: any) {
          const all = tableRows(t);
          const keep = all.filter((r) => (pred ? !pred(r) : false));
          log.push(`delete ${t.__table} ${all.length - keep.length}`);
          rows[t.__table] = keep;
          return Promise.resolve(undefined).then(res, rej);
        },
      };
      return q;
    },
  };

  return { db, rows, ops, turns, handoffs, log, faults };
}

/** The stub modules for installHarness, wired to one fake database held on globalThis.__fake. */
export function fakeDbStubs(): Record<string, string> {
  const names = ["eq", "ne", "and", "or", "inArray", "isNull", "lt", "gte", "asc", "desc", "count", "sql"];
  return {
    "@/db": "export const db = globalThis.__fake.db;",
    "@/db/schema/_forge_agent_turns": "export const forgeAgentTurns = globalThis.__fake.turns;",
    "@/db/schema/_forge_agent_handoffs": "export const forgeAgentHandoffs = globalThis.__fake.handoffs;",
    "@/db/schema/_forge_agent": "export const forgeAgentConversations = {}; export const forgeAgentMessages = {};",
    "@/db/schema/_forge_notifications": "export const forgeNotifications = {};",
    "drizzle-orm": names.map((n) => `export const ${n} = globalThis.__fake.ops.${n};`).join("\n"),
  };
}
