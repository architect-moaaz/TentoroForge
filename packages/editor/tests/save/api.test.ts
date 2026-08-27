import { describe, it, expect, vi, beforeEach } from "vitest";
import { saveSchema, loadSchema, listPages } from "../../src/save/api";

beforeEach(() => { vi.restoreAllMocks(); });

describe("saveSchema", () => {
  it("POSTs to /api/editor/save with path + schema and returns response", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ ok: true, savedSchema: {}, suggestions: [] }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const r = await saveSchema("products/list", { schemaVersion: "1" } as any);
    expect(fetchMock).toHaveBeenCalledWith("/api/editor/save", expect.objectContaining({ method: "POST" }));
    expect(r.ok).toBe(true);
  });

  it("surfaces 422 validation errors", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ ok: false, errors: [{ path: ["root"], message: "bad" }] }), { status: 422 }));
    vi.stubGlobal("fetch", fetchMock);
    const r = await saveSchema("products/list", {} as any);
    expect(r.ok).toBe(false);
    expect(r.errors).toHaveLength(1);
  });
});

describe("loadSchema", () => {
  it("GETs /api/editor/load with path query", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ schema: { schemaVersion: "1" } }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const r = await loadSchema("products/list");
    expect(fetchMock).toHaveBeenCalledWith("/api/editor/load?path=products%2Flist", expect.any(Object));
    expect(r.schema.schemaVersion).toBe("1");
  });
});

describe("listPages", () => {
  it("GETs /api/editor/pages and returns paths array", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ paths: ["products/list", "customers/list"] }), { status: 200 })
    );
    vi.stubGlobal("fetch", fetchMock);
    const r = await listPages();
    expect(fetchMock).toHaveBeenCalledWith("/api/editor/pages", expect.objectContaining({ headers: expect.objectContaining({ Accept: "application/json" }) }));
    expect(r.paths).toEqual(["products/list", "customers/list"]);
  });

  it("uses provided baseUrl as prefix", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ paths: [] }), { status: 200 })
    );
    vi.stubGlobal("fetch", fetchMock);
    await listPages("http://localhost:3000");
    expect(fetchMock).toHaveBeenCalledWith("http://localhost:3000/api/editor/pages", expect.any(Object));
  });

  it("throws on non-ok response", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("", { status: 500 })));
    await expect(listPages()).rejects.toThrow("listPages: 500");
  });
});
