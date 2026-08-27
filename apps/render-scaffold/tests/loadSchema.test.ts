import { describe, it } from "node:test";
import assert from "node:assert";
import { loadSchema } from "../src/lib/loadSchema";
import { mkdtempSync, writeFileSync, mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

describe("loadSchema", () => {
  it("reads a schema from disk by projectRoot + page route", async () => {
    const root = mkdtempSync(join(tmpdir(), "scaffold-test-"));
    mkdirSync(join(root, "src/schemas/users"), { recursive: true });
    writeFileSync(join(root, "src/schemas/users/list.json"), JSON.stringify({
      schemaVersion: "1", id: "users/list", route: "/users",
      layout: "DashboardLayout", meta: { title: "Users" },
      dataSources: [], root: { id: "r", type: "Stack", props: {}, children: [] },
    }));
    const schema = await loadSchema(root, "users/list") as any;
    assert.equal(schema?.id, "users/list");
  });

  it("returns null when schema is missing", async () => {
    const root = mkdtempSync(join(tmpdir(), "scaffold-test-"));
    const schema = await loadSchema(root, "does/not-exist");
    assert.equal(schema, null);
  });

  it("prefers <slug>.json over legacy <slug>/list.json when both exist", async () => {
    const root = mkdtempSync(join(tmpdir(), "scaffold-test-"));
    mkdirSync(join(root, "src/schemas/notes"), { recursive: true });
    // New route-slug layout — should win.
    writeFileSync(join(root, "src/schemas/notes.json"), JSON.stringify({
      schemaVersion: "1", id: "notes", route: "/notes",
      layout: "DashboardLayout", meta: { title: "Notes (new)" },
      dataSources: [], root: { id: "r", type: "Stack", props: {}, children: [] },
    }));
    // Legacy <entity>/list.json — should be ignored when the new path exists.
    writeFileSync(join(root, "src/schemas/notes/list.json"), JSON.stringify({
      schemaVersion: "1", id: "notes/list", route: "/notes",
      layout: "DashboardLayout", meta: { title: "Notes (legacy)" },
      dataSources: [], root: { id: "r", type: "Stack", props: {}, children: [] },
    }));
    const schema = await loadSchema(root, "notes") as any;
    assert.equal(schema?.id, "notes");
  });

  it("falls back to <slug>/list.json when <slug>.json is missing", async () => {
    const root = mkdtempSync(join(tmpdir(), "scaffold-test-"));
    mkdirSync(join(root, "src/schemas/notes"), { recursive: true });
    writeFileSync(join(root, "src/schemas/notes/list.json"), JSON.stringify({
      schemaVersion: "1", id: "notes/list", route: "/notes",
      layout: "DashboardLayout", meta: { title: "Notes (legacy)" },
      dataSources: [], root: { id: "r", type: "Stack", props: {}, children: [] },
    }));
    const schema = await loadSchema(root, "notes") as any;
    assert.equal(schema?.id, "notes/list");
  });
});
