import { describe, it, expect, vi } from "vitest";
import { resolveWithBasePath, createBasePathNavigator } from "../src/client/Navigator";

/**
 * The seam every schema-driven navigation goes through. Before this, a host
 * serving app routes under a prefix (the preview renderer's /p/<project>/…)
 * had no way to say so, and `window.location.assign("/items")` resolved
 * against the origin root — measured: a Link on /p/gh0mlpbp/nav-lab-6 landed
 * on localhost:6503/items, a 404. Redirect, Link, NavLink, Button navigate,
 * Table rowHref and the post-submit redirect all shared the one line.
 */
describe("resolveWithBasePath", () => {
  const base = "/p/proj";

  it("prefixes app-absolute routes", () => {
    expect(resolveWithBasePath(base, "/items")).toBe("/p/proj/items");
    expect(resolveWithBasePath(base, "/items/1/edit")).toBe("/p/proj/items/1/edit");
  });

  it("maps the app root onto the base itself", () => {
    expect(resolveWithBasePath(base, "/")).toBe("/p/proj");
  });

  it("never double-prefixes", () => {
    expect(resolveWithBasePath(base, "/p/proj/items")).toBe("/p/proj/items");
    expect(resolveWithBasePath(base, "/p/proj")).toBe("/p/proj");
  });

  it("leaves everything that is not an app route alone", () => {
    expect(resolveWithBasePath(base, "https://example.com/x")).toBe("https://example.com/x");
    expect(resolveWithBasePath(base, "//cdn.example.com/x")).toBe("//cdn.example.com/x");
    expect(resolveWithBasePath(base, "mailto:a@b.c")).toBe("mailto:a@b.c");
    expect(resolveWithBasePath(base, "#section")).toBe("#section");
    expect(resolveWithBasePath(base, "?q=1")).toBe("?q=1");
    expect(resolveWithBasePath(base, "relative/path")).toBe("relative/path");
    expect(resolveWithBasePath(base, "")).toBe("");
  });

  it("is a no-op with no base path, so unprefixed hosts are unchanged", () => {
    expect(resolveWithBasePath("", "/items")).toBe("/items");
    expect(resolveWithBasePath("/", "/items")).toBe("/items");
  });

  it("tolerates a trailing slash on the base", () => {
    expect(resolveWithBasePath("/p/proj/", "/items")).toBe("/p/proj/items");
  });
});

describe("createBasePathNavigator", () => {
  it("translates push and replace, and passes back/refresh straight through", () => {
    const inner = { push: vi.fn(), replace: vi.fn(), back: vi.fn(), refresh: vi.fn() };
    const nav = createBasePathNavigator("/p/proj", inner);
    nav.push("/items");
    nav.replace("/items/new");
    nav.back();
    nav.refresh();
    expect(inner.push).toHaveBeenCalledWith("/p/proj/items");
    expect(inner.replace).toHaveBeenCalledWith("/p/proj/items/new");
    expect(inner.back).toHaveBeenCalled();
    expect(inner.refresh).toHaveBeenCalled();
  });
});
