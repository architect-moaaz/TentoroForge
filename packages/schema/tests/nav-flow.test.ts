import { describe, it, expect } from "vitest";
import { NavFlow } from "../src/nav-flow";

describe("NavFlow Zod schema", () => {
  it("parses canonical shape", () => {
    const raw = {
      version: "1.0",
      initialPage: "home",
      pages: [{
        id: "home", route: "/", title: "Home",
        schemaFile: "src/schemas/home.json", params: [],
      }],
      transitions: [{ id: "t1", from: "home", trigger: "go", to: "other" }],
      guards: { auth: { redirectTo: "login", condition: "x == y" } },
    };
    const parsed = NavFlow.parse(raw);
    expect(parsed.initialPage).toBe("home");
    expect(parsed.pages[0].schemaFile).toBe("src/schemas/home.json");
  });

  it("params defaults to empty array", () => {
    const parsed = NavFlow.parse({
      initialPage: "home",
      pages: [{ id: "home", route: "/", title: "Home", schemaFile: "x" }],
    });
    expect(parsed.pages[0].params).toEqual([]);
  });

  it("transitions defaults to empty array", () => {
    const parsed = NavFlow.parse({
      initialPage: "home",
      pages: [{ id: "home", route: "/", title: "Home", schemaFile: "x" }],
    });
    expect(parsed.transitions).toEqual([]);
  });

  it("rejects missing required fields", () => {
    expect(() => NavFlow.parse({ initialPage: "home" })).toThrow();
  });
});
