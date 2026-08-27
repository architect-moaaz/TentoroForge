// packages/schema/tests/page-v2.test.ts
import { describe, it, expect } from "vitest";
import { Page, PageV1, PageV2 } from "../src/page";

describe("Page discriminated union", () => {
  it("accepts a v1 page (schemaVersion '1')", () => {
    const v1 = {
      schemaVersion: "1",
      id: "products/list",
      route: "/products",
      layout: "DashboardLayout",
      meta: { title: "Products" },
      dataSources: [],
      root: { id: "root", type: "Stack", props: {}, children: [] },
    };
    expect(() => Page.parse(v1)).not.toThrow();
  });

  it("accepts a v2 page with new node types + StyleSlot", () => {
    const v2 = {
      schemaVersion: "2",
      id: "products/list",
      route: "/products",
      layout: "DashboardLayout",
      meta: { title: "Products" },
      dataSources: [],
      root: {
        id: "root", type: "Stack",
        style: { padding: "tokens.spacing.semantic.section" },
        children: [
          { id: "h", type: "Hero",
            props: { headline: "Products", layout: "centered", ctas: [] },
            style: { background: { type: "gradient",
                                   from: "tokens.color.primary.50",
                                   to: "tokens.color.surface.0" } } },
        ],
      },
    };
    expect(() => Page.parse(v2)).not.toThrow();
  });

  it("rejects a page with unknown schemaVersion", () => {
    expect(() => Page.parse({ schemaVersion: "3", id: "x", route: "/", layout: "DashboardLayout",
      meta: {}, dataSources: [], root: { id: "r", type: "Stack", props: {}, children: [] } })).toThrow();
  });

  it("PageV2 rejects a Custom node missing html", () => {
    const bad = { schemaVersion: "2", id: "x", route: "/", layout: "DashboardLayout",
      meta: {}, dataSources: [],
      root: { id: "r", type: "Custom", props: {} } };
    expect(() => PageV2.parse(bad)).toThrow();
  });

  it("PageV2 accepts a Hero with motion + gradient", () => {
    const p = {
      schemaVersion: "2", id: "landing", route: "/", layout: "MarketingLayout",
      meta: {}, dataSources: [],
      root: {
        id: "h", type: "Hero",
        props: { headline: "Modern HR", layout: "centered", ctas: [
          { label: "Sign up", action: { type: "navigate", to: "/signup" } },
        ]},
        style: {
          background: { type: "gradient", from: "tokens.color.primary.50", to: "tokens.color.surface.0" },
          motion: "fade-in",
          padding: "tokens.spacing.semantic.section",
        },
      },
    };
    expect(() => PageV2.parse(p)).not.toThrow();
  });

  it("PageV2 rejects unknown root type", () => {
    expect(() => PageV2.parse({
      schemaVersion: "2", id: "x", route: "/", layout: "DashboardLayout",
      meta: {}, dataSources: [],
      root: { id: "r", type: "TotallyMadeUp", props: {} },
    })).toThrow();
  });

  it("PageV2 rejects unknown types nested inside Hero children", () => {
    const bad = {
      schemaVersion: "2", id: "x", route: "/", layout: "DashboardLayout",
      meta: {}, dataSources: [],
      root: {
        id: "h", type: "Hero",
        props: { headline: "X", layout: "centered", ctas: [] },
        children: [{ id: "fake", type: "TotallyMadeUp", props: {} }],
      },
    };
    expect(() => PageV2.parse(bad)).toThrow();
  });

  it("PageV2 rejects unknown types nested inside Section children", () => {
    const bad = {
      schemaVersion: "2", id: "x", route: "/", layout: "DashboardLayout",
      meta: {}, dataSources: [],
      root: {
        id: "s", type: "Section",
        props: { variant: "feature" },
        children: [{ id: "fake", type: "TotallyMadeUp", props: {} }],
      },
    };
    expect(() => PageV2.parse(bad)).toThrow();
  });

  it("PageV2 accepts valid v2 children nested inside Hero", () => {
    const good = {
      schemaVersion: "2", id: "x", route: "/", layout: "DashboardLayout",
      meta: {}, dataSources: [],
      root: {
        id: "h", type: "Hero",
        props: { headline: "X", layout: "centered", ctas: [] },
        children: [{
          id: "m", type: "MetricTile",
          props: { label: "Active users", value: 1234, format: "number" },
        }],
      },
    };
    expect(() => PageV2.parse(good)).not.toThrow();
  });
});
