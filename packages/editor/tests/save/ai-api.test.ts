import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { getSuggestions, regenerateSection } from "../../src/save/api";

const mockPage: any = {
  schemaVersion: "1",
  id: "p",
  route: "/",
  root: { id: "r", type: "Stack", children: [] },
};

describe("getSuggestions", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("POSTs to /api/editor/suggest with mode=ambient", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ suggestions: [{ title: "Fix aria", description: "Add aria-label" }] }),
    });
    vi.stubGlobal("fetch", mockFetch);

    const result = await getSuggestions(mockPage, "ambient");

    expect(mockFetch).toHaveBeenCalledWith(
      "/api/editor/suggest",
      expect.objectContaining({
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: "ambient", schema: mockPage }),
      })
    );
    expect(result.suggestions).toHaveLength(1);
    expect(result.suggestions[0].title).toBe("Fix aria");
  });

  it("respects custom baseUrl", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ suggestions: [] }),
    });
    vi.stubGlobal("fetch", mockFetch);

    await getSuggestions(mockPage, "ambient", "http://localhost:6500");

    expect(mockFetch).toHaveBeenCalledWith(
      "http://localhost:6500/api/editor/suggest",
      expect.anything()
    );
  });

  it("throws on non-ok response", async () => {
    const mockFetch = vi.fn().mockResolvedValue({ ok: false, status: 500 });
    vi.stubGlobal("fetch", mockFetch);

    await expect(getSuggestions(mockPage, "ambient")).rejects.toThrow("getSuggestions: 500");
  });
});

describe("regenerateSection", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("POSTs to /api/editor/suggest with mode=regenerate", async () => {
    const subtree = { id: "n1", type: "Box", children: [] };
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ subtree: { id: "n1", type: "Stack", children: [] } }),
    });
    vi.stubGlobal("fetch", mockFetch);

    const result = await regenerateSection("Make it a stack", subtree);

    expect(mockFetch).toHaveBeenCalledWith(
      "/api/editor/suggest",
      expect.objectContaining({
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: "regenerate", prompt: "Make it a stack", subtree }),
      })
    );
    expect(result.subtree.type).toBe("Stack");
  });

  it("throws on non-ok response", async () => {
    const mockFetch = vi.fn().mockResolvedValue({ ok: false, status: 422 });
    vi.stubGlobal("fetch", mockFetch);

    await expect(regenerateSection("test", {})).rejects.toThrow("regenerateSection: 422");
  });

  it("respects custom baseUrl", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ subtree: {} }),
    });
    vi.stubGlobal("fetch", mockFetch);

    await regenerateSection("prompt", {}, "http://localhost:6500");

    expect(mockFetch).toHaveBeenCalledWith(
      "http://localhost:6500/api/editor/suggest",
      expect.anything()
    );
  });
});
