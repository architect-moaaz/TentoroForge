import { describe, it, expect } from "vitest";
import { readFileSync } from "fs";
import { join, dirname } from "path";
import { fileURLToPath } from "url";
import { compile } from "../src/index.js";
import type { AppIR } from "@tentoroforge/ir";

const __dirname = dirname(fileURLToPath(import.meta.url));
const fixturesDir = join(__dirname, "..", "..", "ir", "fixtures");

function loadFixture(name: string): AppIR {
  const raw = readFileSync(join(fixturesDir, `${name}.json`), "utf-8");
  return JSON.parse(raw);
}

describe("compile", () => {
  // ─── All fixtures should compile without errors ───

  const fixtures = [
    "simple-table",
    "sidebar-detail",
    "form-page",
    "dashboard",
    "auth-login",
    "settings",
  ];

  for (const name of fixtures) {
    it(`fixture "${name}" should compile without errors`, () => {
      const ir = loadFixture(name);
      const result = compile(ir);

      if (result.errors.length > 0) {
        console.error(`Compile errors for ${name}:`, result.errors);
      }
      expect(result.errors).toHaveLength(0);
      expect(Object.keys(result.files).length).toBeGreaterThan(0);
    });
  }

  // ─── Output should contain expected structures ───

  describe("output structure", () => {
    it("simple-table should produce a page file at correct route", () => {
      const ir = loadFixture("simple-table");
      const result = compile(ir);
      expect(result.files["app/users/page.tsx"]).toBeDefined();
    });

    it("sidebar-detail should produce a page file at correct route", () => {
      const ir = loadFixture("sidebar-detail");
      const result = compile(ir);
      expect(result.files["app/tasks/page.tsx"]).toBeDefined();
    });

    it("form-page should produce a page file at correct route", () => {
      const ir = loadFixture("form-page");
      const result = compile(ir);
      expect(result.files["app/tasks/new/page.tsx"]).toBeDefined();
    });

    it("dashboard should produce a page file at correct route", () => {
      const ir = loadFixture("dashboard");
      const result = compile(ir);
      expect(result.files["app/dashboard/page.tsx"]).toBeDefined();
    });

    it("auth-login should produce a page file at correct route", () => {
      const ir = loadFixture("auth-login");
      const result = compile(ir);
      expect(result.files["app/login/page.tsx"]).toBeDefined();
    });

    it("settings should produce a page file at correct route", () => {
      const ir = loadFixture("settings");
      const result = compile(ir);
      expect(result.files["app/settings/page.tsx"]).toBeDefined();
    });
  });

  // ─── Output should contain key code elements ───

  describe("code content", () => {
    it("simple-table page should have DataTable and useState", () => {
      const ir = loadFixture("simple-table");
      const result = compile(ir);
      const code = result.files["app/users/page.tsx"];

      expect(code).toContain('"use client"');
      expect(code).toContain("useState");
      expect(code).toContain("DataTable");
      expect(code).toContain("export default function");
    });

    it("sidebar-detail page should have Repeater output and Slot conditions", () => {
      const ir = loadFixture("sidebar-detail");
      const result = compile(ir);
      const code = result.files["app/tasks/page.tsx"];

      expect(code).toContain('"use client"');
      expect(code).toContain("useState");
      expect(code).toContain(".map(");  // Repeater
      expect(code).toContain("== null");  // Slot null check
    });

    it("form-page should have form element and submit handler", () => {
      const ir = loadFixture("form-page");
      const result = compile(ir);
      const code = result.files["app/tasks/new/page.tsx"];

      expect(code).toContain("<form");
      expect(code).toContain("onSubmit");
      expect(code).toContain("preventDefault");
    });

    it("dashboard should have StatCard and Grid", () => {
      const ir = loadFixture("dashboard");
      const result = compile(ir);
      const code = result.files["app/dashboard/page.tsx"];

      expect(code).toContain("Card");
      expect(code).toContain("grid");
    });

    it("auth-login should have email and password inputs", () => {
      const ir = loadFixture("auth-login");
      const result = compile(ir);
      const code = result.files["app/login/page.tsx"];

      expect(code).toContain('type="email"');
      expect(code).toContain('type="password"');
    });

    it("settings should have Switch and conditional sections", () => {
      const ir = loadFixture("settings");
      const result = compile(ir);
      const code = result.files["app/settings/page.tsx"];

      expect(code).toContain("Switch");
      expect(code).toContain("===");  // switch cases
    });
  });

  // ─── Formatters file ───

  describe("utility files", () => {
    it("should generate formatters file when pipes are used", () => {
      const ir = loadFixture("sidebar-detail");
      const result = compile(ir);

      // sidebar-detail uses relativeDate pipe
      expect(result.files["lib/formatters.ts"]).toBeDefined();
      expect(result.files["lib/formatters.ts"]).toContain("formatRelativeDate");
    });
  });

  // ─── Error handling ───

  describe("error handling", () => {
    it("should return errors for invalid IR", () => {
      const ir = {
        $schema: "wrong/1.0",
        app: { name: "" },
        tokens: {},
        dataSources: {},
        pages: [],
      } as any;

      const result = compile(ir);
      expect(result.errors.length).toBeGreaterThan(0);
    });

    it("should return errors for unknown node types", () => {
      const ir: AppIR = {
        $schema: "tentoroforge/ir/1.0",
        app: { name: "Test" },
        tokens: {},
        dataSources: {},
        pages: [
          {
            $id: "test",
            route: "/test",
            root: { node: "FakeWidget" } as any,
          },
        ],
      };

      const result = compile(ir);
      expect(result.errors.length).toBeGreaterThan(0);
    });
  });

  // ─── Selective compilation ───

  describe("selective compilation", () => {
    it("should compile only specified pages", () => {
      const ir = loadFixture("simple-table");
      // Add a second page
      ir.pages.push({
        $id: "other",
        route: "/other",
        root: { node: "Stack", children: [{ node: "Text", content: "Other" }] },
      } as any);

      const result = compile(ir, { pageIds: ["user-list"] });
      expect(Object.keys(result.files)).toContain("app/users/page.tsx");
      expect(Object.keys(result.files)).not.toContain("app/other/page.tsx");
    });
  });
});
