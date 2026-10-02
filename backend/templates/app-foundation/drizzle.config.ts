import type { Config } from "drizzle-kit";

export default {
  schema: "./src/db/schema/",
  out: "./drizzle",
  dialect: "postgresql",
  dbCredentials: {
    url: process.env.DATABASE_URL!,
  },
  // The seed's bookkeeping table lives outside the schema (see assembly.py).
  tablesFilter: ["!_forge_seed_meta"],
} satisfies Config;
