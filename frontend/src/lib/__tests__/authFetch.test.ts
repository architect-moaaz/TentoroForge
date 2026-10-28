/**
 * `authFetch` renews an expired sign-in once, as `api` does. Without it a panel that read through here (the mobile builds) got a
 * 401 for ever and showed an empty list while a build was running (2026-10-23).
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";

import { authFetch } from "../api";

const calls: { url: string; auth: string | null }[] = [];
let script: Array<{ url?: RegExp; status: number; body?: unknown }> = [];

function reply(status: number, body: unknown = {}) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

beforeEach(() => {
  calls.length = 0;
  localStorage.setItem("token", "old");
  localStorage.setItem("refresh_token", "r1");
  vi.stubGlobal("fetch", async (url: string, init: RequestInit = {}) => {
    calls.push({ url, auth: new Headers(init.headers || {}).get("Authorization") });
    const next = script.shift();
    if (!next) throw new Error(`unexpected request to ${url}`);
    return reply(next.status, next.body);
  });
});
afterEach(() => { vi.unstubAllGlobals(); localStorage.clear(); script = []; });

describe("authFetch with a sign-in that has expired", () => {
  it("renews it and sends the request again with the new token", async () => {
    script = [{ status: 401 }, { status: 200, body: { access_token: "new", refresh_token: "r2" } }, { status: 200, body: [{ id: "b1" }] }];
    const res = await authFetch("http://x/api/builds");
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual([{ id: "b1" }]);
    expect(calls.map((c) => c.auth)).toEqual(["Bearer old", null, "Bearer new"]);
    expect(localStorage.getItem("token")).toBe("new");
    expect(localStorage.getItem("refresh_token")).toBe("r2");
  });

  it("replaces a stale bearer token the caller set itself", async () => {
    script = [{ status: 401 }, { status: 200, body: { access_token: "new" } }, { status: 200 }];
    const res = await authFetch("http://x/api/builds", { headers: { Authorization: "Bearer stale" } });
    expect(res.status).toBe(200);
    expect(calls[2].auth).toBe("Bearer new");
  });

  it("uses the token someone else already renewed, without renewing again", async () => {
    script = [{ status: 401 }, { status: 200 }];
    const first = fetch;   // the stub
    vi.stubGlobal("fetch", async (url: string, init: RequestInit = {}) => {
      localStorage.setItem("token", "renewed-elsewhere");
      return first(url, init);
    });
    const res = await authFetch("http://x/api/builds");
    expect(res.status).toBe(200);
    expect(calls.some((c) => c.url.includes("/api/auth/refresh"))).toBe(false);
  });

  it("gives back the 401 when it cannot be renewed, and does not send people to the login page", async () => {
    script = [{ status: 401 }, { status: 401 }];
    const res = await authFetch("http://x/api/builds");
    expect(res.status).toBe(401);
    expect(localStorage.getItem("token")).toBe("old");
  });

  it("does not send a request again when it carried a token that is not a bearer one", async () => {
    script = [{ status: 401 }];
    const res = await authFetch("http://x/api/builds", { headers: { Authorization: "Basic abc" } });
    expect(res.status).toBe(401);
    expect(calls).toHaveLength(1);
  });

  it("leaves a request that worked alone", async () => {
    script = [{ status: 200 }];
    expect((await authFetch("http://x/api/builds")).status).toBe(200);
    expect(calls).toHaveLength(1);
  });
});
