import { describe, it, expect } from "vitest";
import { pageJsonSchema } from "../src/json-schema";

describe("pageJsonSchema", () => {
  it("returns a valid JSON Schema object with $schema and discriminated union branches", () => {
    const js = pageJsonSchema();
    expect(js).toHaveProperty("$schema");
    // Page is now a discriminated union (PageV1 | PageV2) — the schema is emitted
    // as anyOf with two branches, each containing properties.schemaVersion and
    // properties.root. We verify the top-level structure and spot-check one branch.
    const schema = js as Record<string, unknown>;
    expect(schema).toHaveProperty("anyOf");
    const branches = schema["anyOf"] as Array<Record<string, unknown>>;
    expect(branches.length).toBe(2);
    // Both branches must have schemaVersion and root properties
    for (const branch of branches) {
      expect(branch).toHaveProperty("properties.schemaVersion");
      expect(branch).toHaveProperty("properties.root");
    }
  });
});
