import { describe, it, expect } from "vitest";
import { Page, LayoutTemplate, SCHEMA_VERSION } from "../src";

describe("Page", () => {
  it("requires schemaVersion = '1'", () => {
    expect(() =>
      Page.parse({
        schemaVersion: "1",
        id: "p",
        route: "/products",
        root: { id: "r", type: "Box", children: [] },
      })
    ).not.toThrow();

    expect(() =>
      Page.parse({
        schemaVersion: "0",
        id: "p",
        route: "/x",
        root: { id: "r", type: "Box", children: [] },
      })
    ).toThrow(/schemaVersion/);
  });

  it("validates dataSources shape", () => {
    expect(() =>
      Page.parse({
        schemaVersion: SCHEMA_VERSION,
        id: "p",
        route: "/x",
        dataSources: [{ name: "products", entity: "Product", op: "list" }],
        root: { id: "r", type: "Box", children: [] },
      })
    ).not.toThrow();
  });

  it("rejects unknown top-level fields", () => {
    expect(() =>
      Page.parse({
        schemaVersion: SCHEMA_VERSION,
        id: "p",
        route: "/x",
        root: { id: "r", type: "Box", children: [] },
        bogus: 1,
      })
    ).toThrow();
  });
});

describe("LayoutTemplate", () => {
  it("must contain at least one Slot somewhere in its tree", () => {
    expect(() =>
      LayoutTemplate.parse({
        schemaVersion: "1",
        id: "DashboardLayout",
        root: {
          id: "shell",
          type: "Stack",
          children: [{ id: "main", type: "Slot", props: { name: "main" } }],
        },
      })
    ).not.toThrow();

    expect(() =>
      LayoutTemplate.parse({
        schemaVersion: "1",
        id: "Empty",
        root: { id: "x", type: "Box", children: [] },
      })
    ).toThrow(/at least one Slot/);
  });
});
