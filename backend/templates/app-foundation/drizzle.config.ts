import type { Config } from "drizzle-kit";

export default {
  schema: "./src/db/schema/",
  out: "./drizzle",
  dialect: "postgresql",
  dbCredentials: {
    url: process.env.DATABASE_URL!,
  },
  // The seed's bookkeeping tables live outside the schema (see assembly.py).
  tablesFilter: ["!_forge_seed_meta", "!_forge_import_log"],
} satisfies Config;
