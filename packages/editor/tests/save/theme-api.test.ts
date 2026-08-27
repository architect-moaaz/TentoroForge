import { describe, it, expect, vi, beforeEach } from "vitest";
import { getTheme, saveTheme } from "../../src/save/api";

beforeEach(() => { vi.restoreAllMocks(); });

describe("getTheme", () => {
  it("GETs /api/editor/theme and returns tokens", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ tokens: { colors: { "primary.500": "#3b82f6" } }, source: "default" }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const r = await getTheme();
    expect(r.tokens.colors["primary.500"]).toBe("#3b82f6");
    expect(r.source).toBe("default");
  });
});

describe("saveTheme", () => {
  it("POSTs /api/editor/theme with tokens", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ ok: true }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await saveTheme({ colors: { "primary.500": "#ff0000" } } as any);
    expect(fetchMock).toHaveBeenCalledWith("/api/editor/theme", expect.objectContaining({ method: "POST" }));
  });
});
