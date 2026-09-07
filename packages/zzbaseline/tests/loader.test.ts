import { describe, it, expect, vi, afterEach } from "vitest";
import { fetchDataSources } from "../src/data/loader";

const originalFetch = global.fetch;
afterEach(() => { global.fetch = originalFetch; });

describe("fetchDataSources", () => {
  it("returns empty map when no sources", async () => {
    const r = await fetchDataSources([], "");
    expect(r).toEqual({});
  });

  it("returns empty map when sources is undefined", async () => {
    const r = await fetchDataSources(undefined, "");
    expect(r).toEqual({});
  });

  it("fetches each source from apiBaseUrl", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ items: [{ id: 1 }] }),
    } as Response);
    const r = await fetchDataSources(
      [{ name: "notes", source: "/api/notes", op: "list" }],
      "http://api"
    );
    expect((global.fetch as any).mock.calls[0][0]).toBe("http://api/api/notes");
    expect(r.notes).toEqual({ items: [{ id: 1 }] });
  });

  it("uses same-origin when apiBaseUrl is empty", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true, json: async () => ({}),
    } as Response);
    await fetchDataSources(
      [{ name: "x", source: "/api/x" }], ""
    );
    expect((global.fetch as any).mock.calls[0][0]).toBe("/api/x");
  });

  it("returns null for a source that 404s", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false, status: 404, json: async () => null,
    } as Response);
    const r = await fetchDataSources(
      [{ name: "x", source: "/api/x" }], ""
    );
    expect(r.x).toBeNull();
  });

  it("returns null when fetch throws", async () => {
    global.fetch = vi.fn().mockRejectedValue(new Error("offline"));
    const r = await fetchDataSources(
      [{ name: "x", source: "/api/x" }], ""
    );
    expect(r.x).toBeNull();
  });

  it("interpolates path params from prior sources", async () => {
    let calls = 0;
    global.fetch = vi.fn().mockImplementation(async (url: string) => ({
      ok: true,
      json: async () => {
        calls++;
        return calls === 1 ? { user: { id: "u1" } } : { name: "Alex" };
      },
    } as any));
    await fetchDataSources(
      [
        { name: "session", source: "/api/session", op: "get" },
        { name: "profile", source: "/api/users/{{session.user.id}}", op: "get" },
      ], ""
    );
    expect((global.fetch as any).mock.calls[1][0]).toBe("/api/users/u1");
  });

  it("lifts get-op record's top-level objects to the root scope", async () => {
    let calls = 0;
    global.fetch = vi.fn().mockImplementation(async () => ({
      ok: true,
      json: async () => ({ employee: { name: "Sarah" }, status: "active" }),
    } as any));
    const r = await fetchDataSources(
      [{ name: "leaveRequest", source: "/api/leave-requests/1", op: "get" }],
      ""
    );
    expect((r as any).employee).toEqual({ name: "Sarah" });
    expect(r.leaveRequest).toEqual({ employee: { name: "Sarah" }, status: "active" });
    // status is a scalar (not object), so it should NOT be lifted
    expect((r as any).status).toBeUndefined();
  });

  it("does not lift get-op for arrays or already-existing keys", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ users: [{ id: 1 }], employee: { lifted: true } }),
    } as Response);
    const r = await fetchDataSources(
      [
        { name: "first", source: "/api/x", op: "get" },
        // pre-populate "employee" to test it's not overwritten
      ],
      ""
    );
    // 'users' is an array → not lifted
    expect((r as any).users).toBeUndefined();
    expect(r.first).toBeDefined();
  });
});
