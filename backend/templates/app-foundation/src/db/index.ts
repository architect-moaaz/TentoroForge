import { drizzle } from "drizzle-orm/postgres-js";
import postgres from "postgres";
import * as schema from "./schema";

const connectionString = process.env.DATABASE_URL!;
// One client per process. `next dev` re-evaluates this module on every
// recompile; a fresh `postgres()` each time is a fresh pool of ten, and after
// ten reloads Postgres answers "too many clients already" to everyone —
// the page reviewer's crawl of nlwtcyz5 took the database down that way.
const globalForDb = globalThis as unknown as { __forgeSql?: ReturnType<typeof postgres> };
const client = globalForDb.__forgeSql ?? postgres(connectionString, { prepare: false });
if (process.env.NODE_ENV !== "production") globalForDb.__forgeSql = client;
export const db = drizzle(client, { schema });
