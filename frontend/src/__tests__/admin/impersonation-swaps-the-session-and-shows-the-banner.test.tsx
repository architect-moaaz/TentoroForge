/**
 * Impersonation: the super admin's own tokens go aside, the person's
 * 30-minute token takes the slot (with no refresh, so it cannot outlive
 * itself), every page shows the amber bar, and "Return to cockpit" puts
 * the admin's session back.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push, replace: vi.fn() }) }));

import { ImpersonationBanner } from "@/components/admin/ImpersonationBanner";
import { COCKPIT_RETURN_KEY, REFRESH_KEY, TOKEN_KEY } from "@/lib/auth-storage";
import { useAuthStore } from "@/stores/auth";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const admin = { id: "a1", email: "admin@tentoro.ai", name: "Admin", orgs: [], platform_role: "super_admin", impersonated_by: null };
const tester = { id: "t1", email: "tester@example.com", name: "Tester", orgs: [{ org_id: "o1", org_name: "Acme", role: "owner" }], platform_role: null };

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

/** The platform as the browser sees it: /me answers for whoever's token is sent. */
function stubPlatform() {
  const calls: { url: string; auth: string | null; method: string }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const headers = new Headers(init?.headers);
    const auth = headers.get("Authorization");
    calls.push({ url, auth, method: init?.method ?? "GET" });
    if (url.endsWith("/api/admin/people/t1/impersonate")) {
      return json({ access_token: "acting-as-tester", expires_at: "2026-10-15T12:30:00Z", user: tester, default_org_id: "o1" });
    }
    if (url.endsWith("/api/auth/me")) {
      if (auth === "Bearer acting-as-tester") return json({ ...tester, impersonated_by: { id: admin.id, email: admin.email } });
      if (auth === "Bearer admin-access") return json(admin);
      return json({ detail: "Not authenticated" }, 401);
    }
    return json({ detail: `unexpected ${url}` }, 500);
  }));
  return calls;
}

let root: Root; let el: HTMLDivElement;
beforeEach(() => {
  localStorage.clear(); sessionStorage.clear(); push.mockReset();
  el = document.createElement("div"); document.body.appendChild(el);
});
afterEach(() => { if (root) act(() => root.unmount()); el.remove(); vi.unstubAllGlobals(); });

function mountBanner() {
  const qc = new QueryClient();
  act(() => {
    root = createRoot(el);
    root.render(<QueryClientProvider client={qc}><ImpersonationBanner /></QueryClientProvider>);
  });
}

describe("acting as a person", () => {
  it("swaps the session, shows the bar on every page, and returns on request", async () => {
    const calls = stubPlatform();
    localStorage.setItem(TOKEN_KEY, "admin-access");
    localStorage.setItem(REFRESH_KEY, "admin-refresh");
    useAuthStore.setState({ user: admin as never, token: "admin-access" });

    mountBanner();
    expect(el.textContent).toBe("");  // nothing while the admin is themselves

    let landing: string | null = null;
    await act(async () => { landing = await useAuthStore.getState().impersonate("t1"); });

    expect(landing).toBe("o1");
    expect(localStorage.getItem(TOKEN_KEY)).toBe("acting-as-tester");
    expect(localStorage.getItem(REFRESH_KEY)).toBeNull();
    expect(JSON.parse(sessionStorage.getItem(COCKPIT_RETURN_KEY)!)).toMatchObject({ token: "admin-access", refresh_token: "admin-refresh" });
    expect(useAuthStore.getState().user?.email).toBe("tester@example.com");
    expect(useAuthStore.getState().user?.impersonated_by?.email).toBe("admin@tentoro.ai");
    // The grant was asked for with the admin's own token; /me afterwards with the person's.
    expect(calls.find((c) => c.url.endsWith("/impersonate"))?.auth).toBe("Bearer admin-access");
    expect(calls.filter((c) => c.url.endsWith("/api/auth/me")).at(-1)?.auth).toBe("Bearer acting-as-tester");

    expect(el.textContent).toContain("Viewing as tester@example.com");
    expect(el.textContent).toContain("admin@tentoro.ai");

    const back = el.querySelector("button")!;
    expect(back.textContent).toContain("Return to cockpit");
    await act(async () => { back.click(); await Promise.resolve(); });
    await act(async () => { await new Promise((r) => setTimeout(r, 0)); });

    expect(localStorage.getItem(TOKEN_KEY)).toBe("admin-access");
    expect(localStorage.getItem(REFRESH_KEY)).toBe("admin-refresh");
    expect(sessionStorage.getItem(COCKPIT_RETURN_KEY)).toBeNull();
    expect(useAuthStore.getState().user?.email).toBe("admin@tentoro.ai");
    expect(el.textContent).toBe("");
    expect(push).toHaveBeenCalledWith("/admin/people");
  });

  it("brings the admin back by itself when the person's token is refused", async () => {
    stubPlatform();
    localStorage.setItem(TOKEN_KEY, "admin-access");
    sessionStorage.setItem(COCKPIT_RETURN_KEY, JSON.stringify({ token: "admin-access", refresh_token: null, saved_at: 1 }));
    localStorage.setItem(TOKEN_KEY, "expired-impersonation");
    useAuthStore.setState({ user: null, token: "expired-impersonation" });

    await act(async () => { await useAuthStore.getState().fetchUser(); });

    expect(localStorage.getItem(TOKEN_KEY)).toBe("admin-access");
    expect(useAuthStore.getState().user?.email).toBe("admin@tentoro.ai");
    expect(sessionStorage.getItem(COCKPIT_RETURN_KEY)).toBeNull();
  });
});
