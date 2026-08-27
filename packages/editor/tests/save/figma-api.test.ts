import { describe, it, expect, vi, beforeEach } from "vitest";
import { extractFromFigma, parseFigmaUrl } from "../../src/save/api";

beforeEach(() => {
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// parseFigmaUrl
// ---------------------------------------------------------------------------

describe("parseFigmaUrl", () => {
  it("parses a /design URL with node-id", () => {
    const url =
      "https://www.figma.com/design/abc123/My-Design?node-id=1-2&t=xyz";
    const result = parseFigmaUrl(url);
    expect(result).toEqual({ fileKey: "abc123", nodeId: "1:2" });
  });

  it("parses a /file URL with node-id", () => {
    const url = "https://www.figma.com/file/XYZ789/Name?node-id=10-20";
    const result = parseFigmaUrl(url);
    expect(result).toEqual({ fileKey: "XYZ789", nodeId: "10:20" });
  });

  it("converts hyphens to colons in nodeId", () => {
    const url = "https://figma.com/design/KEY/name?node-id=3-4-5";
    const result = parseFigmaUrl(url);
    expect(result?.nodeId).toBe("3:4:5");
  });

  it("returns null for non-Figma URLs", () => {
    expect(parseFigmaUrl("https://example.com/design/abc?node-id=1")).toBeNull();
  });

  it("returns null when node-id query param is missing", () => {
    expect(parseFigmaUrl("https://figma.com/design/abc123/Name")).toBeNull();
  });

  it("returns null for empty string", () => {
    expect(parseFigmaUrl("")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// extractFromFigma
// ---------------------------------------------------------------------------

describe("extractFromFigma", () => {
  it("POSTs to /api/figma/extract with fileKey + nodeId", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(
        JSON.stringify({ schema: { root: { id: "n1", type: "Box" } } }),
        { status: 200 }
      )
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await extractFromFigma({ fileKey: "abc", nodeId: "1:2" });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/figma/extract",
      expect.objectContaining({ method: "POST" })
    );
    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(body).toEqual({ fileKey: "abc", nodeId: "1:2" });
    expect(result.schema.root.type).toBe("Box");
  });

  it("respects baseUrl prefix", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ schema: null }), { status: 200 })
    );
    vi.stubGlobal("fetch", fetchMock);

    await extractFromFigma({ fileKey: "k", nodeId: "1:1" }, "http://localhost:6501");

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:6501/api/figma/extract",
      expect.any(Object)
    );
  });

  it("throws on non-ok HTTP status", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("", { status: 500 }))
    );
    await expect(
      extractFromFigma({ fileKey: "k", nodeId: "1:1" })
    ).rejects.toThrow("extractFromFigma: 500");
  });
});
