/**
 * Data Engine — Aggregations
 *
 * Provides count/sum/avg/min/max with optional group-by and filtering.
 *
 * Uses `db: any` because the actual query construction depends on the
 * ORM/driver in the generated app (typically Drizzle ORM).
 * The pseudocode below is written for Drizzle — adapt as needed.
 *
 * Route: POST /api/data/{table}/aggregate
 */

export type AggregationFn = "count" | "sum" | "avg" | "min" | "max";

export interface AggregationQuery {
  table: string;
  fn: AggregationFn;
  field?: string;            // required for sum/avg/min/max
  groupBy?: string[];        // optional grouping fields
  filter?: Record<string, any>;
}

export interface AggregationResult {
  groups: Array<Record<string, any> & { _count: number; _value?: number }>;
  total: number;
}

/**
 * Execute an aggregation query against the given table.
 *
 * NOTE: This is a sketch — the actual DB query construction depends on
 * whether the generated app uses Drizzle / Prisma / raw SQL.
 * The implementer should adapt to the actual ORM in use.
 * For Drizzle, replace `db.insert(TABLE)` patterns with the proper
 * Drizzle query-builder calls shown in the pseudocode below.
 *
 * @param db     DB connection (Drizzle `db`, Prisma `prisma`, etc.)
 * @param query  Aggregation parameters
 */
export async function executeAggregation(
  db: any,
  query: AggregationQuery,
): Promise<AggregationResult> {
  const { table, fn, field, groupBy = [], filter } = query;

  // Whitelist aggregation function to prevent injection
  if (!["count", "sum", "avg", "min", "max"].includes(fn)) {
    throw new Error(`invalid aggregation: ${fn}`);
  }
  if (fn !== "count" && !field) {
    throw new Error(`aggregation ${fn} requires a field`);
  }

  // Build query — actual implementation depends on the DB driver
  // Pseudocode for Drizzle:
  let qb = db.select({
    ...Object.fromEntries(groupBy.map((g) => [g, db[table][g]])),
    _count: db.count(),
    _value: fn !== "count" && field ? db[fn](db[table][field]) : undefined,
  }).from(db[table]);

  if (filter) {
    for (const [k, v] of Object.entries(filter)) {
      qb = qb.where(db[table][k].eq(v));
    }
  }

  if (groupBy.length > 0) {
    qb = qb.groupBy(...groupBy.map((g) => db[table][g]));
  }

  const groups = await qb;
  const total = groups.reduce((acc: number, g: any) => acc + (g._count ?? 0), 0);
  return { groups, total };
}
