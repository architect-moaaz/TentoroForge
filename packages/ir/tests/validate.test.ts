import { describe, it, expect } from "vitest";
import { readFileSync } from "fs";
import { join, dirname } from "path";
import { fileURLToPath } from "url";
import { validateIR } from "../src/validate.js";
import type { AppIR } from "../src/types.js";

const __dirname = dirname(fileURLToPath(import.meta.url));
const fixturesDir = join(__dirname, "..", "fixtures");

function loadFixture(name: string): AppIR {
  const raw = readFileSync(join(fixturesDir, `${name}.json`), "utf-8");
  return JSON.parse(raw);
}

describe("validateIR", () => {
  // ─── Fixtures should pass validation ───

  describe("fixtures", () => {
    const fixtures = [
      "simple-table",
      "sidebar-detail",
      "form-page",
      "dashboard",
      "auth-login",
      "settings",
    ];

    for (const name of fixtures) {
      it(`fixture "${name}" should be valid`, () => {
        const ir = loadFixture(name);
        const errors = validateIR(ir);
        const criticalErrors = errors.filter((e) => e.severity === "error");
        if (criticalErrors.length > 0) {
          console.error(`Errors in ${name}:`, JSON.stringify(criticalErrors, null, 2));
        }
        expect(criticalErrors).toHaveLength(0);
      });
    }
  });

  // ─── Schema validation ───

  describe("schema", () => {
    it("should reject unknown schema version", () => {
      const ir: AppIR = {
        $schema: "wrong/1.0" as AppIR["$schema"],
        app: { name: "Test" },
        tokens: {},
        dataSources: {},
        pages: [],
      };
      const errors = validateIR(ir);
      expect(errors.some((e) => e.code === "INVALID_SCHEMA")).toBe(true);
    });

    it("should require app name", () => {
      const ir: AppIR = {
        $schema: "tentoroforge/ir/1.0",
        app: { name: "" },
        tokens: {},
        dataSources: {},
        pages: [],
      };
      const errors = validateIR(ir);
      expect(errors.some((e) => e.code === "MISSING_REQUIRED" && e.path === "app.name")).toBe(true);
    });
  });

  // ─── Page validation ───

  describe("pages", () => {
    it("should require page $id and route", () => {
      const ir: AppIR = {
        $schema: "tentoroforge/ir/1.0",
        app: { name: "Test" },
        tokens: {},
        dataSources: {},
        pages: [
          {
            $id: "",
            route: "",
            root: { node: "Stack", children: [] },
          },
        ],
      };
      const errors = validateIR(ir);
      expect(errors.some((e) => e.code === "MISSING_REQUIRED" && e.path.includes("$id"))).toBe(true);
      expect(errors.some((e) => e.code === "MISSING_REQUIRED" && e.path.includes("route"))).toBe(true);
    });

    it("should detect duplicate page IDs", () => {
      const ir: AppIR = {
        $schema: "tentoroforge/ir/1.0",
        app: { name: "Test" },
        tokens: {},
        dataSources: {},
        pages: [
          { $id: "page-1", route: "/a", root: { node: "Stack", children: [] } },
          { $id: "page-1", route: "/b", root: { node: "Stack", children: [] } },
        ],
      };
      const errors = validateIR(ir);
      expect(errors.some((e) => e.code === "DUPLICATE_PAGE_ID")).toBe(true);
    });

    it("should detect duplicate routes", () => {
      const ir: AppIR = {
        $schema: "tentoroforge/ir/1.0",
        app: { name: "Test" },
        tokens: {},
        dataSources: {},
        pages: [
          { $id: "page-1", route: "/same", root: { node: "Stack", children: [] } },
          { $id: "page-2", route: "/same", root: { node: "Stack", children: [] } },
        ],
      };
      const errors = validateIR(ir);
      expect(errors.some((e) => e.code === "DUPLICATE_ROUTE")).toBe(true);
    });
  });

  // ─── Node validation ───

  describe("nodes", () => {
    it("should reject unknown node types", () => {
      const ir: AppIR = {
        $schema: "tentoroforge/ir/1.0",
        app: { name: "Test" },
        tokens: {},
        dataSources: {},
        pages: [
          {
            $id: "test",
            route: "/test",
            root: { node: "NonExistentWidget" } as any,
          },
        ],
      };
      const errors = validateIR(ir);
      expect(errors.some((e) => e.code === "UNKNOWN_NODE_TYPE")).toBe(true);
    });

    it("should require required props", () => {
      const ir: AppIR = {
        $schema: "tentoroforge/ir/1.0",
        app: { name: "Test" },
        tokens: {},
        dataSources: {},
        pages: [
          {
            $id: "test",
            route: "/test",
            root: {
              node: "Stack",
              children: [
                // Text requires "content" prop
                { node: "Text" } as any,
              ],
            },
          },
        ],
      };
      const errors = validateIR(ir);
      expect(errors.some((e) => e.code === "MISSING_REQUIRED" && e.path.includes("content"))).toBe(true);
    });

    it("should validate children recursively", () => {
      const ir: AppIR = {
        $schema: "tentoroforge/ir/1.0",
        app: { name: "Test" },
        tokens: {},
        dataSources: {},
        pages: [
          {
            $id: "test",
            route: "/test",
            root: {
              node: "Stack",
              children: [
                {
                  node: "Row",
                  children: [
                    { node: "FakeNode" } as any,
                  ],
                },
              ],
            },
          },
        ],
      };
      const errors = validateIR(ir);
      expect(errors.some((e) => e.code === "UNKNOWN_NODE_TYPE" && e.path.includes("children[0].children[0]"))).toBe(true);
    });
  });

  // ─── Data source validation ───

  describe("dataSources", () => {
    it("should require type, method, and path", () => {
      const ir: AppIR = {
        $schema: "tentoroforge/ir/1.0",
        app: { name: "Test" },
        tokens: {},
        dataSources: {
          broken: {} as any,
        },
        pages: [],
      };
      const errors = validateIR(ir);
      expect(errors.filter((e) => e.code === "MISSING_REQUIRED" && e.path.startsWith("dataSources.broken")).length).toBeGreaterThanOrEqual(3);
    });

    it("should reject invalid HTTP methods", () => {
      const ir: AppIR = {
        $schema: "tentoroforge/ir/1.0",
        app: { name: "Test" },
        tokens: {},
        dataSources: {
          bad: { type: "rest", method: "YOLO" as any, path: "/api/test" },
        },
        pages: [],
      };
      const errors = validateIR(ir);
      expect(errors.some((e) => e.code === "INVALID_VALUE")).toBe(true);
    });
  });

  // ─── Action validation ───

  describe("actions", () => {
    it("should warn on unknown mutation source", () => {
      const ir: AppIR = {
        $schema: "tentoroforge/ir/1.0",
        app: { name: "Test" },
        tokens: {},
        dataSources: {},
        pages: [
          {
            $id: "test",
            route: "/test",
            root: {
              node: "Stack",
              children: [
                {
                  node: "Text",
                  content: "click me",
                  action: { type: "mutate", source: "nonExistent" },
                } as any,
              ],
            },
          },
        ],
      };
      const errors = validateIR(ir);
      expect(errors.some((e) => e.code === "UNKNOWN_DATA_SOURCE")).toBe(true);
    });

    it("should validate sequence action steps", () => {
      const ir: AppIR = {
        $schema: "tentoroforge/ir/1.0",
        app: { name: "Test" },
        tokens: {},
        dataSources: {},
        pages: [
          {
            $id: "test",
            route: "/test",
            root: {
              node: "Stack",
              children: [
                {
                  node: "Form",
                  bind: "state:form",
                  onSubmit: {
                    type: "sequence",
                    steps: [
                      { type: "mutate", source: "missing" },
                      { type: "toast", variant: "success", message: "done" },
                    ],
                  },
                } as any,
              ],
            },
          },
        ],
      };
      const errors = validateIR(ir);
      expect(errors.some((e) => e.code === "UNKNOWN_DATA_SOURCE")).toBe(true);
    });
  });

  // ─── Binding validation ───

  describe("bindings", () => {
    it("should warn on unknown state reference", () => {
      const ir: AppIR = {
        $schema: "tentoroforge/ir/1.0",
        app: { name: "Test" },
        tokens: {},
        dataSources: {},
        pages: [
          {
            $id: "test",
            route: "/test",
            state: { name: "" },
            root: {
              node: "Stack",
              children: [
                {
                  node: "TextInput",
                  bind: "state:nonExistent",
                },
              ],
            },
          },
        ],
      };
      const errors = validateIR(ir);
      expect(errors.some((e) => e.code === "UNKNOWN_STATE")).toBe(true);
    });

    it("should warn on unknown data source reference", () => {
      const ir: AppIR = {
        $schema: "tentoroforge/ir/1.0",
        app: { name: "Test" },
        tokens: {},
        dataSources: {},
        pages: [
          {
            $id: "test",
            route: "/test",
            root: {
              node: "Stack",
              children: [
                {
                  node: "DataTable",
                  data: "source:nonExistent",
                  columns: [{ field: "name", header: "Name" }],
                },
              ],
            },
          },
        ],
      };
      const errors = validateIR(ir);
      expect(errors.some((e) => e.code === "UNKNOWN_DATA_SOURCE")).toBe(true);
    });
  });

  // ─── Fragment validation ───

  describe("fragments", () => {
    it("should reject unknown fragment references", () => {
      const ir: AppIR = {
        $schema: "tentoroforge/ir/1.0",
        app: { name: "Test" },
        tokens: {},
        dataSources: {},
        fragments: {},
        pages: [
          {
            $id: "test",
            route: "/test",
            root: {
              node: "Stack",
              children: [
                { node: "FragmentRef", $ref: "#/fragments/nonExistent" },
              ],
            },
          },
        ],
      };
      const errors = validateIR(ir);
      expect(errors.some((e) => e.code === "UNKNOWN_FRAGMENT")).toBe(true);
    });
  });
});
